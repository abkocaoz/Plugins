"""Setler arası ortak gereksinimleri metin benzerliğiyle gruplar.

Algoritma:
  1. Karşılaştırılacak satırlar (varsayılan: Requirement + Information) "öğe" olur.
  2. Her öğe için gevşek eşleştirme metni (küçük harf, noktalama yok, ekipman adı
     maskelenmiş) çıkarılır.
  3. Farklı setlerdeki öğe çiftleri için benzerlik puanı (0-100) hesaplanır.
  4. Çiftler puana göre büyükten küçüğe işlenir; bir grupta her setten en fazla
     bir öğe olacak şekilde gruplar birleştirilir (açgözlü birleştirme).
  5. Elle yapılan birleştirme / ayırma kararları en önce uygulanır.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

import numpy as np
from rapidfuzz import fuzz, process

from .normalize import match_form, split_title_body


def item_key(set_name: str, req_id: str) -> str:
    return f"{set_name}|{req_id}"


def source_tokens(source: str) -> set[str]:
    return {t for t in re.split(r"[\s,;]+", source or "") if t}


def build_items(sets: dict, include_types: list[str]) -> list[dict]:
    """Setlerdeki karşılaştırılacak satırları düz öğe listesine çevirir."""
    types = {t.lower() for t in include_types}
    items = []
    for set_name, s in sets.items():
        eq = s.get("equipment", "")
        for r in s["rows"]:
            rtype = (r["type"] or "").lower()
            if rtype == "heading":
                continue
            if types and rtype not in types and not (rtype == "" and "" in types):
                continue
            if not r["text"].strip():
                continue
            title, body = split_title_body(r["text"])
            items.append({
                "key": item_key(set_name, r["id"]),
                "set": set_name,
                "id": r["id"],
                "row": r["row"],
                "equipment": eq,
                "title": title,
                "body": body,
                "text": r["text"],
                "type": r["type"],
                "source": r["source"],
                "section": r["section"],
                "attrs": r["attrs"],
                "mtext": match_form(r["text"], eq),
            })
    return items


class _DSU:
    def __init__(self, items):
        self.parent = list(range(len(items)))
        self.sets = [{it["set"]} for it in items]

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b, force=False) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if not force and self.sets[ra] & self.sets[rb]:
            return False
        self.parent[rb] = ra
        self.sets[ra] |= self.sets[rb]
        return True


def candidate_pairs(items: list[dict], low_threshold: int) -> list[tuple[int, int, int]]:
    """Farklı setlerdeki, puanı low_threshold ve üzerindeki (i, j, puan) çiftleri."""
    uniq: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        uniq[it["mtext"]].append(i)
    texts = list(uniq.keys())
    groups = [uniq[t] for t in texts]

    pairs: list[tuple[int, int, int]] = []
    # Birebir aynı metinler
    for g in groups:
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                i, j = g[a], g[b]
                if items[i]["set"] != items[j]["set"]:
                    pairs.append((i, j, 100))
    if len(texts) > 1:
        mat = process.cdist(
            texts, texts, scorer=fuzz.ratio, score_cutoff=low_threshold,
            dtype=np.uint8, workers=-1,
        )
        ui, uj = np.nonzero(np.triu(mat, k=1))
        for u, v in zip(ui.tolist(), uj.tolist()):
            score = int(mat[u, v])
            for i in groups[u]:
                for j in groups[v]:
                    if items[i]["set"] != items[j]["set"]:
                        pairs.append((i, j, score))
    return pairs


def cluster(
    items: list[dict],
    threshold: int,
    low_threshold: int,
    manual: dict | None = None,
) -> tuple[list[list[int]], list[dict]]:
    """Öğeleri gruplar. Dönüş: (gruplar, eşleşme önerileri)."""
    manual = manual or {}
    idx = {it["key"]: i for i, it in enumerate(items)}
    detached = {idx[k] for k in manual.get("detach", []) if k in idx}
    dsu = _DSU(items)

    for a, b in manual.get("merge", []):
        if a in idx and b in idx:
            dsu.union(idx[a], idx[b], force=True)

    pairs = candidate_pairs(items, low_threshold)
    pairs.sort(key=lambda p: (-p[2], p[0], p[1]))
    for i, j, s in pairs:
        if s < threshold:
            break
        if i in detached or j in detached:
            continue
        dsu.union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[dsu.find(i)].append(i)
    clusters = sorted(groups.values(), key=lambda g: min(g))

    # Öneriler: eşik altında kalan benzer çiftler ve aynı Source'a sahip ayrı gruplar
    # (yalnızca ortak seti olmayan, yani birleştirilebilir gruplar için)
    root = {i: dsu.find(i) for i in range(len(items))}
    suggestions = []
    seen = set()
    for i, j, s in pairs:
        if s >= threshold or root[i] == root[j] or dsu.sets[root[i]] & dsu.sets[root[j]]:
            continue
        k = (min(root[i], root[j]), max(root[i], root[j]))
        if k in seen:
            continue
        seen.add(k)
        suggestions.append({"a": items[i]["key"], "b": items[j]["key"], "puan": s, "neden": "Benzer metin"})

    by_source: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        for t in source_tokens(it["source"]):
            by_source[t].append(i)
    for tok, lst in by_source.items():
        roots = {}
        for i in lst:
            roots.setdefault(root[i], i)
        rl = list(roots.values())
        for a in range(len(rl)):
            for b in range(a + 1, len(rl)):
                i, j = rl[a], rl[b]
                k = (min(root[i], root[j]), max(root[i], root[j]))
                if k in seen or dsu.sets[root[i]] & dsu.sets[root[j]]:
                    continue
                seen.add(k)
                s = int(fuzz.ratio(items[i]["mtext"], items[j]["mtext"]))
                suggestions.append({"a": items[i]["key"], "b": items[j]["key"], "puan": s,
                                    "neden": f"Aynı Source ({tok})"})
    suggestions.sort(key=lambda x: -x["puan"])
    return clusters, suggestions


def cluster_id(member_keys: list[str]) -> str:
    return "G-" + hashlib.sha1(min(member_keys).encode("utf-8")).hexdigest()[:8]
