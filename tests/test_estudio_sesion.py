from datetime import datetime, timezone

from estudios.estudio_sesion import bucketear


def _row_at(iso: str):
    ts = int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return [ts, 100.0, 100.0, 100.0, 100.0, 1.0, 0.5]


def test_bucketear_por_hora_y_finde():
    rows = [
        _row_at("2026-01-05T14:00:00"),  # lunes 14 UTC
        _row_at("2026-01-10T14:00:00"),  # sábado 14 UTC
        _row_at("2026-01-05T15:00:00"),  # lunes 15 UTC
    ]
    b = bucketear(rows)
    assert b[(14, False)] == [0]
    assert b[(14, True)] == [1]
    assert b[(15, False)] == [2]
