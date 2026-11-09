"""Indicadores diarios de presión bajista por emisor (fase 4).

Una fila por emisor y día de bolsa, desde su primera posición pública, con:
- suma_pct           suma de las posiciones cortas publicadas (% del capital)
- num_fondos         fondos con posición pública (>= 0,5 %)
- fondos_nuevos      fondos que aparecen sin haber tenido posición en las VENTANA_NUEVO sesiones anteriores
- salidas            fondos que tenían posición la sesión anterior y hoy ya no
- var_suma_5d/20d    variación de la suma frente a 5 y 20 sesiones antes (puntos porcentuales)
- peso_mayor_fondo   % de la suma que tiene el fondo más grande (concentración)
- cierre, var_precio_5d/20d (%), volumen_medio_20d
- dias_cubrir        sesiones que tardarían los bajistas en recomprar con el volumen medio de
                     20 sesiones: suma_pct × acciones en circulación / volumen medio

Las sesiones se cuentan con el calendario de bolsa (dim_fecha), no con días naturales.
Se guardan los días con posiciones y las 20 sesiones siguientes a la última (para ver la salida).
"""
import numpy as np
import pandas as pd

VENTANA_NUEVO = 20
COLUMNAS = ["fecha", "lei", "suma_pct", "num_fondos", "fondos_nuevos", "salidas", "var_suma_5d",
            "var_suma_20d", "peso_mayor_fondo", "cierre", "var_precio_5d", "var_precio_20d",
            "volumen_medio_20d", "dias_cubrir"]


def movimientos_fondos(posiciones, sesiones):
    """Entradas de fondos nuevos y salidas, con el índice de sesión de bolsa.

    Devuelve (nuevos, salidas): DataFrames con fecha, lei y tenedor.
    """
    indice = pd.Series(np.arange(len(sesiones)), index=sesiones)
    df = posiciones[["fecha", "lei", "tenedor"]].copy()
    df["sesion"] = df["fecha"].map(indice)
    df = df.dropna(subset=["sesion"]).sort_values(["lei", "tenedor", "sesion"])
    grupo = df.groupby(["lei", "tenedor"])["sesion"]
    previa, siguiente = grupo.shift(1), grupo.shift(-1)
    nuevos = df[previa.isna() | (df["sesion"] - previa > VENTANA_NUEVO)][["fecha", "lei", "tenedor"]]
    # Sale el día siguiente a su última sesión con posición (si ese día ya tiene datos)
    ultima = df["sesion"].max()
    sale = (siguiente.isna() | (siguiente - df["sesion"] > 1)) & (df["sesion"] < ultima)
    salidas = df[sale].assign(fecha=lambda x: sesiones[(x["sesion"] + 1).astype(int)].to_numpy())
    return nuevos.reset_index(drop=True), salidas[["fecha", "lei", "tenedor"]].reset_index(drop=True)


def precios_diarios(precios):
    """Cierre, variación del precio y volumen medio de 20 sesiones por emisor."""
    p = precios.sort_values(["lei", "fecha"]).copy()
    g = p.groupby("lei")
    p["var_precio_5d"] = (g["cierre_ajustado"].pct_change(5, fill_method=None) * 100)
    p["var_precio_20d"] = (g["cierre_ajustado"].pct_change(20, fill_method=None) * 100)
    p["volumen_medio_20d"] = g["volumen"].transform(lambda v: v.rolling(20, min_periods=10).mean())
    return p[["fecha", "lei", "cierre", "var_precio_5d", "var_precio_20d", "volumen_medio_20d"]]


def calcular(posiciones, precios, fechas, acciones):
    """posiciones/precios: tablas gold; fechas: dim_fecha; acciones: lei → acciones en circulación."""
    ultima = posiciones["fecha"].max()
    sesiones = pd.DatetimeIndex(fechas.loc[fechas["es_dia_bolsa"] & (fechas["fecha"] <= ultima), "fecha"])
    sesiones = sesiones.sort_values()

    por_dia = posiciones.groupby(["lei", "fecha"]).agg(
        suma_pct=("pct", "sum"), num_fondos=("pct", "size"), mayor=("pct", "max")).reset_index()

    # Rejilla completa de sesiones de cada emisor, desde su primera posición hasta el último dato
    primera = por_dia.groupby("lei")["fecha"].min()
    rejilla = pd.concat([pd.DataFrame({"lei": lei, "fecha": sesiones[sesiones >= desde]})
                         for lei, desde in primera.items()], ignore_index=True)
    ind = rejilla.merge(por_dia, on=["lei", "fecha"], how="left")
    ind[["suma_pct", "num_fondos", "mayor"]] = ind[["suma_pct", "num_fondos", "mayor"]].fillna(0)
    ind = ind.sort_values(["lei", "fecha"], ignore_index=True)
    g = ind.groupby("lei")["suma_pct"]
    ind["var_suma_5d"] = ind["suma_pct"] - g.shift(5).fillna(0)
    ind["var_suma_20d"] = ind["suma_pct"] - g.shift(20).fillna(0)
    ind["peso_mayor_fondo"] = np.where(ind["suma_pct"] > 0, ind["mayor"] / ind["suma_pct"].where(
        ind["suma_pct"] > 0) * 100, np.nan)

    nuevos, salidas = movimientos_fondos(posiciones, sesiones)
    for nombre, tabla in [("fondos_nuevos", nuevos), ("salidas", salidas)]:
        cuenta = tabla.groupby(["lei", "fecha"]).size().rename(nombre)
        ind = ind.merge(cuenta, left_on=["lei", "fecha"], right_index=True, how="left")
        ind[nombre] = ind[nombre].fillna(0).astype("int32")

    ind = ind.merge(precios_diarios(precios), on=["lei", "fecha"], how="left")
    ind = ind.merge(acciones[["lei", "acciones"]], on="lei", how="left")
    cortas = ind["suma_pct"] / 100 * ind["acciones"]
    ind["dias_cubrir"] = (cortas / ind["volumen_medio_20d"]).where(ind["volumen_medio_20d"] > 0)

    # Solo días con posiciones y las 20 sesiones siguientes (para registrar la salida)
    reciente = ind.groupby("lei")["suma_pct"].transform(lambda s: s.rolling(21, min_periods=1).max())
    ind = ind[reciente > 0]
    ind["num_fondos"] = ind["num_fondos"].astype("int32")
    return ind[COLUMNAS].reset_index(drop=True), nuevos
