"""Gruplar içinde referans belirleme ve farkların sınıflandırılması."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from rapidfuzz import fuzz

from .matching import build_items, cluster, cluster_id
from .normalize import (
    MODAL_RE, collapse_ws, compare_form, decimal_commas, match_form, modal_diff,
    number_diff, raw_numbers,
)

SEVERITY = {"Yüksek": 3, "Orta": 2, "Düşük": 1}

DEFAULT_SETTINGS = {
    "include_types": ["Requirement", "Information"],
    "threshold": 85,           # bu puan ve üzeri otomatik eşleşir
    "low_threshold": 60,       # öneri listesi için alt sınır
    "min_sets": 2,             # "ortak" sayılmak için en az kaç sette olmalı
    "missing_ratio": 0.5,      # setlerin en az bu oranında varsa, olmayan setler "eksik" sayılır
    "compare_section": True,
    "check_empty_source": True,
    "master_set": "",
}


def field_specs(sets: dict, settings: dict) -> list[dict]:
    """Karşılaştırılacak alanlar (ID ve metin sütununun kendisi hariç tüm sütunlar)."""
    first = next(iter(sets.values()))
    h = first["headers"]
    specs = [
        {"name": "Başlık", "kind": "text", "get": lambda it: it["title"]},
        {"name": "Gövde", "kind": "text", "get": lambda it: it["body"]},
        {"name": h[1], "kind": "source", "get": lambda it: it["source"]},
        {"name": h[3], "kind": "type", "get": lambda it: it["type"]},
    ]
    for col in h[4:]:
        specs.append({"name": col, "kind": "attr", "get": (lambda c: lambda it: it["attrs"].get(c, ""))(col)})
    if settings.get("compare_section", True):
        specs.append({"name": "Bölüm", "kind": "section", "get": lambda it: it["section"]})
    return specs


def classify_text(ref: str, val: str) -> list[tuple[str, str, str]]:
    """(kategori, önem, detay) etiketleri."""
    tags = []
    nd = number_diff(ref, val)
    if nd:
        tags.append(("Sayısal değer", "Yüksek", nd))
    md = modal_diff(ref, val)
    if md:
        tags.append(("Zorunluluk ifadesi", "Yüksek", md))
    if not nd:
        ra, rb = Counter(raw_numbers(ref)), Counter(raw_numbers(val))
        if ra != rb:
            tags.append(("Sayı biçimi (ondalık ayraç)", "Orta",
                         f"{', '.join((ra - rb).elements())} ↔ {', '.join((rb - ra).elements())}"))
    mr, mv = match_form(ref), match_form(val)

    def strip(s):  # sayılar ve zorunluluk kelimeleri çıkarılmış metin
        return collapse_ws(MODAL_RE.sub(" ", "".join(ch for ch in s if not ch.isdigit())))

    if mr == mv:
        if not tags:
            tags.append(("Biçim (harf/noktalama/boşluk)", "Düşük", ""))
    elif strip(mr) != strip(mv):
        if not ref.strip() or not val.strip():
            tags.append(("Eksik değer", "Orta", ""))
        else:
            tags.append(("Metin", "Orta", f"benzerlik %{int(fuzz.ratio(mr, mv))}"))
    return tags


def classify_attr(spec: dict, ref: str, val: str) -> list[tuple[str, str, str]]:
    name = spec["name"]
    if spec["kind"] == "section":
        return [("Bölüm yeri", "Düşük", "")]
    if not ref.strip() or not val.strip():
        cat = "Eksik değer"
    elif spec["kind"] == "source":
        cat = "İzlenebilirlik (Source)"
    elif spec["kind"] == "type":
        cat = "Tür (Attribute)"
    elif match_form(ref) == match_form(val):
        return [("Biçim (harf/noktalama/boşluk)", "Düşük", "")]
    else:
        cat = "Öznitelik"
    sev = "Yüksek" if "safety" in name.lower() or "emniyet" in name.lower() else "Orta"
    return [(cat, sev, "")]


def _pick_reference(values: list[tuple[str, str]], master_set: str, set_order: dict):
    """values: [(set, değer)] -> (referans, belirsiz_mi)"""
    for s, v in values:
        if master_set and s == master_set:
            return v, False
    cnt = Counter(v for _, v in values)
    top = cnt.most_common()
    best = top[0][1]
    candidates = [v for v, c in top if c == best]
    tie = len(candidates) > 1
    if tie:
        first = min(((set_order.get(s, 0), v) for s, v in values if v in candidates))
        return first[1], True
    return candidates[0], False


def analyze(sets: dict, settings: dict, manual: dict | None = None) -> dict:
    settings = {**DEFAULT_SETTINGS, **(settings or {})}
    set_names = list(sets.keys())
    set_order = {s: i for i, s in enumerate(set_names)}
    master = settings.get("master_set") or ""
    items = build_items(sets, settings["include_types"])
    groups, suggestions = cluster(items, settings["threshold"], settings["low_threshold"], manual)
    specs = field_specs(sets, settings) if sets else []

    clusters, diffs = [], []
    item_cluster = {}
    n_sets = len(set_names)
    no = 0
    for g in groups:
        members = sorted(g, key=lambda i: (set_order[items[i]["set"]], items[i]["row"]))
        member_sets = {items[i]["set"] for i in members}
        keys = [items[i]["key"] for i in members]
        cid = cluster_id(keys)
        for i in members:
            item_cluster[items[i]["key"]] = cid
        is_common = len(member_sets) >= settings["min_sets"]
        if is_common:
            no += 1
        refs = {}
        cdiffs = []
        for spec in specs:
            vals = [(items[i]["set"], compare_form(spec["get"](items[i]), items[i]["equipment"])) for i in members]
            ref, tie = _pick_reference(vals, master, set_order)
            refs[spec["name"]] = {"value": ref, "tie": tie}
            if not is_common:
                continue
            for i, (s, v) in zip(members, vals):
                if v == ref:
                    continue
                if spec["kind"] == "text":
                    tags = classify_text(ref, v)
                else:
                    tags = classify_attr(spec, ref, v)
                if not tags:
                    continue
                tags.sort(key=lambda t: -SEVERITY[t[1]])
                it = items[i]
                cdiffs.append({
                    "key": f"{it['key']}::{spec['name']}",
                    "grup": cid, "grup_no": no, "set": s, "id": it["id"], "item": it["key"],
                    "alan": spec["name"], "kategori": tags[0][0], "onem": tags[0][1],
                    "etiketler": "; ".join(f"{c}{' (' + d + ')' if d else ''}" for c, _, d in tags),
                    "referans": ref, "deger": v, "belirsiz": tie,
                })
        # Eksik gereksinim
        missing = []
        if is_common and n_sets > 1:
            need = max(settings["min_sets"], math.ceil(settings["missing_ratio"] * n_sets))
            if len(member_sets) >= need:
                missing = [s for s in set_names if s not in member_sets]
                for s in missing:
                    cdiffs.append({
                        "key": f"EKSIK::{s}::{cid}", "grup": cid, "grup_no": no, "set": s, "id": "—",
                        "item": "", "alan": "(Gereksinim)", "kategori": "Eksik gereksinim", "onem": "Orta",
                        "etiketler": f"{len(member_sets)}/{n_sets} sette var",
                        "referans": refs.get("Gövde", {}).get("value", ""), "deger": "",
                        "belirsiz": False, "uyeler": keys,
                    })
        diffs.extend(cdiffs)
        title = refs.get("Başlık", {}).get("value") or refs.get("Gövde", {}).get("value", "")[:90]
        sev = max((SEVERITY[d["onem"]] for d in cdiffs), default=0)
        clusters.append({
            "cid": cid, "no": no if is_common else None, "common": is_common,
            "members": members, "sets": sorted(member_sets, key=set_order.get),
            "coverage": len(member_sets), "title": title, "refs": refs,
            "diff_count": len(cdiffs),
            "diff_sets": sorted({d["set"] for d in cdiffs}, key=set_order.get),
            "max_sev": {3: "Yüksek", 2: "Orta", 1: "Düşük", 0: ""}[sev],
            "categories": sorted({d["kategori"] for d in cdiffs}),
            "missing": missing,
        })

    # Öğe düzeyi kontroller
    by_set_text = defaultdict(list)
    for it in items:
        by_set_text[(it["set"], it["mtext"])].append(it)
    for it in items:
        cid = item_cluster.get(it["key"], "")
        dc = decimal_commas(it["text"])
        if dc:
            diffs.append(_check(it, cid, "Kontrol: ondalık virgül", "Ondalık ayraç (virgül)", "Orta",
                                ", ".join(dc), it["text"]))
        dup = [o for o in by_set_text[(it["set"], it["mtext"])] if o["key"] != it["key"]]
        if dup:
            diffs.append(_check(it, cid, "Kontrol: set içi tekrar", "Set içi tekrar", "Orta",
                                "Aynı metin: " + ", ".join(o["id"] for o in dup), it["text"]))
        if settings.get("check_empty_source") and it["type"].lower() == "requirement" and not it["source"].strip():
            diffs.append(_check(it, cid, "Kontrol: boş Source", "Boş Source", "Düşük",
                                "Requirement türünde Source boş", ""))
    cno = {c["cid"]: c["no"] for c in clusters}
    for d in diffs:
        if not d.get("grup_no"):
            d["grup_no"] = cno.get(d["grup"])

    return {
        "items": items, "clusters": clusters, "diffs": diffs, "suggestions": suggestions,
        "fields": [s["name"] for s in specs], "set_names": set_names,
        "item_cluster": item_cluster, "settings": settings,
    }


def _check(it, cid, field, cat, sev, detail, value):
    return {
        "key": f"{it['key']}::{field}", "grup": cid, "grup_no": None, "set": it["set"], "id": it["id"],
        "item": it["key"], "alan": field, "kategori": cat, "onem": sev, "etiketler": detail,
        "referans": "", "deger": value, "belirsiz": False,
    }
