import json
import os

from estudios.reporte import escribir_reporte


def test_escribir_reporte_incluye_preregistro_y_celdas(tmp_path):
    ruta = escribir_reporte(
        "demo", {"umbral": "mediana >= 0.14%"}, celdas=12,
        resultados={"grupo": {"n": 3}}, base_dir=str(tmp_path),
    )
    md = open(os.path.join(ruta, "reporte.md")).read()
    assert "Pre-registro" in md and "mediana >= 0.14%" in md
    assert "Celdas miradas: 12" in md
    datos = json.load(open(os.path.join(ruta, "resultados.json")))
    assert datos["preregistro"]["umbral"] == "mediana >= 0.14%"
    assert datos["celdas"] == 12
