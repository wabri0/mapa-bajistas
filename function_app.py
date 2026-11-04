"""Azure Functions: ingesta diaria del Excel de posiciones cortas de la CNMV.

La CNMV actualiza el fichero por la tarde-noche (p. ej. 2-nov-2026 a las 19:25 UTC),
así que se comprueba cada hora de 13:00 a 21:00 UTC de lunes a viernes y solo se
guarda cuando cambia el contenido. El horario se cambia con la variable CRON_INGESTA.
"""
import json
import logging

import azure.functions as func

from src.ingesta.almacen import AlmacenBlob
from src.ingesta.ejecutar import ErrorIngesta, ingestar
from src.limpieza import silver

app = func.FunctionApp()
# El SDK de Azure registra cada cabecera HTTP a nivel INFO: ruido y coste en Application Insights
logging.getLogger("azure").setLevel(logging.WARNING)


@app.timer_trigger(schedule="%CRON_INGESTA%", arg_name="temporizador", run_on_startup=False, use_monitor=True)
def ingesta_cnmv(temporizador: func.TimerRequest) -> None:
    bronze = AlmacenBlob.desde_entorno("bronze")
    silver_almacen = AlmacenBlob.desde_entorno("silver")
    try:
        resultado = ingestar(bronze)
        # La silver se rehace solo cuando llega un fichero nuevo (o si aún no existe)
        if resultado["estado"] == "nuevo" or silver_almacen.leer_texto(f"{silver.PREFIJO}/calidad.json") is None:
            calidad = silver.ejecutar(bronze, silver_almacen)
            logging.info("SILVER_CNMV_OK %s", json.dumps(calidad, ensure_ascii=False, default=str))
    except ErrorIngesta as e:
        # El prefijo INGESTA_CNMV_FALLO es el que vigila la alerta de Application Insights
        logging.error("INGESTA_CNMV_FALLO %s: %s", type(e).__name__, e)
        raise
    if aviso := resultado.get("aviso"):
        logging.error("INGESTA_CNMV_FALLO Desactualizado: %s", aviso)
    logging.info("INGESTA_CNMV_OK %s", json.dumps(resultado, ensure_ascii=False))
