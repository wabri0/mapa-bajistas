"""Azure Functions: ingesta diaria del Excel de posiciones cortas de la CNMV.

La CNMV actualiza el fichero por la tarde-noche (p. ej. 2-nov-2026 a las 19:25 UTC),
así que se comprueba cada hora de 13:00 a 21:00 UTC de lunes a viernes y solo se
guarda cuando cambia el contenido. El horario se cambia con la variable CRON_INGESTA.

Cadena: bronze (Excel original) → silver (Parquet limpio) → gold (Azure SQL, con precios
de Yahoo). Cada paso solo se rehace si el anterior ha cambiado. La gold se carga si existe
la variable SQL_SERVIDOR.
"""
import json
import logging

import azure.functions as func

from src.ingesta.almacen import AlmacenBlob
from src.ingesta.ejecutar import ErrorIngesta, ingestar
from src.limpieza import silver
from src.modelo import bd as modelo_bd
from src.modelo import cargar as modelo_cargar

app = func.FunctionApp()
# El SDK de Azure registra cada cabecera HTTP a nivel INFO: ruido y coste en Application Insights
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


@app.timer_trigger(schedule="%CRON_INGESTA%", arg_name="temporizador", run_on_startup=False, use_monitor=True)
def ingesta_cnmv(temporizador: func.TimerRequest) -> None:
    bronze = AlmacenBlob.desde_entorno("bronze")
    silver_almacen = AlmacenBlob.desde_entorno("silver")
    try:
        resultado = ingestar(bronze)
        # La silver se rehace si no corresponde al último fichero de bronze o a las reglas actuales:
        # llega un fichero nuevo, aún no existe, la última construcción falló (se reintenta cada hora)
        # o se ha desplegado una versión nueva de las reglas de limpieza
        calidad_previa = json.loads(silver_almacen.leer_texto(f"{silver.PREFIJO}/calidad.json") or "{}")
        if (calidad_previa.get("origen_bronze"), calidad_previa.get("version_reglas")) != (
                resultado["ruta"], silver.VERSION_REGLAS):
            calidad = silver.ejecutar(bronze, silver_almacen)
            logging.info("SILVER_CNMV_OK %s", json.dumps(calidad, ensure_ascii=False, default=str))
            if calidad["grupos_por_revisar"]:
                # Aviso, no error: los datos se publican igual; falta decidir el grupo en grupos_gestores.csv
                logging.warning("INGESTA_CNMV_REVISAR Grupo gestor sin revisar: %s",
                                json.dumps(calidad["grupos_por_revisar"], ensure_ascii=False))
        # Gold: solo despierta la base de datos si tiene que cargar una silver nueva
        if modelo_bd.configurada():
            if estado_gold := modelo_cargar.ejecutar(silver_almacen):
                logging.info("GOLD_CARGA_OK %s", json.dumps(estado_gold["carga"], ensure_ascii=False, default=str))
    except ErrorIngesta as e:
        # El prefijo INGESTA_CNMV_FALLO es el que vigila la alerta de Application Insights
        logging.error("INGESTA_CNMV_FALLO %s: %s", type(e).__name__, e)
        raise
    if aviso := resultado.get("aviso"):
        logging.error("INGESTA_CNMV_FALLO Desactualizado: %s", aviso)
    logging.info("INGESTA_CNMV_OK %s", json.dumps(resultado, ensure_ascii=False))
