# El mapa de los bajistas

Trabajo final (Track B, arquitectura técnica): plataforma en Azure que sigue a diario las posiciones cortas netas que publica la CNMV, las cruza con la cotización y avisa a cada cliente (cotizadas atendidas por una consultora de relación con inversores), con los datos de cada cliente aislados. Entrega: 10-ene-2027. El plan por fases está en [docs/planning.md](docs/planning.md); el usuario pide «procede con la fase N».

## Estado

| Fase | Estado |
| --- | --- |
| 0 · Validación de datos | Hecha (falta, a propósito, el correo al profesor y las entrevistas: no recordarlos) |
| 1 · Ingesta diaria (bronze) | Hecha y en producción |
| 2 · Limpieza (silver) | Hecha y en producción |
| 3 · Base de datos SQL, precios, clientes y RLS | En curso: tickers resueltos en `src/modelo/tickers.csv` |

## Arquitectura (prototipo)

```
Timer (cada hora 13-21 UTC, L-V; CRON_INGESTA) → Azure Function func-mapa-bajistas (Python 3.14, Flex Consumption)
  ├─ src/ingesta  → stmapabajistas/bronze   (Excel original, sin tocar)
  └─ src/limpieza → stmapabajistas/silver   (Parquet: notificaciones, emisores, fondos, intervalos, posiciones diarias)
Fallos y avisos → Application Insights → alerta-ingesta-cnmv-fallo → correo
Despliegue: push a main → GitHub Actions (pruebas + empaquetado) → Azure
```

- Recursos en `rg-mapa-bajistas`, suscripción Azure for Students. **Solo se puede desplegar en** francecentral, switzerlandnorth, polandcentral, denmarkeast, austriaeast (política de la suscripción): se usa **France Central**. Los costes de producción se presupuestan en Spain Central o West Europe.
- Acceso a datos con identidad administrada, sin secretos. Presupuesto con alerta en 1 US$/mes.

## Reglas de datos (no cambiar sin justificar con datos)

- Agrupar por **LEI** (emisor), nunca por ISIN: los ISIN cambian tras operaciones corporativas.
- Cada aviso vale hasta el siguiente; < 0,5 % = cerrada. **Caducidad de 365 días** para posiciones no vigentes sin aviso (la CNMV no publica la mayoría de los cierres).
- La hoja de vigentes de la CNMV muestra un día las posiciones que acaban de bajar del 0,5 %: no cuentan en el cuadre.
- `src/limpieza/grupos_gestores.csv` es una tabla revisada a mano. Ante la duda, no unir entidades.
- Si cambian las reglas de limpieza, subir `VERSION_REGLAS` en `src/limpieza/silver.py` (fuerza la reconstrucción en Azure).
- Toda cifra del informe sale de los datos y se recalcula si cambian las reglas («el dato manda»).

## Comandos

```
.venv/Scripts/python -m src.ingesta.ejecutar    # descarga el Excel a data/raw/cnmv/...
.venv/Scripts/python -m src.limpieza.silver     # construye data/silver/cnmv/
.venv/Scripts/python -m pytest -q               # pruebas (las de datos reales usan el Excel más reciente de data/raw)
```

## Convenciones

- Código, comentarios, commits y documentación en **español**; identificadores en español (`ingestar`, `posiciones_diarias`).
- **Commits sin ninguna firma de Claude** (ni `Co-Authored-By` ni pie). Commits y push a `main` forman parte del flujo habitual.
- En el portal de Azure: Claude rellena los formularios y **el usuario pulsa «Crear»** en los recursos nuevos. Las asignaciones de roles IAM las hace el usuario.
- Cada fase cierra con su parte del informe en `docs/informe/` (borradores por sección).
- El usuario está aprendiendo Azure: explicar en lenguaje llano y con ejemplos reales.
