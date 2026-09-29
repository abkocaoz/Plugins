"""Arayüz tasarım sistemi: renk tokenları, genel CSS ve küçük HTML bileşenleri.

Renkler rollere göre tanımlıdır (yüzey, mürekkep, çizgi, vurgu, durum). Durum renkleri
(iyi / uyarı / ciddi / kritik) yalnızca durum için kullanılır ve hiçbir zaman tek başına
anlam taşımaz: her zaman bir simge ve etiketle birlikte gösterilir.
"""
from __future__ import annotations

import html

import streamlit as st

# --------------------------------------------------------------------------- tokenlar
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
LINE = "#e1e0d9"
PAGE = "#f9f9f7"
SURFACE = "#fcfcfb"
SURFACE_2 = "#f3f2ee"
ACCENT = "#2a78d6"
ACCENT_WASH = "#eaf2fc"

# Durum: (işaret rengi, zemin tonu)
TONES = {
    "good": ("#0ca30c", "#e5f4e5"),
    "warning": ("#fab219", "#fdf1d6"),
    "serious": ("#ec835a", "#fbe7de"),
    "critical": ("#d03b3b", "#f8e1e1"),
    "neutral": ("#898781", "#f0efec"),
    "info": (ACCENT, ACCENT_WASH),
}

# Önem → (ton, simge)
SEVERITY_STYLE = {
    "Yüksek": ("critical", "▲"),
    "Orta": ("warning", "◆"),
    "Düşük": ("neutral", "▽"),
}

# Kapsam matrisi hücreleri → ton
CELL_TONE = {"✓": "good", "≠": "critical", "–": "neutral"}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


# --------------------------------------------------------------------------- genel CSS
_CSS = f"""
<style>
:root {{
  --gk-ink:{INK}; --gk-ink-2:{INK_2}; --gk-muted:{MUTED}; --gk-line:{LINE};
  --gk-page:{PAGE}; --gk-surface:{SURFACE}; --gk-surface-2:{SURFACE_2};
  --gk-accent:{ACCENT}; --gk-accent-wash:{ACCENT_WASH};
  --gk-border:rgba(11,11,11,.10); --gk-radius:10px;
}}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1480px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
h3 {{ font-size: 1.15rem !important; font-weight: 600 !important; margin-top: .6rem; }}

/* ---- kenar çubuğu */
section[data-testid="stSidebar"] {{ background: var(--gk-surface-2); border-right: 1px solid var(--gk-line); }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
/* Streamlit sürümüne göre radyo seçeneği ya doğrudan label ya da label[data-testid=stRadioOption] */
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; width: 100%; display: flex;
  flex-direction: column; align-items: stretch; }}
section[data-testid="stSidebar"] [data-testid="stRadio"],
section[data-testid="stSidebar"] [data-testid="stRadio"] > div,
section[data-testid="stSidebar"] [role="radiogroup"] > div {{ width: 100%; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{ display: flex; box-sizing: border-box; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
  width: 100%; margin: 0; padding: 7px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid transparent; transition: background .12s;
}}
section[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child,
section[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child:not([data-testid="stMarkdownContainer"]) {{
  display: none;
}}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(11,11,11,.05); }}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: var(--gk-surface); border-color: var(--gk-border);
  box-shadow: 0 1px 2px rgba(11,11,11,.06);
}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
  font-weight: 600; color: var(--gk-accent);
}}
section[data-testid="stSidebar"] [role="radiogroup"] p {{ font-size: 14px; }}

/* ---- marka / proje kartı */
.gk-brand {{ display:flex; align-items:center; gap:10px; margin: 0 0 14px; }}
.gk-brand-mark {{ width:34px; height:34px; border-radius:9px; background:var(--gk-accent); color:#fff;
  display:flex; align-items:center; justify-content:center; font-weight:700; font-size:15px; }}
.gk-brand-t {{ font-weight:700; font-size:15px; line-height:1.15; color:var(--gk-ink); }}
.gk-brand-s {{ font-size:12px; color:var(--gk-muted); }}
.gk-proj {{ background:var(--gk-surface); border:1px solid var(--gk-border); border-radius:var(--gk-radius);
  padding:10px 12px; margin: 6px 0 12px; }}
.gk-proj-l {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--gk-muted); }}
.gk-proj-n {{ font-weight:600; color:var(--gk-ink); margin:1px 0 6px; word-break:break-word; }}
.gk-proj-m {{ font-size:12px; color:var(--gk-ink-2); display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
.gk-navlabel {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--gk-muted);
  margin: 8px 2px 4px; }}

/* ---- sayfa başlığı */
.gk-ph {{ margin: 0 0 18px; padding-bottom: 14px; border-bottom: 1px solid var(--gk-line); }}
.gk-ph-step {{ font-size:12px; font-weight:600; color:var(--gk-accent); letter-spacing:.04em;
  text-transform:uppercase; }}
.gk-ph-t {{ font-size: 28px; font-weight: 700; color: var(--gk-ink); line-height:1.2; margin: 2px 0 4px; }}
.gk-ph-s {{ font-size: 14.5px; color: var(--gk-ink-2); max-width: 900px; line-height:1.5; }}

/* ---- istatistik kartları */
.gk-tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin: 4px 0 18px; }}
.gk-tile {{ background:var(--gk-surface); border:1px solid var(--gk-border); border-radius:var(--gk-radius);
  padding:12px 14px 11px; }}
.gk-tile-l {{ font-size:13px; color:var(--gk-ink-2); display:flex; align-items:center; gap:6px; }}
.gk-tile-v {{ font-size:28px; font-weight:650; color:var(--gk-ink); line-height:1.15; margin-top:4px; }}
.gk-tile-n {{ font-size:12px; color:var(--gk-muted); margin-top:2px; }}
.gk-dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; flex:none; }}

/* ---- çip, lejant, kart */
.gk-chip {{ display:inline-flex; align-items:center; gap:5px; padding:1px 8px 1px 7px; border-radius:999px;
  font-size:12px; font-weight:600; color:var(--gk-ink); white-space:nowrap; line-height:20px; }}
.gk-chip i {{ font-style:normal; font-size:10px; }}
.gk-legend {{ display:flex; flex-wrap:wrap; gap:14px; font-size:12.5px; color:var(--gk-ink-2); margin: 2px 0 8px; }}
.gk-legend span {{ display:inline-flex; align-items:center; gap:6px; }}
.gk-sw {{ width:18px; height:14px; border-radius:3px; display:inline-flex; align-items:center; justify-content:center;
  font-size:10px; font-weight:700; color:var(--gk-ink); }}
.gk-card {{ background:var(--gk-surface); border:1px solid var(--gk-border); border-radius:var(--gk-radius);
  padding:14px 16px; margin-bottom:10px; }}
.gk-card-h {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; font-size:14px; }}
.gk-card-h b {{ color:var(--gk-ink); }}
.gk-card-h .gk-meta {{ color:var(--gk-muted); font-size:12.5px; }}
.gk-ref-l {{ font-size:12px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:var(--gk-accent); }}
.gk-ref-t {{ font-weight:600; margin:4px 0 2px; color:var(--gk-ink); }}
.gk-ref-b {{ color:var(--gk-ink); line-height:1.6; }}
.gk-steps {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-top:8px; }}
.gk-step-n {{ width:26px; height:26px; border-radius:50%; background:var(--gk-accent-wash); color:var(--gk-accent);
  font-weight:700; display:flex; align-items:center; justify-content:center; font-size:13px; margin-bottom:8px; }}
.gk-step-t {{ font-weight:600; color:var(--gk-ink); margin-bottom:3px; }}
.gk-step-d {{ font-size:13px; color:var(--gk-ink-2); line-height:1.45; }}

/* ---- kelime farkı */
.gk-diff {{ white-space:pre-wrap; line-height:1.7; color:var(--gk-ink); }}
.gk-diff del {{ background:{TONES['critical'][1]}; text-decoration:line-through; text-decoration-color:{TONES['critical'][0]};
  border-bottom:2px solid {TONES['critical'][0]}; border-radius:2px; padding:0 1px; }}
.gk-diff ins {{ background:{TONES['good'][1]}; text-decoration:none; border-bottom:2px solid {TONES['good'][0]};
  border-radius:2px; padding:0 1px; }}

/* ---- veri tablosu */
.gk-wrap {{ overflow:auto; border:1px solid var(--gk-border); border-radius:var(--gk-radius); background:var(--gk-surface); }}
.gk-t {{ border-collapse:separate; border-spacing:0; font-size:13px; color:var(--gk-ink); width:max-content; }}
.gk-t th {{ position:sticky; top:0; z-index:2; background:var(--gk-surface-2); color:var(--gk-ink-2);
  text-align:left; font-weight:600; font-size:12px; padding:8px 10px; white-space:nowrap;
  border-bottom:1px solid var(--gk-line); }}
.gk-t th small {{ color:var(--gk-muted); font-weight:500; }}
.gk-t td {{ padding:8px 10px; vertical-align:top; white-space:pre-wrap; word-break:break-word; min-width:90px;
  border-bottom:1px solid var(--gk-line); background:var(--gk-surface); line-height:1.5; }}
.gk-t td.gk-k, .gk-t th.gk-k {{ position:sticky; left:0; z-index:1; font-weight:600; min-width:110px;
  white-space:nowrap; box-shadow: 1px 0 0 var(--gk-line); }}
.gk-t td.gk-k {{ background:var(--gk-surface-2); border-bottom-color:#d6d4cc; }}
.gk-t th.gk-k {{ z-index:3; }}
.gk-t tr.gk-grp td {{ border-top:2px solid var(--gk-line); }}
.gk-t td.gk-d {{ background:{TONES['critical'][1]}; box-shadow: inset 3px 0 0 {TONES['critical'][0]}; }}
.gk-t td.gk-r {{ background:var(--gk-accent-wash); box-shadow: inset 3px 0 0 var(--gk-accent); }}
.gk-t td.gk-m {{ background:{TONES['neutral'][1]}; color:var(--gk-muted); }}
.gk-t small.gk-n {{ display:block; margin-top:5px; color:#9b2626; font-weight:600; font-size:11.5px; }}

/* ---- Streamlit bileşenleri */
div[data-testid="stExpander"] details {{ border-radius:var(--gk-radius); border-color:var(--gk-border);
  background:var(--gk-surface); }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:var(--gk-radius); }}
.stButton button, .stDownloadButton button {{ border-radius:8px; font-weight:500; }}
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{ border-radius:var(--gk-radius); }}
</style>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- bileşenler
def page_header(step: str, title: str, subtitle: str = ""):
    st.markdown(
        f'<div class="gk-ph"><div class="gk-ph-step">{esc(step)}</div>'
        f'<div class="gk-ph-t">{esc(title)}</div>'
        + (f'<div class="gk-ph-s">{subtitle}</div>' if subtitle else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def stat_tiles(tiles: list[dict]):
    """tiles: [{label, value, note?, tone?}] — tone verilirse etiketin yanında durum noktası çıkar."""
    out = []
    for t in tiles:
        dot = ""
        if t.get("tone"):
            dot = f'<span class="gk-dot" style="background:{TONES[t["tone"]][0]}"></span>'
        note = f'<div class="gk-tile-n">{esc(t["note"])}</div>' if t.get("note") else ""
        out.append(f'<div class="gk-tile"><div class="gk-tile-l">{dot}{esc(t["label"])}</div>'
                   f'<div class="gk-tile-v">{esc(t["value"])}</div>{note}</div>')
    st.markdown(f'<div class="gk-tiles">{"".join(out)}</div>', unsafe_allow_html=True)


def chip(label: str, tone: str = "neutral", icon: str = "") -> str:
    fg, bg = TONES[tone]
    ic = f'<i style="color:{fg}">{esc(icon)}</i>' if icon else f'<span class="gk-dot" style="background:{fg}"></span>'
    return f'<span class="gk-chip" style="background:{bg}">{ic}{esc(label)}</span>'


def sev_chip(sev: str) -> str:
    if sev not in SEVERITY_STYLE:
        return ""
    tone, icon = SEVERITY_STYLE[sev]
    return chip(sev, tone, icon)


def legend(items: list[tuple[str, str, str]]):
    """items: [(ton, simge, etiket)]"""
    parts = []
    for tone, glyph, label in items:
        fg, bg = TONES[tone]
        parts.append(f'<span><span class="gk-sw" style="background:{bg};box-shadow:inset 3px 0 0 {fg}">'
                     f'{esc(glyph)}</span>{esc(label)}</span>')
    st.markdown(f'<div class="gk-legend">{"".join(parts)}</div>', unsafe_allow_html=True)


def sev_cell_css(v) -> str:
    """pandas Styler için: önem hücresi."""
    if v in SEVERITY_STYLE:
        fg, bg = TONES[SEVERITY_STYLE[v][0]]
        return f"background-color:{bg};color:{INK};font-weight:600;border-left:3px solid {fg}"
    return ""


def matrix_cell_css(v) -> str:
    if v in CELL_TONE:
        fg, bg = TONES[CELL_TONE[v]]
        return f"background-color:{bg};color:{INK};text-align:center;font-weight:700"
    return ""


def html_table(header: list[str], rows: list[tuple[str, list[tuple[str, str]]]], sticky_cols: int = 1,
               max_height: int = 620, cell_width: int = 420) -> str:
    """Kaydırılabilir, metni satır kaydıran HTML tablo.

    rows: [(satır_sınıfı, [(hücre_html, hücre_sınıfı), ...]), ...] — hücre_html önceden kaçışlanmış olmalı.
    İlk sütun yatay kaydırmada sabit kalır.
    """
    th = "".join(f'<th class="{"gk-k" if i < sticky_cols else ""}">{h}</th>' for i, h in enumerate(header))
    body = []
    for rcls, cells in rows:
        tds = "".join(
            f'<td class="{"gk-k " if i < sticky_cols else ""}{cls}" style="max-width:{cell_width}px">{val}</td>'
            for i, (val, cls) in enumerate(cells)
        )
        body.append(f'<tr class="{rcls}">{tds}</tr>')
    return (f'<div class="gk-wrap" style="max-height:{max_height}px"><table class="gk-t"><thead><tr>{th}</tr>'
            f'</thead><tbody>{"".join(body)}</tbody></table></div>')
