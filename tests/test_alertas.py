import pandas as pd
import pytest

from src.alertas import indicadores, reglas

LEI_A, LEI_B = "A" * 20, "B" * 20


def calendario(desde="2024-01-01", hasta="2024-03-29"):
    dias = pd.bdate_range(desde, hasta)
    return pd.DataFrame({"fecha": dias, "es_dia_bolsa": True})


def posiciones(*tramos):
    """tramos: (lei, tenedor, desde, hasta, pct) → posiciones diarias en días laborables."""
    filas = []
    for lei, tenedor, desde, hasta, pct in tramos:
        for dia in pd.bdate_range(desde, hasta):
            filas.append((dia, lei, tenedor, pct))
    return pd.DataFrame(filas, columns=["fecha", "lei", "tenedor", "pct"])


def precios(lei=LEI_A, volumen=1000, desde="2024-01-01", hasta="2024-03-29"):
    dias = pd.bdate_range(desde, hasta)
    cierre = pd.Series(range(len(dias)), dtype=float) + 10
    return pd.DataFrame({"fecha": dias, "lei": lei, "cierre": cierre, "cierre_ajustado": cierre, "volumen": volumen})


ACCIONES = pd.DataFrame({"lei": [LEI_A], "acciones": [1_000_000]})


@pytest.fixture
def caso():
    pos = posiciones(
        (LEI_A, "FONDO 1", "2024-01-01", "2024-03-29", 1.0),
        (LEI_A, "FONDO 2", "2024-01-15", "2024-01-31", 0.6),  # entra el 15-ene y sale el 1-feb
        (LEI_A, "FONDO 2", "2024-02-12", "2024-02-12", 0.7),  # vuelve a los 7 días: no es nuevo
    )
    return indicadores.calcular(pos, precios(), calendario(), ACCIONES), pos


def fila(ind, fecha, lei=LEI_A):
    return ind[(ind["lei"] == lei) & (ind["fecha"] == pd.Timestamp(fecha))].iloc[0]


# ---------- Indicadores ----------

def test_suma_fondos_y_concentracion(caso):
    (ind, _), _ = caso
    f = fila(ind, "2024-01-15")
    assert f["suma_pct"] == pytest.approx(1.6) and f["num_fondos"] == 2
    assert f["peso_mayor_fondo"] == pytest.approx(62.5)  # 1,0 de 1,6


def test_variaciones_en_sesiones(caso):
    (ind, _), _ = caso
    assert fila(ind, "2024-01-15")["var_suma_5d"] == pytest.approx(0.6)
    assert fila(ind, "2024-01-19")["var_suma_5d"] == pytest.approx(0.6)  # 5 sesiones antes: 12-ene
    assert fila(ind, "2024-01-22")["var_suma_5d"] == pytest.approx(0)    # 5 sesiones antes: 15-ene


def test_fondos_nuevos_y_salidas(caso):
    (ind, nuevos), _ = caso
    assert set(zip(nuevos["tenedor"], nuevos["fecha"].dt.strftime("%Y-%m-%d"))) == {
        ("FONDO 1", "2024-01-01"), ("FONDO 2", "2024-01-15")}  # la vuelta del 12-feb no cuenta
    assert fila(ind, "2024-02-01")["salidas"] == 1
    assert fila(ind, "2024-02-12")["fondos_nuevos"] == 0


def test_dias_para_cubrir(caso):
    (ind, _), _ = caso
    f = fila(ind, "2024-02-28")  # 1 % de 1.000.000 acciones = 10.000; volumen medio 1.000
    assert f["dias_cubrir"] == pytest.approx(10)


def test_sin_acciones_no_hay_dias_para_cubrir():
    pos = posiciones((LEI_B, "FONDO 1", "2024-01-01", "2024-02-29", 1.0))
    ind, _ = indicadores.calcular(pos, precios(LEI_B), calendario(), ACCIONES)
    assert ind["dias_cubrir"].isna().all()


def test_se_registra_la_salida_total_y_luego_se_corta():
    # B sigue con posiciones hasta marzo: los datos llegan hasta el 29-mar
    pos = posiciones((LEI_A, "FONDO 1", "2024-01-01", "2024-01-31", 1.0), (LEI_B, "G", "2024-01-01", "2024-03-29", 1.0))
    ind, _ = indicadores.calcular(pos, precios(), calendario(), ACCIONES)
    ind = ind[ind["lei"] == LEI_A]
    assert fila(ind, "2024-02-01")["suma_pct"] == 0 and fila(ind, "2024-02-01")["salidas"] == 1
    assert ind["fecha"].max() == pd.Timestamp("2024-02-28")  # 20 sesiones después de la última posición


def test_los_festivos_no_cuentan_como_sesiones():
    cal = calendario()
    cal.loc[cal["fecha"] == "2024-01-10", "es_dia_bolsa"] = False
    pos = posiciones((LEI_A, "FONDO 1", "2024-01-01", "2024-01-31", 1.0))
    pos = pos[pos["fecha"] != "2024-01-10"]
    ind, _ = indicadores.calcular(pos, precios(), cal, ACCIONES)
    assert pd.Timestamp("2024-01-10") not in set(ind["fecha"])


# ---------- Reglas ----------

NOMBRES = pd.Series({LEI_A: "EMPRESA A, S.A.", LEI_B: "EMPRESA B, S.A."})
SEGUIMIENTO = pd.DataFrame({"cliente_id": [1, 2], "lei": [LEI_A, LEI_B], "rol": ["propia", "propia"]})


def regla(*filas):
    return pd.DataFrame(filas, columns=["regla_id", "cliente_id", "tipo", "umbral", "ambito"])


def test_fondo_nuevo_con_nombre_y_porcentaje(caso):
    (ind, nuevos), pos = caso
    al = reglas.evaluar(ind, nuevos, pos, regla((1, 1, "fondo_nuevo", None, "propia")), SEGUIMIENTO, NOMBRES)
    assert list(al["tenedor"]) == ["FONDO 1", "FONDO 2"]
    assert al.iloc[1]["mensaje"] == "Empresa A: entra un fondo nuevo, FONDO 2, con un 0,60 % (suma 1,60 %, 2 fondos)."


def test_umbral_solo_avisa_al_cruzarlo(caso):
    (ind, nuevos), pos = caso
    al = reglas.evaluar(ind, nuevos, pos, regla((1, 1, "suma_supera", 1.5, "propia")), SEGUIMIENTO, NOMBRES)
    # supera el 1,5 % el 15-ene, sigue por encima hasta el 31-ene y vuelve a cruzar el 12-feb
    assert list(al["fecha"].dt.strftime("%Y-%m-%d")) == ["2024-01-15", "2024-02-12"]


def test_cada_cliente_solo_recibe_lo_suyo(caso):
    (ind, nuevos), pos = caso
    al = reglas.evaluar(ind, nuevos, pos, regla((1, 1, "fondo_nuevo", None, "propia"),
                                                 (2, 2, "fondo_nuevo", None, "propia")), SEGUIMIENTO, NOMBRES)
    assert set(al["cliente_id"]) == {1}  # el cliente 2 sigue a B, sin posiciones


def test_ambito_competidoras():
    pos = posiciones((LEI_A, "F", "2024-01-01", "2024-02-29", 0.8), (LEI_B, "G", "2024-01-01", "2024-02-29", 0.8))
    ind, nuevos = indicadores.calcular(pos, precios(), calendario(), ACCIONES)
    seg = pd.DataFrame({"cliente_id": [1, 1], "lei": [LEI_A, LEI_B], "rol": ["propia", "competidora"]})
    al = reglas.evaluar(ind, nuevos, pos, regla((1, 1, "fondo_nuevo", None, "competidora")), seg, NOMBRES)
    assert set(al["lei"]) == {LEI_B}


def test_tipo_desconocido_falla(caso):
    (ind, nuevos), pos = caso
    with pytest.raises(ValueError):
        reglas.evaluar(ind, nuevos, pos, regla((1, 1, "inventada", 1, "propia")), SEGUIMIENTO, NOMBRES)


@pytest.mark.parametrize("nombre,corto", [
    ("GRIFOLS, S.A.", "Grifols"),
    ("SOLARIA ENERGIA Y MEDIOAMBIENTE, S.A.", "Solaria Energia y Medioambiente"),
    ("FERROVIAL N.V.", "Ferrovial"),
    ("LABORATORIOS FARMACEUTICOS ROVI, S.A.", "Laboratorios Farmaceuticos Rovi"),
])
def test_nombre_corto(nombre, corto):
    assert reglas.nombre_corto(nombre) == corto


def test_tipos_de_regla_coinciden_con_el_sql():
    from pathlib import Path
    texto = (Path(__file__).parents[1] / "sql" / "01_esquema.sql").read_text(encoding="utf-8")
    for tipo in reglas.TIPOS:
        assert f"'{tipo}'" in texto
