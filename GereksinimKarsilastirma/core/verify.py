"""Temel çizgi (ilk analiz) ile güncel analizi karşılaştırarak düzeltmeleri doğrular.

Tamamen kural tabanlıdır; LLM kullanılmaz.
"""
from __future__ import annotations

from datetime import datetime

FIXED = "✅ Düzeldi"
STILL = "⚠️ Hâlâ farklı"
CHANGED = "🔄 Değişti, hâlâ farklı"
NEW = "🆕 Yeni fark"
GONE = "❌ Öğe bulunamadı"

_KEEP = ("key", "grup", "grup_no", "set", "id", "item", "alan", "kategori", "onem",
         "etiketler", "referans", "deger", "uyeler")


def make_baseline(analysis: dict, sets: dict) -> dict:
    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "set_versions": {k: v["loaded_at"] for k, v in sets.items()},
        "diffs": {d["key"]: {k: d[k] for k in _KEEP if k in d} for d in analysis["diffs"]},
    }


def compare_to_baseline(baseline: dict, analysis: dict) -> list[dict]:
    cur = {d["key"]: d for d in analysis["diffs"]}
    items = {it["key"] for it in analysis["items"]}
    item_cluster = analysis["item_cluster"]
    cluster_sets = {c["cid"]: set(c["sets"]) for c in analysis["clusters"]}
    rows, handled = [], set()

    for key, old in baseline["diffs"].items():
        if key.startswith("EKSIK::"):
            cids = {item_cluster[m] for m in old.get("uyeler", []) if m in item_cluster}
            if any(old["set"] in cluster_sets.get(c, set()) for c in cids):
                status, new = FIXED, None
            else:
                status = STILL
                new = next((d for d in analysis["diffs"] if d["key"].startswith(f"EKSIK::{old['set']}::")
                            and d["grup"] in cids), None)
                if new:
                    handled.add(new["key"])
            rows.append(_row(old, new, status))
            continue
        new = cur.get(key)
        if new:
            handled.add(key)
            status = STILL if new["deger"] == old["deger"] else CHANGED
        elif old.get("item") and old["item"] not in items:
            status = GONE
        else:
            status = FIXED
        rows.append(_row(old, new, status))

    for key, d in cur.items():
        if key not in baseline["diffs"] and key not in handled:
            rows.append(_row(None, d, NEW))
    return rows


def _row(old, new, status):
    src = new or old
    return {
        "Durum": status,
        "Grup No": src.get("grup_no"),
        "Set": src["set"],
        "Req ID": src["id"],
        "Alan": src["alan"],
        "Kategori": src["kategori"],
        "Önem": src["onem"],
        "Önceki değer": (old or {}).get("deger", ""),
        "Güncel değer": (new or {}).get("deger", "") if status != FIXED else "",
        "Referans": src.get("referans", ""),
        "key": src["key"],
    }
