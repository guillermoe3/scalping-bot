from __future__ import annotations

import html
import json
import os
from typing import List, Tuple

_COLS = [
    ("name", "Corrida"), ("label", "Etiqueta"), ("range", "Rango"),
    ("commit", "Commit"), ("total_trades", "Trades"), ("win_rate", "Win rate"),
    ("total_net_pnl", "P&L neto"), ("profit_factor", "Profit factor"),
    ("max_drawdown", "Max DD"), ("max_consecutive_losses", "Racha perd."),
    ("gate_vetoes", "Vetos"),
    ("equity", "Equity"),
]


def collect_runs(base_dir: str) -> Tuple[List[dict], List[str]]:
    runs: List[dict] = []
    corrupt: List[str] = []
    if not os.path.isdir(base_dir):
        return runs, corrupt
    for name in sorted(os.listdir(base_dir), reverse=True):
        run_dir = os.path.join(base_dir, name)
        if not os.path.isdir(run_dir):
            continue
        try:
            with open(os.path.join(run_dir, "meta.json")) as f:
                meta = json.load(f)
            with open(os.path.join(run_dir, "summary.json")) as f:
                summary = json.load(f)
            runs.append({"name": name, "meta": meta, "summary": summary})
        except (OSError, ValueError):
            corrupt.append(name)
    return runs, corrupt


def _sparkline_svg(points: List[list], width: int = 140, height: int = 36) -> str:
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    y_min, y_max = min(ys + [0.0]), max(ys + [0.0])
    x_span = (xs[-1] - xs[0]) or 1
    y_span = (y_max - y_min) or 1
    coords = " ".join(
        f"{(x - xs[0]) / x_span * width:.1f},{height - (y - y_min) / y_span * height:.1f}"
        for x, y in points
    )
    # Status palette (dataviz skill): good/critical, distinct from categorical hues.
    # Colors are set via the `style` attribute (not `stroke=`) so CSS custom
    # properties resolve reliably, including the dark-mode override.
    color_var = "--good" if ys[-1] >= 0 else "--critical"
    zero_y = height - (0.0 - y_min) / y_span * height
    title = html.escape(f"equity final: {ys[-1]:+.2f}")
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
        f'<title>{title}</title>'
        f'<line x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}" style="stroke:var(--baseline)" stroke-width="1"/>'
        f'<polyline fill="none" style="stroke:var({color_var})" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{coords}"/></svg>'
    )


def _fmt(value, spec: str = "") -> str:
    if value is None or value == "inf":
        return "∞" if value == "inf" else "—"
    try:
        return html.escape(format(value, spec) if spec else str(value))
    except (TypeError, ValueError):
        return html.escape(str(value))


def _fmt_vetoes(vetoes) -> str:
    if not isinstance(vetoes, dict) or not vetoes:
        return "—"
    parts = [f"{k}:{v}" for k, v in sorted(vetoes.items(), key=lambda kv: -kv[1]) if v]
    return html.escape(" ".join(parts)) if parts else "0"


def _row(run: dict) -> str:
    meta, m = run["meta"], run["summary"]["metrics"]
    cells = [
        html.escape(run["name"]),
        html.escape(str(meta.get("label") or "—")),
        html.escape(f"{meta.get('start', '?')} → {meta.get('end', '?')}"),
        html.escape(str(meta.get("git_commit", "?"))),
        _fmt(m.get("total_trades")),
        _fmt(m.get("win_rate"), ".1%"),
        _fmt(m.get("total_net_pnl"), "+.2f"),
        _fmt(m.get("profit_factor"), ".2f"),
        _fmt(m.get("max_drawdown"), ".2f"),
        _fmt(m.get("max_consecutive_losses")),
        _fmt_vetoes(m.get("gate_vetoes")),
        _sparkline_svg(run["summary"].get("equity_curve", [])),
    ]
    numeric_cols = {4, 5, 6, 7, 8, 9}  # total_trades..max_consecutive_losses
    tds = []
    for i, c in enumerate(cells):
        cls = ' class="num"' if i in numeric_cols else ""
        tds.append(f"<td{cls}>{c}</td>")
    return "<tr>" + "".join(tds) + "</tr>"


# Colors follow the dataviz skill's reference palette (references/palette.md):
# chart chrome & ink tokens for light/dark, status "good"/"critical" for the
# sparkline trend line (a mark), never for table text.
_STYLE = """:root{
  --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --baseline:#c3c2b7; --good:#0ca30c; --critical:#d03b3b; --warning:#fab219;
}
@media (prefers-color-scheme:dark){:root{
  --surface:#1a1a19; --page:#0d0d0d; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --baseline:#383835; --good:#0ca30c; --critical:#e66767; --warning:#fab219;
}}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:2rem;background:var(--page);color:var(--ink)}
h1{font-size:1.25rem;font-weight:600}
table{border-collapse:collapse;width:100%;background:var(--surface)}
th,td{padding:.45rem .6rem;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
td.num,th{font-variant-numeric:tabular-nums}
th{cursor:pointer;background:var(--surface);position:sticky;top:0;color:var(--ink-2);font-weight:600;
   border-bottom:1px solid var(--baseline)}
td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
.warn{color:var(--ink);background:color-mix(in srgb, var(--warning) 18%, var(--surface));
      border:1px solid var(--warning);border-radius:.35rem;padding:.5rem .75rem;display:inline-block}
.muted{color:var(--muted)}
.wrap{overflow-x:auto;border:1px solid var(--grid);border-radius:.35rem}"""

_SORT_JS = """document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
const tb=th.closest('table').querySelector('tbody');const dir=th.dataset.dir=th.dataset.dir==='a'?'d':'a';
[...tb.rows].sort((x,y)=>{const a=x.cells[i].innerText,b=y.cells[i].innerText;
const na=parseFloat(a.replace(/[^\\d.-]/g,'')),nb=parseFloat(b.replace(/[^\\d.-]/g,''));
const c=(isNaN(na)||isNaN(nb))?a.localeCompare(b):na-nb;return dir==='a'?c:-c;})
.forEach(r=>tb.appendChild(r));}));"""


def render_index(runs: List[dict], corrupt: List[str]) -> str:
    headers = "".join(f"<th>{html.escape(title)}</th>" for _, title in _COLS)
    body = "".join(_row(r) for r in runs)
    warn = ""
    if corrupt:
        names = ", ".join(html.escape(c) for c in corrupt)
        warn = f'<p><span class="warn">⚠ Corridas ilegibles (ignoradas): {names}</span></p>'
    empty = ('<p class="muted">Sin corridas todavía. Corré un backtest para ver resultados acá.</p>'
             if not runs else "")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<title>Backtest runs — scalping-bot</title><style>{_STYLE}</style></head><body>
<h1>Corridas de backtest</h1>{warn}{empty}
<div class="wrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
<p class="muted">Click en un encabezado ordena por esa columna. Detalle completo de cada corrida en su carpeta (trades.csv).</p>
<script>{_SORT_JS}</script></body></html>"""


def write_index(base_dir: str) -> str:
    runs, corrupt = collect_runs(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, "index.html")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_index(runs, corrupt))
    os.replace(tmp, path)
    return path
