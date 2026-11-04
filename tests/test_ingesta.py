import json
from datetime import datetime, time, timedelta, timezone

import pytest

from src.ingesta import cnmv
from src.ingesta.almacen import AlmacenLocal
from src.ingesta.ejecutar import RUTA_ESTADO, ErrorFormato, ingestar
from tests.conftest import EXCEL, requiere_excel

pytestmark = requiere_excel


@pytest.fixture(scope="module")
def contenido():
    return EXCEL.read_bytes()


@pytest.fixture(scope="module")
def libro(contenido):
    return cnmv.abrir(contenido)


@pytest.fixture(scope="module")
def ahora(libro):
    """El día siguiente a la publicación, a las 15:00 UTC."""
    return datetime.combine(cnmv.fecha_publicacion(libro) + timedelta(days=1), time(15), timezone.utc)


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
    assert cnmv.fecha_publicacion(libro).year >= 2026


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


def test_primera_captura_guarda_y_la_segunda_no(tmp_path, contenido, libro, ahora):
    almacen = AlmacenLocal(tmp_path)
    r1 = ingestar(almacen, contenido=contenido, cabeceras={}, ahora=ahora)
    assert r1["estado"] == "nuevo"
    guardado = tmp_path / r1["ruta"]
    assert guardado.read_bytes() == contenido  # bronze: el fichero sin tocar
    assert f"fecha_publicacion={cnmv.fecha_publicacion(libro)}" in r1["ruta"]
    assert json.loads((tmp_path / RUTA_ESTADO).read_text())["hash_contenido"] == r1["hash_contenido"]

    r2 = ingestar(almacen, contenido=contenido, cabeceras={}, ahora=ahora.replace(hour=16))
    assert r2["estado"] == "sin_cambios"
    assert len(list(tmp_path.rglob("*.xls"))) == 1


def test_formato_invalido_se_guarda_en_rechazados_y_avisa(tmp_path, ahora):
    with pytest.raises(ErrorFormato):
        ingestar(AlmacenLocal(tmp_path), contenido=b"<html></html>", cabeceras={}, ahora=ahora)
    assert len(list((tmp_path / "cnmv/net_short_positions/rechazados").glob("*.xls"))) == 1
    assert not (tmp_path / RUTA_ESTADO).exists()


def test_avisa_si_la_cnmv_deja_de_publicar(tmp_path, contenido, libro, ahora):
    publicado = cnmv.fecha_publicacion(libro)
    dia_habil = publicado + timedelta(days=7)
    while dia_habil.weekday() >= 5:
        dia_habil += timedelta(days=1)
    tarde = datetime.combine(dia_habil, time(15), timezone.utc)
    r = ingestar(AlmacenLocal(tmp_path), contenido=contenido, cabeceras={}, ahora=tarde)
    assert "aviso" in r and r["dias_sin_publicar"] == (dia_habil - publicado).days
    assert "aviso" not in ingestar(AlmacenLocal(tmp_path / "b"), contenido=contenido, cabeceras={}, ahora=ahora)
