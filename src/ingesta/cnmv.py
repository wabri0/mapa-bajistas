"""Descarga, huella y validación del Excel de posiciones cortas netas de la CNMV."""
import hashlib
import time
from datetime import date

import requests
import xlrd

URL = "https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls"
USER_AGENT = "mapa-bajistas/1.0 (proyecto academico)"

HOJA_FECHA = "Fecha_-_Date"
HOJAS_DATOS = ["Última_-_Current", "Serie_-_Series", "Anteriores_-_Previous"]
FILA_CABECERA = 3
CABECERA = [
    "LEI",
    "ISIN",
    "Emisor / Issuer",
    "Tenedor de la Posición / Position holder",
    "Fecha posición / Position date",
    "Posición corta (%) / Net short position (%)",
]
# Cabecera de un fichero OLE2 (Excel 97-2003): si no empieza así, no es el Excel
FIRMA_OLE = bytes.fromhex("d0cf11e0a1b11ae1")


class ErrorIngesta(Exception):
    """Fallo que debe generar un aviso."""


class ErrorDescarga(ErrorIngesta):
    pass


class ErrorFormato(ErrorIngesta):
    pass


def descargar(sesion=None, intentos=3, espera=10, timeout=60):
    """Devuelve (contenido, cabeceras HTTP). Reintenta ante errores de red o 5xx."""
    sesion = sesion or requests.Session()
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            r = sesion.get(URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code == 200:
                return r.content, dict(r.headers)
            ultimo_error = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            ultimo_error = f"{type(e).__name__}: {e}"
        if intento < intentos:
            time.sleep(espera * intento)
    raise ErrorDescarga(f"No se pudo descargar {URL} tras {intento} intentos ({ultimo_error})")


def sha256(contenido):
    return hashlib.sha256(contenido).hexdigest()


def abrir(contenido):
    if not contenido.startswith(FIRMA_OLE):
        raise ErrorFormato(f"El fichero no es un Excel 97-2003 (empieza por {contenido[:16]!r})")
    try:
        return xlrd.open_workbook(file_contents=contenido)
    except Exception as e:
        raise ErrorFormato(f"xlrd no puede abrir el fichero: {e}") from e


def hash_contenido(libro):
    """Huella de los valores de todas las hojas, ignorando los metadatos del fichero.

    Dos descargas con los mismos datos dan la misma huella aunque cambien los bytes
    de la cabecera (por ejemplo, si el fichero se ha abierto y guardado en Excel).
    """
    h = hashlib.sha256()
    for hoja in sorted(libro.sheets(), key=lambda s: s.name):
        h.update(f"#{hoja.name}\n".encode())
        for i in range(hoja.nrows):
            h.update(("\x1f".join(repr(v) for v in hoja.row_values(i)) + "\n").encode())
    return h.hexdigest()


def fecha_publicacion(libro):
    hoja = libro.sheet_by_name(HOJA_FECHA)
    return date.fromisoformat(str(hoja.cell_value(3, 1)).strip())


def validar(libro):
    """Lista de problemas de formato; vacía si el fichero tiene la estructura esperada."""
    problemas = []
    nombres = libro.sheet_names()
    for hoja in [HOJA_FECHA, *HOJAS_DATOS]:
        if hoja not in nombres:
            problemas.append(f"Falta la hoja {hoja!r} (hojas: {nombres})")
    if problemas:
        return problemas

    try:
        fecha_publicacion(libro)
    except (ValueError, IndexError) as e:
        problemas.append(f"Fecha de publicación ilegible en {HOJA_FECHA!r}: {e}")

    for nombre in HOJAS_DATOS:
        hoja = libro.sheet_by_name(nombre)
        if hoja.nrows <= FILA_CABECERA:
            problemas.append(f"{nombre}: sin cabecera ({hoja.nrows} filas)")
            continue
        cabecera = [str(v).strip() for v in hoja.row_values(FILA_CABECERA)]
        if cabecera != CABECERA:
            problemas.append(f"{nombre}: cabecera distinta: {cabecera}")
            continue
        malas = []
        for i in range(FILA_CABECERA + 1, hoja.nrows):
            fila = hoja.row_values(i)
            try:
                date.fromisoformat(str(fila[4]).strip())
                if not 0 <= float(fila[5]) <= 100:
                    raise ValueError("porcentaje fuera de rango")
            except (ValueError, TypeError) as e:
                malas.append(f"fila {i + 1}: {e}")
        if malas:
            problemas.append(f"{nombre}: {len(malas)} filas con fecha o % inválidos, p. ej. {malas[:3]}")

    if libro.sheet_by_name("Serie_-_Series").nrows <= FILA_CABECERA + 1:
        problemas.append("Serie_-_Series no tiene datos")
    return problemas
