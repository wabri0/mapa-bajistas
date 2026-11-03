"""Fase 0: validación del Excel de posiciones cortas netas de la CNMV.

Reproduce todas las cifras de docs/fase0/hallazgos_datos.md:
perfil de las hojas, problemas de calidad, validación de la serie diaria
reconstruida contra la hoja de posiciones vigentes y casos Grifols y Solaria.

Uso:
    python scripts/fase0_explorar.py data/raw/NetShortPositions_2026-11-02.xls
"""
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 200)

COLS = ["lei", "isin", "emisor", "tenedor", "fecha", "pct"]
HOJAS = {
    "vigentes": "Última_-_Current",
    "serie": "Serie_-_Series",
    "anteriores": "Anteriores_-_Previous",
}
UMBRAL = 0.5
GRIFOLS_A = "ES0171996087"
SOLARIA = "ES0165386014"


def cargar(ruta, hoja):
    df = pd.read_excel(ruta, sheet_name=hoja, header=None, skiprows=4, names=COLS, engine="xlrd")
    df["fecha"] = pd.to_datetime(df["fecha"].astype(str).str.strip())
    return df


def perfil(nombre, df):
    print(f"\n== {nombre}: {len(df)} filas")
    print(f"  fechas de posición: {df.fecha.min().date()} -> {df.fecha.max().date()}")
    print(f"  emisores {df['emisor'].nunique()} | LEI {df['lei'].nunique()} | "
          f"ISIN {df['isin'].nunique()} (en mayúsculas: {df['isin'].str.upper().nunique()}) | "
          f"tenedores {df['tenedor'].nunique()}")
    print(f"  % mín/máx {df.pct.min()} / {df.pct.max()} | filas < {UMBRAL} %: {(df.pct < UMBRAL).sum()} "
          f"| filas = 0: {(df.pct == 0).sum()}")
    print(f"  duplicados exactos: {df.duplicated(COLS).sum()} | "
          f"ISIN escritos en minúsculas: {(df['isin'] != df['isin'].str.upper()).sum()} | nulos: {df[COLS].isna().sum().sum()}")


def serie_diaria(hist, isin, desde, hasta):
    """Arrastra la última notificación de cada fondo; por debajo del umbral cuenta como 0 publicado."""
    g = hist[hist["isin"] == isin].sort_values("fecha").groupby(["tenedor", "fecha"], as_index=False)["pct"].last()
    w = g.pivot(index="fecha", columns="tenedor", values="pct")
    w = w.reindex(pd.date_range(w.index.min(), hasta, freq="D")).ffill().fillna(0)
    w = w.where(w >= UMBRAL, 0).loc[desde:hasta]
    return pd.DataFrame({"suma_pct": w.sum(axis=1).round(2), "fondos": (w > 0).sum(axis=1)})


def main(ruta):
    d = {k: cargar(ruta, h) for k, h in HOJAS.items()}
    print("Fichero:", ruta)
    for k, df in d.items():
        perfil(k, df)

    for df in d.values():
        df["isin"] = df["isin"].str.upper()
    vig = d["vigentes"].drop_duplicates(COLS)
    hist = pd.concat([d["serie"], d["anteriores"]]).drop_duplicates(COLS)
    solape = d["serie"].merge(d["anteriores"], on=["isin", "tenedor", "fecha"], suffixes=("_s", "_a"))
    print(f"\nHistórico único (serie + anteriores, sin duplicados): {len(hist)} notificaciones, "
          f"{hist['emisor'].nunique()} emisores, {hist['tenedor'].nunique()} tenedores, {hist['isin'].nunique()} ISIN")
    print(f"Solape serie/anteriores: {len(solape)} filas, mismo % en el {(solape.pct_s == solape.pct_a).mean():.0%}")
    print("\nNotificaciones por año:")
    print(hist.fecha.dt.year.value_counts().sort_index().to_frame("n").T.to_string())

    print("\nEmisores con varios ISIN (operaciones corporativas):")
    varios = hist.groupby("emisor")["isin"].unique()
    for emisor, isins in varios[varios.str.len() > 1].items():
        print(f"  {emisor}: {', '.join(sorted(isins))}")

    # Validación: la última notificación de cada par ISIN-fondo debe reproducir la hoja de vigentes
    ultima = hist.sort_values("fecha").groupby(["isin", "tenedor"]).tail(1)
    reconstruido = ultima[ultima.pct >= UMBRAL].groupby("isin")["pct"].sum().round(2)
    oficial = vig.groupby("isin")["pct"].sum().round(2)
    cmp = pd.concat([reconstruido.rename("reconstruido"), oficial.rename("vigentes_cnmv")], axis=1).fillna(0)
    malos = cmp[(cmp.reconstruido - cmp.vigentes_cnmv).abs() > 0.001]
    print(f"\nValidación contra vigentes: {len(cmp) - len(malos)} de {len(cmp)} ISIN cuadran")
    print(malos.to_string())

    print("\nRanking de vigentes por suma de posiciones:")
    rk = vig.groupby("emisor").agg(suma_pct=("pct", "sum"), fondos=("tenedor", "nunique"))
    print(rk.sort_values("suma_pct", ascending=False).head(5).round(2).to_string())

    print(f"\n######## GRIFOLS clase A ({GRIFOLS_A})")
    g = hist[(hist["isin"] == GRIFOLS_A) & hist.fecha.between("2023-11-01", "2024-03-31")]
    print(g.sort_values("fecha")[["fecha", "tenedor", "pct"]].to_string(index=False))
    t = serie_diaria(hist, GRIFOLS_A, "2023-09-01", "2024-06-30")
    print("\nSuma publicada en fechas clave:")
    print(t.loc[["2023-10-31", "2023-12-29", "2024-01-08", "2024-01-09", "2024-01-31",
                 "2024-02-29", "2024-03-14", "2024-03-29", "2024-05-31"]].to_string())
    print(f"Media sep-dic 2023: {t.loc[:'2023-12-31', 'suma_pct'].mean():.2f} % | "
          f"media feb-mar 2024: {t.loc['2024-02-01':'2024-03-31', 'suma_pct'].mean():.2f} %")
    aqr = hist[(hist["isin"] == GRIFOLS_A) & hist["tenedor"].str.startswith("AQR")].sort_values("fecha")
    print("AQR en Grifols (hueco 2018-2024 sin notificaciones):",
          ", ".join(f"{f:%Y-%m-%d} {p}" for f, p in zip(aqr.fecha, aqr.pct)))

    print(f"\n######## SOLARIA ({SOLARIA})")
    t = serie_diaria(hist, SOLARIA, "2018-01-01", vig.fecha.max())
    print(f"Primera notificación: {hist[hist['isin'] == SOLARIA].fecha.min().date()}")
    print(f"Máximo de la suma: {t.suma_pct.max()} % el {t.suma_pct.idxmax().date()}")
    print(f"Máximo de fondos: {t.fondos.max()} el {t.fondos.idxmax().date()}")
    print(f"Último día: {t.iloc[-1].to_dict()}")
    print("Máximo anual de suma y fondos:")
    print(t.groupby(t.index.year).max().T.to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/NetShortPositions_2026-11-02.xls")
