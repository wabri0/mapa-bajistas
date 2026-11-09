import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.ingesta.almacen import AlmacenLocal
from src.modelo import bd, cargar, gold, precios

SQL = Path(__file__).parents[1] / "sql"
LEI_A, LEI_B = "A" * 20, "B" * 20


def tabla_precios(filas):
    """filas: (fecha, ticker, cierre, volumen) → tabla como la de precios.leer()."""
    df = pd.DataFrame(filas, columns=["fecha", "ticker", "cierre", "volumen"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["cierre_ajustado"] = df["cierre"]
    df["lei"] = df["ticker"].map({"AAA.MC": LEI_A, "BBB.MC": LEI_B})
    return df[["fecha", "lei", "ticker", "cierre", "cierre_ajustado", "volumen"]]


def acciones_del_dia(dia, n, volumen=1000):
    return [(dia, f"X{i}.MC", 1.0, volumen) for i in range(n)]


# ---------- Calendario de bolsa ----------

@pytest.mark.parametrize("anio,esperado", [(2019, date(2019, 4, 21)), (2024, date(2024, 3, 31)),
                                           (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))])
def test_domingo_de_pascua(anio, esperado):
    assert gold.domingo_de_pascua(anio) == esperado


def test_festivos_de_bolsa_2026():
    assert gold.festivos_bolsa(2026) == {date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
                                         date(2026, 5, 1), date(2026, 12, 25), date(2026, 12, 26)}


def test_dia_bolsa_por_ibex_por_acciones_y_dias_inventados():
    filas = [("2012-01-03", "^IBEX", 8000, 0), ("2012-01-04", "^IBEX", 8100, 0)]
    filas += acciones_del_dia("2012-01-02", 12)             # sin IBEX, pero cotizan 12 acciones
    filas += acciones_del_dia("2012-01-05", 12, volumen=0)  # día inventado: precios sin volumen
    filas += acciones_del_dia("2012-01-06", 3)              # muy pocas acciones: no cuenta
    fechas = gold.dim_fecha(tabla_precios(filas), date(2012, 1, 6)).set_index("fecha")
    bolsa = fechas["es_dia_bolsa"]
    assert bolsa["2012-01-02"] and bolsa["2012-01-03"] and bolsa["2012-01-04"]
    assert not bolsa["2012-01-05"] and not bolsa["2012-01-06"]
    assert fechas.loc["2012-01-06", "origen_calendario"] == "yahoo"


def test_dias_futuros_con_la_regla_de_festivos():
    precios_ = tabla_precios([("2026-12-22", "^IBEX", 17000, 0)])
    fechas = gold.dim_fecha(precios_, date(2026, 12, 22)).set_index("fecha")
    assert fechas.index.max() == pd.Timestamp("2026-12-31")
    assert fechas.loc["2026-12-23", "origen_calendario"] == "previsto"
    assert fechas.loc["2026-12-23", "es_dia_bolsa"]          # miércoles normal
    assert not fechas.loc["2026-12-25", "es_dia_bolsa"]      # Navidad
    assert not fechas.loc["2026-12-27", "es_dia_bolsa"]      # domingo
    fila = fechas.loc["2026-12-23"]
    assert fila["fecha_id"] == 20261223 and fila["dia_semana"] == 3 and fila["nombre_dia"] == "miércoles"


# ---------- Tablas gold ----------

@pytest.fixture
def silver_minima():
    # 29-mar-2024 es Viernes Santo: la silver (días laborables) tiene posición ese día
    dias = pd.to_datetime(["2024-03-28", "2024-03-29", "2024-04-02"])
    diarias = pd.DataFrame({"fecha": dias, "lei": LEI_A, "tenedor": "FONDO X", "pct": [0.6, 0.6, 0.7]})
    notif = pd.DataFrame({"lei": [LEI_A], "isin": ["ES0000000001"], "emisor": ["EMPRESA A"],
                          "tenedor": ["FONDO X"], "fecha_posicion": [pd.Timestamp("2024-03-28")], "pct": [0.6],
                          "fecha_primera_captura": [pd.NaT], "grupo_gestor": ["X"]})
    emisores = pd.DataFrame({"lei": [LEI_A], "emisor": ["EMPRESA A"], "isins": ["ES0000000001"],
                             "primera": dias[:1], "ultima": dias[:1], "notificaciones": [1]})
    fondos = pd.DataFrame({"tenedor": ["FONDO X"], "primera": dias[:1], "ultima": dias[:1],
                           "notificaciones": [1], "grupo_gestor": ["X"], "grupo_revisado": [False]})
    return {"posiciones_diarias": diarias, "notificaciones": notif, "emisores": emisores, "fondos": fondos}


@pytest.fixture
def precios_minimos():
    filas = []
    for dia in ["2024-03-28", "2024-04-01", "2024-04-02"]:  # 1-abr es Lunes de Pascua, pero hay un dato raro
        if dia != "2024-04-01":
            filas.append((dia, "^IBEX", 11000, 0))
        filas.append((dia, "AAA.MC", 10.0, 500 if dia != "2024-04-01" else 0))
    return tabla_precios(filas)


def test_construir_quita_festivos_y_el_indice(silver_minima, precios_minimos, monkeypatch):
    monkeypatch.setattr(precios, "tabla_tickers", lambda: pd.DataFrame({"lei": [LEI_A], "ticker": ["AAA.MC"]}))
    tablas, informe = gold.construir(silver_minima, precios_minimos, date(2024, 4, 2))
    assert tablas["posicion_diaria"]["fecha"].dt.strftime("%Y-%m-%d").tolist() == ["2024-03-28", "2024-04-02"]
    assert informe["posiciones_en_festivo_eliminadas"] == 1
    assert set(tablas["precio_diario"]["fecha"].dt.strftime("%Y-%m-%d")) == {"2024-03-28", "2024-04-02"}
    assert tablas["precio_diario"]["lei"].eq(LEI_A).all()       # el IBEX no es un emisor
    assert informe["precios_fuera_de_bolsa_eliminados"] == 1
    em = tablas["dim_emisor"].iloc[0]
    assert em["ticker"] == "AAA.MC" and em["tiene_precios"]
    assert set(tablas) == set(cargar.ESQUEMA_STG)


def test_tablas_gold_tienen_las_columnas_de_stg(silver_minima, precios_minimos, monkeypatch):
    monkeypatch.setattr(precios, "tabla_tickers", lambda: pd.DataFrame({"lei": [LEI_A], "ticker": ["AAA.MC"]}))
    tablas, _ = gold.construir(silver_minima, precios_minimos, date(2024, 4, 2))
    for nombre, esquema in cargar.ESQUEMA_STG.items():
        tabla = cargar.a_arrow(tablas[nombre], esquema)
        assert tabla.column_names == list(esquema)
    captura = cargar.a_arrow(tablas["notificacion"], cargar.ESQUEMA_STG["notificacion"])["fecha_primera_captura"]
    assert captura.null_count == 1  # NaT → NULL en SQL


def columnas_sql(tabla):
    texto = (SQL / "01_esquema.sql").read_text(encoding="utf-8")
    cuerpo = re.search(rf"CREATE TABLE {re.escape(tabla)} \((.*?)\);", texto, re.S).group(1)
    return [re.match(r"\s*(\w+)", trozo).group(1) for trozo in cuerpo.split(",")
            if re.match(r"\s*\w+\s+[A-Z]", trozo)]


@pytest.mark.parametrize("nombre", list(cargar.ESQUEMA_STG))
def test_esquema_stg_coincide_con_el_sql(nombre):
    assert columnas_sql(f"stg.{nombre}") == list(cargar.ESQUEMA_STG[nombre])


# ---------- Precios ----------

def test_controles_de_precios():
    tickers = pd.DataFrame({"lei": [LEI_A, LEI_B], "ticker": ["AAA.MC", "BBB.MC"]})
    tabla = tabla_precios([("2026-11-02", "AAA.MC", 1, 1), ("2026-11-02", "^IBEX", 1, 0)])
    informe, problemas = precios.controles(tabla, tickers, date(2026, 11, 20))
    assert informe["tickers_sin_datos"] == ["BBB.MC"]
    assert any("valores con datos" in p for p in problemas)
    assert any("IBEX no tiene datos" in p for p in problemas)


def test_precio_del_dia_solo_tras_el_cierre(tmp_path, monkeypatch):
    tickers = precios.tabla_tickers()
    filas = [(d, t, 1.0, 100) for d in ["2026-11-06", "2026-11-09"] for t in [*tickers["ticker"], "^IBEX"]]
    monkeypatch.setattr(precios, "descargar", lambda _: tabla_precios(filas).drop(columns="lei"))
    almacen = AlmacenLocal(tmp_path)
    precios.actualizar(almacen, datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
    assert precios.leer(almacen)["fecha"].max() == pd.Timestamp("2026-11-06")
    precios.actualizar(almacen, datetime(2026, 11, 9, 19, tzinfo=timezone.utc))
    assert precios.leer(almacen)["fecha"].max() == pd.Timestamp("2026-11-09")


# ---------- Orquestación ----------

def preparar_silver(tmp_path, silver_minima):
    almacen = AlmacenLocal(tmp_path)
    for nombre, df in silver_minima.items():
        almacen.escribir_bytes(f"cnmv/{nombre}.parquet", cargar.silver.a_parquet(df), sobrescribir=True)
    almacen.escribir_texto("cnmv/calidad.json", json.dumps({"origen_bronze": "b/1.xls", "version_reglas": "v1"}))
    return almacen


def test_no_recarga_si_la_base_ya_tiene_esta_silver(tmp_path, silver_minima, precios_minimos, monkeypatch):
    almacen = preparar_silver(tmp_path, silver_minima)
    monkeypatch.setattr(precios, "tabla_tickers", lambda: pd.DataFrame({"lei": [LEI_A], "ticker": ["AAA.MC"]}))
    monkeypatch.setattr(precios, "actualizar", lambda *a: None)
    almacen.escribir_bytes("yahoo/precios.parquet", cargar.silver.a_parquet(precios_minimos))
    llamadas = []
    monkeypatch.setattr(cargar, "cargar_bd", lambda tablas, clave: llamadas.append(clave) or {"carga_id": 1})
    ahora = datetime(2024, 4, 2, 20, tzinfo=timezone.utc)
    assert cargar.ejecutar(almacen, ahora=ahora)["carga"] == {"carga_id": 1}
    assert cargar.ejecutar(almacen, ahora=ahora) is None             # misma silver: no toca la base
    assert len(llamadas) == 1
    almacen.escribir_texto("cnmv/calidad.json", json.dumps({"origen_bronze": "b/2.xls", "version_reglas": "v1"}))
    assert cargar.ejecutar(almacen, ahora=ahora) is not None         # fichero nuevo de la CNMV
    assert len(llamadas) == 2


def test_si_yahoo_falla_se_usan_los_precios_anteriores(tmp_path, silver_minima, precios_minimos, monkeypatch,
                                                       caplog):
    almacen = preparar_silver(tmp_path, silver_minima)
    monkeypatch.setattr(precios, "tabla_tickers", lambda: pd.DataFrame({"lei": [LEI_A], "ticker": ["AAA.MC"]}))

    def falla(*_):
        raise precios.ErrorPrecios("Yahoo no responde")
    monkeypatch.setattr(precios, "actualizar", falla)
    with pytest.raises(precios.ErrorPrecios):                         # sin precios previos: error
        cargar.ejecutar(almacen, cargar=False, ahora=datetime(2024, 4, 2, 20, tzinfo=timezone.utc))
    almacen.escribir_bytes("yahoo/precios.parquet", cargar.silver.a_parquet(precios_minimos))
    estado = cargar.ejecutar(almacen, cargar=False, ahora=datetime(2024, 4, 2, 20, tzinfo=timezone.utc))
    assert estado["informe"]["filas_precio_diario"] == 2
    assert "INGESTA_CNMV_REVISAR" in caplog.text


# ---------- Scripts SQL ----------

def test_lotes_separados_por_go():
    texto = "SELECT 1;\nGO\nSELECT 'GOTHAM';\n  go  \n\nSELECT 2\nGO;\n"
    assert bd.lotes(texto) == ["SELECT 1;", "SELECT 'GOTHAM';", "SELECT 2"]


@pytest.mark.parametrize("script", sorted(p.name for p in SQL.glob("*.sql")))
def test_scripts_sql_se_pueden_repetir(script):
    """Cada CREATE va protegido: IF ... IS NULL justo antes, o DROP ... IF EXISTS en el lote anterior.
    (CREATE OR ALTER ya se puede repetir y no lo detecta la expresión)."""
    texto = re.sub(r"/\*.*?\*/|--[^\n]*", "", (SQL / script).read_text(encoding="utf-8"), flags=re.S)
    for m in re.finditer(r"\bCREATE\s+(TABLE|ROLE|USER|SCHEMA|SECURITY POLICY|PROCEDURE|FUNCTION)\s+(#?)", texto):
        if m.group(2) == "#":  # tablas temporales
            continue
        if m.group(1) == "SECURITY POLICY":
            assert "DROP SECURITY POLICY IF EXISTS" in texto[:m.start()], f"{script}: política sin DROP previo"
        else:
            assert "IS NULL" in texto[max(0, m.start() - 120):m.start()], f"{script}: {m.group(0)} sin protección"
