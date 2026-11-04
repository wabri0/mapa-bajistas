from datetime import date

import pandas as pd
import pytest

from src.ingesta import cnmv
from src.ingesta.almacen import AlmacenLocal
from src.limpieza import silver
from tests.conftest import EXCEL, requiere_excel

VIG, SERIE, ANT = cnmv.HOJAS_DATOS
LEI_A, LEI_B = "A" * 20, "B" * 20
PUBLICACION = date(2026, 11, 3)  # martes


def filas(*registros):
    """registros: (hoja, lei, isin, tenedor, fecha, pct) -> DataFrame como el de leer_notificaciones."""
    df = pd.DataFrame(registros, columns=["hoja", "lei", "isin", "tenedor", "fecha_posicion", "pct"])
    df["emisor"] = df["lei"].map({LEI_A: "EMPRESA A, S.A.", LEI_B: "EMPRESA B, S.A."})
    df["fecha_posicion"] = pd.to_datetime(df["fecha_posicion"])
    return df[["lei", "isin", "emisor", "tenedor", "fecha_posicion", "pct", "hoja"]]


def tramos_de(crudas):
    notif, vigentes, informe = silver.limpiar(crudas)
    return silver.intervalos(notif, vigentes, PUBLICACION), informe


def test_quita_duplicados_entre_hojas_y_ignora_la_hoja_de_vigentes():
    crudas = filas(
        (VIG, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
    )
    notif, vigentes, informe = silver.limpiar(crudas)
    assert len(notif) == 1 and informe["duplicados_eliminados"] == 2
    assert vigentes == {(LEI_A, "Fondo X")}


def test_cada_notificacion_vale_hasta_la_siguiente_y_por_debajo_del_umbral_se_cierra():
    tramos, _ = tramos_de(filas(
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-05", 0.8),
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-10", 0.4),
    ))
    assert tramos[["pct", "desde", "hasta"]].values.tolist() == [
        [0.6, pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-04")],
        [0.8, pd.Timestamp("2026-10-05"), pd.Timestamp("2026-10-09")],
    ]
    assert not tramos["cierre_inferido"].any()


def test_una_posicion_vigente_llega_hasta_la_fecha_de_publicacion():
    tramos, _ = tramos_de(filas(
        (VIG, LEI_A, "ES0000000001", "Fondo X", "2026-10-20", 0.7),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2026-10-20", 0.7),
    ))
    assert tramos.loc[0, "hasta"] == pd.Timestamp(PUBLICACION) and tramos.loc[0, "vigente"]


def test_sin_aviso_de_cierre_caduca_a_los_365_dias():
    tramos, _ = tramos_de(filas(
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2018-08-15", 0.6),   # nada durante 6 años
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2024-08-14", 0.5),   # posición nueva
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2024-09-02", 0.4),
    ))
    assert tramos.loc[0, "hasta"] == pd.Timestamp("2019-08-15") and tramos.loc[0, "cierre_inferido"]
    assert tramos.loc[1, "hasta"] == pd.Timestamp("2024-09-01") and not tramos.loc[1, "cierre_inferido"]


def test_una_posicion_que_ya_no_esta_vigente_tambien_caduca():
    tramos, _ = tramos_de(filas((ANT, LEI_A, "ES0000000001", "Fondo X", "2018-08-15", 0.6)))
    assert tramos.loc[0, "hasta"] == pd.Timestamp("2019-08-15") and tramos.loc[0, "cierre_inferido"]


def test_una_posicion_vigente_no_caduca_aunque_sea_antigua():
    tramos, _ = tramos_de(filas(
        (VIG, LEI_A, "ES0000000001", "Fondo X", "2025-04-04", 0.6),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2025-04-04", 0.6),
    ))
    assert tramos.loc[0, "hasta"] == pd.Timestamp(PUBLICACION) and not tramos.loc[0, "cierre_inferido"]


def test_un_cambio_de_isin_no_rompe_la_serie_porque_se_agrupa_por_lei():
    tramos, _ = tramos_de(filas(
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-01-05", 0.9),   # ISIN antiguo, sin aviso de cierre
        (VIG, LEI_A, "ES0000000002", "Fondo X", "2026-03-02", 0.7),   # ISIN nuevo tras la operación
        (SERIE, LEI_A, "ES0000000002", "Fondo X", "2026-03-02", 0.7),
    ))
    assert tramos["pct"].tolist() == [0.9, 0.7]
    assert tramos.loc[0, "hasta"] == pd.Timestamp("2026-03-01") and not tramos["cierre_inferido"].any()


def test_dos_porcentajes_el_mismo_dia_se_queda_el_mayor_y_se_cuenta():
    notif, _, informe = silver.limpiar(filas(
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000002", "Fondo X", "2026-10-01", 0.7),
    ))
    assert notif["pct"].tolist() == [0.7] and informe["conflictos_mismo_dia"] == 2


def test_posiciones_diarias_solo_en_dias_habiles():
    tramos, _ = tramos_de(filas(
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-10-30", 0.6),   # viernes
        (ANT, LEI_A, "ES0000000001", "Fondo X", "2026-11-04", 0.3),   # miércoles
    ))
    diarias = silver.posiciones_diarias(tramos)
    assert diarias["fecha"].dt.strftime("%a %d").tolist() == ["Fri 30", "Mon 02", "Tue 03"]


def test_grupo_gestor_une_entidades_de_la_misma_casa():
    notif, _, _ = silver.limpiar(filas(
        (ANT, LEI_A, "ES0000000001", "Citadel Advisors LLC", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000001", "Citadel Europe LLP", "2026-10-01", 0.6),
        (ANT, LEI_A, "ES0000000001", "Fondo Sin Grupo", "2026-10-01", 0.6),
    ))
    grupos = silver.tabla_fondos(notif).set_index("tenedor")["grupo_gestor"]
    assert grupos["Citadel Advisors LLC"] == grupos["Citadel Europe LLP"] == "Citadel"
    assert grupos["Fondo Sin Grupo"] == "Fondo Sin Grupo"


def test_controles_detectan_porcentajes_imposibles_y_descuadres():
    crudas = filas(
        (VIG, LEI_A, "ES0000000001", "Fondo X", "2026-10-20", 0.7),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2026-10-20", 0.7),
        (ANT, LEI_B, "ES0000000003", "Fondo Y", "2026-10-20", 150.0),
    )
    notif, vigentes, informe = silver.limpiar(crudas)
    diarias = silver.posiciones_diarias(silver.intervalos(notif, vigentes, PUBLICACION))
    vig = crudas[crudas["hoja"] == VIG].assign(pct=0.9)  # la CNMV diría 0,9 y reconstruimos 0,7
    criticos = silver.controles(notif, vig, diarias, PUBLICACION, informe)
    assert informe["pct_fuera_de_rango"] == 1
    assert any("fuera de rango" in c for c in criticos) and any("no cuadran" in c for c in criticos)


def test_la_hoja_de_vigentes_muestra_un_dia_las_que_bajan_del_umbral_y_no_descuadran():
    crudas = filas(
        (VIG, LEI_A, "ES0000000001", "Fondo X", "2026-11-02", 0.49),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2026-10-29", 0.5),
        (SERIE, LEI_A, "ES0000000001", "Fondo X", "2026-11-02", 0.49),
        (VIG, LEI_A, "ES0000000001", "Fondo Y", "2026-10-29", 0.6),
        (SERIE, LEI_A, "ES0000000001", "Fondo Y", "2026-10-29", 0.6),
    )
    notif, vigentes, informe = silver.limpiar(crudas)
    diarias = silver.posiciones_diarias(silver.intervalos(notif, vigentes, PUBLICACION))
    assert silver.controles(notif, crudas[crudas["hoja"] == VIG], diarias, PUBLICACION, informe) == []


@requiere_excel
def test_fichero_real_cuadra_con_la_cnmv_y_se_guarda(tmp_path):
    from src.ingesta.ejecutar import ingestar

    bronze, destino = AlmacenLocal(tmp_path / "bronze"), AlmacenLocal(tmp_path / "silver")
    ingestar(bronze, contenido=EXCEL.read_bytes(), cabeceras={})
    informe = silver.ejecutar(bronze, destino)
    assert informe["criticos"] == [] and informe["cuadre_vigentes"]["descuadres"] == []
    assert informe["notificaciones"] > 12000 and informe["emisores"] >= 80
    diarias = pd.read_parquet(tmp_path / "silver" / "cnmv" / "posiciones_diarias.parquet")
    assert diarias["fecha"].dt.day_of_week.max() <= 4

    # Caso Grifols (con caducidad de 365 días): máximo de 3,88 % el 14-mar-2024
    emisores = pd.read_parquet(tmp_path / "silver" / "cnmv" / "emisores.parquet")
    lei = emisores.loc[emisores["emisor"].str.contains("GRIFOLS"), "lei"].iloc[0]
    suma = diarias[(diarias["lei"] == lei) & diarias["fecha"].between("2024-01-01", "2024-06-30")].groupby("fecha")["pct"].sum()
    assert round(suma.max(), 2) == 3.88 and suma.idxmax() == pd.Timestamp("2024-03-14")


@requiere_excel
def test_segunda_ejecucion_fecha_solo_las_notificaciones_nuevas(tmp_path):
    from src.ingesta.ejecutar import ingestar

    bronze, destino = AlmacenLocal(tmp_path / "bronze"), AlmacenLocal(tmp_path / "silver")
    ingestar(bronze, contenido=EXCEL.read_bytes(), cabeceras={})
    silver.ejecutar(bronze, destino)
    previas = pd.read_parquet(tmp_path / "silver" / "cnmv" / "notificaciones.parquet")
    assert previas["fecha_primera_captura"].isna().all()  # carga histórica

    # Simula que la carga anterior no tenía la notificación más reciente
    recortadas = previas[previas["fecha_posicion"] < previas["fecha_posicion"].max()]
    destino.escribir_bytes("cnmv/notificaciones.parquet", silver.a_parquet(recortadas), sobrescribir=True)
    informe = silver.ejecutar(bronze, destino, captura_utc="2026-11-04T20:00:00+00:00")
    nuevas = len(previas) - len(recortadas)
    assert informe["notificaciones_nuevas"] == nuevas
    notif = pd.read_parquet(tmp_path / "silver" / "cnmv" / "notificaciones.parquet")
    assert notif["fecha_primera_captura"].notna().sum() == nuevas
