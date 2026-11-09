"""El panel de Power BI se genera como código: se comprueba que es coherente con el modelo y con SQL."""
import json
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
import generar_powerbi as pbi  # noqa: E402


@pytest.fixture(scope="module")
def proyecto(tmp_path_factory):
    destino = tmp_path_factory.mktemp("powerbi")
    pbi.DESTINO = destino
    pbi.generar()
    return destino


def campos(obj):
    """Todas las referencias a columnas y medidas de un visual: (tipo, tabla, nombre)."""
    if isinstance(obj, dict):
        for tipo in ("Column", "Measure"):
            if tipo in obj and "Entity" in obj[tipo].get("Expression", {}).get("SourceRef", {}):
                yield tipo, obj[tipo]["Expression"]["SourceRef"]["Entity"], obj[tipo]["Property"]
        for v in obj.values():
            yield from campos(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from campos(v)


def test_los_visuales_usan_campos_del_modelo(proyecto):
    columnas = {(t, c) for t, (_, cols) in pbi.TABLAS.items() for c, _, _ in cols}
    medidas = {(t, m) for t, lista in pbi.MEDIDAS.items() for m, *_ in lista}
    visuales = list(proyecto.rglob("visual.json"))
    assert len(visuales) > 20
    for v in visuales:
        for tipo, tabla, nombre in campos(json.loads(v.read_text(encoding="utf-8"))):
            conjunto = columnas if tipo == "Column" else medidas
            assert (tabla, nombre) in conjunto, f"{v.parent.name}: {tipo} {tabla}.{nombre} no existe"


def test_las_columnas_del_modelo_existen_en_sql():
    sql = (RAIZ / "sql" / "01_esquema.sql").read_text(encoding="utf-8")
    for tabla, (esquema, columnas) in pbi.TABLAS.items():
        nombre = f"{esquema}.{tabla}"
        bloques = re.findall(rf"CREATE TABLE {re.escape(nombre)} \((.*?)\n\);", sql, re.S)
        bloques += re.findall(rf"ALTER TABLE {re.escape(nombre)} ADD (.*?);", sql, re.S)
        texto = "\n".join(bloques)
        assert texto, nombre
        for col, _, opciones in columnas:
            if not opciones.get("calculada"):
                assert re.search(rf"\b{col}\b", texto), f"{nombre}.{col} no está en sql/01_esquema.sql"


def test_las_medidas_solo_usan_tablas_y_medidas_conocidas():
    medidas = {m for lista in pbi.MEDIDAS.values() for m, *_ in lista}
    for lista in pbi.MEDIDAS.values():
        for nombre, dax, *_ in lista:
            for tabla, col in re.findall(r"(\w+)\[([^\]]+)\]", dax):
                assert tabla in pbi.TABLAS, f"{nombre}: tabla {tabla}"
                assert col in {c for c, _, _ in pbi.TABLAS[tabla][1]}, f"{nombre}: columna {tabla}[{col}]"
            for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", dax):
                assert ref in medidas, f"{nombre}: medida [{ref}]"


def test_roles_de_seguridad(proyecto):
    roles = proyecto / f"{pbi.NOMBRE}.SemanticModel" / "definition" / "roles"
    assert (roles / "Cliente demo A.tmdl").read_text(encoding="utf-8").count("dim_cliente[cliente_id] = 1") == 1
    assert (roles / "Cliente demo B.tmdl").read_text(encoding="utf-8").count("dim_cliente[cliente_id] = 2") == 1
    assert "tablePermission" not in (roles / "Consultora.tmdl").read_text(encoding="utf-8")


def test_cada_pagina_lleva_la_nota_de_la_cnmv(proyecto):
    paginas = proyecto / f"{pbi.NOMBRE}.Report" / "definition" / "pages"
    for pagina in [p for p in paginas.iterdir() if p.is_dir()]:
        textos = " ".join(v.read_text(encoding="utf-8") for v in pagina.rglob("visual.json"))
        assert "gratuita en www.cnmv.es" in textos, pagina.name


def test_generar_dos_veces_da_lo_mismo(proyecto, tmp_path):
    pbi.DESTINO = tmp_path
    pbi.generar()
    for f in proyecto.rglob("*"):
        if f.is_file():
            assert (tmp_path / f.relative_to(proyecto)).read_bytes() == f.read_bytes(), f
