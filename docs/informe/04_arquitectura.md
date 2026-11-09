# 4. Arquitectura propuesta

> Borrador por fases. Fase 1 (ingesta y capa bronze) escrita el 3-nov-2026; fases 3 (base de datos gold) y 4 (indicadores y alertas) el 9-nov-2026. La limpieza de la fase 2 está en la sección 3.2; la fase 5 añadirá su apartado.

## 4.1 Ingesta diaria y capa bronze (fase 1)

**Qué hace.** Una Azure Function con temporizador descarga el Excel de posiciones cortas de la CNMV, comprueba que tiene el formato esperado y, si el contenido ha cambiado, guarda el fichero original sin modificar en Blob Storage. Si algo falla, deja un error que dispara un aviso.

| Componente | Recurso del prototipo | Por qué |
| --- | --- | --- |
| Cómputo | Azure Functions, plan **Consumo flexible** (Linux, Python 3.14, 512 MB) | Sin servidor y escala a cero: solo se paga cuando se ejecuta. El uso previsto (unas 200 ejecuciones de pocos segundos al mes) cabe en la cuota gratuita |
| Capa bronze | Cuenta de almacenamiento `stmapabajistas` (Standard LRS, Data Lake Gen2), contenedor privado `bronze` | Almacenamiento barato e inmutable de los ficheros originales, que permite reprocesar desde cero |
| Acceso a datos | **Identidad administrada** de la Function, con el rol *Storage Blob Data Contributor* limitado a esa cuenta | Sin contraseñas ni claves en el código ni en la configuración |
| Monitorización | Application Insights | Registro de cada ejecución y base de las alertas |
| Despliegue | GitHub Actions con identidad federada (OIDC): pruebas → empaquetado → despliegue en cada *push* a `main` | Despliegue repetible, sin secretos de larga duración |
| Región | **France Central** | La suscripción Azure for Students solo permite cinco regiones europeas, y ni West Europe ni Spain Central están entre ellas. En producción se presupuesta Spain Central o West Europe |

**Horario.** El planning preveía una descarga a las 16:15, pero al comprobarlo se vio que la CNMV actualizó el fichero del 2-nov-2026 a las **19:25 UTC (20:25 en Madrid)**. Por eso la Function comprueba el fichero **cada hora de 13:00 a 21:00 UTC, de lunes a viernes** (`CRON_INGESTA = 0 0 13-21 * * 1-5`) y solo guarda una copia cuando el contenido cambia. Cuesta prácticamente lo mismo que una ejecución diaria y no depende de la hora a la que publique la CNMV. Las cabeceras `Last-Modified` registradas cada día permitirán ajustar el horario.

**Detección de cambios.** Se calculan dos huellas:
- **SHA-256 del fichero**: identifica exactamente lo que se descargó.
- **Hash del contenido**: se calcula sobre los valores de todas las hojas. En la fase 0 se comprobó que una copia del mismo Excel abierta en Excel tenía 16 bytes distintos en la cabecera y los mismos datos. Comparar solo el SHA-256 habría dado un falso «fichero nuevo».

La cabecera `ETag` de la CNMV **no sirve** para detectar cambios. Dos descargas del mismo fichero, con el mismo `Last-Modified` y los mismos bytes, devolvieron ETag distintos (`be80dee3…` y `d3d6fce3…`), probablemente porque los sirven servidores distintos. Se guarda solo como dato de auditoría.

**Prueba en la nube (3-nov-2026, 10:26 UTC).**
- Primera ejecución manual: estado `nuevo`, 6,7 s. Las huellas son idénticas a las de la ejecución local (SHA-256 `942cd305…`, contenido `67cc238c…`).
- Segunda ejecución: estado `sin_cambios`, 1,9 s, sin duplicar el fichero.

**Organización de la capa bronze.**
```
bronze/cnmv/net_short_positions/
  fecha_publicacion=2026-11-02/NetShortPositions_2026-11-02_captura20261103T093711Z.xls
  _estado.json          ← última captura (huellas, fecha, ETag)
  rechazados/           ← ficheros con formato inesperado, para analizarlos
```
Cada fichero lleva como metadatos sus huellas, la fecha de publicación, las cabeceras HTTP y la URL de origen. Si la CNMV corrige un fichero ya publicado, se guarda una captura nueva con otra hora en el nombre, y la original se conserva.

**Carga del histórico.** No hace falta una carga aparte: cada Excel de la CNMV ya contiene el historial completo desde junio de 2010 (12.360 notificaciones únicas). La primera captura es la carga histórica.

**Avisos.** La Function registra `INGESTA_CNMV_FALLO` y termina con error en estos casos:
- La descarga falla tras 3 intentos.
- El fichero no es un Excel 97-2003, por ejemplo porque se recibe una página HTML de mantenimiento.
- Falta alguna hoja o cambia la cabecera.
- Hay fechas o porcentajes que no se pueden leer.
- En un día laborable, el fichero lleva más de 4 días sin publicarse.

La regla de alerta `alerta-ingesta-cnmv-fallo` de Application Insights vigila ese texto, el aviso `INGESTA_CNMV_REVISAR` (entidad nueva cuyo grupo gestor hay que decidir; ver sección 3.2) y cualquier ejecución fallida. Se evalúa cada hora y envía un correo al grupo de acciones `ag-mapa-bajistas-correo`. Avisa una vez cuando empieza el problema y otra cuando se resuelve. Coste: 0,50 US$ al mes.

**Calidad.** 9 pruebas automáticas cubren:
- El fichero real es válido.
- El hash de contenido ignora los metadatos.
- Se detectan los cambios de formato: hoja que falta, cabecera distinta, fecha o porcentaje ilegible y fichero HTML.
- No se guardan duplicados.
- Los ficheros rechazados se apartan.
- Se avisa cuando el fichero está desactualizado.

## 4.2 Base de datos gold, precios y aislamiento de clientes (fase 3)

**Qué hace.** Cuando la capa silver cambia, la misma Function descarga los precios de Yahoo Finance, prepara las tablas del modelo en estrella y las carga en una base de datos Azure SQL. En esa base conviven los datos públicos, iguales para todos, y los datos confidenciales de cada cliente, separados por seguridad a nivel de fila (RLS).

| Componente | Recurso del prototipo | Por qué |
| --- | --- | --- |
| Base de datos | **Azure SQL Database, oferta gratuita** (`sql-mapa-bajistas` / `sqldb-mapa-bajistas`): uso general sin servidor, hasta 2 vCores, 32 GB | Gratis de por vida: 100.000 segundos de vCore y 32 GB al mes. Al llegar al límite se pausa hasta el mes siguiente; el cobro por exceso está desactivado |
| Acceso | **Solo Microsoft Entra ID**, sin usuarios con contraseña. La Function entra con su identidad administrada y el rol `rol_carga` | No hay ninguna contraseña que guardar ni que pueda filtrarse |
| Red | Punto de conexión público con firewall: servicios de Azure y la IP del desarrollador. TLS 1.2 como mínimo | Suficiente para el prototipo. En producción, punto de conexión privado dentro de una red virtual |
| Conector | `mssql-python` (Microsoft), con carga masiva desde Arrow | Funciona con Python 3.14, trae su propio driver para Linux y carga 280.000 filas en segundos |
| Precios | `yfinance`, descarga completa cada día (76 valores e IBEX desde 2010, unos 6 s) → `silver/yahoo/precios.parquet` | Rehacerla entera mantiene al día el cierre ajustado tras dividendos y ampliaciones. Solo para uso académico (ver sección 3.3) |
| Memoria de la Function | 2.048 MB (antes 512 MB) | La reconstrucción de silver y gold llega a unos 350 MB en local, más lo que usa el propio host de Azure. El consumo sigue muy por debajo de la cuota gratuita del plan |

**Modelo en estrella.**

| Esquema | Tabla | Contenido | Filas (fichero de la CNMV del 3-nov-2026) |
| --- | --- | --- | --- |
| `dw` (público) | `dim_fecha` | Calendario de 2010 a fin del año en curso, con los días de bolsa | 6.209 (4.349 de bolsa) |
| | `dim_emisor` | Empresas por LEI, con sus ISIN y su código de Yahoo | 80 |
| | `dim_fondo` | Entidades tenedoras y su grupo gestor | 229 |
| | `fact_posicion_diaria` | % corto de cada fondo en cada empresa, cada día de bolsa | 215.680 |
| | `fact_precio_diario` | Cierre, cierre ajustado y volumen | 279.625 |
| | `fact_notificacion` | Cada aviso publicado, con la fecha en que se capturó | 12.370 |
| `cliente` (confidencial) | `dim_cliente`, `cliente_emisor` | Clientes y empresas que sigue cada uno (la propia y sus competidoras) | 2 y 8 (demo) |
| | `alerta`, `nota` | Avisos generados (fase 4) y comentarios internos | 0 y 3 (demo) |
| | `usuario_cliente` | Qué usuario pertenece a qué cliente | 2 (demo) |

Los identificadores (`emisor_id`, `fondo_id`) los asigna la base de datos y no cambian entre cargas, porque las tablas de clientes los usan. Las dimensiones se actualizan con `MERGE` por su clave natural (LEI y nombre del fondo). Los hechos se sustituyen enteros en cada carga: la silver se reconstruye completa y una regla nueva puede cambiar el pasado («el dato manda»).

**Calendario de bolsa.** La silver reparte cada posición por días laborables. Aquí se quitan los festivos de bolsa: 4.245 filas en 82 días, como Navidad, Viernes Santo o el 1 de mayo. Yahoo no sirve tal cual como calendario:
- Le faltan días del IBEX en que sí hubo bolsa (2-ene-2012 y 2-ene-2017, con más de 50 acciones negociadas).
- Repite el 24-dic-2019 como 25-dic-2019, con volumen cero.

Por eso un día cuenta como de bolsa si cotizó el IBEX o **al menos 10 acciones con volumen**. Los días posteriores al último dato se marcan con la regla de festivos de la Bolsa de Madrid (1-ene, Viernes Santo, Lunes de Pascua, 1-may, 25 y 26-dic). Esa regla coincide con lo observado en todos los días desde 2010 salvo cuatro: el 24 y el 31 de diciembre de 2010 y de 2021, en los que Yahoo no tiene datos de ningún valor. El precio del día solo se guarda después del cierre (17:00 UTC), para no cargar un precio a mitad de sesión.

**Carga diaria.**
1. La Function vacía las tablas de paso (`stg`) y copia en ellas las tablas gold con carga masiva.
2. Ejecuta `dw.usp_cargar`, que en **una sola transacción** actualiza las dimensiones, sustituye los hechos y comprueba que ningún cruce ha perdido filas. Si algo no cuadra, se deshace todo y la base queda como estaba.
3. Cada carga queda registrada en `dw.carga`: fichero de la CNMV de origen, versión de las reglas y filas cargadas.

La primera carga, lanzada en local, tardó 25 s. La primera carga automática de la Function llegó el 9-nov-2026 a las 19:00 UTC, con el fichero del 6-nov (216.111 posiciones). Los procedimientos usan `EXECUTE AS OWNER`, así que la identidad de la Function solo puede ejecutarlos y escribir en `stg`: no puede borrar ni modificar directamente las tablas de `dw`.

**Uso de la oferta gratuita.** La base de datos se pausa sola cuando nadie la usa. Para no despertarla cada hora, la Function guarda en `silver/gold/estado.json` qué silver hay cargada, y solo se conecta cuando llega un fichero nuevo de la CNMV, cambian las reglas de limpieza o cambia el modelo. Estimación: una carga al día de menos de un minuto, más el tiempo hasta la pausa automática, unos 40.000 segundos de vCore al mes de los 100.000 gratuitos, con margen para las consultas del panel.

**Aislamiento de clientes (RLS).** Una función de seguridad (`seguridad.fn_cliente_visible`) deja ver una fila de `cliente` solo si el usuario es de la consultora, de la carga o administrador, o si figura en `usuario_cliente` con el cliente de esa fila. La política aplica dos tipos de regla:
- **Filtro:** al leer, cada usuario ve solo sus filas.
- **Bloqueo:** nadie puede crear o mover una alerta o nota a otro cliente.

Los clientes ni siquiera tienen permiso para leer `usuario_cliente`. Prueba con dos clientes ficticios (`sql/06_prueba_rls.sql`):

| Usuario | Clientes | Empresas seguidas | Notas | Notas de otros | Posiciones públicas |
| --- | --- | --- | --- | --- | --- |
| `demo_cliente_a` (sigue a Grifols) | 1 | 4 | 2 | 0 | 215.680 |
| `demo_cliente_b` (sigue a Solaria) | 1 | 4 | 1 | 0 | 215.680 |
| `demo_consultora` | 2 | 8 | 3 | — | 215.680 |

Cuando el cliente A intenta escribir una nota a nombre del cliente B, la base lo rechaza (*block predicate*). Al intentar leer la tabla de usuarios, recibe un error de permiso. En producción, cada persona entraría con su cuenta de Entra ID. El panel de Power BI de la fase 5 repetirá la misma separación con sus propios roles.

**Comprobación de cifras.** Las cifras del caso Grifols salen iguales consultando la base de datos:
- 1,59 % de media entre septiembre y diciembre de 2023, con 3 fondos de media.
- Máximo de 3,88 % con 5 fondos el 14-mar-2024.

Solaria también cuadra: 16,06 % con 18 fondos el 19-dic-2024.

**Calidad.** 26 pruebas nuevas, 53 en total:
- Calendario: Pascua, festivos, días que faltan e inventados, y días futuros.
- Festivos e índice fuera de los hechos.
- Tipos y columnas idénticos entre Python y las tablas `stg`.
- Precio del día solo tras el cierre.
- Uso de los precios anteriores si Yahoo falla (con aviso `INGESTA_CNMV_REVISAR`).
- No se recarga la base si la silver no ha cambiado.
- Los scripts SQL se pueden ejecutar varias veces.

Los errores de carga se registran como `INGESTA_CNMV_FALLO`, así que la alerta por correo existente también los cubre.

## 4.3 Indicadores y alertas por cliente (fase 4)

**Qué hace.** En cada carga, la Function calcula seis indicadores diarios por empresa. Después evalúa las reglas que cada cliente tiene guardadas en la base de datos y registra sus alertas en `cliente.alerta`. Esa tabla está protegida con la misma seguridad por filas que el resto de datos de clientes.

**Indicadores** (`dw.fact_indicador_diario`, 93.372 filas con el fichero de la CNMV del 6-nov-2026). Hay una fila por empresa y día de bolsa con posiciones, más las 20 sesiones siguientes para registrar la salida. Las variaciones se cuentan en sesiones de bolsa, no en días naturales.

| Indicador | Cálculo | Para qué sirve |
| --- | --- | --- |
| Suma de posiciones cortas | Suma de los % publicados ese día | Presión bajista total |
| Número de bajistas | Fondos con posición ≥ 0,5 % | Si el ataque es de uno o de muchos |
| Fondos nuevos y salidas | Un fondo es nuevo si no tenía posición en las 20 sesiones anteriores. Así no cuenta como entrada el que baja un día del 0,5 % y vuelve | Detectar la llegada de un bajista |
| Variación a 5 y 20 sesiones | Suma de hoy menos la de hace 5 o 20 sesiones, en puntos | Velocidad del ataque |
| Concentración | Peso del mayor fondo en la suma (%) | Si depende de un solo fondo |
| Días para cubrir | Acciones en corto (suma × acciones en circulación) / volumen medio de 20 sesiones | Cuánto tardarían los bajistas en recomprar: riesgo de subida brusca si se ven obligados |

El cálculo tarda menos de un segundo para todo el histórico.

**Limitaciones de «días para cubrir».**
- Usa las acciones en circulación **actuales**. El histórico de Yahoo no es fiable: tiene saltos de mil veces, como Duro Felguera con 58.000 millones de acciones durante dos años. En fechas antiguas de empresas que cambiaron su capital, el dato es aproximado. Para las alertas, que miran los últimos días, sí es fiable.
- El volumen es solo el de la Bolsa de Madrid. No incluye otras plataformas (Cboe, Turquoise), así que la liquidez real es mayor y los días reales para cubrir, menos.

**Reglas por cliente** (`cliente.regla_alerta`). Hay seis tipos: fondo nuevo, la suma supera un %, la suma sube X puntos en 5 o en 20 sesiones, el número de fondos supera N y los días para cubrir superan N. Cada regla se aplica a la empresa propia del cliente, a sus competidoras o a ambas.

Las reglas de umbral solo avisan **el día en que se cruza el umbral**, no todos los días que siga por encima, para no repetir el mismo aviso cada mañana. La consultora cambia las reglas en la base de datos sin tocar el código. Cada cliente puede leer sus reglas, pero no las de otro.

| Cliente de demostración | Perfil | Reglas |
| --- | --- | --- |
| A, farmacéutica (sigue a Grifols, Almirall, Rovi y Faes) | Quiere enterarse pronto | Cualquier fondo nuevo; subida de 0,5 puntos en 5 sesiones; suma > 2 %. En competidoras, subida de 1 punto en 20 sesiones |
| B, renovables (sigue a Solaria, Grenergy, Acciona Energía y Soltec) | Convive con muchos cortos; solo quiere lo grande | Subida de 1,5 puntos en 20 sesiones; 15 fondos o más; más de 20 sesiones para cubrir. En competidoras, suma > 5 % |

**Resultado sobre el histórico (2010 a nov-2026).** Las reglas se evalúan sobre todos los datos, así que se ve qué habría recibido cada cliente.

| Cliente | Alertas | De ellas en 2024 | Desglose |
| --- | --- | --- | --- |
| A | 53 | 12 | 23 fondos nuevos, 22 subidas en 5 sesiones, 7 cruces del 2 %, 1 en competidoras |
| B | 20 | 10 | 9 subidas en 20 sesiones, 10 de días para cubrir, 1 de 15 fondos |

De media, unas 3 alertas al año para el cliente A y menos de 2 para el B, concentradas en los años de crisis (12 y 10 en 2024). Es un volumen que un equipo de relación con inversores puede atender.

**Caso Grifols con las reglas del cliente A.**
1. **8-ene-2024, víspera del informe de Gotham:** entra General Industrial Partners LLP con un 0,57 %, la suma pasa del 1,62 % al 2,19 % y saltan tres alertas a la vez: fondo nuevo, subida de 0,57 puntos en 5 sesiones y suma por encima del 2 %. Al día siguiente esa posición baja al 0,06 %. (Pendiente de confirmar con una fuente si esta entidad está vinculada a Gotham City Research antes de usarlo en la presentación.)
2. **29-ene:** entra Qube Research & Technologies (0,50 %).
3. **9-feb:** la suma sube 0,58 puntos en 5 sesiones, hasta el 2,91 %.
4. **6-mar:** entra Marshall Wace, y la suma llega al 3,79 % con 5 fondos.

Como la CNMV publica cada posición con al menos un día de retraso, la alerta llega con la publicación, no antes. La Function lo detecta la misma tarde en que aparece el fichero.

**Caso Solaria con las reglas del cliente B.**
- **2024:** los días para cubrir superan 20 sesiones en julio y octubre.
- **1-nov y 20-nov-2024:** la suma sube más de 1,5 puntos en 20 sesiones.
- **19-nov-2024:** se llega a 15 fondos.
- **19-dic-2024:** se alcanza el máximo de 16,06 % con 18 fondos.

**Carga y aislamiento.**
1. Python evalúa las reglas y deja las alertas en `stg.alerta`.
2. `cliente.usp_cargar_alertas` las incorpora con un `MERGE`, sin duplicar las que ya existían. Repetir la carga da 0 alertas nuevas. Si se cambia una regla, las alertas que ya no salen se borran, salvo las ya enviadas.
3. La prueba de seguridad (`sql/06_prueba_rls.sql`) da:
   - `demo_cliente_a`: 4 reglas y 53 alertas, ninguna de otro cliente.
   - `demo_cliente_b`: 4 reglas y 20 alertas, ninguna de otro cliente.
   - `demo_consultora`: las 8 reglas y las 73 alertas.

**Prueba en la nube (9-nov-2026, 19:21 UTC).** Ejecución manual de la Function con el fichero publicado ese día: 216.168 posiciones, 93.408 filas de indicadores y las mismas 73 alertas, ninguna duplicada. Queda comprobado que la identidad de la Function tiene los permisos justos para leer las reglas y escribir las alertas.

**Envío.** El prototipo registra las alertas en la tabla, que mostrará el panel de la fase 5, y deja en Application Insights una línea `ALERTA_CLIENTE` por cada alerta nueva de los últimos 10 días. La tabla tiene la columna `enviada_utc` para el envío por correo en producción, que se diseñará y presupuestará en la fase 6 (por ejemplo, con Azure Communication Services Email).

**Mantenimiento.** Cuando aparece en la CNMV una empresa nueva sin código de Yahoo, la Function avisa con `INGESTA_CNMV_REVISAR`. Así ocurrió con **Puig Brands**, primera posición corta el 4-nov-2026, que se añadió a `tickers.csv` (`PUIG.MC`).

**Calidad.** 20 pruebas nuevas, 73 en total:
- Cálculo de cada indicador con casos pequeños hechos a mano.
- Fondo que vuelve antes de 20 sesiones (no es nuevo).
- Festivos.
- Aviso solo al cruzar el umbral.
- Separación de clientes y ámbito de competidoras.
- Nombres de empresa en los mensajes.
- Tipos de regla iguales en Python y en SQL.
- Aviso de emisor sin código.
