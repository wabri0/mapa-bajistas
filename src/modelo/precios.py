"""Precios diarios de Yahoo Finance para los emisores con posiciones cortas.

- Se descargan con yfinance todos los códigos de tickers.csv y el IBEX 35 (^IBEX), desde 2010.
- La descarga completa tarda unos segundos, así que se rehace entera cada vez: así el cierre
  ajustado recoge siempre los últimos dividendos y ampliaciones de capital.
- Se guarda en silver/yahoo/precios.parquet. Si Yahoo falla, se sigue con la copia anterior.
- El dato del día solo se guarda después del cierre de la bolsa (17:35 en Madrid): antes sería
  un precio a mitad de sesión.
"""
import io
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.ingesta.cnmv import ErrorIngesta

PREFIJO = "yahoo"
INDICE = "^IBEX"
DESDE = "2010-01-01"
TICKERS = Path(__file__).with_name("tickers.csv")
# Por debajo de este número de valores con datos se considera que la descarga ha fallado
MINIMO_TICKERS = 60
# Si el último día con datos del IBEX es más antiguo, la descarga no está al día
DIAS_MAXIMOS_SIN_DATOS = 6
# Hora UTC a partir de la cual el precio del día ya es el de cierre (17:35 en Madrid en invierno)
HORA_CIERRE_UTC = 17


class ErrorPrecios(ErrorIngesta):
    """La descarga de Yahoo Finance ha fallado o está incompleta."""


def tabla_tickers():
    """lei → ticker de Yahoo. Los emisores sin código (o sin precios) siguen en la tabla."""
    return pd.read_csv(TICKERS, dtype=str, encoding="utf-8")


def descargar(tickers, desde=DESDE):
    """Cierre, cierre ajustado y volumen diarios en formato largo: una fila por ticker y día."""
    import yfinance as yf

    # Los valores ya excluidos de bolsa dan error cada día: quedan en el informe de calidad
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    # En Azure solo se puede escribir en la carpeta temporal
    yf.set_tz_cache_location(str(Path(tempfile.gettempdir()) / "yfinance"))
    datos = yf.download(sorted(set(tickers)), start=desde, auto_adjust=False, actions=False,
                        group_by="ticker", progress=False, threads=True)
    if datos is None or datos.empty:
        raise ErrorPrecios("Yahoo Finance no ha devuelto datos")
    largo = datos.stack(level=0, future_stack=True).reset_index()
    largo = largo.rename(columns={"Date": "fecha", "Ticker": "ticker", "Close": "cierre",
                                  "Adj Close": "cierre_ajustado", "Volume": "volumen"})
    largo = largo.dropna(subset=["cierre"])
    largo["fecha"] = pd.to_datetime(largo["fecha"]).dt.tz_localize(None).dt.normalize()
    largo["volumen"] = largo["volumen"].fillna(0).astype("int64")
    return largo[["fecha", "ticker", "cierre", "cierre_ajustado", "volumen"]].sort_values(
        ["ticker", "fecha"], ignore_index=True)


def con_lei(precios, tickers):
    """Añade el LEI de cada ticker; el IBEX queda sin LEI."""
    mapa = tickers.dropna(subset=["ticker"]).set_index("ticker")["lei"]
    return precios.assign(lei=precios["ticker"].map(mapa))[
        ["fecha", "lei", "ticker", "cierre", "cierre_ajustado", "volumen"]]


def controles(precios, tickers, hoy):
    """Informe de la descarga y lista de problemas que la invalidan."""
    con_datos = set(precios["ticker"])
    esperados = set(tickers["ticker"].dropna())
    ibex = precios.loc[precios["ticker"] == INDICE, "fecha"]
    informe = {
        "filas": len(precios),
        "tickers_con_datos": len(con_datos - {INDICE}),
        "tickers_sin_datos": sorted(esperados - con_datos),
        "primera_fecha": str(precios["fecha"].min().date()) if len(precios) else None,
        "ultima_fecha_ibex": str(ibex.max().date()) if len(ibex) else None,
    }
    problemas = []
    if informe["tickers_con_datos"] < MINIMO_TICKERS:
        problemas.append(f"solo {informe['tickers_con_datos']} valores con datos")
    if not len(ibex):
        problemas.append("falta el IBEX 35")
    elif (pd.Timestamp(hoy) - ibex.max()).days > DIAS_MAXIMOS_SIN_DATOS:
        problemas.append(f"el IBEX no tiene datos desde el {informe['ultima_fecha_ibex']}")
    return informe, problemas


def actualizar(almacen_silver, ahora=None):
    """Descarga los precios y los guarda en silver. Devuelve el informe; lanza ErrorPrecios si fallan."""
    ahora = ahora or datetime.now(timezone.utc)
    tickers = tabla_tickers()
    precios = con_lei(descargar([*tickers["ticker"].dropna(), INDICE]), tickers)
    if ahora.hour < HORA_CIERRE_UTC:
        precios = precios[precios["fecha"] < pd.Timestamp(ahora.date())].reset_index(drop=True)
    informe, problemas = controles(precios, tickers, ahora.date())
    if problemas:
        raise ErrorPrecios(f"Descarga de precios incompleta: {problemas}")
    informe["descarga_utc"] = ahora.isoformat(timespec="seconds")
    buf = io.BytesIO()
    precios.to_parquet(buf, index=False)
    almacen_silver.escribir_bytes(f"{PREFIJO}/precios.parquet", buf.getvalue(), sobrescribir=True)
    try:
        acciones = actualizar_acciones(almacen_silver, tickers, ahora)
        informe["emisores_con_acciones"] = int(acciones["lei"].nunique())
    except Exception as e:  # sin acciones solo falta «días para cubrir»: no debe parar nada
        logging.warning("INGESTA_CNMV_REVISAR Acciones en circulación no actualizadas: %s", e)
    almacen_silver.escribir_texto(f"{PREFIJO}/calidad.json", json.dumps(informe, indent=2, ensure_ascii=False))
    return informe


def leer(almacen_silver):
    """Los últimos precios guardados en silver, o None si aún no hay."""
    contenido = almacen_silver.leer_bytes(f"{PREFIJO}/precios.parquet")
    return pd.read_parquet(io.BytesIO(contenido)) if contenido else None


def descargar_acciones(tickers):
    """Acciones en circulación actuales de cada ticker. Los que fallan no aparecen.

    Se usa el dato actual y no el histórico: el histórico de Yahoo tiene errores graves
    (p. ej. Duro Felguera con 58.000 millones de acciones durante dos años).
    """
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    def una(ticker):
        try:
            return ticker, yf.Ticker(ticker).fast_info.get("shares")
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(una, sorted(set(tickers))))
    return pd.DataFrame([(t, int(n)) for t, n in resultados if n], columns=["ticker", "acciones"])


def actualizar_acciones(almacen_silver, tickers, ahora):
    """Guarda las acciones en circulación por emisor; si un valor falla, conserva el dato anterior."""
    nuevas = descargar_acciones(tickers["ticker"].dropna())
    nuevas["consulta_utc"] = pd.Timestamp(ahora).tz_convert(None) if pd.Timestamp(ahora).tzinfo else pd.Timestamp(ahora)
    previas = leer_acciones(almacen_silver)
    if previas is not None:
        nuevas = pd.concat([nuevas, previas[~previas["ticker"].isin(nuevas["ticker"])][nuevas.columns]])
    mapa = tickers.dropna(subset=["ticker"]).set_index("ticker")["lei"]
    acciones = nuevas.assign(lei=nuevas["ticker"].map(mapa))[["lei", "ticker", "acciones", "consulta_utc"]]
    acciones = acciones.sort_values("lei", ignore_index=True)
    buf = io.BytesIO()
    acciones.to_parquet(buf, index=False)
    almacen_silver.escribir_bytes(f"{PREFIJO}/acciones.parquet", buf.getvalue(), sobrescribir=True)
    return acciones


def leer_acciones(almacen_silver):
    contenido = almacen_silver.leer_bytes(f"{PREFIJO}/acciones.parquet")
    return pd.read_parquet(io.BytesIO(contenido)) if contenido else None
