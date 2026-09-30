"""Metin normalizasyonu ve karşılaştırma için yardımcı çıkarımlar."""
from __future__ import annotations

import re
from collections import Counter

EQUIP_PLACEHOLDER = "<EKIPMAN>"

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w<>°%]+", re.UNICODE)
# Sayılar: 57.2 / 75,2 / -54 / 1,000  (tanımlayıcıların içindeki rakamlar da dahil;
# her iki tarafta da aynı olacakları için farkı etkilemezler)
_NUM_RE = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)*")
# Virgüllü ondalık: 75,2 (1,000 gibi binlik ayırıcı hariç)
_DEC_COMMA_RE = re.compile(r"(?<![\d,.])\d+,\d{1,2}(?![\d])")
MODAL_RE = re.compile(r"\b(shall not|shall|should not|should|will|must|may|can)\b", re.I)


def collapse_ws(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").replace("\xa0", " ")).strip()


def split_title_body(text: str) -> tuple[str, str]:
    """İlk satır kısa ve noktayla bitmiyorsa başlık kabul edilir."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    if len(lines) >= 2 and len(lines[0]) <= 150 and not lines[0].endswith((".", ":", ";")):
        return lines[0], " ".join(lines[1:])
    return "", " ".join(lines)


def mask_equipment(s: str, equipment: str) -> str:
    if equipment:
        s = re.sub(re.escape(equipment), EQUIP_PLACEHOLDER, s, flags=re.I)
    return s


def compare_form(s: str, equipment: str = "") -> str:
    """Karşılaştırmada kullanılan biçim: boşluklar tekleştirilmiş, ekipman adı maskelenmiş."""
    return collapse_ws(mask_equipment(s or "", equipment))


def match_form(s: str, equipment: str = "") -> str:
    """Eşleştirmede kullanılan gevşek biçim: küçük harf, noktalama yok."""
    s = compare_form(s, equipment).lower()
    return collapse_ws(_PUNCT_RE.sub(" ", s))


def numbers(s: str) -> list[str]:
    """Metindeki sayılar (ondalık virgül noktaya çevrilmiş)."""
    out = []
    for m in _NUM_RE.findall(s or ""):
        if re.fullmatch(r"-?\d+,\d{1,2}", m):
            m = m.replace(",", ".")
        else:
            m = m.replace(",", "")  # binlik ayırıcı
        out.append(m)
    return out


def raw_numbers(s: str) -> list[str]:
    return _NUM_RE.findall(s or "")


def decimal_commas(s: str) -> list[str]:
    return _DEC_COMMA_RE.findall(s or "")


def modals(s: str) -> Counter:
    return Counter(m.lower() for m in MODAL_RE.findall(s or ""))


def number_diff(ref: str, val: str) -> str:
    """İki metnin sayısal farkını '70 → 71' biçiminde özetler; fark yoksa ''."""
    a, b = Counter(numbers(ref)), Counter(numbers(val))
    if a == b:
        return ""
    only_ref = list((a - b).elements())
    only_val = list((b - a).elements())
    return f"{', '.join(only_ref) or '∅'} → {', '.join(only_val) or '∅'}"


def modal_diff(ref: str, val: str) -> str:
    a, b = modals(ref), modals(val)
    if a == b:
        return ""
    only_ref = list((a - b).elements())
    only_val = list((b - a).elements())
    return f"{', '.join(only_ref) or '∅'} → {', '.join(only_val) or '∅'}"
