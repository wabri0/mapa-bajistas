"""Reglas de alerta por cliente (fase 4).

Cada cliente tiene sus reglas en cliente.regla_alerta: qué indicador vigila, con qué umbral y
sobre qué empresas (la suya, sus competidoras o todas las que sigue). Tipos de regla:

- fondo_nuevo         entra un fondo sin posición en las 20 sesiones anteriores (una alerta por fondo)
- suma_supera         la suma de posiciones cortas cruza hacia arriba el umbral (%)
- suma_sube_5d        la suma sube al menos el umbral (puntos) en 5 sesiones
- suma_sube_20d       ídem en 20 sesiones
- fondos_supera       el número de fondos cruza hacia arriba el umbral
- dias_cubrir_supera  los días para cubrir cruzan hacia arriba el umbral

Las reglas de umbral avisan solo el día en que se cruza (no todos los días que siga por encima),
para que un cliente no reciba el mismo aviso cada mañana.
Las alertas se calculan sobre todo el histórico: así se ve qué habría recibido cada cliente
en casos como Grifols (enero de 2024).
"""
import re

import pandas as pd

INDICADOR = {"suma_supera": "suma_pct", "suma_sube_5d": "var_suma_5d", "suma_sube_20d": "var_suma_20d",
             "fondos_supera": "num_fondos", "dias_cubrir_supera": "dias_cubrir"}
TIPOS = {"fondo_nuevo", *INDICADOR}
AMBITOS = {"propia": {"propia"}, "competidora": {"competidora"}, "todas": {"propia", "competidora"}}
COLUMNAS = ["cliente_id", "regla_id", "lei", "fecha", "tenedor", "tipo", "valor", "mensaje"]


def num(x, decimales=2):
    """Número con coma decimal: 1.5 → '1,50'."""
    return f"{x:.{decimales}f}".replace(".", ",")


def nombre_corto(nombre):
    """'GRIFOLS, S.A.' → 'Grifols'; 'SOLARIA ENERGIA Y MEDIOAMBIENTE, S.A.' → 'Solaria Energia y Medioambiente'."""
    limpio = re.sub(r",?\s*(S\.A\.U?\.?|SOCIEDAD AN[OÓ]NIMA|N\.V\.|PLC|LIMITED|LTD\.?|S\.E\.)\s*$", "", nombre.strip(),
                    flags=re.I)
    palabras = limpio.title().split()
    return " ".join(p.lower() if p.lower() in {"y", "de", "del", "la", "las", "los", "e"} and i else p
                    for i, p in enumerate(palabras))


def mensaje(tipo, empresa, fila, umbral, tenedor=None, pct_fondo=None):
    estado = f"suma {num(fila.suma_pct)} %, {int(fila.num_fondos)} fondos"
    if tipo == "fondo_nuevo":
        return f"{empresa}: entra un fondo nuevo, {tenedor}, con un {num(pct_fondo)} % ({estado})."
    if tipo == "suma_supera":
        return f"{empresa}: las posiciones cortas superan el {num(umbral)} % ({estado})."
    if tipo in ("suma_sube_5d", "suma_sube_20d"):
        sesiones = 5 if tipo == "suma_sube_5d" else 20
        var = fila.var_suma_5d if sesiones == 5 else fila.var_suma_20d
        return (f"{empresa}: las posiciones cortas suben {num(var)} puntos en {sesiones} sesiones "
                f"({estado}).")
    if tipo == "fondos_supera":
        return f"{empresa}: ya son {int(fila.num_fondos)} los fondos con posición corta ({estado})."
    if tipo == "dias_cubrir_supera":
        return (f"{empresa}: los bajistas necesitarían {num(fila.dias_cubrir, 1)} sesiones para recomprar "
                f"con el volumen medio ({estado}).")
    raise ValueError(tipo)


def evaluar(indicadores, nuevos, posiciones, reglas, seguimiento, nombres):
    """Devuelve las alertas de todos los clientes.

    indicadores, nuevos: salida de indicadores.calcular
    posiciones: posiciones diarias (para el % del fondo que entra)
    reglas: regla_id, cliente_id, tipo, umbral, ambito (solo las activas)
    seguimiento: cliente_id, lei, rol ('propia' o 'competidora')
    nombres: lei → nombre del emisor
    """
    desconocidas = set(reglas["tipo"]) - TIPOS
    if desconocidas:
        raise ValueError(f"Tipos de regla desconocidos: {desconocidas}")
    ind = indicadores.sort_values(["lei", "fecha"]).reset_index(drop=True)
    previo = ind.groupby("lei")[list(set(INDICADOR.values()))].shift(1)
    filas = []
    for regla in reglas.itertuples():
        leis = set(seguimiento.loc[(seguimiento["cliente_id"] == regla.cliente_id)
                                   & seguimiento["rol"].isin(AMBITOS[regla.ambito]), "lei"])
        if regla.tipo == "fondo_nuevo":
            entradas = nuevos[nuevos["lei"].isin(leis)].merge(
                posiciones[["fecha", "lei", "tenedor", "pct"]], on=["fecha", "lei", "tenedor"])
            entradas = entradas.merge(ind, on=["lei", "fecha"])
            for e in entradas.itertuples():
                filas.append((regla.cliente_id, regla.regla_id, e.lei, e.fecha, e.tenedor, regla.tipo, e.pct,
                              mensaje(regla.tipo, nombre_corto(nombres[e.lei]), e, regla.umbral, e.tenedor, e.pct)))
            continue
        col = INDICADOR[regla.tipo]
        cruza = ind["lei"].isin(leis) & (ind[col] >= regla.umbral) & ~(previo[col] >= regla.umbral)
        for e in ind[cruza].itertuples():
            filas.append((regla.cliente_id, regla.regla_id, e.lei, e.fecha, None, regla.tipo, getattr(e, col),
                          mensaje(regla.tipo, nombre_corto(nombres[e.lei]), e, regla.umbral)))
    alertas = pd.DataFrame(filas, columns=COLUMNAS)
    return alertas.sort_values(["cliente_id", "fecha", "regla_id"], ignore_index=True)
