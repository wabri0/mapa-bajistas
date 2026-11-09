"""Capa gold: de las tablas silver (CNMV y Yahoo) a las tablas del modelo en estrella.

Aquí solo se preparan las tablas con sus claves naturales (fecha, LEI, nombre del fondo).
Los identificadores numéricos (emisor_id, fondo_id) los asigna la base de datos al cargar,
para que no cambien entre cargas: las tablas de clientes los usan.

Calendario de bolsa (dim_fecha):
- Un día es de bolsa si ese día cotizó el IBEX 35 o al menos UMBRAL_ACCIONES acciones con volumen.
  Hace falta lo segundo porque a Yahoo le faltan días del IBEX (2-ene-2012 y 2-ene-2017, con
  más de 50 acciones negociadas). El volumen evita días inventados: Yahoo repite el 24-dic-2019
  como 25-dic-2019 con volumen cero.
- Los días posteriores al último dato se marcan con la regla de festivos de la Bolsa de Madrid
  (1-ene, Viernes Santo, Lunes de Pascua, 1-may, 25 y 26-dic), hasta que lleguen los precios.
"""
from datetime import date, timedelta

import pandas as pd

from src.modelo.precios import DESDE, INDICE

VERSION_MODELO = "2026-11-09 v3 nombre corto"
UMBRAL_ACCIONES = 10
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def domingo_de_pascua(anio):
    """Algoritmo de Meeus/Jones/Butcher para el calendario gregoriano."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def festivos_bolsa(anio):
    """Días entre semana en que cierra la Bolsa de Madrid (calendario TARGET2 que sigue BME)."""
    pascua = domingo_de_pascua(anio)
    return {date(anio, 1, 1), pascua - timedelta(days=2), pascua + timedelta(days=1),
            date(anio, 5, 1), date(anio, 12, 25), date(anio, 12, 26)}


def dias_bolsa_observados(precios):
    """Días con cotización del IBEX o de al menos UMBRAL_ACCIONES acciones con volumen."""
    ibex = set(precios.loc[precios["ticker"] == INDICE, "fecha"])
    acciones = precios[(precios["ticker"] != INDICE) & (precios["volumen"] > 0)]
    por_dia = acciones.groupby("fecha").size()
    return ibex | set(por_dia[por_dia >= UMBRAL_ACCIONES].index)


def dim_fecha(precios, hasta):
    """Un día por fila desde 2010 hasta el 31 de diciembre del año de `hasta`."""
    ultimo_dato = precios["fecha"].max()
    fin = max(pd.Timestamp(hasta), ultimo_dato)
    dias = pd.date_range(DESDE, f"{fin.year}-12-31", freq="D")
    observados = dias_bolsa_observados(precios)
    festivos = {f for anio in range(dias[0].year, fin.year + 1) for f in festivos_bolsa(anio)}
    previsto = (dias.day_of_week < 5) & ~pd.Series(dias.date).isin(festivos).to_numpy()
    observado = dias <= ultimo_dato
    return pd.DataFrame({
        "fecha_id": (dias.year * 10000 + dias.month * 100 + dias.day).astype("int32"),
        "fecha": dias,
        "anio": dias.year.astype("int16"),
        "trimestre": dias.quarter.astype("int8"),
        "mes": dias.month.astype("int8"),
        "nombre_mes": [MESES[m - 1] for m in dias.month],
        "dia": dias.day.astype("int8"),
        "dia_semana": (dias.day_of_week + 1).astype("int8"),  # 1 = lunes
        "nombre_dia": [DIAS[d] for d in dias.day_of_week],
        "semana_iso": dias.isocalendar().week.to_numpy().astype("int8"),
        "es_dia_bolsa": pd.Series(dias.isin(list(observados))).where(observado, previsto).astype(bool).to_numpy(),
        "origen_calendario": ["yahoo" if o else "previsto" for o in observado],
    })


def dim_emisor(emisores, tickers, precios, acciones):
    from src.alertas.reglas import nombre_corto

    con_precios = set(precios["lei"].dropna())
    columnas = ["lei", "ticker"] + (["nombre_corto"] if "nombre_corto" in tickers else [])
    em = emisores.merge(tickers[columnas], on="lei", how="left")
    if "nombre_corto" not in em:
        em["nombre_corto"] = None
    # Nombre revisado a mano en tickers.csv; si falta (emisor nuevo), el automático
    em["nombre_corto"] = em["nombre_corto"].fillna(em["emisor"].map(nombre_corto))
    em = em.merge(acciones[["lei", "acciones"]].drop_duplicates("lei"), on="lei", how="left")
    return pd.DataFrame({
        "lei": em["lei"], "nombre": em["emisor"], "isins": em["isins"], "ticker": em["ticker"],
        "tiene_precios": em["lei"].isin(con_precios),
        "primera_notificacion": em["primera"], "ultima_notificacion": em["ultima"],
        "notificaciones": em["notificaciones"].astype("int32"),
        "acciones_circulacion": em["acciones"].astype("Int64"),
        "nombre_corto": em["nombre_corto"],
    })


def dim_fondo(fondos):
    return pd.DataFrame({
        "tenedor": fondos["tenedor"], "grupo_gestor": fondos["grupo_gestor"],
        "grupo_revisado": fondos["grupo_revisado"].astype(bool),
        "primera_notificacion": fondos["primera"], "ultima_notificacion": fondos["ultima"],
        "notificaciones": fondos["notificaciones"].astype("int32"),
    })


def construir(silver, precios, hoy, acciones=None):
    """silver: dict con las tablas de silver/cnmv; acciones: lei → acciones en circulación (opcional).

    Devuelve (tablas gold, informe). Además de las tablas que se cargan en SQL, incluye
    «fondo_nuevo» (entradas de fondos), que usan las reglas de alerta.
    """
    from src.alertas import indicadores
    from src.modelo.precios import tabla_tickers

    if acciones is None:
        acciones = pd.DataFrame({"lei": pd.Series(dtype=str), "acciones": pd.Series(dtype="int64")})

    fechas = dim_fecha(precios, hoy)
    bolsa = set(fechas.loc[fechas["es_dia_bolsa"], "fecha"])

    diarias = silver["posiciones_diarias"]
    en_bolsa = diarias["fecha"].isin(bolsa)
    posiciones = diarias.loc[en_bolsa, ["fecha", "lei", "tenedor", "pct"]].reset_index(drop=True)

    cotizaciones = precios[precios["lei"].notna()]
    en_bolsa_precio = cotizaciones["fecha"].isin(bolsa)
    precios_gold = cotizaciones.loc[en_bolsa_precio, ["fecha", "lei", "cierre", "cierre_ajustado", "volumen"]]
    # Un mismo emisor podría tener dos códigos: se queda el de mayor volumen cada día
    precios_gold = (precios_gold.sort_values("volumen").drop_duplicates(["fecha", "lei"], keep="last")
                    .sort_values(["lei", "fecha"], ignore_index=True))
    # Yahoo da cierres ajustados negativos en algún valor (Duro Felguera): no tienen sentido
    precios_gold["cierre_ajustado"] = precios_gold["cierre_ajustado"].where(precios_gold["cierre_ajustado"] > 0)

    notif = silver["notificaciones"]
    notificaciones = pd.DataFrame({
        "fecha": notif["fecha_posicion"], "lei": notif["lei"], "tenedor": notif["tenedor"],
        "isin": notif["isin"], "pct": notif["pct"],
        "fecha_primera_captura": pd.to_datetime(notif["fecha_primera_captura"]),
    })

    indicador, nuevos = indicadores.calcular(posiciones, precios_gold, fechas, acciones)
    tablas = {
        "dim_fecha": fechas,
        "dim_emisor": dim_emisor(silver["emisores"], tabla_tickers(), precios, acciones),
        "dim_fondo": dim_fondo(silver["fondos"]),
        "posicion_diaria": posiciones,
        "precio_diario": precios_gold,
        "notificacion": notificaciones,
        "indicador_diario": indicador,
        "fondo_nuevo": nuevos,
    }
    festivos = diarias.loc[~en_bolsa, "fecha"]
    informe = {
        "version_modelo": VERSION_MODELO,
        "dias_calendario": len(fechas),
        "dias_bolsa": int(fechas["es_dia_bolsa"].sum()),
        "ultimo_dia_con_precios": str(precios["fecha"].max().date()),
        "posiciones_en_festivo_eliminadas": int((~en_bolsa).sum()),
        "dias_festivos_con_posiciones": int(festivos.nunique()),
        "precios_fuera_de_bolsa_eliminados": int((~en_bolsa_precio).sum()),
        **{f"filas_{k}": len(v) for k, v in tablas.items()},
    }
    return tablas, informe
