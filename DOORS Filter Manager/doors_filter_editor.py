#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOORS Filtre Yöneticisi — Filtre Editörü (Python / Tkinter)
===========================================================

IBM DOORS 9.x (klasik, DXL destekli) için filtre tanımlarını düzenleyen
masaüstü uygulama. Bir filtre, VE/VEYA ile zincirlenen 1..10 koşuldan
oluşur; koşullar soldan sağa birleştirilir: ((k1 ∘ k2) ∘ k3) ...

Tanımlar iki dosyaya kaydedilir:

  * filters.json  — kanonik, insan tarafından okunabilir kayıt (bu editör
                    tarafından okunur/yazılır). Sürüm 2 şeması; eski (v1,
                    attr1/attr2'li) dosyalar da okunur ve dönüştürülür.
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

APP_TITLE = "DOORS Filtre Yöneticisi"
JSON_NAME = "filters.json"
DAT_NAME = "filters.dat"

# DOORS klasik DXL, dosyaları yerel ANSI kod sayfasıyla okur. Türkçe
# Windows'ta bu cp1254'tür. Farklı yerel ayardaki bir DOORS istemcisi için
# bu sabiti değiştirin (ör. "cp1252").
DAT_ENCODING = "cp1254"

DEFAULT_DAT_PATH = r"C:\DOORS_Filters\filters.dat"

# Bir filtredeki en fazla koşul sayısı (UI ve format üst sınırı; DXL
# tarafındaki toplam koşul havuzu MAX_CONDS=2000 ile ayrıca sınırlıdır).
MAX_CONDITIONS = 10

# (kod, ekranda gösterilen etiket) — kod .json/.dat/DXL tarafında kullanılır.
OPERATORS = [
    ("contains",     "içerir"),
    ("equals",       "eşittir"),
    ("not_equals",   "eşit değildir"),
    ("is_empty",     "boştur"),
    ("greater_than", "büyüktür"),
    ("less_than",    "küçüktür"),
]
OP_CODES = [c for c, _ in OPERATORS]
OP_LABEL_BY_CODE = dict(OPERATORS)
OP_CODE_BY_LABEL = {lbl: c for c, lbl in OPERATORS}
NO_VALUE_OPS = {"is_empty"}


def new_cond():
    return {"logic": "AND", "attr": "", "op": "contains", "val": ""}


def new_filter_dict():
    return {"name": "", "conditions": [new_cond()]}


def _normalize_cond(c):
    out = new_cond()
    lg = str(c.get("logic", "AND") or "AND").strip().upper()
    out["logic"] = "OR" if lg == "OR" else "AND"
    out["attr"] = str(c.get("attr", "") or "").strip()
    op = str(c.get("op", "contains") or "").strip()
    out["op"] = op if op in OP_CODES else "contains"
    out["val"] = ("" if out["op"] in NO_VALUE_OPS
                  else str(c.get("val", "") or "").strip())
    return out


def normalize_filter(d):
    """Eksik anahtarları tamamlar; v1 şemasını (attr1/attr2) v2'ye çevirir."""
    name = str(d.get("name", "") or "").strip()
    conds = d.get("conditions")
    if not isinstance(conds, list):
        # v1 şeması: attr1/op1/val1 [+ logic + attr2/op2/val2]
        conds = [{"attr": d.get("attr1", ""), "op": d.get("op1", "contains"),
                  "val": d.get("val1", "")}]
        if str(d.get("logic", "NONE") or "").strip().upper() in ("AND", "OR"):
            conds.append({"logic": d.get("logic"), "attr": d.get("attr2", ""),
                          "op": d.get("op2", "contains"),
                          "val": d.get("val2", "")})
    out = [_normalize_cond(c) for c in conds if isinstance(c, dict)]
    out = out[:MAX_CONDITIONS]
    if not out:
        out = [new_cond()]
    return {"name": name, "conditions": out}


def validate_filter(d, other_names):
    """Hata mesajları listesi döndürür (boş liste = geçerli)."""
    errs = []
    name = d["name"]
    if not name:
        errs.append("Filtre adı boş olamaz.")
    elif name in other_names:
        errs.append("'%s' adında başka bir filtre zaten var." % name)

    for i, c in enumerate(d["conditions"], start=1):
        if not c["attr"]:
            errs.append("%d. koşul: attribute adı boş olamaz." % i)
        if c["op"] not in NO_VALUE_OPS and not c["val"]:
            errs.append("%d. koşul: değer boş olamaz "
                        "(boşluk kontrolü için 'boştur' kullanın)." % i)
        for v in (c["attr"], c["val"]):
            if "\n" in v or "\r" in v:
                errs.append("%d. koşul: alanlar satır sonu karakteri "
                            "içeremez." % i)
                break
    if "\n" in name or "\r" in name:
        errs.append("Filtre adı satır sonu karakteri içeremez.")
    return errs


def cp1254_problem_chars(d):
    """filters.dat'a yazılamayacak (kod sayfası dışı) karakterleri döndürür."""
    bad = set()
    texts = [d.get("name", "")]
    for c in d.get("conditions", []):
        texts += [c.get("attr", ""), c.get("val", "")]
    for text in texts:
        for ch in text:
            try:
                ch.encode(DAT_ENCODING)
            except UnicodeEncodeError:
                bad.add(ch)
    return sorted(bad)


# ---------------------------------------------------------------------------
# JSON ve DAT serileştirme
# ---------------------------------------------------------------------------

def filters_to_json_text(filters):
    out = []
    for f in filters:
        conds = []
        for i, c in enumerate(f["conditions"]):
            item = {"attr": c["attr"], "op": c["op"], "val": c["val"]}
            if i > 0:
                item["logic"] = c["logic"]
            conds.append(item)
        out.append({"name": f["name"], "conditions": conds})
    doc = {"format": "doors-filter-manager", "version": 2, "filters": out}
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
    DXL tarafının okuduğu satır bazlı format (v2). Kayıt yapısı:

        FILTER
        name=Filtre Adı
        attr=Status
        op=equals
        val=Approved
        logic=AND            <- SONRAKİ koşulu öncekine bağlar
        attr=Priority
        op=equals
        val=High
        END

    '#' ile başlayan satırlar yorumdur. Her satır ilk '=' işaretinden
    bölünür (değer '=' içerebilir). Koşullar dosyadaki sırayla soldan sağa
    birleştirilir: ((k1 ∘ k2) ∘ k3)... DXL parser eski v1 anahtarlarını da
    (attr1/op1/val1/attr2/...) sondaki rakamı atarak aynı şemaya indirger.
    """
    lines = [
        "# DOORS Filter Manager veri dosyasi (v2)",
        "# Kosullar soldan saga birlestirilir: ((k1 . k2) . k3) ...",
        "# Bu dosya doors_filter_editor.py tarafindan uretilir; elle duzenlemeyin.",
        "",
    ]
    for f in filters:
        lines.append("FILTER")
        lines.append("name=%s" % f["name"])
        for i, c in enumerate(f["conditions"]):
            if i > 0:
                lines.append("logic=%s" % c["logic"])
            lines.append("attr=%s" % c["attr"])
            lines.append("op=%s" % c["op"])
            lines.append("val=%s" % c["val"])
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
// filters.dat dosyasi ayni Python editorun kayit adiminda uretilir.
//
// Veri formati (v2): FILTER/END bloklari; name= ve tekrarlanan
// attr=/op=/val= gruplari; gruplar arasinda logic=AND|OR satiri.
// Kosullar dosyadaki sirayla soldan saga birlestirilir:
//   ((k1 . k2) . k3) ...
// Eski v1 anahtarlari (attr1/op1/...) sondaki rakam atilarak okunur.
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
int MAX_CONDS   = 2000

//---------------------------------------------------------------------------
// Filtre kayitlari (filters.dat'tan yuklenir)
// Her filtre, kosul havuzunda [gCondStart, gCondStart+gCondCount) araligini
// kullanir. gCLogic[k], k. kosulu bir oncekine baglayan operatordur
// ("AND"/"OR"; her filtrenin ilk kosulunda bos string).
//---------------------------------------------------------------------------

int    gCount = 0
string gNames[MAX_FILTERS]
int    gCondStart[MAX_FILTERS]
int    gCondCount[MAX_FILTERS]

int    gCondTotal = 0
string gCAttr[MAX_CONDS]
string gCOp[MAX_CONDS]
string gCVal[MAX_CONDS]
string gCLogic[MAX_CONDS]

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

// Anahtarin sonundaki rakamlari atar: "attr2" -> "attr" (v1 uyumu).
string baseKey(string k) {
    int n = length k
    int j = n
    while (j > 0) {
        char c = k[j-1]
        if (c >= '0' && c <= '9') j--
        else break
    }
    if (j <= 0 || j == n) return k
    return k[0:j-1]
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

bool attrExists(Module m, string attrName) {
    if (null m) return false
    AttrDef ad = find(m, attrName)
    return (!(null ad))
}

//---------------------------------------------------------------------------
// filters.dat yukleme
//---------------------------------------------------------------------------

// Bekleyen kosulu havuza ekler. lg: bu kosulu oncekine baglayan operator.
void commitPending(string a, string o, string v, string lg, int &curCount) {
    if (a == "" || o == "") return
    if (gCondTotal >= MAX_CONDS) return
    gCAttr[gCondTotal] = a
    gCOp[gCondTotal]   = o
    gCVal[gCondTotal]  = v
    if (curCount == 0) gCLogic[gCondTotal] = ""
    else if (lg == "OR") gCLogic[gCondTotal] = "OR"
    else gCLogic[gCondTotal] = "AND"
    gCondTotal++
    curCount++
}

bool loadFilters() {
    gCount = 0
    gCondTotal = 0
    gLoadError = ""

    Stat st = create(DAT_FILE)
    if (null st) {
        gLoadError = "Veri dosyasi bulunamadi:\n" DAT_FILE "\n\nOnce Python editorde filtre kaydedin."
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
    string nm = ""
    int recStart = 0
    int curCount = 0
    // bekleyen (henuz havuza yazilmamis) kosul:
    string pAttr = ""; string pOp = ""; string pVal = ""
    string pLogic = ""         // bekleyen kosulu oncekine baglayan operator
    string pendingLogic = ""   // en son okunan logic= degeri (sonraki kosul icin)

    while (true) {
        if (end of inp) break
        inp >> line
        line = trimStr(line)
        if (line == "") continue
        if (line[0] == '#') continue

        if (line == "FILTER") {
            inRec = true
            nm = ""
            recStart = gCondTotal
            curCount = 0
            pAttr = ""; pOp = ""; pVal = ""
            pLogic = ""; pendingLogic = ""
            continue
        }

        if (line == "END") {
            if (inRec) {
                commitPending(pAttr, pOp, pVal, pLogic, curCount)
                if (nm != "" && curCount > 0 && gCount < MAX_FILTERS) {
                    gNames[gCount] = nm
                    gCondStart[gCount] = recStart
                    gCondCount[gCount] = curCount
                    gCount++
                } else {
                    gCondTotal = recStart   // gecersiz kayit: kosullari geri al
                }
            }
            inRec = false
            continue
        }

        if (!inRec) continue

        if (splitKeyValue(line, key, val)) {
            key = baseKey(trimStr(key))
            if (key == "name") nm = val
            else if (key == "attr") {
                if (pAttr != "") commitPending(pAttr, pOp, pVal, pLogic, curCount)
                pAttr = val; pOp = ""; pVal = ""
                pLogic = trimStr(pendingLogic)
                pendingLogic = ""
            }
            else if (key == "op")    pOp = val
            else if (key == "val")   pVal = val
            else if (key == "logic") pendingLogic = val
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
    int s = gCondStart[i]
    int k
    for (k = 0; k < gCondCount[i]; k++) {
        if (!attrExists(m, gCAttr[s+k])) {
            return "Oznitelik (attribute) bu modulde tanimli degil: '" gCAttr[s+k] "'"
        }
        if (!isKnownOp(gCOp[s+k])) {
            return "Bilinmeyen operator: '" gCOp[s+k] "'"
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

// Kosullari soldan saga birlestirir: ((k1 . k2) . k3) ...
Filter buildRecord(int i) {
    int s = gCondStart[i]
    Filter f = buildCondition(gCAttr[s], gCOp[s], gCVal[s])
    int k
    for (k = 1; k < gCondCount[i]; k++) {
        Filter fk = buildCondition(gCAttr[s+k], gCOp[s+k], gCVal[s+k])
        if (gCLogic[s+k] == "OR") f = (f || fk)
        else f = (f && fk)
    }
    return f
}

string describeCondition(string a, string o, string v) {
    if (o == "is_empty") return "[" a "] is empty"
    return "[" a "] " o " '" v "'"
}

string describeRecord(int i) {
    int s = gCondStart[i]
    string out = ""
    int k
    for (k = 0; k < gCondCount[i]; k++) {
        if (k > 0) out = out " " gCLogic[s+k] " "
        out = out describeCondition(gCAttr[s+k], gCOp[s+k], gCVal[s+k])
    }
    if (gCondCount[i] > 2) out = out "   (soldan saga birlesir)"
    return out
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
// DXL'de button() callback'leri DBE (dugme elemani) parametresi alir;
// DB alan imzalar 'incorrect arguments for function (button)' hatasi verir.
//---------------------------------------------------------------------------

void onApply(DBE dbe) {
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

void onAnd(DBE dbe) { doCombine(true) }
void onOr(DBE dbe)  { doCombine(false) }

void onRemove(DBE dbe) {
    Module m = targetModule()
    if (null m) return
    filtering off
    refresh m
    gHasActive = false
    gActiveDesc = ""
    set(gStatus, "(filtre yok - filtreleme kapali)")
}

void onDetail(DBE dbe) {
    int i = selIndex()
    if (i < 0) { ack "Once listeden bir filtre secin."; return }
    set(gDetail, describeRecord(i))
}

void onReload(DBE dbe) {
    clearList()
    if (!loadFilters()) {
        ack("Veri dosyasi yeniden yuklenemedi:\n\n" gLoadError)
    }
    fillList()
    set(gDetail, "")
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

    DBE lblFile = label(gDlg, "Veri dosyasi: " DAT_FILE)
    gLst = list(gDlg, "Kayitli filtreler:", 320, 12, items)
    gLst->"right"->"unattached"

    gDetail = field(gDlg, "Secili filtre tanimi:", "", 55)
    gStatus = field(gDlg, "Aktif filtre:", "(yok)", 55)

    // Dugmeler listenin sag yanina dikey kolon olarak yerlesir.
    // Hepsinin sol kenari listenin sag kenarina, sag kenari pencereye
    // baglanir; boylece esit genislikte hizali bir kolon olusur.
    // (Kapat dugmesi yok: DOORS pencereye kendi Close dugmesini ekler.)
    DBE bApply  = button(gDlg, "Uygula",          onApply)
    DBE bAnd    = button(gDlg, "AND ile Ekle",    onAnd)
    DBE bOr     = button(gDlg, "OR ile Ekle",     onOr)
    DBE bDetail = button(gDlg, "Detay",           onDetail)
    DBE bRemove = button(gDlg, "Filtreyi Kaldir", onRemove)
    DBE bReload = button(gDlg, "Yeniden Yukle",   onReload)

    bApply->"top"->"spaced"->lblFile
    bApply->"left"->"spaced"->gLst
    bApply->"right"->"form"

    bAnd->"top"->"spaced"->bApply
    bAnd->"left"->"spaced"->gLst
    bAnd->"right"->"form"

    bOr->"top"->"spaced"->bAnd
    bOr->"left"->"spaced"->gLst
    bOr->"right"->"form"

    bDetail->"top"->"spaced"->bOr
    bDetail->"left"->"spaced"->gLst
    bDetail->"right"->"form"

    bRemove->"top"->"spaced"->bDetail
    bRemove->"left"->"spaced"->gLst
    bRemove->"right"->"form"

    bReload->"top"->"spaced"->bRemove
    bReload->"left"->"spaced"->gLst
    bReload->"right"->"form"

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

def run_gui(test_hook=None):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from datetime import datetime

    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".doors_filter_editor.json")

    # ---- görsel tema ------------------------------------------------------
    NAVY = "#1f3a5f"          # başlık çubuğu
    NAVY_SOFT = "#bcd0e8"     # başlıktaki ikincil metin
    ACCENT = "#2f6fdb"        # ana eylem rengi
    ACCENT_DARK = "#265cb8"
    BG = "#eef1f5"            # pencere zemini
    CARD = "#ffffff"          # kart zemini
    TEXT = "#1c2733"
    MUTED = "#5c6b7a"
    OK_GREEN = "#1e7e34"
    ERR_RED = "#c0392b"
    ATTR_BLUE = "#1d4ed8"     # önizlemede attribute rengi
    VAL_GREEN = "#0b7a4b"     # önizlemede değer rengi

    COMMON_ATTRS = [
        "Object Text", "Object Heading", "Object Short Text",
        "Status", "Priority", "Rationale",
        "Created By", "Created On", "Last Modified By", "Last Modified On",
        "Absolute Number",
    ]

    TEMPLATES = [
        ("Metinde kelime ara",
         {"name": "Kelime Ara", "conditions": [
             {"attr": "Object Text", "op": "contains", "val": ""}]}),
        ("Duruma göre süz (Status)",
         {"name": "Durum Filtresi", "conditions": [
             {"attr": "Status", "op": "equals", "val": ""}]}),
        ("Boş bırakılmış alanları bul",
         {"name": "Bos Alanlar", "conditions": [
             {"attr": "Rationale", "op": "is_empty", "val": ""}]}),
        ("İki koşullu örnek (VE)",
         {"name": "Oncelikli ve Acik", "conditions": [
             {"attr": "Priority", "op": "equals", "val": "High"},
             {"logic": "AND", "attr": "Status", "op": "not_equals",
              "val": "Closed"}]}),
        ("Üç koşullu örnek (VEYA + VE)",
         {"name": "Aday Gereksinimler", "conditions": [
             {"attr": "Status", "op": "equals", "val": "Proposed"},
             {"logic": "OR", "attr": "Status", "op": "equals",
              "val": "In Review"},
             {"logic": "AND", "attr": "Priority", "op": "equals",
              "val": "High"}]}),
    ]

    LOGIC_TR = {"AND": "VE", "OR": "VEYA"}
    LOGIC_FROM_TR = {"VE": "AND", "VEYA": "OR"}

    def load_config():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save_config(cfg):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass  # yapılandırma yazılamazsa sessizce geç; işlevsellik etkilenmez

    class FilterEditorApp:
        def __init__(self, root):
            self.root = root
            self.folder = None
            self.filters = []
            self.edit_index = None        # None = yeni kayıt formu
            self._form_snapshot = None    # son yüklenen formun normalize hali
            self._suppress_select = False
            self.rows = []                # dinamik koşul satırları

            self._setup_fonts_and_style()
            root.title(APP_TITLE)
            root.geometry("1020x680")
            root.minsize(900, 600)
            root.configure(bg=BG)

            self._build_header()
            self._build_welcome()
            self._build_main()
            self._build_footer()
            self._show_welcome()

            cfg = load_config()
            last = cfg.get("last_folder")
            if last and os.path.isdir(last):
                self._open_folder(last, interactive=False)

        # ------------------------------------------------ tema / yazı tipi
        def _setup_fonts_and_style(self):
            fams = set(tkfont.families())
            self.F = ("Segoe UI" if "Segoe UI" in fams
                      else "DejaVu Sans" if "DejaVu Sans" in fams
                      else tkfont.nametofont("TkDefaultFont").actual("family"))
            F = self.F
            style = ttk.Style(self.root)
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure(".", background=BG, foreground=TEXT, font=(F, 10))
            style.configure("Card.TFrame", background=CARD)
            style.configure("Card.TLabel", background=CARD, foreground=TEXT)
            style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT,
                            font=(F, 11, "bold"))
            style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
            style.configure("BgMuted.TLabel", background=BG, foreground=MUTED)
            style.configure("Error.TLabel", background=CARD, foreground=ERR_RED,
                            font=(F, 9))
            style.configure("Accent.TButton", background=ACCENT, foreground="white",
                            padding=(14, 7), borderwidth=0, focusthickness=1,
                            font=(F, 10, "bold"))
            style.map("Accent.TButton",
                      background=[("active", ACCENT_DARK), ("disabled", "#9db4d6")])
            style.configure("Ghost.TButton", background=CARD, foreground=TEXT,
                            padding=(10, 5))
            style.configure("Link.TButton", background=CARD, foreground=ACCENT,
                            borderwidth=0, padding=(2, 2), font=(F, 10, "underline"))
            style.map("Link.TButton", foreground=[("active", ACCENT_DARK)],
                      background=[("active", CARD)])
            style.configure("Treeview", rowheight=26, background=CARD,
                            fieldbackground=CARD, font=(F, 10))
            style.configure("Treeview.Heading", font=(F, 10, "bold"))
            style.configure("TCombobox", padding=3)
            style.configure("TEntry", padding=3)
            style.configure("TMenubutton", background=CARD, padding=(10, 5))

        # ------------------------------------------------ üst çubuk
        def _build_header(self):
            h = tk.Frame(self.root, bg=NAVY)
            h.pack(fill="x")
            tk.Label(h, text="DOORS Filtre Yöneticisi", bg=NAVY, fg="white",
                     font=(self.F, 14, "bold")).pack(side="left", padx=14, pady=10)
            self.folder_lbl = tk.Label(h, text="", bg=NAVY, fg=NAVY_SOFT,
                                       font=(self.F, 9))
            self.folder_lbl.pack(side="left", padx=6)
            self.change_btn = tk.Button(
                h, text="Klasör Değiştir", command=self.choose_folder,
                bg=NAVY, fg="white", activebackground=ACCENT_DARK,
                activeforeground="white", relief="flat", bd=0,
                font=(self.F, 9), padx=10, pady=4, cursor="hand2")
            self.change_btn.pack(side="right", padx=12)

        # ------------------------------------------------ karşılama ekranı
        def _build_welcome(self):
            self.welcome = tk.Frame(self.root, bg=BG)
            card = tk.Frame(self.welcome, bg=CARD, padx=44, pady=36,
                            highlightbackground="#d5dce5", highlightthickness=1)
            card.place(relx=0.5, rely=0.44, anchor="center")
            tk.Label(card, text="Hoş geldiniz", bg=CARD, fg=TEXT,
                     font=(self.F, 16, "bold")).pack(anchor="w")
            tk.Label(card,
                     text="Üç adımda DOORS filtreleriniz hazır:",
                     bg=CARD, fg=MUTED, font=(self.F, 10)).pack(anchor="w", pady=(4, 14))
            steps = [
                ("1", "Filtrelerin saklanacağı bir klasör seçin"),
                ("2", "Filtrelerinizi cümle kurar gibi tanımlayın — her değişiklik otomatik kaydedilir"),
                ("3", "'DXL Üret' ile DOORS paneli scriptini alın ve modülde çalıştırın"),
            ]
            for no, txt in steps:
                row = tk.Frame(card, bg=CARD)
                row.pack(anchor="w", pady=3, fill="x")
                tk.Label(row, text=no, bg=ACCENT, fg="white", width=2,
                         font=(self.F, 10, "bold")).pack(side="left")
                tk.Label(row, text=" " + txt, bg=CARD, fg=TEXT,
                         font=(self.F, 10)).pack(side="left")
            ttk.Button(card, text="Klasör Seç ve Başla", style="Accent.TButton",
                       command=self.choose_folder).pack(anchor="w", pady=(20, 0))

        def _show_welcome(self):
            self.welcome.pack(fill="both", expand=True)

        def _show_main(self):
            self.welcome.pack_forget()
            self.main.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        # ------------------------------------------------ ana düzen
        def _build_main(self):
            self.main = tk.Frame(self.root, bg=BG)

            # -- sol: filtre listesi
            left = tk.Frame(self.main, bg=CARD, padx=10, pady=10,
                            highlightbackground="#d5dce5", highlightthickness=1)
            left.pack(side="left", fill="both", padx=(0, 12))
            ttk.Label(left, text="Filtrelerim", style="CardTitle.TLabel").pack(anchor="w")
            self.tree = ttk.Treeview(left, columns=("ozet",), show="tree headings",
                                     height=16, selectmode="browse")
            self.tree.heading("#0", text="Ad", anchor="w")
            self.tree.heading("ozet", text="Özet", anchor="w")
            self.tree.column("#0", width=170, stretch=False)
            self.tree.column("ozet", width=240)
            self.tree.pack(fill="both", expand=True, pady=(8, 8))
            self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
            self.tree.bind("<Delete>", lambda e: self.on_delete())

            lb = tk.Frame(left, bg=CARD)
            lb.pack(fill="x")
            ttk.Button(lb, text="+ Yeni Filtre", style="Accent.TButton",
                       command=self.on_new).pack(side="left")
            ttk.Button(lb, text="Kopyala", style="Ghost.TButton",
                       command=self.on_copy).pack(side="left", padx=6)
            ttk.Button(lb, text="Sil", style="Ghost.TButton",
                       command=self.on_delete).pack(side="left")

            # -- sağ: düzenleme formu
            right = tk.Frame(self.main, bg=CARD, padx=16, pady=12,
                             highlightbackground="#d5dce5", highlightthickness=1)
            right.pack(side="left", fill="both", expand=True)

            top = tk.Frame(right, bg=CARD)
            top.pack(fill="x")
            ttk.Label(top, text="Filtre Tanımla", style="CardTitle.TLabel").pack(side="left")
            tmpl_btn = ttk.Menubutton(top, text="Hazır Şablonlar")
            tmpl_btn.pack(side="right")
            tmpl_menu = tk.Menu(tmpl_btn, tearoff=0)
            for tlabel, tdata in TEMPLATES:
                tmpl_menu.add_command(
                    label=tlabel, command=lambda d=tdata: self.apply_template(d))
            tmpl_btn.configure(menu=tmpl_menu)

            ttk.Label(right, text="Filtre adı", style="Muted.TLabel").pack(
                anchor="w", pady=(10, 2))
            self.name_var = tk.StringVar()
            self.name_entry = ttk.Entry(right, textvariable=self.name_var,
                                        font=(self.F, 11))
            self.name_entry.pack(fill="x")
            self.name_var.trace_add("write", lambda *_: self._on_form_change())
            self.name_entry.bind("<Return>", lambda e: self.on_save_form())

            # koşullar (dinamik satırlar)
            ttk.Label(right, text="Koşullar", style="Muted.TLabel").pack(
                anchor="w", pady=(14, 2))
            self.conds_container = tk.Frame(right, bg=CARD)
            self.conds_container.pack(fill="x")

            self.add_link = ttk.Button(right,
                                       text="+ Koşul ekle (VE / VEYA)",
                                       style="Link.TButton",
                                       command=self.on_add_cond)
            self.add_link.pack(anchor="w", pady=(8, 0))

            self.fold_hint = ttk.Label(
                right, style="Muted.TLabel",
                text="Koşullar soldan sağa birleştirilir: ((1. ∘ 2.) ∘ 3.) …")

            # canlı önizleme
            ttk.Label(right, text="Önizleme — filtre DOORS'ta şunu yapacak:",
                      style="Muted.TLabel").pack(anchor="w", pady=(16, 2))
            self.preview = tk.Text(right, height=3, bd=0, wrap="word",
                                   bg="#f4f7fb", padx=10, pady=8,
                                   font=(self.F, 10), cursor="arrow")
            self.preview.pack(fill="x")
            self.preview.tag_configure("attr", foreground=ATTR_BLUE,
                                       font=(self.F, 10, "bold"))
            self.preview.tag_configure("op", foreground=MUTED)
            self.preview.tag_configure("val", foreground=VAL_GREEN,
                                       font=(self.F, 10, "bold"))
            self.preview.tag_configure("logic", foreground=TEXT,
                                       font=(self.F, 10, "bold"))
            self.preview.tag_configure("hint", foreground=MUTED,
                                       font=(self.F, 10, "italic"))
            self.preview.configure(state="disabled")

            self.err_lbl = ttk.Label(right, text="", style="Error.TLabel",
                                     wraplength=520, justify="left")
            self.err_lbl.pack(anchor="w", pady=(6, 0))

            self.save_btn = ttk.Button(right, text="Filtreyi Kaydet",
                                       style="Accent.TButton",
                                       command=self.on_save_form)
            self.save_btn.pack(anchor="e", pady=(10, 0))

            self._build_rows([new_cond()])

        # ------------------------------------------------ koşul satırları
        def _build_rows(self, conds):
            """Koşul satırlarını verilen listeye göre baştan kurar."""
            for r in self.rows:
                r["frame"].destroy()
            self.rows = []
            for i, c in enumerate(conds):
                self._append_row(c, first=(i == 0))
            self._update_row_controls()
            self._on_form_change()

        def _append_row(self, c, first):
            i = len(self.rows)
            frame = tk.Frame(self.conds_container, bg=CARD)
            frame.grid(row=i, column=0, sticky="ew", pady=2)
            self.conds_container.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=3)
            frame.columnconfigure(3, weight=2)

            logic_var = None
            if first:
                tk.Label(frame, text="", bg=CARD, width=7).grid(row=0, column=0)
            else:
                logic_var = tk.StringVar(
                    value=LOGIC_TR.get(c.get("logic", "AND"), "VE"))
                cb = ttk.Combobox(frame, textvariable=logic_var,
                                  values=["VE", "VEYA"], state="readonly", width=5)
                cb.grid(row=0, column=0, padx=(0, 4))
                logic_var.trace_add("write", lambda *_: self._on_form_change())

            attr_var = tk.StringVar(value=c.get("attr", ""))
            attr_cb = ttk.Combobox(frame, textvariable=attr_var, width=20,
                                   values=COMMON_ATTRS, font=(self.F, 10))
            attr_cb.configure(postcommand=lambda cb=attr_cb: cb.configure(
                values=self._attr_suggestions()))
            attr_cb.grid(row=0, column=1, sticky="ew")

            op_var = tk.StringVar(
                value=OP_LABEL_BY_CODE.get(c.get("op", "contains"), OPERATORS[0][1]))
            op_cb = ttk.Combobox(frame, textvariable=op_var, state="readonly",
                                 width=13, values=[lbl for _, lbl in OPERATORS])
            op_cb.grid(row=0, column=2, padx=6)

            val_var = tk.StringVar(value=c.get("val", ""))
            val_entry = ttk.Entry(frame, textvariable=val_var, width=18,
                                  font=(self.F, 10))
            val_entry.grid(row=0, column=3, sticky="ew")
            val_entry.bind("<Return>", lambda e: self.on_save_form())

            rm_btn = ttk.Button(frame, text="×", style="Link.TButton", width=2,
                                command=lambda idx=i: self.on_remove_cond(idx))
            rm_btn.grid(row=0, column=4, padx=(4, 0))

            for var in (attr_var, op_var, val_var):
                var.trace_add("write", lambda *_: self._on_form_change())

            self.rows.append({"frame": frame, "logic_var": logic_var,
                              "attr_var": attr_var, "attr_cb": attr_cb,
                              "op_var": op_var, "val_var": val_var,
                              "val_entry": val_entry, "rm_btn": rm_btn})

        def _update_row_controls(self):
            single = len(self.rows) <= 1
            for r in self.rows:
                r["rm_btn"].state(["disabled"] if single else ["!disabled"])
            self.add_link.state(
                ["disabled"] if len(self.rows) >= MAX_CONDITIONS else ["!disabled"])
            if len(self.rows) > 2:
                self.fold_hint.pack(anchor="w", pady=(4, 0), after=self.add_link)
            else:
                self.fold_hint.pack_forget()

        def _rows_to_conds(self):
            conds = []
            for i, r in enumerate(self.rows):
                logic = "AND"
                if i > 0 and r["logic_var"] is not None:
                    logic = LOGIC_FROM_TR.get(r["logic_var"].get(), "AND")
                conds.append({
                    "logic": logic,
                    "attr": r["attr_var"].get().strip(),
                    "op": OP_CODE_BY_LABEL.get(r["op_var"].get(), "contains"),
                    "val": r["val_var"].get().strip(),
                })
            return conds

        def on_add_cond(self):
            if len(self.rows) >= MAX_CONDITIONS:
                return
            conds = self._rows_to_conds()
            conds.append(new_cond())
            self._build_rows(conds)
            self.rows[-1]["attr_cb"].focus_set()  # odak yeni satırın attribute kutusuna

        def on_remove_cond(self, idx):
            if len(self.rows) <= 1:
                return
            conds = self._rows_to_conds()
            del conds[idx]
            self._build_rows(conds)

        def _attr_suggestions(self):
            used = []
            for f in self.filters:
                for c in f["conditions"]:
                    a = c.get("attr", "")
                    if a and a not in used and a not in COMMON_ATTRS:
                        used.append(a)
            return COMMON_ATTRS + used

        # ------------------------------------------------ alt çubuk
        def _build_footer(self):
            f = tk.Frame(self.root, bg=BG)
            f.pack(fill="x", side="bottom")
            inner = tk.Frame(f, bg=BG, padx=12, pady=10)
            inner.pack(fill="x")
            self.dxl_btn = ttk.Button(inner, text="DXL Üret → DOORS'ta kullan",
                                      style="Accent.TButton",
                                      command=self.on_generate_dxl)
            self.dxl_btn.pack(side="left")
            self.dxl_btn.configure(state="disabled")  # klasör seçilince açılır
            self.status_lbl = tk.Label(inner, text="", bg=BG, fg=MUTED,
                                       font=(self.F, 9), anchor="e")
            self.status_lbl.pack(side="right", fill="x", expand=True)

        def _set_status(self, text, color=None):
            self.status_lbl.configure(text=text, fg=color or MUTED)

        # ------------------------------------------------ form yardımcıları
        def _on_form_change(self):
            self._sync_value_states()
            self._render_preview()
            self.err_lbl.configure(text="")

        def _sync_value_states(self):
            for r in self.rows:
                op = OP_CODE_BY_LABEL.get(r["op_var"].get(), "contains")
                r["val_entry"].configure(
                    state="disabled" if op in NO_VALUE_OPS else "normal")

        def _form_to_dict(self):
            return {"name": self.name_var.get().strip(),
                    "conditions": self._rows_to_conds()}

        def _dict_to_form(self, d):
            d = normalize_filter(d)
            self.name_var.set(d["name"])
            self._build_rows(d["conditions"])
            self._form_snapshot = normalize_filter(self._form_to_dict())
            self._render_preview()

        def _form_dirty(self):
            if self._form_snapshot is None:
                return False
            return normalize_filter(self._form_to_dict()) != self._form_snapshot

        # ------------------------------------------------ önizleme
        def _preview_segments(self, d):
            segs = []
            for i, c in enumerate(d["conditions"]):
                if i > 0:
                    segs.append(("   %s   " % LOGIC_TR[c["logic"]], "logic"))
                segs.append(("«%s»" % (c["attr"] or "…?"), "attr"))
                segs.append((" " + OP_LABEL_BY_CODE.get(c["op"], c["op"]), "op"))
                if c["op"] not in NO_VALUE_OPS:
                    segs.append((' "%s"' % (c["val"] or "…?"), "val"))
            return segs

        def _render_preview(self):
            d = normalize_filter(self._form_to_dict())
            empty = all(not c["attr"] and not c["val"] for c in d["conditions"])
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            if empty:
                self.preview.insert(
                    "end", "Yukarıda attribute, operatör ve değer seçtikçe "
                           "filtrenin ne yapacağını burada göreceksiniz.", "hint")
            else:
                self.preview.insert("end", "Şu nesneleri göster:  ", "op")
                for text, tag in self._preview_segments(d):
                    self.preview.insert("end", text, tag)
            self.preview.configure(state="disabled")

        def _summary_text(self, d):
            parts = [text for text, _tag in self._preview_segments(d)]
            s = "".join(parts).replace("   ", " ").strip()
            return (s[:57] + "…") if len(s) > 58 else s

        # ------------------------------------------------ liste yönetimi
        def _refresh_tree(self, select=None):
            self.tree.delete(*self.tree.get_children())
            for i, fdef in enumerate(self.filters):
                self.tree.insert("", "end", iid=str(i), text=fdef["name"],
                                 values=(self._summary_text(fdef),))
            if select is not None and 0 <= select < len(self.filters):
                self._suppress_select = True
                try:
                    self.tree.selection_set(str(select))
                    self.tree.see(str(select))
                finally:
                    self._suppress_select = False

        def on_tree_select(self, _event=None):
            if self._suppress_select:
                return
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx == self.edit_index:
                return
            if self._form_dirty() and not messagebox.askyesno(
                    "Kaydedilmemiş değişiklik",
                    "Formdaki değişiklikler kaydedilmedi ve kaybolacak.\n"
                    "Yine de başka filtreye geçilsin mi?"):
                self._suppress_select = True
                try:
                    if self.edit_index is not None:
                        self.tree.selection_set(str(self.edit_index))
                    elif self.tree.selection():
                        self.tree.selection_remove(*self.tree.selection())
                finally:
                    self._suppress_select = False
                return
            self.edit_index = idx
            self._dict_to_form(self.filters[idx])
            self._set_status("Düzenleniyor: %s" % self.filters[idx]["name"])

        # ------------------------------------------------ olaylar
        def choose_folder(self):
            folder = filedialog.askdirectory(title="Filtrelerin saklanacağı klasörü seçin")
            if folder:
                self._open_folder(folder, interactive=True)

        def _open_folder(self, folder, interactive):
            json_path = os.path.join(folder, JSON_NAME)
            filters = []
            if os.path.exists(json_path):
                try:
                    filters = read_json_file(json_path)
                except (ValueError, OSError) as exc:
                    if interactive:
                        messagebox.showerror(
                            "Yükleme hatası", "filters.json okunamadı:\n%s" % exc)
                    return
            self.folder = folder
            self.filters = filters
            self.edit_index = None
            save_config({"last_folder": folder})
            self.folder_lbl.configure(text=folder)
            self.dxl_btn.configure(state="normal")
            self._show_main()
            self._refresh_tree()
            self.on_new()
            if filters:
                self._set_status("%d filtre yüklendi." % len(filters))
            else:
                self._set_status("Yeni klasör — ilk filtrenizi tanımlayın.")

        def on_new(self):
            self.edit_index = None
            self._suppress_select = True
            try:
                if self.tree.selection():
                    self.tree.selection_remove(*self.tree.selection())
            finally:
                self._suppress_select = False
            self._dict_to_form(new_filter_dict())
            self.name_entry.focus_set()

        def apply_template(self, data):
            d = normalize_filter(dict(data))
            base, n = d["name"], 2
            existing = {f["name"] for f in self.filters}
            while d["name"] in existing:
                d["name"] = "%s %d" % (base, n)
                n += 1
            self.edit_index = None
            self._suppress_select = True
            try:
                if self.tree.selection():
                    self.tree.selection_remove(*self.tree.selection())
            finally:
                self._suppress_select = False
            self._dict_to_form(d)
            # şablon dolduktan sonra kullanıcı ilk boş alana odaklansın
            for r in self.rows:
                op = OP_CODE_BY_LABEL.get(r["op_var"].get(), "contains")
                if op not in NO_VALUE_OPS and not r["val_var"].get().strip():
                    r["val_entry"].focus_set()
                    break
            else:
                self.name_entry.focus_set()
            self._set_status("Şablon yüklendi — değeri doldurup kaydedin.")

        def on_copy(self):
            sel = self.tree.selection()
            if not sel:
                self._set_status("Kopyalamak için listeden bir filtre seçin.", ERR_RED)
                return
            src = normalize_filter(self.filters[int(sel[0])])
            base = src["name"] + " (kopya)"
            name, n = base, 2
            existing = {f["name"] for f in self.filters}
            while name in existing:
                name = "%s %d" % (base, n)
                n += 1
            src["name"] = name
            self.filters.append(src)
            self.edit_index = len(self.filters) - 1
            self._refresh_tree(select=self.edit_index)
            self._dict_to_form(self.filters[self.edit_index])
            self._autosave()

        def on_save_form(self):
            d = normalize_filter(self._form_to_dict())
            others = [f["name"] for i, f in enumerate(self.filters)
                      if i != self.edit_index]
            errs = validate_filter(d, others)
            if errs:
                self.err_lbl.configure(text=" • " + "\n • ".join(errs))
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
            else:
                self.filters[self.edit_index] = d
            self._form_snapshot = normalize_filter(self._form_to_dict())
            self._refresh_tree(select=self.edit_index)
            self._autosave()

        def on_delete(self):
            sel = self.tree.selection()
            if not sel:
                self._set_status("Silmek için listeden bir filtre seçin.", ERR_RED)
                return
            idx = int(sel[0])
            name = self.filters[idx]["name"]
            if not messagebox.askyesno("Silme onayı", "'%s' silinsin mi?" % name):
                return
            del self.filters[idx]
            self.edit_index = None
            self._refresh_tree()
            self._dict_to_form(new_filter_dict())
            self._autosave("Silindi: %s" % name)

        def _autosave(self, prefix=None):
            if not self.folder:
                return
            try:
                write_json_file(os.path.join(self.folder, JSON_NAME), self.filters)
                write_dat_file(os.path.join(self.folder, DAT_NAME), self.filters)
            except OSError as exc:
                messagebox.showerror("Kayıt hatası", "Dosyalar yazılamadı:\n%s" % exc)
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            msg = "✓ Kaydedildi %s (%d filtre)" % (stamp, len(self.filters))
            if prefix:
                msg = "%s — %s" % (prefix, msg)
            self._set_status(msg, OK_GREEN)

        def on_generate_dxl(self):
            if not self.folder:
                return
            if self._form_dirty() and not messagebox.askyesno(
                    "Kaydedilmemiş form",
                    "Formdaki değişiklikler henüz filtre listesine kaydedilmedi "
                    "ve DXL'in kullanacağı dosyada yer almayacak.\n\n"
                    "Yine de devam edilsin mi?"):
                return
            self._autosave()
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
            self._set_status("DXL üretildi: %s" % out_path, OK_GREEN)
            messagebox.showinfo(
                "DXL üretildi",
                "DXL dosyası oluşturuldu:\n%s\n\nDOORS'ta formal modül açıkken "
                "Tools > Edit DXL > Load… ile yükleyip Run ile çalıştırın.\n"
                "Ayrıntılar için README.md dosyasına bakın." % out_path)

    root = tk.Tk()
    app = FilterEditorApp(root)
    if test_hook is not None:      # otomatik testler icin: mainloop acilmaz
        try:
            test_hook(app)
        finally:
            root.destroy()
        return
    root.mainloop()


# ---------------------------------------------------------------------------
# Komut satırı girişi
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="DOORS Filtre Yöneticisi — Filtre Editörü. "
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
