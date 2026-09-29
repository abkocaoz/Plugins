"""Gereksinim Karşılaştırma — DOORS setleri arasında ortak gereksinim ve fark analizi.

Çalıştırma:  streamlit run app.py
"""
from __future__ import annotations

import difflib
import html
import json
import re

import numpy as np
import pandas as pd
import streamlit as st

from core import export, llm
from core.compare import SEVERITY, analyze, field_specs
from core.loader import parse_set, set_name_from_filename
from core.normalize import compare_form
from core.project import (
    STATUSES, list_projects, load_project, log, new_project, safe_name, save_project,
)
from core.verify import CHANGED, FIXED, GONE, NEW, STILL, compare_to_baseline, make_baseline

st.set_page_config(page_title="Gereksinim Karşılaştırma", page_icon="📑", layout="wide")

PAGES = [
    "1 · Veri Yükleme",
    "2 · Ortak Gereksinimler",
    "3 · Grup Detayı",
    "4 · Fark Listesi",
    "5 · Eşleşme Önerileri",
    "6 · Doğrulama",
    "7 · Ayarlar",
]
SEV_COLOR = {"Yüksek": "#f8cbad", "Orta": "#ffe699", "Düşük": "#ddebf7"}
CELL_COLOR = {"✓": "#c6efce", "≠": "#f8cbad", "–": "#ededed"}

ss = st.session_state
ss.setdefault("project", None)
ss.setdefault("analysis", None)
ss.setdefault("analysis_sig", None)
ss.setdefault("emb_cache", {})
ss.setdefault("semantic", [])
ss.setdefault("excel", None)


# --------------------------------------------------------------------------- yardımcılar
def persist():
    if ss.project:
        save_project(ss.project)


def goto(page: str, **kw):
    ss["nav_target"] = page
    for k, v in kw.items():
        ss[k] = v
    st.rerun()


def get_analysis() -> dict | None:
    p = ss.project
    if not p or not p["sets"]:
        return None
    sig = json.dumps({
        "sets": {k: [v["loaded_at"], v["equipment"], len(v["rows"])] for k, v in p["sets"].items()},
        "settings": p["settings"], "manual": p["manual"],
    }, sort_keys=True, ensure_ascii=False)
    if ss.analysis_sig != sig:
        with st.spinner("Setler analiz ediliyor…"):
            ss.analysis = analyze(p["sets"], p["settings"], p["manual"])
        ss.analysis_sig = sig
        ss.excel = None
    return ss.analysis


def html_diff(ref: str, val: str) -> str:
    """Kelime düzeyinde fark: referansta olup bu sette olmayan kırmızı, fazladan olan yeşil."""
    ta = re.findall(r"\s+|[^\s]+", ref or "")
    tb = re.findall(r"\s+|[^\s]+", val or "")
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    out = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        a, b = html.escape("".join(ta[a1:a2])), html.escape("".join(tb[b1:b2]))
        if op == "equal":
            out.append(a)
        if op in ("delete", "replace") and a:
            out.append(f'<del style="background:#f8cbad;color:#000;">{a}</del>')
        if op in ("insert", "replace") and b:
            out.append(f'<ins style="background:#c6efce;color:#000;text-decoration:none;">{b}</ins>')
    return f'<div style="white-space:pre-wrap;line-height:1.6;">{"".join(out)}</div>'


def llm_cfg() -> dict:
    return ss.project["llm"]


def llm_ready() -> bool:
    return bool(ss.project and ss.project["llm"].get("enabled"))


def load_files(files) -> list[str]:
    """Yüklenen dosyaları projeye ekler/günceller. Mesaj listesi döner."""
    p = ss.project
    msgs = []
    first = next(iter(p["sets"].values()), None)
    for f in files:
        name = set_name_from_filename(f.name)
        try:
            s = parse_set(f.name, f.getvalue())
        except Exception as e:  # noqa: BLE001
            msgs.append(f"❌ {f.name}: {e}")
            continue
        if first and len(s["headers"]) != len(first["headers"]):
            msgs.append(f"⚠️ {f.name}: sütun sayısı ({len(s['headers'])}) ilk setle "
                        f"({len(first['headers'])}) aynı değil. Yine de yüklendi.")
        if name in p["sets"]:
            if not s["equipment"]:
                s["equipment"] = p["sets"][name]["equipment"]
            log(p, f"{name} güncellendi ({f.name})")
            msgs.append(f"🔄 {name} güncellendi — {len(s['rows'])} satır")
        else:
            log(p, f"{name} eklendi ({f.name})")
            msgs.append(f"✅ {name} eklendi — {len(s['rows'])} satır")
        p["sets"][name] = s
        first = first or s
    persist()
    return msgs


def group_label(c: dict) -> str:
    sev = f" · {c['max_sev']}" if c["max_sev"] else ""
    return f"#{c['no']} — {c['title'][:80]} ({c['coverage']} set{sev})"


def decision(key: str) -> dict:
    return ss.project["decisions"].get(key, {"durum": "Açık", "not": ""})


def apply_editor_changes(edited: pd.DataFrame, original: pd.DataFrame):
    changed = False
    dec = ss.project["decisions"]
    for idx in edited.index:
        k = original.at[idx, "key"]
        new_d, new_n = edited.at[idx, "Durum"], edited.at[idx, "Not"] or ""
        old = dec.get(k, {"durum": "Açık", "not": ""})
        if new_d != old["durum"] or new_n != old["not"]:
            dec[k] = {"durum": new_d, "not": new_n}
            changed = True
    if changed:
        persist()


def explain_many(diffs: list[dict]):
    p = ss.project
    todo = [d for d in diffs if d["key"] not in p["llm_notes"] and d["referans"] and d["deger"]]
    if not todo:
        st.info("Açıklanacak yeni fark yok (hepsi zaten açıklanmış ya da uygun değil).")
        return
    bar = st.progress(0.0, text=f"LLM çalışıyor… 0/{len(todo)}")
    for n, d in enumerate(todo, start=1):
        try:
            p["llm_notes"][d["key"]] = llm.explain_diff(llm_cfg(), p["llm_cache"], d["alan"],
                                                        d["referans"], d["deger"])
        except llm.OllamaError as e:
            st.error(str(e))
            break
        bar.progress(n / len(todo), text=f"LLM çalışıyor… {n}/{len(todo)}")
        if n % 5 == 0:
            persist()
    persist()
    bar.empty()


def style_sev(df: pd.DataFrame, col="Önem"):
    return df.style.map(lambda v: f"background-color:{SEV_COLOR.get(v, '')};color:#000" if v in SEV_COLOR else "",
                        subset=[col])


def open_project(p: dict, save: bool = False):
    ss.project = p
    ss.analysis_sig = None
    ss.semantic = []
    if save:
        persist()
    # Sayfa yenilendiğinde (F5) aynı projenin yeniden açılması için adres çubuğunda tutulur
    st.query_params["proje"] = safe_name(p["name"])
    st.rerun()


if ss.project is None and st.query_params.get("proje") in list_projects():
    ss.project = load_project(st.query_params["proje"])
    ss.analysis_sig = None

# --------------------------------------------------------------------------- kenar çubuğu
with st.sidebar:
    st.title("📑 Gereksinim Karşılaştırma")
    projects = list_projects()
    with st.expander("Proje", expanded=ss.project is None):
        if projects:
            sel = st.selectbox("Mevcut projeler", projects, key="proj_sel")
            if st.button("📂 Projeyi aç"):
                open_project(load_project(sel))
        new_name = st.text_input("Yeni proje adı", placeholder="ör. LCS ESD Karşılaştırma")
        if st.button("➕ Yeni proje oluştur", disabled=not new_name.strip()):
            if new_name.strip() in projects:
                st.error("Bu adda bir proje zaten var.")
            else:
                open_project(new_project(new_name.strip()), save=True)
    if ss.project:
        p = ss.project
        st.success(f"**Proje:** {p['name']}")
        st.caption(f"{len(p['sets'])} set · son kayıt {p['updated'].replace('T', ' ')}")
        if llm_ready():
            st.caption(f"🤖 Ollama: {p['llm']['chat_model']}")
        else:
            st.caption("🤖 LLM kapalı (Ayarlar'dan açılabilir)")
    if "nav_target" in ss:
        ss["nav"] = ss.pop("nav_target")
    page = st.radio("Sayfa", PAGES, key="nav", label_visibility="collapsed")

if not ss.project:
    st.header("Hoş geldiniz 👋")
    st.markdown(
        "Soldaki **Proje** bölümünden yeni bir proje oluşturun ya da mevcut bir projeyi açın.\n\n"
        "**Akış:**\n"
        "1. DOORS'tan aldığınız CSV/Excel dosyalarını yükleyin.\n"
        "2. Ortak gereksinimleri ve farkları inceleyin, her fark için karar verin.\n"
        "3. Fark listesini Excel'e aktarıp DOORS'ta düzeltin.\n"
        "4. **Doğrulama** sayfasında temel çizgi oluşturun, düzeltilmiş CSV'leri yükleyin ve kontrol edin."
    )
    st.stop()

P = ss.project
A = get_analysis()


def need_analysis():
    if A is None:
        st.info("Önce **1 · Veri Yükleme** sayfasından en az bir set yükleyin.")
        st.stop()


# --------------------------------------------------------------------------- 1. veri yükleme
if page == PAGES[0]:
    st.header("1 · Veri Yükleme")
    st.markdown(
        "DOORS'tan aldığınız **CSV** (veya Excel) dosyalarını seçin. Set adı dosya adından alınır; "
        "aynı adla tekrar yüklenen dosya **eski setin yerine geçer**.\n\n"
        "Sütunlar **sırayla** okunur: `ID · Source · Metin · Attribute · diğer öznitelikler…`"
    )
    files = st.file_uploader("Dosyalar", type=["csv", "xlsx", "xls"], accept_multiple_files=True,
                             key=f"up_{len(P['history'])}")
    if st.button("📥 Yükle / Güncelle", type="primary", disabled=not files):
        for m in load_files(files):
            st.write(m)
        st.rerun()

    if P["sets"]:
        st.subheader(f"Yüklü setler ({len(P['sets'])})")
        rows = []
        for name, s in P["sets"].items():
            n_req = sum(1 for r in s["rows"] if r["type"].lower() == "requirement")
            rows.append({"Sil": False, "Set": name, "Ekipman adı": s["equipment"], "Dosya": s["filename"],
                         "Satır": len(s["rows"]), "Requirement": n_req,
                         "Yüklenme": s["loaded_at"].replace("T", " ")})
        df = pd.DataFrame(rows)
        edited = st.data_editor(
            df, hide_index=True, key=f"sets_{len(P['history'])}",
            disabled=["Set", "Dosya", "Satır", "Requirement", "Yüklenme"],
            column_config={
                "Ekipman adı": st.column_config.TextColumn(
                    help="Metinde geçen ekipman adı karşılaştırmada <EKIPMAN> ile maskelenir; "
                         "böylece ekipman adı farkı hata sayılmaz."),
                "Sil": st.column_config.CheckboxColumn(width="small"),
            },
        )
        c1, c2 = st.columns(2)
        if c1.button("💾 Ekipman adlarını kaydet"):
            for _, r in edited.iterrows():
                P["sets"][r["Set"]]["equipment"] = (r["Ekipman adı"] or "").strip()
            persist()
            st.rerun()
        to_del = edited.loc[edited["Sil"], "Set"].tolist()
        if c2.button(f"🗑️ Seçili setleri sil ({len(to_del)})", disabled=not to_del):
            for n in to_del:
                P["sets"].pop(n, None)
                log(P, f"{n} silindi")
            persist()
            st.rerun()

        st.subheader("Ana set (referans)")
        opts = ["(Yok — çoğunluk esas alınsın)"] + list(P["sets"].keys())
        cur = P["settings"].get("master_set") or opts[0]
        ms = st.selectbox(
            "Referans kabul edilecek set", opts, index=opts.index(cur) if cur in opts else 0,
            help="Örneğin Sistem Gereksinim Dokümanı'nı (SRD) yükleyip ana set seçerseniz, farklar ona göre "
                 "hesaplanır. Seçilmezse her alanda en çok tekrar eden değer referans olur.")
        new_ms = "" if ms == opts[0] else ms
        if new_ms != P["settings"].get("master_set", ""):
            P["settings"]["master_set"] = new_ms
            persist()
            st.rerun()

        first = next(iter(P["sets"].values()))
        with st.expander("Algılanan sütunlar"):
            st.write(pd.DataFrame({"Sıra": range(1, len(first["headers"]) + 1), "Sütun": first["headers"]}))

# --------------------------------------------------------------------------- 2. ortak gereksinimler
elif page == PAGES[1]:
    need_analysis()
    st.header("2 · Ortak Gereksinimler")
    common = [c for c in A["clusters"] if c["common"]]
    diffs = A["diffs"]
    n_sets = len(A["set_names"])
    m = st.columns(5)
    m[0].metric("Set", n_sets)
    m[1].metric("Ortak grup", len(common))
    m[2].metric("Farklı olan grup", sum(1 for c in common if c["diff_count"]))
    m[3].metric("Yüksek önemli fark", sum(1 for d in diffs if d["onem"] == "Yüksek"))
    m[4].metric("Tek sette kalan", sum(len(c["members"]) for c in A["clusters"] if not c["common"]))

    f1, f2, f3, f4 = st.columns([1, 1, 1.4, 1.4])
    only_diff = f1.toggle("Yalnızca farklı olanlar", value=True)
    sev_f = f2.multiselect("Önem", ["Yüksek", "Orta", "Düşük"])
    cat_f = f3.multiselect("Fark türü", sorted({k for c in common for k in c["categories"]}))
    set_f = f4.multiselect("Sette farkı olan", A["set_names"])
    q = st.text_input("Ara (başlık/metin)", placeholder="ör. LOW PRESSURE")

    mat = export.matrix_table(A)
    rows = []
    for c in common:
        if only_diff and not c["diff_count"]:
            continue
        if sev_f and c["max_sev"] not in sev_f:
            continue
        if cat_f and not set(cat_f) & set(c["categories"]):
            continue
        if set_f and not set(set_f) & set(c["diff_sets"]):
            continue
        if q and q.lower() not in (c["title"] + " " + c["refs"].get("Gövde", {}).get("value", "")).lower():
            continue
        rows.append(c["no"])
    view = mat[mat["Grup No"].isin(rows)] if not mat.empty else mat
    st.caption(f"{len(view)} grup gösteriliyor · ✓ referansla aynı · ≠ farklı · – bu sette yok. "
               "Detay için bir satır seçin.")
    if not view.empty:
        styled = view.style.map(
            lambda v: f"background-color:{CELL_COLOR[v]};color:#000;text-align:center" if v in CELL_COLOR else "",
            subset=A["set_names"],
        ).map(lambda v: f"background-color:{SEV_COLOR.get(v, '')};color:#000" if v in SEV_COLOR else "",
              subset=["En yüksek önem"])
        ev = st.dataframe(styled, hide_index=True, on_select="rerun", selection_mode="single-row",
                          height=min(600, 38 + 35 * len(view)),
                          column_config={"Başlık / Metin": st.column_config.TextColumn(width="large")})
        if ev.selection.rows:
            no = int(view.iloc[ev.selection.rows[0]]["Grup No"])
            cid = next(c["cid"] for c in common if c["no"] == no)
            goto(PAGES[2], detail_cid=cid)

# --------------------------------------------------------------------------- 3. grup detayı
elif page == PAGES[2]:
    need_analysis()
    st.header("3 · Grup Detayı")
    common = [c for c in A["clusters"] if c["common"]]
    if not common:
        st.info("Ortak gereksinim grubu bulunamadı.")
        st.stop()
    by_cid = {c["cid"]: c for c in common}
    if st.toggle("Yalnızca farklı olan grupları gez", value=True, key="detail_only_diff"):
        common = [c for c in common if c["diff_count"] or c["cid"] == ss.get("detail_cid")] or common
    ids = [c["cid"] for c in common]
    cur = ss.get("detail_cid")
    idx = ids.index(cur) if cur in ids else 0
    nav1, nav2, nav3 = st.columns([1, 8, 1])
    if nav1.button("◀", disabled=idx == 0):
        goto(PAGES[2], detail_cid=ids[idx - 1])
    cid = nav2.selectbox("Grup", ids, index=idx, format_func=lambda k: group_label(by_cid[k]),
                         label_visibility="collapsed")
    if nav3.button("▶", disabled=idx >= len(ids) - 1):
        goto(PAGES[2], detail_cid=ids[idx + 1])
    ss.detail_cid = cid
    c = by_cid[cid]
    items = A["items"]
    members = [items[i] for i in c["members"]]
    cdiffs = [d for d in A["diffs"] if d["grup"] == cid]

    st.markdown(f"**Kapsam:** {c['coverage']}/{len(A['set_names'])} set"
                + (f" · **Eksik olduğu setler:** {', '.join(c['missing'])}" if c["missing"] else ""))
    ref_title = c["refs"].get("Başlık", {}).get("value", "")
    ref_body = c["refs"].get("Gövde", {}).get("value", "")
    with st.container(border=True):
        tie = any(r["tie"] for r in c["refs"].values())
        src = f"ana set ({P['settings']['master_set']})" if P["settings"].get("master_set") in c["sets"] \
            else "çoğunluk"
        st.markdown(f"**Referans metin** <small>({src}{' · ⚠️ bazı alanlarda eşit oy' if tie else ''})</small>",
                    unsafe_allow_html=True)
        if ref_title:
            st.markdown(f"**{html.escape(ref_title)}**")
        st.write(ref_body)

    # Setlere göre tablo (farklı hücreler renkli)
    st.subheader("Setlerdeki haller")
    specs = field_specs(P["sets"], P["settings"])
    table = []
    for it in members:
        r = {"Set": it["set"], "Req ID": it["id"], "Ekipman": it["equipment"]}
        for spec in specs:
            r[spec["name"]] = spec["get"](it)
        table.append(r)
    tdf = pd.DataFrame(table)
    diff_cells = {(d["set"], d["alan"]) for d in cdiffs if not d["alan"].startswith("Kontrol:")}

    def _style_row(row):
        return ["background-color:#f8cbad;color:#000" if (row["Set"], col) in diff_cells else ""
                for col in row.index]

    st.dataframe(tdf.style.apply(_style_row, axis=1), hide_index=True,
                 column_config={"Gövde": st.column_config.TextColumn(width="large")})

    # Metin farkları
    text_diffs = [d for d in cdiffs if d["alan"] in ("Başlık", "Gövde")]
    if text_diffs:
        st.subheader("Metin farkları")
        st.caption("🟥 referansta olup bu sette olmayan · 🟩 bu sette fazladan/farklı olan")
        for d in text_diffs:
            with st.container(border=True):
                st.markdown(f"**{d['set']} · {d['id']} · {d['alan']}** — "
                            f"<span style='background:{SEV_COLOR[d['onem']]};color:#000;padding:0 6px;"
                            f"border-radius:4px'>{d['onem']}</span> {html.escape(d['etiketler'])}",
                            unsafe_allow_html=True)
                st.markdown(html_diff(d["referans"], d["deger"]), unsafe_allow_html=True)
                note = P["llm_notes"].get(d["key"])
                if note:
                    st.info(f"🤖 **{note['kategori']}** ({note['onem']}) — {note['aciklama']}"
                            + (f"\n\n**Önerilen metin:** {note['oneri']}" if note.get("oneri") else ""))

    # Kararlar
    st.subheader("Farklar ve kararlar")
    if cdiffs:
        ddf = export.diff_table({"diffs": cdiffs}, P)
        ddf = ddf[["Set", "Req ID", "Alan", "Kategori", "Önem", "Detay", "Bu setteki değer", "Durum", "Not",
                   "key"]].reset_index(drop=True)
        edited = st.data_editor(
            ddf, hide_index=True, key=f"dec_{cid}",
            disabled=[c_ for c_ in ddf.columns if c_ not in ("Durum", "Not")],
            column_config={"Durum": st.column_config.SelectboxColumn(options=STATUSES, required=True),
                           "key": None, "Bu setteki değer": st.column_config.TextColumn(width="medium")},
        )
        apply_editor_changes(edited, ddf)
    else:
        st.success("Bu grupta fark yok. ✓")

    # LLM
    with st.expander("🤖 LLM yardımcıları", expanded=bool(text_diffs) and llm_ready()):
        if not llm_ready():
            st.info("LLM kapalı. **7 · Ayarlar** sayfasından Ollama'yı etkinleştirin.")
        else:
            b1, b2 = st.columns(2)
            if b1.button("Bu gruptaki farkları açıkla ve düzeltme öner", disabled=not cdiffs):
                explain_many([d for d in cdiffs if d["alan"] != "(Gereksinim)"
                              and not d["alan"].startswith("Kontrol:")])
                st.rerun()
            if b2.button("Referans metnin dil/yazım kontrolü"):
                try:
                    res = llm.check_grammar(llm_cfg(), P["llm_cache"], (ref_title + "\n" + ref_body).strip())
                    persist()
                    if res["sorun_var"]:
                        st.warning("\n".join(f"- {x}" for x in res["sorunlar"]))
                        if res["duzeltilmis"]:
                            st.code(res["duzeltilmis"], language=None, wrap_lines=True)
                    else:
                        st.success("Sorun bulunmadı.")
                except llm.OllamaError as e:
                    st.error(str(e))

    with st.expander("🔧 Eşleşmeyi düzelt"):
        opt = {it["key"]: f"{it['set']} · {it['id']}" for it in members}
        k = st.selectbox("Gruptan ayrılacak öğe", list(opt), format_func=opt.get)
        if st.button("Bu öğeyi gruptan ayır"):
            P["manual"]["detach"].append(k)
            P["manual"]["merge"] = [m_ for m_ in P["manual"]["merge"] if k not in m_]
            persist()
            st.rerun()

# --------------------------------------------------------------------------- 4. fark listesi
elif page == PAGES[3]:
    need_analysis()
    st.header("4 · Fark Listesi (DOORS iş listesi)")
    full = export.diff_table(A, P)
    if full.empty:
        st.success("Hiç fark bulunamadı. 🎉")
        st.stop()
    f1, f2, f3 = st.columns(3)
    sev_f = f1.multiselect("Önem", ["Yüksek", "Orta", "Düşük"])
    cat_f = f2.multiselect("Kategori", sorted(full["Kategori"].unique()))
    st_f = f3.multiselect("Durum", STATUSES)
    f4, f5, f6 = st.columns(3)
    set_f = f4.multiselect("Set", A["set_names"])
    field_f = f5.multiselect("Alan", sorted(full["Alan"].unique()))
    q = f6.text_input("Ara", placeholder="Req ID, metin…")
    view = full
    if sev_f:
        view = view[view["Önem"].isin(sev_f)]
    if cat_f:
        view = view[view["Kategori"].isin(cat_f)]
    if st_f:
        view = view[view["Durum"].isin(st_f)]
    if set_f:
        view = view[view["Set"].isin(set_f)]
    if field_f:
        view = view[view["Alan"].isin(field_f)]
    if q:
        mask = view.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(), axis=1)
        view = view[mask]
    view = view.reset_index(drop=True)

    counts = full["Durum"].value_counts()
    st.caption(f"{len(view)} / {len(full)} kayıt · " + " · ".join(f"{s}: {counts.get(s, 0)}" for s in STATUSES))
    sig = abs(hash((tuple(sev_f), tuple(cat_f), tuple(st_f), tuple(set_f), tuple(field_f), q))) % 10**8
    edited = st.data_editor(
        view, hide_index=True, key=f"fl_{sig}", height=560,
        disabled=[c for c in view.columns if c not in ("Durum", "Not")],
        column_config={
            "Durum": st.column_config.SelectboxColumn(options=STATUSES, required=True),
            "key": None,
            "Referans (çoğunluk/ana set)": st.column_config.TextColumn(width="medium"),
            "Bu setteki değer": st.column_config.TextColumn(width="medium"),
        },
    )
    apply_editor_changes(edited, view)

    c1, c2 = st.columns(2)
    with c1:
        if llm_ready():
            cand = [d for d in A["diffs"] if d["key"] in set(view["key"])
                    and d["onem"] in ("Yüksek", "Orta") and d["alan"] != "(Gereksinim)"
                    and not d["alan"].startswith("Kontrol:") and d["key"] not in P["llm_notes"]]
            if st.button(f"🤖 Listelenen Yüksek/Orta farkları LLM ile açıkla ({len(cand)})", disabled=not cand):
                explain_many(cand)
                st.rerun()
    with c2:
        if st.button("📊 Excel raporu hazırla"):
            ss.excel = export.to_excel(A, P)
        if ss.excel:
            st.download_button("⬇️ Excel'i indir", ss.excel, file_name=f"{P['name']}_fark_listesi.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --------------------------------------------------------------------------- 5. eşleşme önerileri
elif page == PAGES[4]:
    need_analysis()
    st.header("5 · Eşleşme Önerileri")
    st.markdown(
        "Otomatik eşleşme eşiğinin (**%{}**) altında kalan ama birbirine benzeyen öğeler ve aynı Source'a "
        "sahip olup farklı gruplara düşen öğeler burada listelenir. Aynı gereksinim olduğunu "
        "düşündüklerinizi işaretleyip birleştirin.".format(P["settings"]["threshold"])
    )
    by_key = {it["key"]: it for it in A["items"]}
    sugg = list(A["suggestions"]) + [s for s in ss.semantic if s["a"] in by_key and s["b"] in by_key]
    ic = A["item_cluster"]
    sugg = [s for s in sugg if ic.get(s["a"]) != ic.get(s["b"])]

    if llm_ready():
        with st.expander("🤖 Anlamsal aday ara (Ollama embedding)"):
            st.caption("Farklı kelimelerle yazılmış ama aynı anlama gelen gereksinimleri bulur. "
                       "Yalnızca tek sette kalan öğeler için aranır.")
            thr = st.slider("Benzerlik eşiği (kosinüs)", 0.70, 0.99, 0.88, 0.01)
            if st.button("Aday ara"):
                singles = [A["items"][i] for c in A["clusters"] if not c["common"] for i in c["members"]]
                groups = [c for c in A["clusters"] if c["common"]]
                try:
                    st_texts = [compare_form(it["text"], it["equipment"]) for it in singles]
                    g_texts = [(c["refs"]["Başlık"]["value"] + " " + c["refs"]["Gövde"]["value"]).strip()
                               for c in groups]
                    with st.spinner("Embedding hesaplanıyor…"):
                        ea = llm.embed(llm_cfg(), st_texts, ss.emb_cache)
                        eb = llm.embed(llm_cfg(), g_texts, ss.emb_cache) if g_texts else np.zeros((0, 1))
                    found = []
                    if len(singles) and len(groups):
                        sim = ea @ eb.T
                        for a_i, it in enumerate(singles):
                            for g_i in np.argsort(-sim[a_i])[:3]:
                                g = groups[g_i]
                                if sim[a_i, g_i] >= thr and it["set"] not in g["sets"]:
                                    target = A["items"][g["members"][0]]["key"]
                                    found.append({"a": it["key"], "b": target, "puan": int(sim[a_i, g_i] * 100),
                                                  "neden": f"Anlamsal (LLM) #{g['no']}"})
                    ss.semantic = found
                    st.success(f"{len(found)} anlamsal aday bulundu.")
                    st.rerun()
                except llm.OllamaError as e:
                    st.error(str(e))

    if not sugg:
        st.success("Öneri yok.")
    else:
        rows = []
        for s in sugg[:500]:
            a, b = by_key[s["a"]], by_key[s["b"]]
            rows.append({"Birleştir": False, "Puan": s["puan"], "Neden": s["neden"],
                         "Set A": a["set"], "ID A": a["id"], "Metin A": compare_form(a["text"], a["equipment"]),
                         "Set B": b["set"], "ID B": b["id"], "Metin B": compare_form(b["text"], b["equipment"]),
                         "_a": s["a"], "_b": s["b"]})
        df = pd.DataFrame(rows)
        st.caption(f"{len(sugg)} öneri" + (" (ilk 500 gösteriliyor)" if len(sugg) > 500 else ""))
        edited = st.data_editor(
            df, hide_index=True, key=f"sug_{len(P['manual']['merge'])}_{len(ss.semantic)}", height=520,
            disabled=[c for c in df.columns if c != "Birleştir"],
            column_config={"_a": None, "_b": None,
                           "Metin A": st.column_config.TextColumn(width="large"),
                           "Metin B": st.column_config.TextColumn(width="large")},
        )
        chosen = edited[edited["Birleştir"]]
        if st.button(f"🔗 Seçilenleri birleştir ({len(chosen)})", type="primary", disabled=chosen.empty):
            for _, r in chosen.iterrows():
                P["manual"]["merge"].append([r["_a"], r["_b"]])
                P["manual"]["detach"] = [k for k in P["manual"]["detach"] if k not in (r["_a"], r["_b"])]
            persist()
            st.rerun()

    st.subheader("Elle yapılan düzeltmeler")
    man = [{"Tür": "Birleştirme", "Öğeler": f"{a} ⇄ {b}", "_i": i} for i, (a, b) in enumerate(P["manual"]["merge"])]
    man += [{"Tür": "Ayırma", "Öğeler": k, "_i": i} for i, k in enumerate(P["manual"]["detach"])]
    if not man:
        st.caption("Yok.")
    else:
        mdf = pd.DataFrame(man)
        mdf.insert(0, "Geri al", False)
        e2 = st.data_editor(mdf, hide_index=True, disabled=["Tür", "Öğeler"], column_config={"_i": None},
                            key=f"man_{len(man)}")
        undo = e2[e2["Geri al"]]
        if st.button(f"↩️ Seçilenleri geri al ({len(undo)})", disabled=undo.empty):
            drop_m = set(undo.loc[undo["Tür"] == "Birleştirme", "_i"])
            drop_d = set(undo.loc[undo["Tür"] == "Ayırma", "_i"])
            P["manual"]["merge"] = [m_ for i, m_ in enumerate(P["manual"]["merge"]) if i not in drop_m]
            P["manual"]["detach"] = [k for i, k in enumerate(P["manual"]["detach"]) if i not in drop_d]
            persist()
            st.rerun()

    with st.expander("Tek sette kalan öğeler"):
        st.dataframe(export.single_table(A), hide_index=True,
                     column_config={"Metin": st.column_config.TextColumn(width="large")})

# --------------------------------------------------------------------------- 6. doğrulama
elif page == PAGES[5]:
    need_analysis()
    st.header("6 · Doğrulama")
    st.markdown(
        "**Akış:** ① Temel çizgiyi oluşturun (şu anki farkların fotoğrafı) → ② DOORS'ta düzeltin → "
        "③ Güncellenmiş CSV'leri aşağıdan yükleyin → ④ Raporu inceleyin."
    )
    base = P.get("baseline")
    c1, c2 = st.columns(2)
    if not base:
        if c1.button("📌 Temel çizgiyi oluştur", type="primary"):
            P["baseline"] = make_baseline(A, P["sets"])
            log(P, "Temel çizgi oluşturuldu")
            persist()
            st.rerun()
        st.stop()
    c1.info(f"Temel çizgi: **{base['created'].replace('T', ' ')}** · {len(base['diffs'])} fark")
    if c2.button("🔁 Temel çizgiyi şimdiki duruma göre yenile",
                 help="Mevcut farkları yeni başlangıç noktası yapar. Önceki doğrulama sonuçları sıfırlanır."):
        P["baseline"] = make_baseline(A, P["sets"])
        log(P, "Temel çizgi yenilendi")
        persist()
        st.rerun()

    with st.container(border=True):
        st.markdown("**Güncellenmiş CSV'leri yükle** (yalnızca değiştirdiğiniz setler yeterli; "
                    "dosya adı set adıyla aynı olmalı)")
        files = st.file_uploader("Güncel dosyalar", type=["csv", "xlsx", "xls"], accept_multiple_files=True,
                                 key=f"vup_{len(P['history'])}", label_visibility="collapsed")
        if files:
            unknown = [f.name for f in files if set_name_from_filename(f.name) not in P["sets"]]
            if unknown:
                st.warning("Şu dosyalar mevcut bir setle eşleşmiyor, yeni set olarak eklenecek: "
                           + ", ".join(unknown))
        if st.button("📥 Yükle ve doğrula", type="primary", disabled=not files):
            for m_ in load_files(files):
                st.write(m_)
            st.rerun()

    changed = [k for k, v in P["sets"].items() if base["set_versions"].get(k) != v["loaded_at"]]
    st.caption("Temel çizgiden sonra güncellenen setler: " + (", ".join(changed) if changed else "yok"))

    rows = compare_to_baseline(base, A)
    vdf = pd.DataFrame(rows)
    if vdf.empty:
        st.success("Temel çizgide ve şu anda hiç fark yok.")
        st.stop()
    counts = vdf["Durum"].value_counts()
    m = st.columns(5)
    for col, s in zip(m, [FIXED, STILL, CHANGED, NEW, GONE]):
        col.metric(s, int(counts.get(s, 0)))
    total_old = len(base["diffs"])
    fixed = int(counts.get(FIXED, 0))
    st.progress(fixed / total_old if total_old else 1.0, text=f"{fixed} / {total_old} fark kapandı")

    todo_keys = {k for k, v in P["decisions"].items() if v.get("durum") == "Düzeltilecek"}
    still_todo = vdf[vdf["key"].isin(todo_keys) & vdf["Durum"].isin([STILL, CHANGED])]
    if not still_todo.empty:
        st.warning(f"**Düzeltilecek** olarak işaretlediğiniz {len(still_todo)} fark hâlâ duruyor.")

    f1, f2, f3 = st.columns(3)
    s_f = f1.multiselect("Durum", [FIXED, STILL, CHANGED, NEW, GONE], default=[STILL, CHANGED, NEW, GONE])
    set_f = f2.multiselect("Set", A["set_names"], default=changed)
    sev_f = f3.multiselect("Önem", ["Yüksek", "Orta", "Düşük"])
    view = vdf
    if s_f:
        view = view[view["Durum"].isin(s_f)]
    if set_f:
        view = view[view["Set"].isin(set_f)]
    if sev_f:
        view = view[view["Önem"].isin(sev_f)]
    view = view.copy()
    view["Kararınız"] = view["key"].map(lambda k: decision(k)["durum"])
    st.dataframe(style_sev(view), hide_index=True, height=520,
                 column_config={"key": None, "Önceki değer": st.column_config.TextColumn(width="medium"),
                                "Güncel değer": st.column_config.TextColumn(width="medium")})

    if st.button("📊 Doğrulama raporunu Excel'e aktar"):
        ss.excel = export.to_excel(A, P, rows)
    if ss.excel:
        st.download_button("⬇️ Excel'i indir", ss.excel, file_name=f"{P['name']}_dogrulama.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.expander("Proje geçmişi"):
        st.dataframe(pd.DataFrame(P["history"][::-1]), hide_index=True)

# --------------------------------------------------------------------------- 7. ayarlar
elif page == PAGES[6]:
    st.header("7 · Ayarlar")
    S = P["settings"]
    st.subheader("Eşleştirme")
    types_found = sorted({r["type"] for s in P["sets"].values() for r in s["rows"] if r["type"]} - {"Heading"})
    opts = sorted(set(types_found) | set(S["include_types"]))
    c1, c2 = st.columns(2)
    inc = c1.multiselect("Karşılaştırılacak satır türleri (Attribute)", opts, default=S["include_types"])
    thr = c2.slider("Otomatik eşleşme eşiği (%)", 60, 100, S["threshold"],
                    help="Normalize edilmiş metinlerin benzerliği bu değer ve üzerindeyse aynı gereksinim sayılır.")
    c3, c4 = st.columns(2)
    low = c3.slider("Öneri alt sınırı (%)", 30, 95, S["low_threshold"],
                    help="Bu değer ile eşleşme eşiği arasındaki çiftler 'Eşleşme Önerileri' sayfasında listelenir.")
    min_sets = c4.number_input("Ortak sayılmak için en az set sayısı", 2, 50, S["min_sets"])
    c5, c6 = st.columns(2)
    miss = c5.slider("Eksik gereksinim uyarısı: grubun bulunduğu set oranı ≥", 0.1, 1.0, float(S["missing_ratio"]),
                     0.05, help="Bir grup setlerin en az bu oranında varsa, olmadığı setler 'Eksik gereksinim' "
                                "olarak listelenir.")
    with c6:
        sec = st.checkbox("Bölüm (başlık altı) farklarını da göster", S["compare_section"])
        es = st.checkbox("Source'u boş Requirement'ları işaretle", S["check_empty_source"])
    if st.button("💾 Eşleştirme ayarlarını kaydet", type="primary"):
        S.update({"include_types": inc, "threshold": int(thr), "low_threshold": int(min(low, thr)),
                  "min_sets": int(min_sets), "missing_ratio": float(miss), "compare_section": sec,
                  "check_empty_source": es})
        persist()
        st.success("Kaydedildi. Analiz yeniden hesaplanacak.")
        st.rerun()

    st.divider()
    st.subheader("🤖 Yerel LLM (Ollama)")
    L = P["llm"]
    st.markdown(
        "LLM yalnızca **yardımcıdır**: farkları Türkçe açıklar, sınıflandırır, İngilizce düzeltme önerir ve "
        "anlamsal eşleşme adayı bulur. Eşleştirme ve doğrulama kararları kural tabanlıdır.\n\n"
        "**4 GB VRAM için öneri:** sohbet modeli `qwen2.5:3b` (veya `llama3.2:3b`), embedding modeli "
        "`nomic-embed-text`. Daha isabetli ama daha yavaş seçenek: `qwen2.5:7b` (kısmen RAM'e taşar).\n\n"
        "Kurulum: `ollama pull qwen2.5:3b` ve `ollama pull nomic-embed-text`"
    )
    en = st.toggle("LLM'i etkinleştir", L["enabled"])
    url = st.text_input("Ollama adresi", L["url"])
    models = ss.get("ollama_models", [])
    if st.button("🔌 Bağlantıyı test et / modelleri listele"):
        try:
            models = llm.list_models(url)
            ss.ollama_models = models
            st.success(f"Bağlantı başarılı. {len(models)} model bulundu.")
        except llm.OllamaError as e:
            st.error(str(e))
    c1, c2 = st.columns(2)
    if models:
        def _idx(name):  # "nomic-embed-text" ile "nomic-embed-text:latest" aynı modeldir
            return next((i for i, m_ in enumerate(models) if m_ == name or m_.split(":")[0] == name), 0)

        chat = c1.selectbox("Sohbet modeli", models, index=_idx(L["chat_model"]))
        emb = c2.selectbox("Embedding modeli", models, index=_idx(L["embed_model"]))
    else:
        chat = c1.text_input("Sohbet modeli", L["chat_model"])
        emb = c2.text_input("Embedding modeli", L["embed_model"])
    # Değişiklikler anında kaydedilir; kenar çubuğu bu sayfadan önce çizildiği için yeniden çalıştırılır.
    new_llm = {"enabled": en, "url": url.strip(), "chat_model": chat.strip(), "embed_model": emb.strip()}
    if any(L.get(k) != v for k, v in new_llm.items()):
        L.update(new_llm)
        persist()
        st.rerun()
    st.caption("LLM ayarları değiştirildiği anda otomatik kaydedilir.")
    if P["llm_notes"] and st.button(f"🧹 LLM açıklamalarını temizle ({len(P['llm_notes'])})"):
        P["llm_notes"], P["llm_cache"] = {}, {}
        persist()
        st.rerun()

    st.divider()
    st.caption(f"Proje dosyası: projeler/{P['name']}.json · Önem sıralaması: "
               + ", ".join(f"{k}={v}" for k, v in SEVERITY.items()))
