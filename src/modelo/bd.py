"""Conexión a Azure SQL Database sin contraseñas y ejecución de scripts.

- En Azure, la Function entra con su identidad administrada.
- En local, se abre el navegador una vez para iniciar sesión con la cuenta de Microsoft
  (la del administrador del servidor). La sesión se guarda cifrada en el equipo, así que
  las siguientes ejecuciones no vuelven a pedirla.
Configuración: SQL_SERVIDOR (p. ej. sql-mapa-bajistas.database.windows.net) y SQL_BASE_DATOS.

Uso local para crear el esquema o lanzar las pruebas:
    python -m src.modelo.bd sql/01_esquema.sql sql/02_carga.sql ...
"""
import logging
import os
import re
import time
from pathlib import Path

from src.ingesta.cnmv import ErrorIngesta

ESCOPO = "https://database.windows.net/.default"
REGISTRO_SESION = Path.home() / ".mapa_bajistas" / "sesion_entra.json"
# La base de datos gratuita se pausa sola: al despertarla, la primera conexión puede fallar
INTENTOS, ESPERA_S = 5, 20
CODIGOS_REINTENTO = ("40613", "40197", "40501", "49918", "49919", "49920", "4060", "10928", "10929")
SEPARADOR = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


class ErrorBD(ErrorIngesta):
    """No se ha podido conectar o la carga en la base de datos ha fallado."""


def configurada():
    return bool(os.environ.get("SQL_SERVIDOR"))


def credencial():
    """Identidad administrada en Azure; inicio de sesión en el navegador (una vez) en local."""
    from azure.identity import ManagedIdentityCredential

    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
        return ManagedIdentityCredential()
    from azure.identity import AuthenticationRecord, InteractiveBrowserCredential, TokenCachePersistenceOptions

    registro = None
    if REGISTRO_SESION.exists():
        registro = AuthenticationRecord.deserialize(REGISTRO_SESION.read_text(encoding="utf-8"))
    cred = InteractiveBrowserCredential(
        tenant_id=os.environ.get("SQL_TENANT") or (registro.tenant_id if registro else None),
        cache_persistence_options=TokenCachePersistenceOptions(name="mapa_bajistas"),
        authentication_record=registro)
    if registro is None:
        registro = cred.authenticate(scopes=[ESCOPO])
        REGISTRO_SESION.parent.mkdir(parents=True, exist_ok=True)
        REGISTRO_SESION.write_text(registro.serialize(), encoding="utf-8")
    return cred


def conectar(servidor=None, base_datos=None, autocommit=True):
    import mssql_python

    servidor = servidor or os.environ["SQL_SERVIDOR"]
    base_datos = base_datos or os.environ.get("SQL_BASE_DATOS", "sqldb-mapa-bajistas")
    cadena = (f"Server=tcp:{servidor},1433;Database={base_datos};Encrypt=yes;"
              "TrustServerCertificate=no;")
    cred = credencial()
    for intento in range(1, INTENTOS + 1):
        try:
            return mssql_python.connect(cadena, autocommit=autocommit, token_provider=cred, timeout=60)
        except mssql_python.Error as e:
            texto = str(e)
            if intento == INTENTOS or not any(c in texto for c in CODIGOS_REINTENTO + ("timeout", "Timeout")):
                raise ErrorBD(f"No se puede conectar a {servidor}/{base_datos}: {texto}") from e
            logging.info("La base de datos se está reanudando (intento %s): %s", intento, texto[:200])
            time.sleep(ESPERA_S)


def lotes(texto):
    """Divide un script por las líneas GO, como hacen SSMS y sqlcmd."""
    return [l.strip() for l in SEPARADOR.split(texto) if l.strip()]


def ejecutar_script(conexion, ruta):
    """Ejecuta un script .sql lote a lote. Devuelve los resultados de las consultas (para las pruebas)."""
    resultados = []
    cur = conexion.cursor()
    for lote in lotes(Path(ruta).read_text(encoding="utf-8")):
        cur.execute(lote)
        while True:
            if cur.description:
                columnas = [c[0] for c in cur.description]
                resultados.append([dict(zip(columnas, fila)) for fila in cur.fetchall()])
            if not cur.nextset():
                break
    conexion.commit()
    return resultados


def main():
    import argparse
    import json

    p = argparse.ArgumentParser(description="Ejecuta scripts SQL en la base de datos de Azure")
    p.add_argument("scripts", nargs="+")
    p.add_argument("--servidor", default=os.environ.get("SQL_SERVIDOR", "sql-mapa-bajistas.database.windows.net"))
    p.add_argument("--base-datos", default=os.environ.get("SQL_BASE_DATOS", "sqldb-mapa-bajistas"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with conectar(args.servidor, args.base_datos) as conexion:
        for ruta in args.scripts:
            resultados = ejecutar_script(conexion, ruta)
            print(f"OK {ruta}")
            for tabla in resultados:
                print(json.dumps(tabla, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
