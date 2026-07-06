#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOORS Kalıcı Filtre Yöneticisi — Filtre Editörü (Python / Tkinter)
==================================================================

IBM DOORS 9.x (klasik, DXL destekli) için filtre tanımlarını düzenleyen
masaüstü uygulama. Tanımlar iki dosyaya kaydedilir:

  * filters.json  — kanonik, insan tarafından okunabilir kayıt (bu editör
                    tarafından okunur/yazılır).
  * filters.dat   — DXL tarafının okuduğu basit, satır bazlı format.
                    DXL'de JSON parser olmadığı için JSON'dan otomatik
                    üretilir. Elle düzenlemeyin; editörden kaydedin.

"DXL Üret" düğmesi, filters.dat yolunu gömülü DXL şablonuna yazarak
kullanıcıya özel bir doors_filter_panel.dxl dosyası üretir.

Komut satırı kullanımı (GUI olmadan):
    python doors_filter_editor.py --emit-dxl CIKTI.dxl --dat-path "C:\\DOORS_Filters\\filters.dat"
    python doors_filter_editor.py --export-dat filters.json filters.dat

Gereksinimler: Python 3.8+ (yalnızca standart kütüphane; GUI için Tkinter).
"""

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# Sabitler ve veri modeli
# ---------------------------------------------------------------------------

APP_TITLE = "DOORS Kalıcı Filtre Yöneticisi — Filtre Editörü"
JSON_NAME = "filters.json"
DAT_NAME = "filters.dat"

# DOORS klasik DXL, dosyaları yerel ANSI kod sayfasıyla okur. Türkçe
# Windows'ta bu cp1254'tür. Farklı yerel ayardaki bir DOORS istemcisi için
# bu sabiti değiştirin (ör. "cp1252").
DAT_ENCODING = "cp1254"

DEFAULT_DAT_PATH = r"C:\DOORS_Filters\filters.dat"

# (kod, ekranda gösterilen etiket) — kod .json/.dat/DXL tarafında kullanılır.
OPERATORS = [
    ("contains",     "contains (içerir)"),
    ("equals",       "equals (eşittir)"),
    ("not_equals",   "not equals (eşit değildir)"),
    ("is_empty",     "is empty (boştur)"),
    ("greater_than", "greater than (büyüktür)"),
    ("less_than",    "less than (küçüktür)"),
]
OP_CODES = [c for c, _ in OPERATORS]
OP_LABEL_BY_CODE = dict(OPERATORS)
OP_CODE_BY_LABEL = {lbl: c for c, lbl in OPERATORS}
NO_VALUE_OPS = {"is_empty"}

LOGIC_CHOICES = ["NONE", "AND", "OR"]

FILTER_KEYS = ("name", "attr1", "op1", "val1", "logic", "attr2", "op2", "val2")


def new_filter_dict():
    return {
        "name": "", "attr1": "", "op1": "contains", "val1": "",
        "logic": "NONE", "attr2": "", "op2": "contains", "val2": "",
    }


def normalize_filter(d):
    """Eksik anahtarları tamamlar, tüm değerleri kırpılmış str yapar."""
    out = new_filter_dict()
    for k in FILTER_KEYS:
        v = d.get(k, out[k])
        out[k] = str(v).strip() if v is not None else ""
    if out["logic"] not in LOGIC_CHOICES:
        out["logic"] = "NONE"
    return out


def validate_filter(d, other_names):
    """Hata mesajları listesi döndürür (boş liste = geçerli)."""
    errs = []
    name = d["name"]
    if not name:
        errs.append("Filtre adı boş olamaz.")
    elif name in other_names:
        errs.append("'%s' adında başka bir filtre zaten var." % name)

    def check_condition(no, attr, op, val):
        if not attr:
            errs.append("%d. koşul: attribute adı boş olamaz." % no)
        if op not in OP_CODES:
            errs.append("%d. koşul: geçersiz operatör '%s'." % (no, op))
        elif op not in NO_VALUE_OPS and not val:
            errs.append("%d. koşul: değer boş olamaz "
                        "(boşluk kontrolü için 'is empty' kullanın)." % no)

    check_condition(1, d["attr1"], d["op1"], d["val1"])
    if d["logic"] in ("AND", "OR"):
        check_condition(2, d["attr2"], d["op2"], d["val2"])

    for k in FILTER_KEYS:
        if "\n" in d[k] or "\r" in d[k]:
            errs.append("'%s' alanı satır sonu karakteri içeremez." % k)
    return errs


def cp1254_problem_chars(d):
    """filters.dat'a yazılamayacak (kod sayfası dışı) karakterleri döndürür."""
    bad = set()
    for k in FILTER_KEYS:
        for ch in d.get(k, ""):
            try:
                ch.encode(DAT_ENCODING)
            except UnicodeEncodeError:
                bad.add(ch)
    return sorted(bad)


# ---------------------------------------------------------------------------
# JSON ve DAT serileştirme
# ---------------------------------------------------------------------------

def filters_to_json_text(filters):
    doc = {"format": "doors-filter-manager", "version": 1, "filters": filters}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def filters_from_json_text(text):
    doc = json.loads(text)
    if isinstance(doc, list):          # eski/sade biçim: doğrudan liste
        raw = doc
    elif isinstance(doc, dict) and isinstance(doc.get("filters"), list):
        raw = doc["filters"]
    else:
        raise ValueError("Beklenmeyen JSON yapısı: 'filters' listesi bulunamadı.")
    return [normalize_filter(f) for f in raw if isinstance(f, dict)]


def filters_to_dat_text(filters):
    """
    DXL tarafının okuduğu satır bazlı format. Kayıt yapısı:

        FILTER
        name=...
        attr1=...
        op1=...
        val1=...
        logic=NONE|AND|OR
        attr2=...
        op2=...
        val2=...
        END

    '#' ile başlayan satırlar yorumdur. Değerler '=' işaretinden sonrası
    olduğu gibi alınır (ilk '=' ayraçtır, değer '=' içerebilir).
    """
    lines = [
        "# DOORS Filter Manager veri dosyasi (v1)",
        "# Bu dosya doors_filter_editor.py tarafindan uretilir; elle duzenlemeyin.",
        "",
    ]
    for f in filters:
        lines.append("FILTER")
        for k in FILTER_KEYS:
            lines.append("%s=%s" % (k, f.get(k, "")))
        lines.append("END")
        lines.append("")
    # DOORS Windows'ta çalışır; CRLF ile yaz.
    return "\r\n".join(lines) + "\r\n"


def write_dat_file(path, filters):
    text = filters_to_dat_text(filters)
    with open(path, "w", encoding=DAT_ENCODING, errors="replace", newline="") as fh:
        fh.write(text)


def write_json_file(path, filters):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(filters_to_json_text(filters))


def read_json_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return filters_from_json_text(fh.read())


# ---------------------------------------------------------------------------
# DXL şablonu (tek kaynak). @@DAT_PATH@@ üretim sırasında doldurulur.
# Şablon bilerek yalnızca ASCII içerir: DXL editörü Unicode dosyaları
# güvenilir açamadığı için UI metinleri aksansız Türkçe yazılmıştır.
# ---------------------------------------------------------------------------

DXL_TEMPLATE = r'''// doors_filter_panel.dxl
//---------------------------------------------------------------------------
// DOORS Kalici Filtre Yoneticisi - Filtre Paneli (DXL)
// Hedef surum: IBM DOORS 9.x klasik (9.7.2.x DXL Reference'a gore yazildi)
//
// Bu dosya doors_filter_editor.py (Python) tarafindan uretilir.
// Asagidaki DAT_FILE yolu uretim sirasinda kullaniciya gore doldurulur.
// filters.dat dosyasi ayni Python editorun "Kaydet" adiminda uretilir.
//
// Calistirma: formal modul penceresinde Tools > Edit DXL > Load... > Run
// Panel modsuzdur (non-modal): acikken modulde calismaya devam edebilirsiniz.
//
// Not: script mevcut view'i degistirmez; yalnizca calisma zamani filtre
// katmanini (set/filtering on-off) degistirir. View'i kaydetmedikce
// kalici bir degisiklik olmaz.
//---------------------------------------------------------------------------

pragma runLim, 0

string DAT_FILE = "@@DAT_PATH@@"

int MAX_FILTERS = 300

//---------------------------------------------------------------------------
// Filtre kayitlari (filters.dat'tan yuklenir)
//---------------------------------------------------------------------------

int    gCount = 0
string gNames[MAX_FILTERS]
string gAttr1[MAX_FILTERS]
string gOp1[MAX_FILTERS]
string gVal1[MAX_FILTERS]
string gLogic[MAX_FILTERS]
string gAttr2[MAX_FILTERS]
string gOp2[MAX_FILTERS]
string gVal2[MAX_FILTERS]

string gLoadError = ""

//---------------------------------------------------------------------------
// Panel durumu
//---------------------------------------------------------------------------

DB  gDlg    = null
DBE gLst    = null
DBE gDetail = null
DBE gStatus = null
int gListSize = 0        // listedeki satir sayisi (noElems'e bagimliligi kaldirir)

Filter gActive           // panelden en son uygulanan (birlesik) filtre
bool   gHasActive = false
string gActiveDesc = ""

//---------------------------------------------------------------------------
// Kucuk yardimcilar
//---------------------------------------------------------------------------

string trimStr(string s) {
    if (null s) return ""
    int n = length s
    int i = 0
    int j = n - 1
    while (i <= j) {
        char c = s[i]
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') i++
        else break
    }
    while (j >= i) {
        char c = s[j]
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') j--
        else break
    }
    if (j < i) return ""
    return s[i:j]
}

// "anahtar=deger" satirini ilk '=' isaretinden boler.
bool splitKeyValue(string line, string &key, string &val) {
    int n = length line
    int i
    for (i = 0; i < n; i++) {
        if (line[i] == '=') {
            if (i == 0) return false
            key = line[0:i-1]
            if (i == n - 1) val = ""
            else val = line[i+1:n-1]
            return true
        }
    }
    return false
}

bool isKnownOp(string op) {
    if (op == "contains")     return true
    if (op == "equals")       return true
    if (op == "not_equals")   return true
    if (op == "is_empty")     return true
    if (op == "greater_than") return true
    if (op == "less_than")    return true
    return false
}

bool opNeedsValue(string op) {
    return (op != "is_empty")
}

bool attrExists(Module m, string attrName) {
    if (null m) return false
    AttrDef ad = find(m, attrName)
    return (!(null ad))
}

//---------------------------------------------------------------------------
// filters.dat yukleme
//---------------------------------------------------------------------------

bool loadFilters() {
    gCount = 0
    gLoadError = ""

    Stat st = create(DAT_FILE)
    if (null st) {
        gLoadError = "Veri dosyasi bulunamadi:\n" DAT_FILE "\n\nOnce Python editorde 'Dosyaya Kaydet' yapin."
        return false
    }
    delete st

    Stream inp = read(DAT_FILE)
    if (null inp) {
        gLoadError = "Veri dosyasi acilamadi: " DAT_FILE
        return false
    }

    string line = ""
    string key = ""
    string val = ""
    bool inRec = false
    string nm = ""; string a1 = ""; string o1 = ""; string v1 = ""
    string lg = ""; string a2 = ""; string o2 = ""; string v2 = ""

    while (true) {
        if (end of inp) break
        inp >> line
        line = trimStr(line)
        if (line == "") continue
        if (line[0] == '#') continue

        if (line == "FILTER") {
            inRec = true
            nm = ""; a1 = ""; o1 = ""; v1 = ""
            lg = "NONE"; a2 = ""; o2 = ""; v2 = ""
            continue
        }

        if (line == "END") {
            if (inRec && nm != "" && a1 != "" && o1 != "") {
                if (gCount < MAX_FILTERS) {
                    gNames[gCount] = nm
                    gAttr1[gCount] = a1;  gOp1[gCount] = o1;  gVal1[gCount] = v1
                    gLogic[gCount] = lg
                    gAttr2[gCount] = a2;  gOp2[gCount] = o2;  gVal2[gCount] = v2
                    gCount++
                }
            }
            inRec = false
            continue
        }

        if (!inRec) continue

        if (splitKeyValue(line, key, val)) {
            key = trimStr(key)
            if      (key == "name")  nm = val
            else if (key == "attr1") a1 = val
            else if (key == "op1")   o1 = val
            else if (key == "val1")  v1 = val
            else if (key == "logic") lg = trimStr(val)
            else if (key == "attr2") a2 = val
            else if (key == "op2")   o2 = val
            else if (key == "val2")  v2 = val
        }
    }
    close inp
    return true
}

//---------------------------------------------------------------------------
// Filtre kurma ve dogrulama
//---------------------------------------------------------------------------

// Uygulamadan ONCE cagrilir; "" donerse kayit gecerli demektir.
// Attribute modulde yoksa script cokmez, aciklayici mesaj doner.
string validateRecord(Module m, int i) {
    if (!attrExists(m, gAttr1[i])) {
        return "Oznitelik (attribute) bu modulde tanimli degil: '" gAttr1[i] "'"
    }
    if (!isKnownOp(gOp1[i])) {
        return "Bilinmeyen operator: '" gOp1[i] "'"
    }
    if (gLogic[i] == "AND" || gLogic[i] == "OR") {
        if (!attrExists(m, gAttr2[i])) {
            return "Oznitelik (attribute) bu modulde tanimli degil: '" gAttr2[i] "'"
        }
        if (!isKnownOp(gOp2[i])) {
            return "Bilinmeyen operator: '" gOp2[i] "'"
        }
    }
    return ""
}

// validateRecord'dan gecmis tek kosul icin Filter nesnesi kurar.
// contains: buyuk/kucuk harf duyarsiz (ucuncu parametre false).
Filter buildCondition(string attrName, string op, string val) {
    if (op == "contains")     return contains(attribute attrName, val, false)
    if (op == "equals")       return (attribute attrName == val)
    if (op == "not_equals")   return (attribute attrName != val)
    if (op == "is_empty")     return (attribute attrName == "")
    if (op == "greater_than") return (attribute attrName > val)
    return (attribute attrName < val)   // less_than
}

Filter buildRecord(int i) {
    Filter f1 = buildCondition(gAttr1[i], gOp1[i], gVal1[i])
    if (gLogic[i] == "AND") return (f1 && buildCondition(gAttr2[i], gOp2[i], gVal2[i]))
    if (gLogic[i] == "OR")  return (f1 || buildCondition(gAttr2[i], gOp2[i], gVal2[i]))
    return f1
}

string describeCondition(string a, string o, string v) {
    if (o == "is_empty") return "[" a "] is empty"
    return "[" a "] " o " '" v "'"
}

string describeRecord(int i) {
    string s = describeCondition(gAttr1[i], gOp1[i], gVal1[i])
    if (gLogic[i] == "AND" || gLogic[i] == "OR") {
        s = s " " gLogic[i] " " describeCondition(gAttr2[i], gOp2[i], gVal2[i])
    }
    return s
}

//---------------------------------------------------------------------------
// Modul ve uygulama yardimcilari
//---------------------------------------------------------------------------

// Aktif formal modulu dondurur; uygun degilse mesaj gosterip null dondurur.
Module targetModule() {
    Module m = current
    if (null m) {
        ack "Aktif bir modul yok.\nOnce bir formal modul acin ve pencereyi aktif yapin."
        return m
    }
    if (type(m) != "Formal") {
        ack("Aktif modul formal degil (" type(m) ").\nFiltre paneli yalnizca formal modullerde calisir.")
        Module mNull = null
        return mNull
    }
    return m
}

// Yalnizca filtre katmanini degistirir; view/kolon duzenine dokunmaz.
void applyActive(Module m) {
    set(m, gActive)
    filtering on
    refresh m
    set(gStatus, gActiveDesc)
}

//---------------------------------------------------------------------------
// Liste yonetimi
//---------------------------------------------------------------------------

void clearList() {
    int k
    for (k = 0; k < gListSize; k++) delete(gLst, 0)
    gListSize = 0
}

void fillList() {
    int i
    if (gCount == 0) {
        insert(gLst, 0, "(tanimli filtre yok - Python editorden kaydedin)")
        gListSize = 1
        return
    }
    for (i = 0; i < gCount; i++) insert(gLst, i, gNames[i])
    gListSize = gCount
    set(gLst, 0)
}

int selIndex() {
    if (gCount == 0) return -1
    int s = get gLst
    if (s < 0 || s >= gCount) return -1
    return s
}

//---------------------------------------------------------------------------
// Dugme geri cagrilari (callbacks)
//---------------------------------------------------------------------------

void onApply(DB db) {
    Module m = targetModule()
    if (null m) return
    int i = selIndex()
    if (i < 0) { ack "Once listeden bir filtre secin."; return }
    string err = validateRecord(m, i)
    if (err != "") {
        ack("Filtre uygulanamadi:\n\n" err "\n\nPanel calismaya devam ediyor.")
        return
    }
    gActive = buildRecord(i)
    gHasActive = true
    gActiveDesc = gNames[i]
    applyActive(m)
    set(gDetail, describeRecord(i))
}

// Secili filtreyi, panelden uygulanmis aktif filtreyle AND/OR birlestirir.
// Aktif filtre yoksa dogrudan uygular.
void doCombine(bool useAnd) {
    Module m = targetModule()
    if (null m) return
    int i = selIndex()
    if (i < 0) { ack "Once listeden bir filtre secin."; return }
    string err = validateRecord(m, i)
    if (err != "") {
        ack("Filtre birlestirilemedi:\n\n" err "\n\nPanel calismaya devam ediyor.")
        return
    }
    Filter f = buildRecord(i)
    if (!gHasActive) {
        gActive = f
        gActiveDesc = gNames[i]
    } else {
        if (useAnd) {
            gActive = (gActive && f)
            gActiveDesc = "(" gActiveDesc ") AND (" gNames[i] ")"
        } else {
            gActive = (gActive || f)
            gActiveDesc = "(" gActiveDesc ") OR (" gNames[i] ")"
        }
    }
    gHasActive = true
    applyActive(m)
    set(gDetail, describeRecord(i))
}

void onAnd(DB db) { doCombine(true) }
void onOr(DB db)  { doCombine(false) }

void onRemove(DB db) {
    Module m = targetModule()
    if (null m) return
    filtering off
    refresh m
    gHasActive = false
    gActiveDesc = ""
    set(gStatus, "(filtre yok - filtreleme kapali)")
}

void onDetail(DB db) {
    int i = selIndex()
    if (i < 0) { ack "Once listeden bir filtre secin."; return }
    set(gDetail, describeRecord(i))
}

void onReload(DB db) {
    clearList()
    if (!loadFilters()) {
        ack("Veri dosyasi yeniden yuklenemedi:\n\n" gLoadError)
    }
    fillList()
    set(gDetail, "")
}

void onClose(DB db) {
    hide gDlg
}

//---------------------------------------------------------------------------
// Panel kurulumu ve baslangic
//---------------------------------------------------------------------------

void buildPanel() {
    int n = gCount
    if (n < 1) n = 1
    string items[n]
    int i
    for (i = 0; i < gCount; i++) items[i] = gNames[i]
    if (gCount == 0) items[0] = "(tanimli filtre yok - Python editorden kaydedin)"
    gListSize = n

    gDlg = create "DOORS Filtre Paneli - Kalici Filtre Yoneticisi"
    label(gDlg, "Veri dosyasi: " DAT_FILE)
    gLst    = list(gDlg, "Kayitli filtreler:", 480, 12, items)
    gDetail = field(gDlg, "Secili filtre tanimi:", "", 60)
    gStatus = field(gDlg, "Aktif filtre:", "(yok)", 60)
    button(gDlg, "Uygula",          onApply)
    button(gDlg, "AND ile Ekle",    onAnd)
    button(gDlg, "OR ile Ekle",     onOr)
    button(gDlg, "Detay",           onDetail)
    button(gDlg, "Filtreyi Kaldir", onRemove)
    button(gDlg, "Yeniden Yukle",   onReload)
    button(gDlg, "Kapat",           onClose)
    realize gDlg
    if (gCount > 0) set(gLst, 0)
    show gDlg
}

Module gStartMod = current
if (null gStartMod) {
    ack "Bu script bir formal modul penceresinden calistirilmalidir.\nOnce bir formal modul acin, sonra Tools > Edit DXL ile calistirin."
} else if (type(gStartMod) != "Formal") {
    ack("Aktif modul formal degil (" type(gStartMod) ").\nFiltre paneli yalnizca formal modullerde calisir.")
} else {
    if (!loadFilters()) {
        ack("Filtre verisi yuklenemedi:\n\n" gLoadError "\n\nPanel yine de acilacak; dosyayi olusturduktan sonra 'Yeniden Yukle' dugmesini kullanin.")
    }
    buildPanel()
}
'''


def dxl_escape_path(p):
    return p.replace("\\", "\\\\").replace('"', '\\"')


def generate_dxl_text(dat_path):
    return DXL_TEMPLATE.lstrip("\n").replace("@@DAT_PATH@@", dxl_escape_path(dat_path))


def write_dxl_file(path, dat_path):
    text = generate_dxl_text(dat_path)
    # ascii ile yazmak, sablona yanlislikla ASCII disi karakter girmesini
    # aninda yakalar (DXL editoru Unicode dosyalari guvenilir acamaz).
    with open(path, "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Tkinter GUI
# ---------------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog

    class FilterEditorApp:
        def __init__(self, root):
            self.root = root
            self.folder = None          # seçilen kayıt klasörü
            self.filters = []           # normalize edilmiş dict listesi
            self.edit_index = None      # None = yeni kayıt formu
            self.dirty = False
            self._build_ui()
            self._refresh_title()

        # ---------------- UI kurulumu ----------------

        def _build_ui(self):
            root = self.root
            root.geometry("860x520")
            root.minsize(760, 460)

            top = ttk.Frame(root, padding=(8, 8, 8, 4))
            top.pack(fill="x")
            ttk.Button(top, text="Klasör Seç…", command=self.choose_folder).pack(side="left")
            self.folder_var = tk.StringVar(value="(kayıt klasörü seçilmedi)")
            ttk.Label(top, textvariable=self.folder_var).pack(side="left", padx=8)

            body = ttk.Frame(root, padding=8)
            body.pack(fill="both", expand=True)
            body.columnconfigure(1, weight=1)
            body.rowconfigure(0, weight=1)

            # Sol: filtre listesi
            left = ttk.LabelFrame(body, text="Filtreler", padding=6)
            left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            left.rowconfigure(0, weight=1)
            self.listbox = tk.Listbox(left, width=32, exportselection=False)
            self.listbox.grid(row=0, column=0, sticky="nsew")
            sb = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
            sb.grid(row=0, column=1, sticky="ns")
            self.listbox.configure(yscrollcommand=sb.set)
            self.listbox.bind("<<ListboxSelect>>", self.on_select)

            lbtns = ttk.Frame(left)
            lbtns.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")
            ttk.Button(lbtns, text="Yeni", command=self.on_new).pack(side="left")
            ttk.Button(lbtns, text="Sil", command=self.on_delete).pack(side="left", padx=6)

            # Sağ: düzenleme formu
            form = ttk.LabelFrame(body, text="Filtre Tanımı", padding=8)
            form.grid(row=0, column=1, sticky="nsew")
            for col in (1, 3, 5):
                form.columnconfigure(col, weight=1)

            ttk.Label(form, text="Filtre adı:").grid(row=0, column=0, sticky="w", pady=3)
            self.name_var = tk.StringVar()
            ttk.Entry(form, textvariable=self.name_var).grid(
                row=0, column=1, columnspan=5, sticky="ew", pady=3)

            op_labels = [lbl for _, lbl in OPERATORS]

            ttk.Label(form, text="1. koşul — attribute:").grid(row=1, column=0, sticky="w", pady=3)
            self.attr1_var = tk.StringVar()
            ttk.Entry(form, textvariable=self.attr1_var).grid(row=1, column=1, sticky="ew", pady=3)
            ttk.Label(form, text="operatör:").grid(row=1, column=2, sticky="e", padx=(8, 2))
            self.op1_var = tk.StringVar(value=op_labels[0])
            self.op1_cb = ttk.Combobox(form, textvariable=self.op1_var,
                                       values=op_labels, state="readonly", width=24)
            self.op1_cb.grid(row=1, column=3, sticky="ew", pady=3)
            ttk.Label(form, text="değer:").grid(row=1, column=4, sticky="e", padx=(8, 2))
            self.val1_var = tk.StringVar()
            self.val1_entry = ttk.Entry(form, textvariable=self.val1_var)
            self.val1_entry.grid(row=1, column=5, sticky="ew", pady=3)

            ttk.Label(form, text="Mantıksal bağ:").grid(row=2, column=0, sticky="w", pady=3)
            self.logic_var = tk.StringVar(value="NONE")
            self.logic_cb = ttk.Combobox(form, textvariable=self.logic_var,
                                         values=LOGIC_CHOICES, state="readonly", width=8)
            self.logic_cb.grid(row=2, column=1, sticky="w", pady=3)
            ttk.Label(form, text="(NONE = tek koşul)").grid(
                row=2, column=2, columnspan=2, sticky="w")

            ttk.Label(form, text="2. koşul — attribute:").grid(row=3, column=0, sticky="w", pady=3)
            self.attr2_var = tk.StringVar()
            self.attr2_entry = ttk.Entry(form, textvariable=self.attr2_var)
            self.attr2_entry.grid(row=3, column=1, sticky="ew", pady=3)
            ttk.Label(form, text="operatör:").grid(row=3, column=2, sticky="e", padx=(8, 2))
            self.op2_var = tk.StringVar(value=op_labels[0])
            self.op2_cb = ttk.Combobox(form, textvariable=self.op2_var,
                                       values=op_labels, state="readonly", width=24)
            self.op2_cb.grid(row=3, column=3, sticky="ew", pady=3)
            ttk.Label(form, text="değer:").grid(row=3, column=4, sticky="e", padx=(8, 2))
            self.val2_var = tk.StringVar()
            self.val2_entry = ttk.Entry(form, textvariable=self.val2_var)
            self.val2_entry.grid(row=3, column=5, sticky="ew", pady=3)

            fbtns = ttk.Frame(form)
            fbtns.grid(row=4, column=0, columnspan=6, pady=(10, 0), sticky="w")
            ttk.Button(fbtns, text="Formu Kaydet (Ekle/Güncelle)",
                       command=self.on_save_form).pack(side="left")
            ttk.Button(fbtns, text="Formu Temizle", command=self.on_new).pack(
                side="left", padx=6)

            self.logic_var.trace_add("write", lambda *_: self._sync_cond2_state())
            self.op1_var.trace_add("write", lambda *_: self._sync_value_states())
            self.op2_var.trace_add("write", lambda *_: self._sync_value_states())

            # Alt: dosya işlemleri + durum çubuğu
            bottom = ttk.Frame(root, padding=(8, 4, 8, 8))
            bottom.pack(fill="x")
            ttk.Button(bottom, text="Dosyaya Kaydet (filters.json + filters.dat)",
                       command=self.on_save_files).pack(side="left")
            ttk.Button(bottom, text="DXL Üret…", command=self.on_generate_dxl).pack(
                side="left", padx=6)
            self.status_var = tk.StringVar(value="Hazır.")
            ttk.Label(bottom, textvariable=self.status_var, anchor="e").pack(
                side="right", fill="x", expand=True)

            root.protocol("WM_DELETE_WINDOW", self.on_close)
            self._sync_cond2_state()

        # ---------------- yardımcılar ----------------

        def _refresh_title(self):
            mark = " *" if self.dirty else ""
            self.root.title(APP_TITLE + mark)

        def _set_status(self, text):
            self.status_var.set(text)

        def _set_dirty(self, dirty=True):
            self.dirty = dirty
            self._refresh_title()

        def _sync_cond2_state(self):
            enabled = self.logic_var.get() in ("AND", "OR")
            state = "normal" if enabled else "disabled"
            cb_state = "readonly" if enabled else "disabled"
            self.attr2_entry.configure(state=state)
            self.op2_cb.configure(state=cb_state)
            self.val2_entry.configure(state=state)
            self._sync_value_states()

        def _sync_value_states(self):
            op1 = OP_CODE_BY_LABEL.get(self.op1_var.get(), "contains")
            self.val1_entry.configure(
                state="disabled" if op1 in NO_VALUE_OPS else "normal")
            if self.logic_var.get() in ("AND", "OR"):
                op2 = OP_CODE_BY_LABEL.get(self.op2_var.get(), "contains")
                self.val2_entry.configure(
                    state="disabled" if op2 in NO_VALUE_OPS else "normal")

        def _form_to_dict(self):
            d = new_filter_dict()
            d["name"] = self.name_var.get().strip()
            d["attr1"] = self.attr1_var.get().strip()
            d["op1"] = OP_CODE_BY_LABEL.get(self.op1_var.get(), "contains")
            d["val1"] = "" if d["op1"] in NO_VALUE_OPS else self.val1_var.get().strip()
            d["logic"] = self.logic_var.get()
            if d["logic"] in ("AND", "OR"):
                d["attr2"] = self.attr2_var.get().strip()
                d["op2"] = OP_CODE_BY_LABEL.get(self.op2_var.get(), "contains")
                d["val2"] = "" if d["op2"] in NO_VALUE_OPS else self.val2_var.get().strip()
            return d

        def _dict_to_form(self, d):
            self.name_var.set(d["name"])
            self.attr1_var.set(d["attr1"])
            self.op1_var.set(OP_LABEL_BY_CODE.get(d["op1"], OPERATORS[0][1]))
            self.val1_var.set(d["val1"])
            self.logic_var.set(d["logic"])
            self.attr2_var.set(d["attr2"])
            self.op2_var.set(OP_LABEL_BY_CODE.get(d["op2"], OPERATORS[0][1]))
            self.val2_var.set(d["val2"])
            self._sync_cond2_state()

        def _refresh_listbox(self, select=None):
            self.listbox.delete(0, "end")
            for f in self.filters:
                self.listbox.insert("end", f["name"])
            if select is not None and 0 <= select < len(self.filters):
                self.listbox.selection_set(select)
                self.listbox.see(select)

        # ---------------- olaylar ----------------

        def choose_folder(self):
            folder = filedialog.askdirectory(title="filters.json klasörünü seçin")
            if not folder:
                return
            if self.dirty and not messagebox.askyesno(
                    "Kaydedilmemiş değişiklik",
                    "Kaydedilmemiş değişiklikler var. Yine de klasör değiştirilsin mi?"):
                return
            self.folder = folder
            self.folder_var.set(folder)
            json_path = os.path.join(folder, JSON_NAME)
            if os.path.exists(json_path):
                try:
                    self.filters = read_json_file(json_path)
                    self._set_status("%d filtre yüklendi: %s" % (len(self.filters), json_path))
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    messagebox.showerror("Yükleme hatası",
                                         "filters.json okunamadı:\n%s" % exc)
                    return
            else:
                self.filters = []
                self._set_status("Yeni klasör; filters.json henüz yok.")
            self.edit_index = None
            self._dict_to_form(new_filter_dict())
            self._refresh_listbox()
            self._set_dirty(False)

        def on_select(self, _event=None):
            sel = self.listbox.curselection()
            if not sel:
                return
            self.edit_index = sel[0]
            self._dict_to_form(self.filters[self.edit_index])
            self._set_status("Düzenleniyor: %s" % self.filters[self.edit_index]["name"])

        def on_new(self):
            self.edit_index = None
            self.listbox.selection_clear(0, "end")
            self._dict_to_form(new_filter_dict())
            self._set_status("Yeni filtre formu.")

        def on_save_form(self):
            d = normalize_filter(self._form_to_dict())
            others = [f["name"] for i, f in enumerate(self.filters)
                      if i != self.edit_index]
            errs = validate_filter(d, others)
            if errs:
                messagebox.showerror("Geçersiz filtre", "\n".join(errs))
                return
            bad = cp1254_problem_chars(d)
            if bad and not messagebox.askyesno(
                    "Karakter uyarısı",
                    "Şu karakterler DOORS veri dosyasına (%s) yazılamaz ve '?' "
                    "ile değiştirilir:\n\n%s\n\nDevam edilsin mi?"
                    % (DAT_ENCODING, "  ".join(bad))):
                return
            if self.edit_index is None:
                self.filters.append(d)
                self.edit_index = len(self.filters) - 1
                self._set_status("Filtre eklendi: %s" % d["name"])
            else:
                self.filters[self.edit_index] = d
                self._set_status("Filtre güncellendi: %s" % d["name"])
            self._refresh_listbox(select=self.edit_index)
            self._set_dirty(True)

        def on_delete(self):
            sel = self.listbox.curselection()
            if not sel:
                messagebox.showinfo("Silme", "Önce listeden bir filtre seçin.")
                return
            idx = sel[0]
            name = self.filters[idx]["name"]
            if not messagebox.askyesno("Silme onayı", "'%s' silinsin mi?" % name):
                return
            del self.filters[idx]
            self.edit_index = None
            self._dict_to_form(new_filter_dict())
            self._refresh_listbox()
            self._set_dirty(True)
            self._set_status("Silindi: %s" % name)

        def on_save_files(self):
            if not self.folder:
                messagebox.showinfo("Klasör gerekli", "Önce 'Klasör Seç…' ile kayıt klasörünü seçin.")
                return
            json_path = os.path.join(self.folder, JSON_NAME)
            dat_path = os.path.join(self.folder, DAT_NAME)
            try:
                write_json_file(json_path, self.filters)
                write_dat_file(dat_path, self.filters)
            except OSError as exc:
                messagebox.showerror("Kayıt hatası", "Dosyalar yazılamadı:\n%s" % exc)
                return
            self._set_dirty(False)
            self._set_status("Kaydedildi: %s ve %s" % (JSON_NAME, DAT_NAME))

        def on_generate_dxl(self):
            if not self.folder:
                messagebox.showinfo("Klasör gerekli", "Önce 'Klasör Seç…' ile kayıt klasörünü seçin.")
                return
            if self.dirty:
                if messagebox.askyesno(
                        "Kaydedilmemiş değişiklik",
                        "Kaydedilmemiş değişiklikler var. Önce dosyaya kaydedilsin mi?"):
                    self.on_save_files()
                    if self.dirty:   # kayıt başarısız olduysa
                        return
            default_dat = os.path.abspath(os.path.join(self.folder, DAT_NAME))
            dat_path = simpledialog.askstring(
                "filters.dat yolu",
                "DXL script'in DOORS makinesinde okuyacağı filters.dat yolu\n"
                "(farklı bir makinede kullanılacaksa oradaki yolu yazın):",
                initialvalue=default_dat, parent=self.root)
            if not dat_path:
                return
            out_path = filedialog.asksaveasfilename(
                title="DXL dosyasını kaydet",
                initialdir=self.folder,
                initialfile="doors_filter_panel.dxl",
                defaultextension=".dxl",
                filetypes=[("DXL script", "*.dxl"), ("Tüm dosyalar", "*.*")])
            if not out_path:
                return
            try:
                write_dxl_file(out_path, dat_path.strip())
            except OSError as exc:
                messagebox.showerror("DXL üretim hatası", "Dosya yazılamadı:\n%s" % exc)
                return
            self._set_status("DXL üretildi: %s" % out_path)
            messagebox.showinfo(
                "DXL üretildi",
                "DXL dosyası oluşturuldu:\n%s\n\nDOORS'ta formal modül açıkken "
                "Tools > Edit DXL > Load… ile yükleyip Run ile çalıştırın.\n"
                "Ayrıntılar için README.md dosyasına bakın." % out_path)

        def on_close(self):
            if self.dirty and not messagebox.askyesno(
                    "Çıkış", "Kaydedilmemiş değişiklikler var. Yine de çıkılsın mı?"):
                return
            self.root.destroy()

    root = tk.Tk()
    FilterEditorApp(root)
    root.mainloop()


# ---------------------------------------------------------------------------
# Komut satırı girişi
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="DOORS Kalıcı Filtre Yöneticisi — Filtre Editörü. "
                    "Argümansız çalıştırılırsa GUI açılır.")
    parser.add_argument("--emit-dxl", metavar="CIKTI.dxl",
                        help="GUI açmadan DXL dosyası üret.")
    parser.add_argument("--dat-path", metavar="YOL", default=DEFAULT_DAT_PATH,
                        help="--emit-dxl için DXL içine gömülecek filters.dat "
                             "yolu (varsayılan: %s)" % DEFAULT_DAT_PATH)
    parser.add_argument("--export-dat", nargs=2, metavar=("GIRDI.json", "CIKTI.dat"),
                        help="GUI açmadan filters.json'dan filters.dat üret.")
    args = parser.parse_args(argv)

    if args.emit_dxl:
        write_dxl_file(args.emit_dxl, args.dat_path)
        print("DXL uretildi: %s (dat yolu: %s)" % (args.emit_dxl, args.dat_path))
        return 0

    if args.export_dat:
        src, dst = args.export_dat
        filters = read_json_file(src)
        write_dat_file(dst, filters)
        print("dat uretildi: %s (%d filtre)" % (dst, len(filters)))
        return 0

    run_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
