"""Fase 3: precios de Yahoo, tablas gold y carga en Azure SQL.

La Function lo llama cada hora después de la silver, pero solo trabaja cuando hace falta:
cuando la silver procede de otro fichero de la CNMV, cambian las reglas de limpieza o cambia
el modelo (VERSION_MODELO). El estado se guarda en silver/gold/estado.json y no en la base
de datos, para no despertarla cada hora: la oferta gratuita tiene un límite de uso al mes.

Uso local:
    python -m src.modelo.cargar --sin-bd     # solo descarga precios y prepara las tablas gold
    python -m src.modelo.cargar              # además las carga en Azure SQL (SQL_SERVIDOR)
"""
import io
import json
import logging
from datetime import datetime, timezone

import pandas as pd

from src.ingesta.cnmv import ErrorIngesta
from src.limpieza import silver
from src.modelo import bd, gold, precios

RUTA_ESTADO = "gold/estado.json"

# Columnas y tipos de las tablas stg, en el mismo orden que en sql/01_esquema.sql
FECHA, TEXTO, ENTERO, ENTERO_LARGO, DECIMAL, LOGICO, MOMENTO = (
    "date", "string", "int32", "int64", "float64", "bool", "timestamp")
ESQUEMA_STG = {
    "dim_fecha": {"fecha_id": ENTERO, "fecha": FECHA, "anio": ENTERO, "trimestre": ENTERO, "mes": ENTERO,
                  "nombre_mes": TEXTO, "dia": ENTERO, "dia_semana": ENTERO, "nombre_dia": TEXTO,
                  "semana_iso": ENTERO, "es_dia_bolsa": LOGICO, "origen_calendario": TEXTO},
    "dim_emisor": {"lei": TEXTO, "nombre": TEXTO, "isins": TEXTO, "ticker": TEXTO, "tiene_precios": LOGICO,
                   "primera_notificacion": FECHA, "ultima_notificacion": FECHA, "notificaciones": ENTERO},
    "dim_fondo": {"tenedor": TEXTO, "grupo_gestor": TEXTO, "grupo_revisado": LOGICO,
                  "primera_notificacion": FECHA, "ultima_notificacion": FECHA, "notificaciones": ENTERO},
    "posicion_diaria": {"fecha": FECHA, "lei": TEXTO, "tenedor": TEXTO, "pct": DECIMAL},
    "precio_diario": {"fecha": FECHA, "lei": TEXTO, "cierre": DECIMAL, "cierre_ajustado": DECIMAL,
                      "volumen": ENTERO_LARGO},
    "notificacion": {"fecha": FECHA, "lei": TEXTO, "tenedor": TEXTO, "isin": TEXTO, "pct": DECIMAL,
                     "fecha_primera_captura": MOMENTO},
}


def a_arrow(df, esquema):
    """DataFrame → tabla Arrow con los tipos exactos de la tabla stg (para la carga masiva)."""
    import pyarrow as pa

    tipos = {FECHA: pa.date32(), TEXTO: pa.string(), ENTERO: pa.int32(), ENTERO_LARGO: pa.int64(),
             DECIMAL: pa.float64(), LOGICO: pa.bool_(), MOMENTO: pa.timestamp("us")}
    columnas = {}
    for col, tipo in esquema.items():
        serie = df[col]
        if tipo == FECHA:
            valores = pd.to_datetime(serie).to_numpy().astype("datetime64[D]")
        elif tipo == MOMENTO:
            valores = pd.to_datetime(serie).to_numpy().astype("datetime64[us]")
        elif tipo == TEXTO:
            valores = serie.astype(object).where(serie.notna(), None).to_numpy()
        else:
            valores = serie.to_numpy()
        columnas[col] = pa.array(valores, type=tipos[tipo], from_pandas=True)
    return pa.table(columnas)


def cargar_bd(tablas, clave, conexion=None):
    """Copia las tablas gold en stg y ejecuta dw.usp_cargar. Devuelve la fila de dw.carga."""
    import mssql_python

    propia = conexion is None
    cx = conexion or bd.conectar()
    try:
        cur = cx.cursor()
        cur.execute("EXEC stg.usp_vaciar")
        for nombre, esquema in ESQUEMA_STG.items():
            res = cur.bulkcopy_arrow(f"stg.{nombre}", a_arrow(tablas[nombre], esquema), timeout=600,
                                     column_mappings=list(esquema), keep_nulls=True, table_lock=True)
            if res["rows_copied"] != len(tablas[nombre]):
                raise bd.ErrorBD(f"stg.{nombre}: copiadas {res['rows_copied']} de {len(tablas[nombre])} filas")
        cur.execute("EXEC dw.usp_cargar @origen_bronze = ?, @version_reglas = ?, @version_modelo = ?",
                    (clave["origen_bronze"], clave["version_reglas"], clave["version_modelo"]))
        columnas = [c[0] for c in cur.description]
        return dict(zip(columnas, cur.fetchone()))
    except mssql_python.Error as e:
        raise bd.ErrorBD(f"Carga en Azure SQL fallida: {e}") from e
    finally:
        if propia:
            cx.close()


def leer_silver(almacen_silver):
    tablas = {}
    for nombre in ["emisores", "fondos", "notificaciones", "posiciones_diarias"]:
        contenido = almacen_silver.leer_bytes(f"{silver.PREFIJO}/{nombre}.parquet")
        if contenido is None:
            raise ErrorIngesta(f"Falta la tabla silver {nombre}")
        tablas[nombre] = pd.read_parquet(io.BytesIO(contenido))
    return tablas


def preparar(almacen_silver, ahora):
    """Actualiza los precios (si Yahoo falla, usa los anteriores) y construye las tablas gold."""
    informe_precios = None
    try:
        informe_precios = precios.actualizar(almacen_silver, ahora)
    except Exception as e:  # Yahoo no es una fuente garantizada: no debe parar la carga
        logging.warning("INGESTA_CNMV_REVISAR Precios de Yahoo no actualizados; se usan los anteriores: %s", e)
    tabla_precios = precios.leer(almacen_silver)
    if tabla_precios is None:
        raise precios.ErrorPrecios("No hay precios guardados y la descarga de Yahoo ha fallado")
    tablas, informe = gold.construir(leer_silver(almacen_silver), tabla_precios, ahora.date())
    informe["precios"] = informe_precios or {"aviso": "no actualizados en esta carga"}
    return tablas, informe


def ejecutar(almacen_silver, forzar=False, ahora=None, cargar=True):
    """Prepara y carga la gold si la base no tiene ya la silver actual. Devuelve el estado, o None si no hacía falta."""
    ahora = ahora or datetime.now(timezone.utc)
    calidad = json.loads(almacen_silver.leer_texto(f"{silver.PREFIJO}/calidad.json") or "{}")
    if not calidad.get("origen_bronze"):
        raise ErrorIngesta("No hay capa silver que cargar")
    clave = {"origen_bronze": calidad["origen_bronze"], "version_reglas": calidad["version_reglas"],
             "version_modelo": gold.VERSION_MODELO}
    previo = json.loads(almacen_silver.leer_texto(RUTA_ESTADO) or "{}")
    if cargar and not forzar and all(previo.get(k) == v for k, v in clave.items()):
        return None

    tablas, informe = preparar(almacen_silver, ahora)
    estado = {**clave, "informe": informe}
    if cargar:
        estado["carga"] = cargar_bd(tablas, clave)
        estado["carga_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        almacen_silver.escribir_texto(RUTA_ESTADO, json.dumps(estado, indent=2, ensure_ascii=False, default=str))
    return estado


def main():
    import argparse

    from src.ingesta.almacen import AlmacenLocal

    p = argparse.ArgumentParser(description="Descarga precios, prepara la capa gold y la carga en Azure SQL")
    p.add_argument("--silver", default="data/silver")
    p.add_argument("--sin-bd", action="store_true", help="no cargar en la base de datos")
    p.add_argument("--forzar", action="store_true", help="cargar aunque la base ya tenga esta silver")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    try:
        estado = ejecutar(AlmacenLocal(args.silver), forzar=args.forzar, cargar=not args.sin_bd)
    except ErrorIngesta as e:
        logging.error("INGESTA_CNMV_FALLO %s: %s", type(e).__name__, e)
        raise SystemExit(1)
    print(json.dumps(estado, indent=2, ensure_ascii=False, default=str) if estado else "La base ya está al día")


if __name__ == "__main__":
    main()
