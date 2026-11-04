"""Capa bronze: guarda ficheros sin modificar, en disco local o en Azure Blob Storage."""
import json
import os
from pathlib import Path


class AlmacenLocal:
    """Misma estructura de rutas que en Blob, bajo una carpeta local."""

    def __init__(self, raiz):
        self.raiz = Path(raiz)

    def leer_texto(self, ruta):
        p = self.raiz / ruta
        return p.read_text(encoding="utf-8") if p.exists() else None

    def leer_bytes(self, ruta):
        p = self.raiz / ruta
        return p.read_bytes() if p.exists() else None

    def escribir_texto(self, ruta, texto):
        p = self.raiz / ruta
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")

    def escribir_bytes(self, ruta, contenido, metadatos=None, sobrescribir=False):
        p = self.raiz / ruta
        if p.exists() and not sobrescribir:
            raise FileExistsError(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contenido)
        if metadatos:
            (p.parent / (p.name + ".meta.json")).write_text(json.dumps(metadatos, indent=2), encoding="utf-8")

    def describir(self, ruta):
        return str(self.raiz / ruta)


class AlmacenBlob:
    """Contenedor de Azure Blob Storage.

    Se configura con BRONZE_ACCOUNT_URL (identidad administrada, sin secretos) o,
    en su defecto, con BRONZE_CONNECTION_STRING. Los contenedores son BRONZE_CONTAINER
    y SILVER_CONTAINER (por defecto "bronze" y "silver").
    """

    def __init__(self, contenedor):
        self.contenedor = contenedor

    @classmethod
    def desde_entorno(cls, capa="bronze"):
        from azure.storage.blob import BlobServiceClient

        nombre = os.environ.get(f"{capa.upper()}_CONTAINER", capa)
        if url := os.environ.get("BRONZE_ACCOUNT_URL"):
            from azure.identity import DefaultAzureCredential

            servicio = BlobServiceClient(url, credential=DefaultAzureCredential())
        else:
            servicio = BlobServiceClient.from_connection_string(os.environ["BRONZE_CONNECTION_STRING"])
        contenedor = servicio.get_container_client(nombre)
        if not contenedor.exists():
            contenedor.create_container()
        return cls(contenedor)

    def leer_texto(self, ruta):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.contenedor.download_blob(ruta).readall().decode("utf-8")
        except ResourceNotFoundError:
            return None

    def leer_bytes(self, ruta):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.contenedor.download_blob(ruta).readall()
        except ResourceNotFoundError:
            return None

    def escribir_texto(self, ruta, texto):
        self.contenedor.upload_blob(ruta, texto.encode("utf-8"), overwrite=True)

    def escribir_bytes(self, ruta, contenido, metadatos=None, sobrescribir=False):
        # Los metadatos de Blob solo admiten ASCII: se guardan como texto plano
        meta = {k: str(v) for k, v in (metadatos or {}).items() if v is not None}
        self.contenedor.upload_blob(ruta, contenido, overwrite=sobrescribir, metadata=meta)

    def describir(self, ruta):
        return f"{self.contenedor.url}/{ruta}"
