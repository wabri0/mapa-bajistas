# El mapa de los bajistas

Trabajo final (Track B, arquitectura técnica): plataforma en Azure que sigue a diario las posiciones cortas netas que publica la CNMV, las cruza con la cotización y avisa a cada cliente (cotizadas atendidas por una consultora de relación con inversores), con los datos de cada cliente aislados. Entrega: 10-ene-2027. El plan por fases está en [docs/planning.md](docs/planning.md); el usuario pide «procede con la fase N».

## Estado (actualizado el 9-nov-2026)

| Fase | Estado |
| --- | --- |
| 0 · Validación de datos | Hecha. El correo al profesor y las entrevistas de horas manuales quedan para más adelante: **no recordárselos** |
| 1 · Ingesta diaria (bronze) | Hecha y en producción |
| 2 · Limpieza (silver) | Hecha y en producción, verificada en Azure |
| 3 · Base de datos SQL, precios, clientes y RLS | Hecha y en producción (9-nov): la Function carga Azure SQL sola |
| 4–7 | Pendientes (ver planning) |

## Fase 3: resumen (hecha)

- **Azure SQL** (oferta gratuita, cobro por exceso desactivado, France Central): servidor `sql-mapa-bajistas`, base `sqldb-mapa-bajistas`, solo Entra (admin `ggomeama@myuax.com`), firewall con servicios de Azure e IP 81.43.33.72 (si cambia la IP del usuario, hay que añadirla en el portal). Usuario `[func-mapa-bajistas]` con `rol_carga`. Function con `SQL_SERVIDOR`, `SQL_BASE_DATOS` y **2048 MB**.
- **Código:** `src/modelo/precios.py` (yfinance, descarga completa en 6 s → `silver/yahoo/precios.parquet`; dato del día solo tras las 17 UTC; si Yahoo falla, aviso `INGESTA_CNMV_REVISAR` y precios anteriores), `gold.py` (día de bolsa = IBEX o ≥ 10 acciones con volumen; futuros con regla de festivos), `bd.py` (identidad administrada en Azure; en local, navegador una vez y sesión en `~/.mapa_bajistas`), `cargar.py` (stg → `dw.usp_cargar` en una transacción; estado en `silver/gold/estado.json` para no despertar la base cada hora). Scripts `sql/01`–`06`. Subir `VERSION_MODELO` en `gold.py` si cambia el modelo (fuerza la recarga).
- **Verificado:** primera carga local en 25 s (215.680 posiciones, 279.625 precios, 12.370 notificaciones); carga automática de la Function el 9-nov a las 19:00 UTC (`dw.carga` id 2, fichero del 6-nov). RLS probada con `demo_cliente_a` (Grifols), `demo_cliente_b` (Solaria) y `demo_consultora`. Cifras de Grifols y Solaria iguales desde SQL. Sección del informe: `docs/informe/04_arquitectura.md` §4.2.
- **Siguiente:** fase 4 (indicadores y alertas en `cliente.alerta`).

## Arquitectura (prototipo)

```
Timer (cada hora 13-21 UTC, L-V; CRON_INGESTA) → Azure Function func-mapa-bajistas (Python 3.14, Flex Consumption, 2048 MB)
  ├─ src/ingesta  → stmapabajistas/bronze   (Excel original, sin tocar)
  ├─ src/limpieza → stmapabajistas/silver   (Parquet: notificaciones, emisores, fondos, posiciones_intervalos, posiciones_diarias + calidad.json)
  └─ src/modelo   → silver/yahoo (precios) → Azure SQL sqldb-mapa-bajistas (esquemas dw, cliente con RLS, stg) — solo si hay silver nueva
Fallos y avisos → Application Insights → alerta-ingesta-cnmv-fallo → correo personal (Gmail) del usuario
Despliegue: push a main → GitHub Actions (descarga el Excel actual, pruebas, empaquetado con .python_packages) → Azure
```

- Repositorio público: github.com/wabri0/mapa-bajistas. El workflow lo generó Azure y se corrigió para empaquetar las dependencias.
- Recursos en `rg-mapa-bajistas`, suscripción Azure for Students (100 US$ de crédito, cuenta de la universidad). **Solo se puede desplegar en** francecentral, switzerlandnorth, polandcentral, denmarkeast, austriaeast (política de la suscripción): se usa **France Central**. Los costes de producción se presupuestan en Spain Central o West Europe.
- Acceso a datos con identidad administrada (rol *Storage Blob Data Contributor* sobre `stmapabajistas` y `rol_carga` en SQL), sin secretos. Variables de la Function: `CRON_INGESTA`, `BRONZE_ACCOUNT_URL`, `BRONZE_CONTAINER`, `SQL_SERVIDOR`, `SQL_BASE_DATOS`; el contenedor `silver` lo crea el propio código.
- Presupuesto `presupuesto-1` con alertas de coste. La alerta por correo cuesta 0,50 US$/mes y vigila `INGESTA_CNMV_FALLO`, `INGESTA_CNMV_REVISAR` y las ejecuciones fallidas; avisa al empezar y al resolverse.
- La CNMV publica el fichero hacia las 19:20 UTC. El ETag de su servidor no es estable: se detectan cambios con el hash del contenido.

## Reglas de datos (no cambiar sin justificar con datos)

- Agrupar por **LEI** (emisor), nunca por ISIN: los ISIN cambian tras operaciones corporativas. Con LEI, la reconstrucción cuadra al 100 % con la hoja de vigentes.
- Cada aviso vale hasta el siguiente; < 0,5 % = cerrada. **Caducidad de 365 días** para posiciones no vigentes sin aviso: la CNMV no publica la mayoría de los cierres (solo 774 en todo el fichero).
- La hoja de vigentes de la CNMV muestra un día las posiciones que acaban de bajar del 0,5 %: no cuentan en el cuadre.
- `src/limpieza/grupos_gestores.csv` es una tabla revisada a mano. Ante la duda, no unir entidades. Una entidad está revisada si figura en la tabla (si es independiente, con su propio nombre como grupo); las nuevas que se parecen a una casa conocida generan el aviso `INGESTA_CNMV_REVISAR`, que no bloquea nada.
- Si cambian las reglas de limpieza, subir `VERSION_REGLAS` en `src/limpieza/silver.py` (fuerza la reconstrucción en Azure).
- Toda cifra del informe sale de los datos y se recalcula si cambian las reglas («el dato manda»). Cifras vigentes del caso Grifols: media de 1,59 % antes del informe de Gotham (9-ene-2024) y máximo de **3,88 % con 5 fondos el 14-mar-2024**; ya no 4,38 %. No hubo escalada previa: se cuenta como respuesta a la crisis. Solaria: máximo de 16,06 % (19-dic-2024) y 18 fondos.
- La nota legal de la CNMV obliga a avisar a los clientes de pago de que el dato es gratuito en cnmv.es (ver `docs/informe/03_datos.md`).

## Comandos

```
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt yfinance mssql-python
.venv/Scripts/python -m src.ingesta.ejecutar    # descarga el Excel a data/raw/cnmv/...
.venv/Scripts/python -m src.limpieza.silver     # construye data/silver/cnmv/
.venv/Scripts/python -m src.modelo.cargar --sin-bd # precios y tablas gold sin cargar en SQL (--forzar: carga en Azure SQL)
.venv/Scripts/python -m src.modelo.bd sql/06_prueba_rls.sql  # ejecuta scripts en Azure SQL (abre el navegador la primera vez)
.venv/Scripts/python -m pytest -q               # 53 pruebas (las de datos reales usan el Excel más reciente de data/raw)
```

Si la carpeta del proyecto cambia de sitio, el `.venv` deja de funcionar: hay que borrarlo y volver a crearlo con la primera línea.

## Documentos fuera del repositorio

- Guion de la presentación al profesor (Claude Docs): https://claude.ai/artifact/UFwpR1gnriUSe7D91ueE55. El usuario prefiere un tono cercano y natural, sin explicar conceptos básicos de finanzas como si el profesor no los supiera.
- Esquema visual del modelo de datos: https://claude.ai/artifact/7r2TrcDoE17AuUYroYqGrv

## Convenciones

- Código, comentarios, commits y documentación en **español**; identificadores en español (`ingestar`, `posiciones_diarias`).
- **Commits sin ninguna firma de Claude** (ni `Co-Authored-By` ni pie de «Generated with Claude Code»). Commits y push a `main` forman parte del flujo habitual.
- En el portal de Azure: Claude rellena los formularios (con la extensión de Chrome) y **el usuario pulsa «Crear»** en los recursos nuevos. Las asignaciones de roles IAM las hace el usuario (el sistema de permisos no deja hacerlas a Claude).
- Cada fase cierra con su parte del informe en `docs/informe/` (borradores por sección).
- El usuario está aprendiendo Azure: explicar en lenguaje llano, con ejemplos reales y, cuando ayude, con esquemas visuales (no ASCII).
