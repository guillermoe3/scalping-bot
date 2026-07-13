"""Corre la matriz pre-registrada del ablation de gates (P0-8) para la decisión N1.

Uso: python run_ablation.py --start 2026-04-01 --end 2026-07-01

12 corridas secuenciales (2 variantes × [base + 5 gates]) con el embudo
pre-registrado en el spec de N1. Nunca paralelizar: cada corrida usa ~2.2 GB.
Criterio de adopción (fijado ANTES de correr): la corrida BASE de una variante
debe ser rentable neta de fees con ≥ 30 trades; si no, no se adopta.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import backtest

RUNS_DIR = "backtest_runs"
FUNNEL_COMPRESSION = 0.6
FUNNEL_MIN_BARS = 2
ABLATABLE_GATES = ("regime_known", "spread", "trend_1h", "breakout_align", "cvd")
INERT_GATES = ("macro", "ob_imbalance")  # neutrales en backtest por diseño
MIN_TRADES_FOR_ADOPTION = 30


def build_run_matrix() -> list:
    matrix = []
    for variant, tag in (("fade", "A"), ("break", "B")):
        matrix.append({"variant": variant, "disabled_gate": None, "label": f"abl{tag}-base"})
        for gate in ABLATABLE_GATES:
            matrix.append({"variant": variant, "disabled_gate": gate,
                           "label": f"abl{tag}-no-{gate}"})
    return matrix


def _spec_matches_meta(spec: dict, meta: dict, start: str, end: str) -> bool:
    if not isinstance(meta, dict):
        return False
    disabled = [spec["disabled_gate"]] if spec["disabled_gate"] else []
    return (meta.get("label") == spec["label"]
            and meta.get("start") == start and meta.get("end") == end
            and meta.get("variant") == spec["variant"]
            and meta.get("disabled_gates") == disabled
            and meta.get("squeeze_compression") == FUNNEL_COMPRESSION
            and meta.get("squeeze_min_bars") == FUNNEL_MIN_BARS)


def find_existing_run(spec: dict, start: str, end: str, runs_dir: str = RUNS_DIR):
    if not os.path.isdir(runs_dir):
        return None
    for name in sorted(os.listdir(runs_dir), reverse=True):
        meta_path = os.path.join(runs_dir, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if _spec_matches_meta(spec, meta, start, end):
            return name
    return None


def _argv_for(spec: dict, start: str, end: str) -> list:
    argv = ["--start", start, "--end", end,
            "--variant", spec["variant"],
            "--squeeze-compression", str(FUNNEL_COMPRESSION),
            "--squeeze-min-bars", str(FUNNEL_MIN_BARS),
            "--label", spec["label"]]
    if spec["disabled_gate"]:
        argv += ["--disable-gate", spec["disabled_gate"]]
    return argv


def run_matrix(start: str, end: str, runner=backtest.main, runs_dir: str = RUNS_DIR) -> None:
    for spec in build_run_matrix():
        existing = find_existing_run(spec, start, end, runs_dir)
        if existing:
            print(f"[skip] {spec['label']} ya corrida: {existing}")
            continue
        print(f"[run ] {spec['label']}")
        rc = runner(_argv_for(spec, start, end))
        if rc != 0:
            raise RuntimeError(f"backtest falló para {spec['label']} (rc={rc})")


def _load_metrics(spec: dict, start: str, end: str, runs_dir: str):
    name = find_existing_run(spec, start, end, runs_dir)
    if name is None:
        return None
    with open(os.path.join(runs_dir, name, "summary.json")) as f:
        return json.load(f)["metrics"]


def _fmt_num(value, spec: str) -> str:
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)  # p. ej. profit_factor serializado como "inf"


def _verdict_line(tag: str, metrics) -> str:
    if metrics is None:
        return f"- Variante {tag}: SIN DATOS (corrida base no encontrada)"
    pnl = metrics.get("total_net_pnl", 0.0)
    trades = metrics.get("total_trades", 0)
    adopted = isinstance(pnl, (int, float)) and pnl > 0 and trades >= MIN_TRADES_FOR_ADOPTION
    verdict = "SE ADOPTA" if adopted else "NO se adopta"
    return (f"- Variante {tag} (base): {trades} trades, P&L neto ${_fmt_num(pnl, '+.2f')} → "
            f"**{verdict}** (criterio pre-registrado: P&L neto > 0 y "
            f"≥ {MIN_TRADES_FOR_ADOPTION} trades)")


def write_report(start: str, end: str, runs_dir: str = RUNS_DIR) -> str:
    lines = [
        f"# Ablation N1/P0-8 — {start} → {end}", "",
        f"Embudo pre-registrado: compresión {FUNNEL_COMPRESSION} · mínimo {FUNNEL_MIN_BARS} velas.",
        f"Gates inertes en backtest (sin corrida propia; un veto de 0 acá NO significa "
        f"\"no aporta\"): {', '.join(INERT_GATES)}.", "",
    ]
    base_metrics = {}
    for variant, tag in (("fade", "A"), ("break", "B")):
        lines += [f"## Variante {tag} ({variant})", "",
                  "| Corrida | Trades | Win rate | P&L neto | Profit factor | Señales | Vetos |",
                  "|---|---|---|---|---|---|---|"]
        for spec in build_run_matrix():
            if spec["variant"] != variant:
                continue
            m = _load_metrics(spec, start, end, runs_dir)
            if m is None:
                lines.append(f"| {spec['label']} | — | — | — | — | — | corrida faltante |")
                continue
            vetoes = m.get("gate_vetoes") or {}
            veto_str = " ".join(f"{k}:{v}" for k, v in
                                sorted(vetoes.items(), key=lambda kv: -kv[1]) if v) or "0"
            lines.append(
                f"| {spec['label']} | {m.get('total_trades', 0)} "
                f"| {_fmt_num(m.get('win_rate', 0), '.1%')} "
                f"| ${_fmt_num(m.get('total_net_pnl', 0), '+.2f')} "
                f"| {_fmt_num(m.get('profit_factor', 0), '.2f')} "
                f"| {m.get('signals_fired', '—')} | {veto_str} |")
            if spec["disabled_gate"] is None:
                base_metrics[tag] = m
        lines.append("")
    lines += ["## Veredicto (criterio pre-registrado)", "",
              _verdict_line("A", base_metrics.get("A")),
              _verdict_line("B", base_metrics.get("B")), ""]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(runs_dir, f"ablation-{date}.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Matriz de ablation N1/P0-8")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusivo)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    run_matrix(args.start, args.end)
    path = write_report(args.start, args.end)
    print(f"Reporte: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
