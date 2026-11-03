"""Orquesta una ejecución de la ingesta: descargar, validar, comparar y guardar.

Uso local (guarda en data/raw con la misma estructura que en la nube):
    python -m src.ingesta.ejecutar
    python -m src.ingesta.ejecutar --fichero ruta/al/NetShortPositions.xls
"""
import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import cnmv
from .cnmv import ErrorFormato, ErrorIngesta  # noqa: F401  (se reexporta para function_app)

PREFIJO = "cnmv/net_short_positions"
RUTA_ESTADO = f"{PREFIJO}/_estado.json"
# Si en un día laborable el fichero lleva más días sin cambiar, se avisa
DIAS_MAX_SIN_PUBLICAR = 4

log = logging.getLogger("ingesta_cnmv")


def ingestar(almacen, contenido=None, cabeceras=None, ahora=None):
    """Ejecuta una captura. Devuelve un dict con el resultado; lanza ErrorIngesta si hay que avisar."""
    ahora = ahora or datetime.now(timezone.utc)
    if contenido is None:
        contenido, cabeceras = cnmv.descargar()
    cabeceras = cabeceras or {}
    captura = ahora.strftime("%Y%m%dT%H%M%SZ")

    sha = cnmv.sha256(contenido)
    try:
        libro = cnmv.abrir(contenido)
        problemas = cnmv.validar(libro)
    except ErrorFormato as e:
        libro, problemas = None, [str(e)]

    if problemas:
        # Se guarda igualmente para poder estudiar el cambio de formato
        ruta = f"{PREFIJO}/rechazados/NetShortPositions_captura{captura}.xls"
        almacen.escribir_bytes(ruta, contenido, {"sha256": sha, "problemas": " | ".join(problemas)[:2000]})
        raise ErrorFormato(f"Formato inesperado ({len(problemas)} problemas), guardado en {ruta}: {problemas}")

    huella = cnmv.hash_contenido(libro)
    publicado = cnmv.fecha_publicacion(libro)
    estado = json.loads(almacen.leer_texto(RUTA_ESTADO) or "{}")

    resultado = {
        "captura_utc": ahora.isoformat(timespec="seconds"),
        "fecha_publicacion": publicado.isoformat(),
        "sha256": sha,
        "hash_contenido": huella,
        "last_modified": cabeceras.get("Last-Modified") or cabeceras.get("last-modified"),
        "etag": cabeceras.get("ETag") or cabeceras.get("etag"),
        "bytes": len(contenido),
    }

    if estado.get("hash_contenido") == huella:
        resultado["estado"] = "sin_cambios"
        resultado["ruta"] = estado.get("ruta")
    else:
        ruta = f"{PREFIJO}/fecha_publicacion={publicado}/NetShortPositions_{publicado}_captura{captura}.xls"
        almacen.escribir_bytes(ruta, contenido, {**resultado, "url_origen": cnmv.URL})
        resultado["estado"] = "nuevo"
        resultado["ruta"] = ruta
        almacen.escribir_texto(RUTA_ESTADO, json.dumps(resultado, indent=2))

    dias = (ahora.date() - publicado).days
    resultado["dias_sin_publicar"] = dias
    if ahora.weekday() < 5 and dias > DIAS_MAX_SIN_PUBLICAR:
        resultado["aviso"] = f"La CNMV no publica un fichero nuevo desde hace {dias} días"
    return resultado


def main():
    from .almacen import AlmacenLocal

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--destino", default="data/raw", help="carpeta raíz de la capa bronze local")
    p.add_argument("--fichero", help="usar un fichero ya descargado en lugar de descargarlo")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    contenido = Path(args.fichero).read_bytes() if args.fichero else None
    try:
        r = ingestar(AlmacenLocal(args.destino), contenido=contenido, cabeceras={} if contenido else None)
    except ErrorIngesta as e:
        log.error("INGESTA_CNMV_FALLO %s: %s", type(e).__name__, e)
        raise SystemExit(1)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
