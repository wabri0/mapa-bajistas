"""Verifica de punta a punta la plataforma en Azure, sin abrir el portal.

Uso:  python scripts/verificar_plataforma.py

Usa la sesión de Microsoft guardada en local (la de src/modelo/bd.py; la primera vez abre el
navegador) y solo lee: no cambia nada. Comprueba, en el orden en que viaja el dato:
  1. Fuente: el Excel de la CNMV responde y cuándo se publicó.
  2. Código: último despliegue de GitHub Actions.
  3. Recursos de Azure: Function (estado, memoria, variables, temporizador), alerta por correo,
     presupuesto y firewall de la base de datos.
  4. Ejecuciones: resumen por día de Application Insights (correctas, fallidas, cargas, alertas).
  5. Capas bronze y silver: últimos ficheros en el almacenamiento.
  6. Base de datos: última carga, frescura de cada tabla, alertas y prueba de seguridad por cliente.
Termina con una lista de problemas (vacía si todo está bien).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.modelo import bd  # noqa: E402

SUSCRIPCION = "3530cc40-51f0-42ae-b89a-4b09adf15fb2"
GRUPO = "rg-mapa-bajistas"
FUNCTION = "func-mapa-bajistas"
ALMACEN = "stmapabajistas"
SERVIDOR_SQL = "sql-mapa-bajistas"
BASE = f"https://management.azure.com/subscriptions/{SUSCRIPCION}/resourceGroups/{GRUPO}/providers"
CNMV = "https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls"
REPO = "wabri0/mapa-bajistas"
AJUSTES_VISIBLES = ["CRON_INGESTA", "BRONZE_ACCOUNT_URL", "BRONZE_CONTAINER", "SQL_SERVIDOR", "SQL_BASE_DATOS"]

problemas = []
cred = bd.credencial()


def titulo(texto):
    print(f"\n=== {texto} ===")


def arm(ruta, version, metodo="GET"):
    token = cred.get_token("https://management.azure.com/.default").token
    url = ruta if ruta.startswith("https://") else f"{BASE}/{ruta}"
    r = requests.request(metodo, f"{url}?api-version={version}", headers={"Authorization": f"Bearer {token}"},
                         timeout=60)
    r.raise_for_status()
    return r.json()


def fuente():
    titulo("1. Fuente: CNMV")
    r = requests.head(CNMV, timeout=30, headers={"User-Agent": "mapa-bajistas-verificacion"})
    print(f"HTTP {r.status_code} · Last-Modified: {r.headers.get('Last-Modified')}")
    if r.status_code != 200:
        problemas.append(f"La CNMV responde {r.status_code}")


def despliegue():
    titulo("2. Código: GitHub Actions")
    run = requests.get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=1", timeout=30).json()["workflow_runs"][0]
    print(f"Último: {run['head_sha'][:7]} · {run['created_at']} · {run['status']} / {run['conclusion']}")
    if run["conclusion"] not in ("success", None):
        problemas.append(f"El último despliegue terminó en {run['conclusion']}")


def recursos():
    titulo("3. Recursos de Azure")
    nombres = sorted(f"{x['type'].split('/')[-1]}: {x['name']}"
                     for x in arm(f"https://management.azure.com/subscriptions/{SUSCRIPCION}/resourceGroups/{GRUPO}/resources",
                                  "2021-04-01")["value"])
    print("\n".join("  " + n for n in nombres))

    site = arm(f"Microsoft.Web/sites/{FUNCTION}", "2023-12-01")["properties"]
    memoria = site.get("functionAppConfig", {}).get("scaleAndConcurrency", {}).get("instanceMemoryMB")
    runtime = site.get("functionAppConfig", {}).get("runtime", {})
    print(f"Function: estado {site['state']} · {runtime.get('name')} {runtime.get('version')} · {memoria} MB")
    if site["state"] != "Running":
        problemas.append(f"La Function está {site['state']}")
    if memoria and memoria < 2048:
        problemas.append(f"La Function tiene {memoria} MB (se necesitan 2048)")
    ajustes = arm(f"Microsoft.Web/sites/{FUNCTION}/config/appsettings/list", "2023-12-01", "POST")["properties"]
    for k in AJUSTES_VISIBLES:
        print(f"  {k} = {ajustes.get(k, '(falta)')}")
        if k not in ajustes:
            problemas.append(f"Falta la variable {k} en la Function")
    for f in arm(f"Microsoft.Web/sites/{FUNCTION}/functions", "2023-12-01")["value"]:
        desactivada = f["properties"].get("isDisabled")
        print(f"  función {f['name'].split('/')[-1]}: {'DESACTIVADA' if desactivada else 'activa'}")
        if desactivada:
            problemas.append(f"La función {f['name']} está desactivada")

    for regla in arm("Microsoft.Insights/scheduledQueryRules", "2023-03-15-preview")["value"]:
        activa = regla["properties"].get("enabled")
        print(f"Alerta por correo {regla['name']}: {'activa' if activa else 'DESACTIVADA'}")
        if not activa:
            problemas.append(f"La alerta {regla['name']} está desactivada")

    for p in arm(f"https://management.azure.com/subscriptions/{SUSCRIPCION}/providers/Microsoft.Consumption/budgets",
                 "2023-05-01")["value"]:
        gasto = p["properties"].get("currentSpend", {})
        print(f"Presupuesto {p['name']}: {gasto.get('amount')} de {p['properties']['amount']} {gasto.get('unit', '')} este mes")

    db = arm(f"Microsoft.Sql/servers/{SERVIDOR_SQL}/databases/sqldb-mapa-bajistas", "2023-08-01-preview")
    print(f"Base de datos: {db['properties'].get('status')} · {db['sku']['name']} · "
          f"oferta gratuita: {db['properties'].get('useFreeLimit')} · "
          f"al agotarla: {db['properties'].get('freeLimitExhaustionBehavior')}")
    reglas = arm(f"Microsoft.Sql/servers/{SERVIDOR_SQL}/firewallRules", "2021-11-01")["value"]
    print("Firewall: " + ", ".join(f"{r['name']} ({r['properties']['startIpAddress']})" for r in reglas))


def ejecuciones():
    titulo("4. Ejecuciones (Application Insights, últimos 7 días)")
    app_id = arm(f"microsoft.insights/components/{FUNCTION}", "2020-02-02")["properties"]["AppId"]
    consulta = """
    union (traces | where message has_any ('SILVER_CNMV_OK', 'GOLD_CARGA_OK', 'INGESTA_CNMV_FALLO',
                                             'INGESTA_CNMV_REVISAR', 'ALERTA_CLIENTE')
                  | extend tipo = extract('^([A-Z_]+)', 1, message)),
          (requests | extend tipo = iif(tostring(success) =~ 'true', 'EJECUCION_OK', 'EJECUCION_FALLIDA'))
    | where timestamp > ago(7d)
    | summarize n = count() by dia = format_datetime(timestamp, 'yyyy-MM-dd'), tipo
    """
    token = cred.get_token("https://api.applicationinsights.io/.default").token
    r = requests.post(f"https://api.applicationinsights.io/v1/apps/{app_id}/query",
                      headers={"Authorization": f"Bearer {token}"}, json={"query": consulta}, timeout=60)
    r.raise_for_status()
    filas = r.json()["tables"][0]["rows"]
    tipos = ["EJECUCION_OK", "EJECUCION_FALLIDA", "SILVER_CNMV_OK", "GOLD_CARGA_OK", "ALERTA_CLIENTE",
             "INGESTA_CNMV_REVISAR", "INGESTA_CNMV_FALLO"]
    tabla = {}
    for dia, tipo, n in filas:
        tabla.setdefault(dia, {})[tipo] = n
    print("día        " + " ".join(f"{t[:14]:>14}" for t in tipos))
    for dia in sorted(tabla, reverse=True):
        print(f"{dia} " + " ".join(f"{tabla[dia].get(t, 0):>14}" for t in tipos))
    ayer = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for dia in (ayer, hoy):
        if tabla.get(dia, {}).get("EJECUCION_FALLIDA"):
            problemas.append(f"Hubo ejecuciones fallidas el {dia}")


def capas():
    titulo("5. Capas bronze y silver")
    from azure.storage.blob import BlobServiceClient

    servicio = BlobServiceClient(f"https://{ALMACEN}.blob.core.windows.net", credential=cred)
    try:
        bronze = [b for b in servicio.get_container_client("bronze").list_blobs(
            name_starts_with="cnmv/net_short_positions/fecha_publicacion=")]
        ultimo = max(bronze, key=lambda b: b.name)
        print(f"Bronze: {len(bronze)} capturas · última {ultimo.name.split('/')[-1]}")
        silver = servicio.get_container_client("silver")
        for b in silver.list_blobs(name_starts_with="cnmv/"):
            if b.name.count("/") == 1:
                print(f"  silver/{b.name}  {b.last_modified:%Y-%m-%d %H:%M} UTC  {b.size // 1024} KB")
        calidad = json.loads(silver.download_blob("cnmv/calidad.json").readall())
        print(f"Calidad: publicación {calidad['fecha_publicacion']} · críticos {calidad['criticos']} · "
              f"descuadres {len(calidad['cuadre_vigentes']['descuadres'])} · reglas {calidad['version_reglas']} · "
              f"retirados conservados {len(calidad.get('emisores_retirados_cnmv', []))}")
        if calidad["criticos"]:
            problemas.append(f"La silver tiene problemas críticos: {calidad['criticos']}")
    except Exception as e:  # sin rol de lectura de datos en el almacenamiento
        print(f"No se pueden leer los ficheros con tu cuenta ({type(e).__name__}). "
              "La base de datos (apartado 6) indica igualmente qué fichero se cargó.")


def base_datos():
    titulo("6. Base de datos")
    with bd.conectar() as cx:
        ultima = bd.ejecutar_script(cx, Path(__file__).with_name("verificar_plataforma.sql"))
        for tabla in ultima:
            for fila in tabla:
                print("  " + " · ".join(f"{k}: {v}" for k, v in fila.items()))
        carga = ultima[0][0]
        if (datetime.now(timezone.utc).replace(tzinfo=None) - carga["fin_utc"]).days >= 4:
            problemas.append(f"La última carga en SQL es del {carga['fin_utc']}")
        rls = bd.ejecutar_script(cx, RAIZ / "sql" / "06_prueba_rls.sql")
        for fila in rls[0]:
            print(f"  RLS {fila['usuario']}: {fila['clientes']} clientes, {fila['alertas']} alertas, "
                  f"{fila['alertas_de_otros']} de otros")
            if fila["alertas_de_otros"]:
                problemas.append(f"{fila['usuario']} ve alertas de otro cliente")
        for t in rls[1:]:
            texto = list(t[0].values())[0]
            print(f"  {texto[:60]}")
            if not texto.startswith("OK"):
                problemas.append(texto)


if __name__ == "__main__":
    for paso in (fuente, despliegue, recursos, ejecuciones, capas, base_datos):
        try:
            paso()
        except Exception as e:
            problemas.append(f"{paso.__name__}: {type(e).__name__}: {e}")
            print(f"ERROR en {paso.__name__}: {e}")
    titulo("Resultado")
    print("Todo correcto" if not problemas else "\n".join(f"- {p}" for p in problemas))
