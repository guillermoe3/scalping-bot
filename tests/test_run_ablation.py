import json

import run_ablation


def _write_fake_run(runs_dir, name, meta, metrics):
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps(meta))
    (run_dir / "summary.json").write_text(json.dumps({"metrics": metrics, "equity_curve": []}))


def _meta_for(spec, start="2026-04-01", end="2026-07-01"):
    return {
        "label": spec["label"], "start": start, "end": end,
        "variant": spec["variant"],
        "disabled_gates": [spec["disabled_gate"]] if spec["disabled_gate"] else [],
        "squeeze_compression": run_ablation.FUNNEL_COMPRESSION,
        "squeeze_min_bars": run_ablation.FUNNEL_MIN_BARS,
    }


def test_matrix_has_12_runs_with_systematic_labels():
    matrix = run_ablation.build_run_matrix()
    labels = [spec["label"] for spec in matrix]

    assert len(matrix) == 12
    assert "ablA-base" in labels and "ablB-base" in labels
    assert "ablA-no-trend_1h" in labels and "ablB-no-cvd" in labels
    assert not any("macro" in l or "ob_imbalance" in l for l in labels)  # inertes excluidos


def test_run_matrix_skips_existing_runs_and_runs_the_rest(tmp_path):
    done = run_ablation.build_run_matrix()[0]  # ablA-base ya corrida
    _write_fake_run(tmp_path, "2026-07-12_00-00-00_ablA-base", _meta_for(done),
                    {"total_trades": 5})
    executed = []

    def fake_runner(argv):
        executed.append(argv)
        # simular que la corrida persiste su run dir para el reporte posterior
        return 0

    run_ablation.run_matrix("2026-04-01", "2026-07-01", runner=fake_runner,
                            runs_dir=str(tmp_path))

    assert len(executed) == 11  # 12 menos la ya corrida
    first = executed[0]
    assert "--variant" in first and "--label" in first
    assert "--squeeze-compression" in first


def test_run_matrix_aborts_when_a_run_fails(tmp_path):
    import pytest

    def failing_runner(argv):
        return 1

    with pytest.raises(RuntimeError):
        run_ablation.run_matrix("2026-04-01", "2026-07-01", runner=failing_runner,
                                runs_dir=str(tmp_path))


def test_report_applies_preregistered_verdict(tmp_path):
    for spec in run_ablation.build_run_matrix():
        profitable = spec["variant"] == "break"
        _write_fake_run(
            tmp_path, f"2026-07-12_01-00-00_{spec['label']}", _meta_for(spec),
            {"total_trades": 40, "win_rate": 0.5, "profit_factor": 1.2,
             "total_net_pnl": 250.0 if profitable else -300.0,
             "signals_fired": 60,
             "gate_vetoes": {"trend_1h": 12, "cvd": 3}},
        )

    path = run_ablation.write_report("2026-04-01", "2026-07-01", runs_dir=str(tmp_path))
    text = open(path).read()

    assert "NO se adopta" in text          # variante A pierde
    assert "SE ADOPTA" in text             # variante B gana con ≥30 trades
    assert "trend_1h:12 cvd:3" in text
    assert "macro" in text and "ob_imbalance" in text  # inertes anotados


def test_report_rejects_profitable_base_with_too_few_trades(tmp_path):
    for spec in run_ablation.build_run_matrix():
        _write_fake_run(
            tmp_path, f"2026-07-12_02-00-00_{spec['label']}", _meta_for(spec),
            {"total_trades": 10, "win_rate": 0.6, "profit_factor": 2.0,
             "total_net_pnl": 500.0, "signals_fired": 12, "gate_vetoes": {}},
        )

    text = open(run_ablation.write_report("2026-04-01", "2026-07-01",
                                          runs_dir=str(tmp_path))).read()

    assert "SE ADOPTA" not in text
