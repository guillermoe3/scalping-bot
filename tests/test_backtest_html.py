import json
import os

from backtest_html import collect_runs, render_index, write_index


def _make_run(base, name, pnl=10.0, corrupt=False, gate_vetoes=None):
    d = os.path.join(base, name)
    os.makedirs(d)
    if corrupt:
        open(os.path.join(d, "meta.json"), "w").write("{not json")
        return
    json.dump({"start": "2026-04-01", "end": "2026-07-01", "label": "base",
               "git_commit": "abc1234", "created_utc": "2026-07-03T15:30:45Z"},
              open(os.path.join(d, "meta.json"), "w"))
    metrics = {"total_trades": 3, "win_rate": 0.66, "total_net_pnl": pnl,
               "profit_factor": 2.0, "max_drawdown": 1.0,
               "max_consecutive_losses": 1}
    if gate_vetoes is not None:
        metrics["gate_vetoes"] = gate_vetoes
    json.dump({"metrics": metrics,
               "equity_curve": [[1, 4.0], [2, -1.0], [3, pnl]],
               "final_equity": pnl},
              open(os.path.join(d, "summary.json"), "w"))


def test_collect_runs_empty_dir(tmp_path):
    runs, corrupt = collect_runs(str(tmp_path))
    assert runs == [] and corrupt == []


def test_collect_runs_reads_runs_and_flags_corrupt(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    _make_run(str(tmp_path), "2026-07-02_10-00-00")
    _make_run(str(tmp_path), "2026-07-03_10-00-00", corrupt=True)
    runs, corrupt = collect_runs(str(tmp_path))
    assert [r["name"] for r in runs] == ["2026-07-02_10-00-00", "2026-07-01_10-00-00"]
    assert corrupt == ["2026-07-03_10-00-00"]


def test_render_index_contains_rows_sparkline_and_no_external_refs(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    runs, corrupt = collect_runs(str(tmp_path))
    html = render_index(runs, corrupt)
    assert "2026-07-01_10-00-00" in html
    assert "<svg" in html and "polyline" in html
    assert "http://" not in html and "https://" not in html  # autocontenido
    assert "<script src" not in html and "<link" not in html


def test_render_index_zero_runs_renders_page():
    html = render_index([], [])
    assert "<table" in html or "Sin corridas" in html


def test_render_index_escapes_labels(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    runs, _ = collect_runs(str(tmp_path))
    runs[0]["meta"]["label"] = "<script>alert(1)</script>"
    assert "<script>alert(1)" not in render_index(runs, [])


def test_render_index_escapes_string_metrics(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    runs, _ = collect_runs(str(tmp_path))
    runs[0]["summary"]["metrics"]["total_trades"] = "<img src=x onerror=alert(1)>"
    html_out = render_index(runs, [])
    assert "<img src=x" not in html_out


def test_write_index_creates_file(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    path = write_index(str(tmp_path))
    assert path.endswith("index.html")
    assert os.path.exists(path)


def test_index_renders_gate_vetoes_sorted_desc(tmp_path):
    _make_run(str(tmp_path), "2026-07-12_10-00-00",
              gate_vetoes={"trend_1h": 12, "cvd": 3, "spread": 0})

    write_index(str(tmp_path))
    html_text = open(os.path.join(str(tmp_path), "index.html")).read()

    assert "trend_1h:12 cvd:3" in html_text  # orden descendente, los ceros no aparecen
    assert "Vetos" in html_text


def test_index_tolerates_runs_without_gate_vetoes(tmp_path):
    _make_run(str(tmp_path), "2026-07-12_10-00-00")  # formato viejo, sin la clave

    write_index(str(tmp_path))
    html_text = open(os.path.join(str(tmp_path), "index.html")).read()

    assert "Vetos" in html_text  # la columna existe igual; la celda rinde "—"
