# El mapa de los bajistas

Plataforma en la nube que descarga cada día las posiciones cortas netas que publica la CNMV (≥ 0,5 % del capital) sobre las cotizadas españolas y las cruza con su cotización, las operaciones de directivos y las participaciones significativas. Cada cliente tiene sus alertas y sus datos aislados.

Proyecto final · Track B (Arquitectura técnica) · Entrega: 10-ene-2027. Planning completo en [docs/planning.md](docs/planning.md).

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `data/raw/` | Ficheros originales de la CNMV (bronze). No se versionan |
| `data/processed/` | Datos limpios (silver) en local. No se versionan |
| `scripts/` | Análisis puntuales, como la validación de la fase 0 |
| `src/ingesta/` | Descarga y hash del Excel (fase 1) |
| `src/limpieza/` | Limpieza y serie diaria (fase 2) |
| `src/modelo/` | Modelo en estrella y carga en SQL (fase 3) |
| `src/alertas/` | Indicadores y reglas de alerta (fase 4) |
| `functions/` | Azure Functions |
| `sql/` | Esquema, RLS y consultas |
| `powerbi/` | Panel de Power BI (fase 5) |
| `tests/` | Pruebas y controles de calidad |
| `docs/informe/` | Secciones del informe, escritas al cerrar cada fase |
| `docs/fase0/` | Hallazgos sobre los datos y tareas pendientes |
| `docs/fuentes/` | Copias de las fuentes legales consultadas |

## Cómo empezar

```
pip install -r requirements.txt
curl -o data/raw/NetShortPositions_$(date +%F).xls https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls
python scripts/fase0_explorar.py data/raw/NetShortPositions_<fecha>.xls
```

## Fuente de los datos

Comisión Nacional del Mercado de Valores (CNMV), posiciones cortas netas. La información puede obtenerse de forma gratuita en www.cnmv.es. Los indicadores de este proyecto son cálculos propios a partir de esos datos.
