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
from src.alertas import reglas as reglas_alerta
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
                   "primera_notificacion": FECHA, "ultima_notificacion": FECHA, "notificaciones": ENTERO,
                   "acciones_circulacion": ENTERO_LARGO, "nombre_corto": TEXTO},
    "dim_fondo": {"tenedor": TEXTO, "grupo_gestor": TEXTO, "grupo_revisado": LOGICO,
                  "primera_notificacion": FECHA, "ultima_notificacion": FECHA, "notificaciones": ENTERO},
    "posicion_diaria": {"fecha": FECHA, "lei": TEXTO, "tenedor": TEXTO, "pct": DECIMAL},
    "precio_diario": {"fecha": FECHA, "lei": TEXTO, "cierre": DECIMAL, "cierre_ajustado": DECIMAL,
                      "volumen": ENTERO_LARGO},
    "notificacion": {"fecha": FECHA, "lei": TEXTO, "tenedor": TEXTO, "isin": TEXTO, "pct": DECIMAL,
                     "fecha_primera_captura": MOMENTO},
    "indicador_diario": {"fecha": FECHA, "lei": TEXTO, "suma_pct": DECIMAL, "num_fondos": ENTERO,
                         "fondos_nuevos": ENTERO, "salidas": ENTERO, "var_suma_5d": DECIMAL, "var_suma_20d": DECIMAL,
                         "peso_mayor_fondo": DECIMAL, "cierre": DECIMAL, "var_precio_5d": DECIMAL,
                         "var_precio_20d": DECIMAL, "volumen_medio_20d": DECIMAL, "dias_cubrir": DECIMAL},
}
# Las alertas se cargan aparte, después de dw.usp_cargar (necesitan las reglas de la base)
ESQUEMA_ALERTA = {"cliente_id": ENTERO, "regla_id": ENTERO, "lei": TEXTO, "fecha": FECHA, "tenedor": TEXTO,
                  "tipo": TEXTO, "valor": DECIMAL, "mensaje": TEXTO}


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
        elif tipo in (ENTERO, ENTERO_LARGO):
            valores = serie.astype("Int64" if tipo == ENTERO_LARGO else "Int32")  # admite vacíos
        else:
            valores = serie.to_numpy()
        columnas[col] = pa.array(valores, type=tipos[tipo], from_pandas=True)
    return pa.table(columnas)


def copiar(cur, nombre, df, esquema):
    """Carga masiva de un DataFrame en stg.<nombre>, comprobando que llegan todas las filas."""
    if not len(df):
        return
    res = cur.bulkcopy_arrow(f"stg.{nombre}", a_arrow(df, esquema), timeout=600,
                             column_mappings=list(esquema), keep_nulls=True, table_lock=True)
    if res["rows_copied"] != len(df):
        raise bd.ErrorBD(f"stg.{nombre}: copiadas {res['rows_copied']} de {len(df)} filas")


def filas(cur):
    columnas = [c[0] for c in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def leer_reglas(cur):
    """Reglas activas y empresas que sigue cada cliente (la Function las ve todas: rol_carga)."""
    cur.execute("SELECT regla_id, cliente_id, tipo, CAST(umbral AS FLOAT) AS umbral, ambito "
                "FROM cliente.regla_alerta WHERE activa = 1")
    reglas = pd.DataFrame(filas(cur), columns=["regla_id", "cliente_id", "tipo", "umbral", "ambito"])
    cur.execute("SELECT ce.cliente_id, e.lei, ce.rol FROM cliente.cliente_emisor AS ce "
                "JOIN dw.dim_emisor AS e ON e.emisor_id = ce.emisor_id")
    seguimiento = pd.DataFrame(filas(cur), columns=["cliente_id", "lei", "rol"])
    return reglas, seguimiento


def cargar_alertas(cur, tablas):
    """Evalúa las reglas de todos los clientes y carga cliente.alerta. Devuelve (resumen, nuevas recientes)."""
    reglas, seguimiento = leer_reglas(cur)
    nombres = tablas["dim_emisor"].set_index("lei")["nombre_corto"]
    alertas = reglas_alerta.evaluar(tablas["indicador_diario"], tablas["fondo_nuevo"], tablas["posicion_diaria"],
                                    reglas, seguimiento, nombres)
    copiar(cur, "alerta", alertas, ESQUEMA_ALERTA)
    cur.execute("EXEC cliente.usp_cargar_alertas")
    resumen = filas(cur)[0]
    recientes = filas(cur) if cur.nextset() else []
    resumen["reglas"] = len(reglas)
    return resumen, recientes


def cargar_bd(tablas, clave, conexion=None):
    """Copia las tablas gold en stg, ejecuta dw.usp_cargar y genera las alertas. Devuelve el resultado."""
    import mssql_python

    propia = conexion is None
    cx = conexion or bd.conectar()
    try:
        cur = cx.cursor()
        cur.execute("EXEC stg.usp_vaciar")
        for nombre, esquema in ESQUEMA_STG.items():
            copiar(cur, nombre, tablas[nombre], esquema)
        cur.execute("EXEC dw.usp_cargar @origen_bronze = ?, @version_reglas = ?, @version_modelo = ?",
                    (clave["origen_bronze"], clave["version_reglas"], clave["version_modelo"]))
        carga = filas(cur)[0]
        resumen, recientes = cargar_alertas(cur, tablas)
        for alerta in recientes:
            # En producción, aquí se enviaría el correo al cliente
            logging.info("ALERTA_CLIENTE cliente=%s %s", alerta["cliente_id"], alerta["mensaje"])
        carga["alertas"] = resumen
        return carga
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
    acciones = precios.leer_acciones(almacen_silver)
    silver_cnmv = leer_silver(almacen_silver)
    sin_ticker = sorted(set(silver_cnmv["emisores"]["lei"]) - set(precios.tabla_tickers()["lei"]))
    if sin_ticker:
        # Emisor nuevo en la CNMV: hay que añadir su código de Yahoo a src/modelo/tickers.csv
        nombres = silver_cnmv["emisores"].set_index("lei")["emisor"]
        logging.warning("INGESTA_CNMV_REVISAR Emisores sin código de Yahoo en tickers.csv: %s",
                        json.dumps({lei: nombres[lei] for lei in sin_ticker}, ensure_ascii=False))
    tablas, informe = gold.construir(silver_cnmv, tabla_precios, ahora.date(), acciones)
    informe["emisores_sin_ticker"] = sin_ticker
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
