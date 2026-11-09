# El mapa de los bajistas

Trabajo final (Track B, arquitectura técnica): plataforma en Azure que sigue a diario las posiciones cortas netas que publica la CNMV, las cruza con la cotización y avisa a cada cliente (cotizadas atendidas por una consultora de relación con inversores), con los datos de cada cliente aislados. Entrega: 10-ene-2027. El plan por fases está en [docs/planning.md](docs/planning.md); el usuario pide «procede con la fase N».

## Estado (actualizado el 9-nov-2026)

| Fase | Estado |
| --- | --- |
| 0 · Validación de datos | Hecha. El correo al profesor y las entrevistas de horas manuales quedan para más adelante: **no recordárselos** |
| 1 · Ingesta diaria (bronze) | Hecha y en producción |
| 2 · Limpieza (silver) | Hecha y en producción, verificada en Azure |
| 3 · Base de datos SQL, precios, clientes y RLS | **En curso** (ver «Fase 3: dónde estamos») |
| 4–7 | Pendientes (ver planning) |

## Fase 3: dónde estamos

- **Hecho:** tabla `src/modelo/tickers.csv` (80 emisores → código de Yahoo; 71 por búsqueda de ISIN, 9 a mano). Hay precios para 75; los 5 sin precio son históricos (Liberbank, Quabit, Axiare, NH/Minor Hotels, Ercros). Regla: priorizar siempre Madrid (`.MC`); para Ferrovial la búsqueda por ISIN devuelve el Nasdaq.
- **Diseño aprobado del modelo en estrella** (explicado para el usuario en la página https://claude.ai/artifact/7r2TrcDoE17AuUYroYqGrv):
  - Esquema `dw` (público): `dim_fecha` (calendario de bolsa a partir de los días con cotización de `^IBEX`), `dim_emisor`, `dim_fondo`, `fact_posicion_diaria` (sin festivos), `fact_precio_diario`, `fact_notificacion`.
  - Esquema `cliente` (confidencial, con RLS): `dim_cliente`, `cliente_emisor`, `alerta` (se llena en la fase 4), `nota`, `usuario_cliente` (usuario → cliente; la consultora tiene un rol que lo ve todo). Dos clientes ficticios para la demo.
- **Decisiones para Azure SQL:** oferta gratuita de Azure SQL Database (se pausa al agotarse, nunca cobra), France Central, **solo autenticación Microsoft Entra (sin contraseñas)** con el usuario como administrador, firewall con la IP del usuario más los servicios de Azure (en producción, red privada). Nombres previstos: servidor `sql-mapa-bajistas`, base `sqldb-mapa-bajistas`. Conector: **`mssql-python`** (trae su propio driver, también para Linux; carga masiva con `bulkcopy_arrow`).
- **Código hecho y desplegado (9-nov, commit 18610fa, 53 pruebas):** `src/modelo/precios.py` (yfinance, descarga completa en 6 s → `silver/yahoo/precios.parquet`; el dato del día solo tras las 17 UTC; si Yahoo falla, aviso `INGESTA_CNMV_REVISAR` y precios anteriores), `gold.py` (día de bolsa = IBEX o ≥ 10 acciones con volumen, porque a Yahoo le faltan el IBEX del 2-ene-2012 y 2-ene-2017 e inventa el 25-dic-2019; días futuros con regla de festivos, que coincide con los datos salvo 24 y 31-dic de 2010 y 2021, sin datos en Yahoo; quita 4.245 posiciones en 82 festivos), `bd.py` (identidad administrada en Azure; en local, navegador una vez y sesión guardada en `~/.mapa_bajistas`), `cargar.py` (stg → `dw.usp_cargar` en una transacción; estado en `silver/gold/estado.json` para no despertar la base cada hora). Scripts `sql/01`–`06` (esquema, carga, roles+RLS, clientes demo A/Grifols y B/Solaria, usuario de la Function, prueba RLS). La Function carga la gold solo si existe `SQL_SERVIDOR`.
- **Siguiente paso (bloqueado el 9-nov porque la extensión de Chrome no estaba conectada):** 1) crear el servidor y la base en el portal (el usuario pulsa «Crear»); 2) en local: `python -m src.modelo.bd sql/01_esquema.sql sql/02_carga.sql sql/03_seguridad.sql sql/05_usuario_function.sql`, luego `python -m src.modelo.cargar --forzar` (primera carga; comprobar que `bulkcopy_arrow` acepta los tipos), luego `sql/04_clientes_demo.sql` y `sql/06_prueba_rls.sql`; 3) en la Function: variables `SQL_SERVIDOR` y `SQL_BASE_DATOS`, y **memoria de instancia a 2048 MB** (pico local de 350 MB con silver + gold; el coste sigue dentro de la cuota gratuita); 4) comprobar `GOLD_CARGA_OK` en Application Insights; 5) sección 4.3 del informe, README y este fichero.

## Arquitectura (prototipo)

```
Timer (cada hora 13-21 UTC, L-V; CRON_INGESTA) → Azure Function func-mapa-bajistas (Python 3.14, Flex Consumption, 512 MB)
  ├─ src/ingesta  → stmapabajistas/bronze   (Excel original, sin tocar)
  └─ src/limpieza → stmapabajistas/silver   (Parquet: notificaciones, emisores, fondos, posiciones_intervalos, posiciones_diarias + calidad.json)
Fallos y avisos → Application Insights → alerta-ingesta-cnmv-fallo → correo personal (Gmail) del usuario
Despliegue: push a main → GitHub Actions (descarga el Excel actual, pruebas, empaquetado con .python_packages) → Azure
```

- Repositorio público: github.com/wabri0/mapa-bajistas. El workflow lo generó Azure y se corrigió para empaquetar las dependencias.
- Recursos en `rg-mapa-bajistas`, suscripción Azure for Students (100 US$ de crédito, cuenta de la universidad). **Solo se puede desplegar en** francecentral, switzerlandnorth, polandcentral, denmarkeast, austriaeast (política de la suscripción): se usa **France Central**. Los costes de producción se presupuestan en Spain Central o West Europe.
- Acceso a datos con identidad administrada (rol *Storage Blob Data Contributor* sobre `stmapabajistas`), sin secretos. Variables de la Function: `CRON_INGESTA`, `BRONZE_ACCOUNT_URL`, `BRONZE_CONTAINER`; el contenedor `silver` lo crea el propio código.
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
.venv/Scripts/python -m src.modelo.cargar --sin-bd # precios y tablas gold sin cargar en SQL
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
