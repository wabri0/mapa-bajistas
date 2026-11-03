import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingesta import cnmv
from src.ingesta.almacen import AlmacenLocal
from src.ingesta.ejecutar import RUTA_ESTADO, ErrorFormato, ingestar

RAW = Path(__file__).parents[1] / "data" / "raw"
EXCEL = RAW / "NetShortPositions_2026-11-02.xls"
pytestmark = pytest.mark.skipif(not EXCEL.exists(), reason="falta el Excel de la CNMV en data/raw")

AHORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def contenido():
    return EXCEL.read_bytes()


@pytest.fixture(scope="module")
def libro(contenido):
    return cnmv.abrir(contenido)


class LibroFalso:
    """Envuelve un libro real y deja cambiar celdas para simular cambios de formato."""

    def __init__(self, libro, cambios=None, quitar_hoja=None):
        self.libro, self.cambios, self.quitar = libro, cambios or {}, quitar_hoja

    def sheet_names(self):
        return [n for n in self.libro.sheet_names() if n != self.quitar]

    def sheet_by_name(self, nombre):
        return HojaFalsa(self.libro.sheet_by_name(nombre), self.cambios.get(nombre, {}))


class HojaFalsa:
    def __init__(self, hoja, cambios):
        self.hoja, self.cambios, self.nrows = hoja, cambios, hoja.nrows

    def row_values(self, i):
        fila = list(self.hoja.row_values(i))
        for (f, c), v in self.cambios.items():
            if f == i:
                fila[c] = v
        return fila

    def cell_value(self, f, c):
        return self.row_values(f)[c]


def test_fichero_real_es_valido(libro):
    assert cnmv.validar(libro) == []
    assert cnmv.fecha_publicacion(libro).isoformat() == "2026-11-02"


def test_hash_de_contenido_ignora_metadatos(contenido, libro):
    # La copia abierta en Excel difiere en 16 bytes de la cabecera OLE, pero no en los datos
    copia = bytearray(contenido)
    copia[553:569] = bytes(16)
    assert cnmv.sha256(bytes(copia)) != cnmv.sha256(contenido)
    assert cnmv.hash_contenido(cnmv.abrir(bytes(copia))) == cnmv.hash_contenido(libro)


def test_detecta_fichero_que_no_es_excel():
    with pytest.raises(ErrorFormato, match="no es un Excel"):
        cnmv.abrir(b"<html>Mantenimiento</html>")


def test_detecta_hoja_que_falta(libro):
    problemas = cnmv.validar(LibroFalso(libro, quitar_hoja="Serie_-_Series"))
    assert any("Falta la hoja" in p for p in problemas)


def test_detecta_cabecera_cambiada(libro):
    falso = LibroFalso(libro, {"Anteriores_-_Previous": {(3, 5): "Net short (%)"}})
    assert any("cabecera distinta" in p for p in cnmv.validar(falso))


def test_detecta_porcentaje_y_fecha_invalidos(libro):
    falso = LibroFalso(libro, {"Última_-_Current": {(4, 5): "n/d", (5, 4): "04/08/2026"}})
    [problema] = cnmv.validar(falso)
    assert "2 filas" in problema


def test_primera_captura_guarda_y_la_segunda_no(tmp_path, contenido):
    almacen = AlmacenLocal(tmp_path)
    r1 = ingestar(almacen, contenido=contenido, cabeceras={}, ahora=AHORA)
    assert r1["estado"] == "nuevo"
    guardado = tmp_path / r1["ruta"]
    assert guardado.read_bytes() == contenido  # bronze: el fichero sin tocar
    assert "fecha_publicacion=2026-11-02" in r1["ruta"]
    assert json.loads((tmp_path / RUTA_ESTADO).read_text())["hash_contenido"] == r1["hash_contenido"]

    r2 = ingestar(almacen, contenido=contenido, cabeceras={}, ahora=AHORA.replace(hour=16))
    assert r2["estado"] == "sin_cambios"
    assert len(list(tmp_path.rglob("*.xls"))) == 1


def test_formato_invalido_se_guarda_en_rechazados_y_avisa(tmp_path):
    with pytest.raises(ErrorFormato):
        ingestar(AlmacenLocal(tmp_path), contenido=b"<html></html>", cabeceras={}, ahora=AHORA)
    assert len(list((tmp_path / "cnmv/net_short_positions/rechazados").glob("*.xls"))) == 1
    assert not (tmp_path / RUTA_ESTADO).exists()


def test_avisa_si_la_cnmv_deja_de_publicar(tmp_path, contenido):
    lunes_siguiente = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
    r = ingestar(AlmacenLocal(tmp_path), contenido=contenido, cabeceras={}, ahora=lunes_siguiente)
    assert "aviso" in r and r["dias_sin_publicar"] == 7
    assert "aviso" not in ingestar(AlmacenLocal(tmp_path / "b"), contenido=contenido, cabeceras={}, ahora=AHORA)
