"""Yerel Ollama sunucusu ile iletişim.

LLM yalnızca yardımcıdır: farkları açıklar, sınıflandırır, düzeltme önerir ve
anlamsal eşleşme adayı bulur. Eşleştirme ve doğrulama kararları kural tabanlıdır.
Sonuçlar proje dosyasında önbelleğe alınır; aynı soru ikinci kez sorulmaz.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import requests

DEFAULT_URL = "http://localhost:11434"
DEFAULT_CHAT_MODEL = "qwen2.5:3b"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
TIMEOUT = 300

# Ollama yerelde çalışır; kurumsal proxy ortam değişkenleri (HTTP_PROXY vb.) atlanır.
_http = requests.Session()
_http.trust_env = False

CATEGORY_TR = {
    "NO_CHANGE": "Fark yok",
    "TYPO": "Yazım hatası",
    "FORMAT": "Biçim farkı",
    "VALUE_CHANGE": "Değer/birim farkı",
    "MODALITY_CHANGE": "Zorunluluk ifadesi farkı",
    "REFERENCE_CHANGE": "Standart/doküman referansı farkı",
    "SCOPE_CHANGE": "Kapsam farkı",
    "MEANING_CHANGE": "Anlam farkı",
}
SEVERITY_TR = {"HIGH": "Yüksek", "MEDIUM": "Orta", "LOW": "Düşük"}

_DIFF_SYSTEM = """You are a senior requirements engineer reviewing aerospace/defense equipment specifications exported from IBM DOORS.
The same common requirement appears in several equipment specification documents. You compare a REFERENCE version with a VARIANT version.
The token <EKIPMAN> stands for the equipment name and must be ignored as a difference.

Answer ONLY with a JSON object with these keys:
- "category": one of NO_CHANGE, TYPO, FORMAT, VALUE_CHANGE, MODALITY_CHANGE, REFERENCE_CHANGE, SCOPE_CHANGE, MEANING_CHANGE
- "severity": one of HIGH, MEDIUM, LOW  (changed numbers, units, limits, shall/should, standards => HIGH)
- "explanation_tr": 1-2 short sentences IN TURKISH describing exactly what differs (quote the differing words/values)
- "likely_error": true if the variant most likely contains a mistake, false if it may be an intentional equipment-specific difference
- "suggested_text": the corrected VARIANT text IN ENGLISH, aligned with the reference (keep <EKIPMAN> as is). Empty string if no change needed."""

_GRAMMAR_SYSTEM = """You are a technical editor for aerospace/defense requirements written in English (INCOSE requirement writing rules).
Check the requirement for spelling, grammar, ambiguity (e.g. "and/or", "etc.", "as appropriate"), wrong decimal separators (e.g. "75,2" instead of "75.2") and inconsistent units.
The token <EKIPMAN> stands for the equipment name.

Answer ONLY with a JSON object with these keys:
- "has_issues": true/false
- "issues_tr": list of short issue descriptions IN TURKISH (empty list if none)
- "corrected_text": corrected requirement IN ENGLISH (same meaning, minimal changes). Empty string if no change needed."""


class OllamaError(RuntimeError):
    pass


def _cache_key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


def list_models(url: str) -> list[str]:
    try:
        r = _http.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception as e:  # noqa: BLE001
        raise OllamaError(f"Ollama'ya bağlanılamadı ({url}): {e}") from e


def _chat_json(url: str, model: str, system: str, user: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096},
    }
    try:
        r = _http.post(f"{url.rstrip('/')}/api/chat", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        content = r.json()["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise OllamaError(f"Ollama isteği başarısız: {e}") from e
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Model geçerli JSON döndürmedi: {content[:200]}") from e


def explain_diff(cfg: dict, cache: dict, field: str, ref: str, val: str) -> dict:
    key = _cache_key("diff", cfg["chat_model"], field, ref, val)
    if key in cache:
        return cache[key]
    user = f"FIELD: {field}\n\nREFERENCE:\n{ref}\n\nVARIANT:\n{val}"
    res = _chat_json(cfg["url"], cfg["chat_model"], _DIFF_SYSTEM, user)
    out = {
        "kategori": CATEGORY_TR.get(str(res.get("category", "")).upper(), str(res.get("category", ""))),
        "onem": SEVERITY_TR.get(str(res.get("severity", "")).upper(), str(res.get("severity", ""))),
        "aciklama": str(res.get("explanation_tr", "")).strip(),
        "hata_olasi": bool(res.get("likely_error", False)),
        "oneri": str(res.get("suggested_text", "")).strip(),
        "model": cfg["chat_model"],
    }
    cache[key] = out
    return out


def check_grammar(cfg: dict, cache: dict, text: str) -> dict:
    key = _cache_key("grammar", cfg["chat_model"], text)
    if key in cache:
        return cache[key]
    res = _chat_json(cfg["url"], cfg["chat_model"], _GRAMMAR_SYSTEM, f"REQUIREMENT:\n{text}")
    issues = res.get("issues_tr") or []
    if isinstance(issues, str):
        issues = [issues]
    out = {
        "sorun_var": bool(res.get("has_issues", False)),
        "sorunlar": [str(x) for x in issues],
        "duzeltilmis": str(res.get("corrected_text", "")).strip(),
        "model": cfg["chat_model"],
    }
    cache[key] = out
    return out


def embed(cfg: dict, texts: list[str], mem_cache: dict) -> np.ndarray:
    """Metinlerin embedding vektörleri (normalize edilmiş). mem_cache bellekte tutulur."""
    model = cfg["embed_model"]
    missing = [t for t in dict.fromkeys(texts) if (model, t) not in mem_cache]
    url = cfg["url"].rstrip("/")
    for start in range(0, len(missing), 32):
        batch = missing[start:start + 32]
        try:
            r = _http.post(f"{url}/api/embed", json={"model": model, "input": batch}, timeout=TIMEOUT)
            r.raise_for_status()
            vecs = r.json()["embeddings"]
        except Exception as e:  # noqa: BLE001
            raise OllamaError(f"Embedding alınamadı ({model}): {e}") from e
        for t, v in zip(batch, vecs):
            v = np.asarray(v, dtype=np.float32)
            mem_cache[(model, t)] = v / (np.linalg.norm(v) or 1.0)
    return np.vstack([mem_cache[(model, t)] for t in texts]) if texts else np.zeros((0, 1))
