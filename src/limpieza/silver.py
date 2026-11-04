"""Capa silver: del Excel de la CNMV a tablas limpias de notificaciones y posiciones diarias.

Reglas (documentadas en docs/informe/03_datos.md):
- La posición corta neta es por emisor, así que se agrupa por LEI y no por ISIN:
  así se absorben los cambios de ISIN tras operaciones corporativas.
- Cada notificación vale hasta la siguiente del mismo fondo y emisor. Por debajo del
  0,5 % la posición deja de ser pública y se trata como cerrada.
- La CNMV no publica la mayoría de los avisos de cierre. Una posición que no sigue vigente
  y pasa más de CADUCIDAD_DIAS sin ningún aviso se da por cerrada CADUCIDAD_DIAS después del
  último (cierre inferido). El 99 % de los cierres publicados llega antes de 301 días.
"""
import io
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.ingesta import cnmv

PREFIJO = "cnmv"
# Cambiarla obliga a reconstruir la silver en Azure aunque no llegue un fichero nuevo
VERSION_REGLAS = "2026-11-04 caducidad-365 grupos-revision"
UMBRAL = 0.5
CADUCIDAD_DIAS = 365
FECHA_MINIMA = pd.Timestamp("2010-01-01")
CLAVE = ["lei", "tenedor", "fecha_posicion"]
TABLAS = ["notificaciones", "emisores", "fondos", "posiciones_intervalos", "posiciones_diarias"]
GRUPOS = Path(__file__).with_name("grupos_gestores.csv")


class ErrorCalidad(cnmv.ErrorIngesta):
    """Los datos no superan los controles críticos de calidad."""


def leer_notificaciones(libro):
    """Todas las filas de las tres hojas de datos, tal cual, con la hoja de origen."""
    filas = []
    for hoja in cnmv.HOJAS_DATOS:
        sh = libro.sheet_by_name(hoja)
        for i in range(cnmv.FILA_CABECERA + 1, sh.nrows):
            filas.append([*sh.row_values(i)[:6], hoja])
    df = pd.DataFrame(filas, columns=["lei", "isin", "emisor", "tenedor", "fecha_posicion", "pct", "hoja"])
    for col in ["lei", "isin", "emisor", "tenedor"]:
        df[col] = df[col].astype(str).str.strip()
    df["isin"] = df["isin"].str.upper()
    df["fecha_posicion"] = pd.to_datetime(df["fecha_posicion"].astype(str).str.strip())
    df["pct"] = df["pct"].astype(float)
    return df


def limpiar(crudas):
    """Quita duplicados (entre hojas y dentro de ellas) y resuelve conflictos del mismo día."""
    df = crudas.assign(vigente=crudas["hoja"].eq(cnmv.HOJAS_DATOS[0]))
    vigentes = set(zip(df.loc[df.vigente, "lei"], df.loc[df.vigente, "tenedor"]))
    df = df[~df.vigente].drop(columns=["hoja", "vigente"])  # Serie y Anteriores contienen ya las vigentes
    sin_dup = df.drop_duplicates(["lei", "isin", "emisor", "tenedor", "fecha_posicion", "pct"])
    # Mismo fondo, emisor y día con dos porcentajes (p. ej. en dos ISIN): se queda el mayor
    sin_dup = sin_dup.sort_values(["lei", "tenedor", "fecha_posicion", "pct"])
    conflictos = sin_dup.duplicated(CLAVE, keep=False)
    limpio = sin_dup.drop_duplicates(CLAVE, keep="last").reset_index(drop=True)
    return limpio, vigentes, {
        "filas_leidas": len(crudas),
        "duplicados_eliminados": len(df) - len(sin_dup),
        "conflictos_mismo_dia": int(conflictos.sum()),
    }


# Palabras que no identifican a una gestora: formas jurídicas, sedes y términos genéricos del sector
GENERICAS = set("""llc lp llp ltd limited inc sa sas plc the co company corp corporation ag ab sl uk europe
european international management managment mangement asset assets capital partners partnership investment
investments investors advisors advisers group global fund funds gestion holdings master financial services
strategies trust national association bank am im sarl pte general partner being of as and london asia ireland
singapore hong kong cayman switzerland spain difc hk securities gcs ii iii sociedade gestora""".split())


def marca(nombre):
    """Primera palabra distintiva del nombre: 'Citadel Europe LLP' -> 'citadel'."""
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    palabras = [p for p in re.split(r"[^a-z0-9]+", s) if len(p) > 1 and p not in GENERICAS]
    return palabras[0] if palabras else s


def tabla_fondos(notif):
    """Fondos con su grupo gestor. Sin revisar en grupos_gestores.csv, el grupo es la propia entidad."""
    grupos = pd.read_csv(GRUPOS, encoding="utf-8")
    fondos = notif.groupby("tenedor").agg(
        primera=("fecha_posicion", "min"), ultima=("fecha_posicion", "max"), notificaciones=("pct", "size"))
    fondos = fondos.reset_index().merge(grupos[["tenedor", "grupo_gestor"]], on="tenedor", how="left")
    fondos["grupo_revisado"] = fondos["grupo_gestor"].notna()
    fondos["grupo_gestor"] = fondos["grupo_gestor"].fillna(fondos["tenedor"])
    return fondos


def grupos_por_revisar(fondos):
    """Entidades sin revisar cuyo nombre comparte marca con otra de distinto grupo (p. ej. un Citadel nuevo).

    No bloquea nada: mientras nadie la revise, la entidad cuenta como su propio grupo. Se da por
    revisada al añadirla a grupos_gestores.csv (con su grupo, o consigo misma si es independiente).
    """
    marcas = fondos.assign(marca=fondos["tenedor"].map(marca))
    pendientes = []
    for f in marcas[~marcas["grupo_revisado"]].itertuples():
        otros = marcas[(marcas["marca"] == f.marca) & (marcas["grupo_gestor"] != f.grupo_gestor)]
        if len(otros):
            pendientes.append({"tenedor": f.tenedor, "grupos_posibles": sorted(otros["grupo_gestor"].unique())})
    return pendientes


def tabla_emisores(notif):
    ultimo = notif.sort_values("fecha_posicion").groupby("lei").tail(1).set_index("lei")["emisor"]
    em = notif.groupby("lei").agg(
        isins=("isin", lambda s: ",".join(sorted(s.unique()))),
        primera=("fecha_posicion", "min"), ultima=("fecha_posicion", "max"), notificaciones=("pct", "size"))
    return em.join(ultimo).reset_index()[["lei", "emisor", "isins", "primera", "ultima", "notificaciones"]]


def intervalos(notif, vigentes, fecha_publicacion):
    """Una fila por tramo en que un fondo mantiene un mismo % público (>= 0,5 %) sobre un emisor."""
    df = notif.sort_values(CLAVE)[CLAVE + ["pct"]].copy()
    siguiente = df.groupby(["lei", "tenedor"])["fecha_posicion"].shift(-1)
    df["desde"] = df["fecha_posicion"]
    df["hasta"] = siguiente - pd.Timedelta(days=1)
    es_ultima = siguiente.isna()
    sigue_viva = pd.Series([(l, t) in vigentes for l, t in zip(df["lei"], df["tenedor"])], index=df.index)
    df["vigente"] = es_ultima & sigue_viva
    df.loc[es_ultima, "hasta"] = pd.Timestamp(fecha_publicacion)
    # Sin aviso de cierre: como mucho CADUCIDAD_DIAS tras el último aviso (salvo que siga vigente)
    limite = df["desde"] + pd.Timedelta(days=CADUCIDAD_DIAS)
    caduca = ~df["vigente"] & (df["hasta"] > limite)
    df.loc[caduca, "hasta"] = limite[caduca]
    df["cierre_inferido"] = caduca & (df["pct"] >= UMBRAL)
    return df[df["pct"] >= UMBRAL].drop(columns="fecha_posicion").reset_index(drop=True)


def posiciones_diarias(tramos):
    """Expande los tramos a días hábiles: una fila por fondo, emisor y día con posición pública."""
    inicio = np.busday_offset(tramos["desde"].values.astype("datetime64[D]"), 0, roll="forward")
    fin = tramos["hasta"].values.astype("datetime64[D]") + np.timedelta64(1, "D")
    n = np.clip(np.busday_count(inicio, fin), 0, None)
    fila = np.repeat(np.arange(len(tramos)), n)
    desfase = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    diarias = tramos.iloc[fila][["lei", "tenedor", "pct"]].reset_index(drop=True)
    diarias.insert(0, "fecha", pd.to_datetime(np.busday_offset(inicio[fila], desfase)))
    return diarias.sort_values(["fecha", "lei", "tenedor"], ignore_index=True)


def controles(notif, vigentes_crudas, diarias, fecha_publicacion, informe):
    """Añade los controles al informe y devuelve la lista de problemas críticos."""
    criticos = []
    lei_mal = (~notif["lei"].str.fullmatch(r"[A-Z0-9]{20}")).sum()
    isin_mal = (~notif["isin"].str.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")).sum()
    pct_mal = (~notif["pct"].between(0, 100)).sum()
    fechas_mal = (~notif["fecha_posicion"].between(FECHA_MINIMA, pd.Timestamp(fecha_publicacion))).sum()
    informe.update(lei_invalidos=int(lei_mal), isin_invalidos=int(isin_mal),
                   pct_fuera_de_rango=int(pct_mal), fechas_imposibles=int(fechas_mal))
    for nombre, n in [("LEI inválidos", lei_mal), ("porcentajes fuera de rango", pct_mal), ("fechas imposibles", fechas_mal)]:
        if n:
            criticos.append(f"{n} {nombre}")

    # Cuadre: el último día reconstruido debe reproducir la hoja de vigentes de la CNMV.
    # Esa hoja muestra un último día las posiciones que acaban de bajar del 0,5 %: no cuentan.
    ultimo = diarias[diarias["fecha"] == diarias["fecha"].max()].groupby("lei")["pct"].sum().round(2)
    publicas = vigentes_crudas[vigentes_crudas["pct"] >= UMBRAL].drop_duplicates(["lei", "tenedor"])
    oficial = publicas.groupby("lei")["pct"].sum().round(2)
    cuadre = pd.concat([ultimo.rename("reconstruido"), oficial.rename("cnmv")], axis=1).fillna(0)
    descuadres = cuadre[(cuadre["reconstruido"] - cuadre["cnmv"]).abs() > 0.001]
    informe["cuadre_vigentes"] = {"emisores": len(cuadre), "descuadres": descuadres.reset_index().to_dict("records")}
    if len(descuadres):
        criticos.append(f"{len(descuadres)} emisores no cuadran con la hoja de vigentes")
    return criticos


def construir(libro, fecha_publicacion, captura_utc=None, previas=None):
    """Devuelve (tablas, informe). `previas` = notificaciones de la silver anterior, para fechar capturas."""
    crudas = leer_notificaciones(libro)
    notif, vigentes, informe = limpiar(crudas)

    # Dos fechas: la de la posición y la de la primera captura en la que apareció la notificación
    # (sin silver previa = carga histórica: la fecha de captura queda vacía)
    if previas is None or not len(previas):
        notif["fecha_primera_captura"] = pd.NaT
    else:
        notif = notif.merge(previas[CLAVE + ["pct", "fecha_primera_captura"]],
                            on=CLAVE + ["pct"], how="left", indicator=True)
        nuevas = notif.pop("_merge").eq("left_only")
        notif.loc[nuevas, "fecha_primera_captura"] = pd.Timestamp(captura_utc).tz_convert(None)
        informe["notificaciones_nuevas"] = int(nuevas.sum())
    fondos = tabla_fondos(notif)
    notif = notif.merge(fondos[["tenedor", "grupo_gestor"]], on="tenedor", how="left")
    if previas is not None and len(previas):
        informe["fondos_nuevos"] = sorted(set(fondos["tenedor"]) - set(previas["tenedor"]))
    informe["grupos_por_revisar"] = grupos_por_revisar(fondos)

    tramos = intervalos(notif, vigentes, fecha_publicacion)
    diarias = posiciones_diarias(tramos)
    vig_crudas = crudas[crudas["hoja"] == cnmv.HOJAS_DATOS[0]]
    criticos = controles(notif, vig_crudas, diarias, fecha_publicacion, informe)
    informe.update(
        fecha_publicacion=str(fecha_publicacion),
        notificaciones=len(notif), emisores=int(notif["lei"].nunique()), fondos=len(fondos),
        grupos_gestores=int(fondos["grupo_gestor"].nunique()), tramos=len(tramos),
        cierres_inferidos=int(tramos["cierre_inferido"].sum()), posiciones_diarias=len(diarias),
        posiciones_vigentes=int(tramos["vigente"].sum()), criticos=criticos)
    tablas = {"notificaciones": notif, "emisores": tabla_emisores(notif), "fondos": fondos,
              "posiciones_intervalos": tramos, "posiciones_diarias": diarias}
    return tablas, informe


def a_parquet(df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def ejecutar(almacen_bronze, almacen_silver, captura_utc=None):
    """Construye la silver a partir de la última captura de bronze y la guarda. Lanza ErrorCalidad si falla."""
    from src.ingesta.ejecutar import RUTA_ESTADO

    estado = json.loads(almacen_bronze.leer_texto(RUTA_ESTADO) or "{}")
    if not estado.get("ruta"):
        raise ErrorCalidad("No hay ninguna captura en bronze")
    libro = cnmv.abrir(almacen_bronze.leer_bytes(estado["ruta"]))
    previas_bytes = almacen_silver.leer_bytes(f"{PREFIJO}/notificaciones.parquet")
    previas = pd.read_parquet(io.BytesIO(previas_bytes)) if previas_bytes else None
    tablas, informe = construir(libro, date.fromisoformat(estado["fecha_publicacion"]),
                                captura_utc or estado["captura_utc"], previas)
    informe["origen_bronze"] = estado["ruta"]
    informe["version_reglas"] = VERSION_REGLAS
    if informe["criticos"]:
        rechazo = f"{PREFIJO}/rechazos/calidad_{estado['fecha_publicacion']}_{Path(estado['ruta']).stem}.json"
        almacen_silver.escribir_texto(rechazo, json.dumps(informe, indent=2, default=str))
        raise ErrorCalidad(f"Controles de calidad fallidos: {informe['criticos']}")
    for nombre in TABLAS:
        almacen_silver.escribir_bytes(f"{PREFIJO}/{nombre}.parquet", a_parquet(tablas[nombre]), sobrescribir=True)
    almacen_silver.escribir_texto(f"{PREFIJO}/calidad.json", json.dumps(informe, indent=2, default=str))
    return informe


def main():
    """Uso local: python -m src.limpieza.silver [--bronze data/raw] [--destino data/silver]"""
    import argparse
    import logging

    from src.ingesta.almacen import AlmacenLocal

    p = argparse.ArgumentParser(description="Construye la capa silver a partir de la última captura de bronze")
    p.add_argument("--bronze", default="data/raw")
    p.add_argument("--destino", default="data/silver")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        informe = ejecutar(AlmacenLocal(args.bronze), AlmacenLocal(args.destino))
    except cnmv.ErrorIngesta as e:
        logging.error("INGESTA_CNMV_FALLO %s: %s", type(e).__name__, e)
        raise SystemExit(1)
    print(json.dumps(informe, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
