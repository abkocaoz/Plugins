"""DOORS CSV / Excel çıktılarını okuyup ortak bir kayıt yapısına çevirir.

Sütunlar ada göre değil SIRAYA göre okunur (3. sütunun başlığı dokümana göre
değiştiği için):
    0: Requirement ID   1: Source   2: Metin (başlık + gövde)   3: Attribute (tür)
    4+: Diğer öznitelikler (Compliance, Maturity, ...)
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

ENCODINGS = ("utf-8-sig", "utf-16", "cp1254", "cp1252", "latin-1")

# 3. sütun başlığından ekipman adını çıkarmak için
_EQUIP_RE = re.compile(
    r"^(.*?)\s*(?:Document\s+)?Equipment\s+Specifications?\s+Document.*$", re.I
)


def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sniff_delimiter(text: str) -> str:
    first_line = text.split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    return max(counts, key=counts.get)


def read_table(filename: str, raw: bytes) -> pd.DataFrame:
    """CSV veya Excel dosyasını, tüm hücreler metin olacak şekilde okur."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(io.BytesIO(raw), dtype=str, header=0)
        df = df.fillna("")
    else:
        text = _decode(raw)
        sep = _sniff_delimiter(text)
        df = pd.read_csv(
            io.StringIO(text), sep=sep, dtype=str, keep_default_na=False,
            quoting=csv.QUOTE_MINIMAL, engine="python",
        )
    # Başlığı boş ve tamamen boş sütunları at (DOORS bazen sona boş sütun ekler)
    keep = [
        c for c in df.columns
        if not (str(c).startswith("Unnamed") and (df[c].astype(str).str.strip() == "").all())
    ]
    return df[keep]


def equipment_from_header(header: str) -> str:
    m = _EQUIP_RE.match(header.strip())
    if m and m.group(1).strip():
        return m.group(1).strip()
    return ""


def clean_cell(value) -> str:
    """Hücreyi saklama için hafifçe temizler (orijinal satır yapısı korunur)."""
    s = "" if value is None else str(value)
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [ln.rstrip() for ln in s.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


def parse_set(filename: str, raw: bytes) -> dict:
    """Bir dosyayı set sözlüğüne çevirir."""
    df = read_table(filename, raw)
    if df.shape[1] < 4:
        raise ValueError(
            f"{filename}: en az 4 sütun bekleniyordu (ID, Source, Metin, Attribute), "
            f"{df.shape[1]} bulundu."
        )
    headers = [str(c) for c in df.columns]
    attr_headers = headers[4:]
    rows = []
    section = ""
    for i, rec in enumerate(df.itertuples(index=False), start=1):
        vals = [clean_cell(v) for v in rec]
        req_id, source, text, rtype = vals[0].strip(), vals[1], vals[2], vals[3].strip()
        if not req_id and not text:
            continue
        if rtype.lower() == "heading":
            section = " ".join(text.split())
        rows.append({
            "row": i,
            "id": req_id,
            "source": source,
            "text": text,
            "type": rtype,
            "section": section if rtype.lower() != "heading" else "",
            "attrs": dict(zip(attr_headers, vals[4:])),
        })
    return {
        "filename": filename,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "headers": headers,
        "equipment": equipment_from_header(headers[2]),
        "rows": rows,
    }


def set_name_from_filename(filename: str) -> str:
    return Path(filename).stem.strip()
