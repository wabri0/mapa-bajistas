# 3. Datos

> Borrador de las fases 0 (3-nov-2026) y 2 (4-nov-2026). Lo marcado con [FUENTE] necesita una cita externa.

## 3.1 Fuente principal: Excel de posiciones cortas netas de la CNMV

| Característica | Valor |
| --- | --- |
| Fichero | `NetShortPositions.xls` (Excel 97-2003) |
| URL de descarga | `https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls` |
| Actualización | Cada día hábil; el fichero lleva su propia fecha de publicación |
| Umbral de publicación | 0,5 % del capital, y cada 0,1 puntos por encima |
| Hojas | Vigentes (63 posiciones), Serie de las vigentes (1.720 filas), Anteriores (12.887 filas) |
| Campos | LEI, ISIN, emisor, fondo, fecha de la posición, % |
| Profundidad | Desde el 10 de junio de 2010 |
| Volumen único | 12.360 notificaciones, 80 emisores, 229 fondos, 90 ISIN |
| Tamaño | 1,7 MB |

El volumen es pequeño: el reto no es el tamaño, sino la ejecución diaria desatendida, la calidad del dato y la separación entre clientes.

## 3.2 Limpieza y capa silver

Cada vez que llega un fichero nuevo, la plataforma lo convierte en cinco tablas limpias en Parquet: la capa *silver*, que ocupa unos 0,5 MB. Con el fichero del 3-nov-2026 la reconstrucción **cuadra al 100 % con las posiciones vigentes que publica la CNMV (30 de 30 emisores)**. El proceso tarda menos de un segundo.

| Tabla | Una fila por… | Filas (3-nov-2026) |
| --- | --- | --- |
| `notificaciones` | notificación única: fondo, emisor, fecha y % | 12.370 |
| `emisores` | empresa (LEI), con sus ISIN y su nombre más reciente | 80 |
| `fondos` | entidad notificante, con su grupo gestor | 229 (199 grupos) |
| `posiciones_intervalos` | tramo en que un fondo mantiene el mismo % público sobre un emisor | 11.594 |
| `posiciones_diarias` | fondo, emisor y día hábil con posición pública | 219.925 |

**Reglas de limpieza:**
- **Duplicados.** Las hojas Serie y Anteriores repiten filas, y la de vigentes repite las de Serie. Se quedan las filas únicas y se eliminan 2.385.
- **ISIN** en mayúsculas: el fichero mezcla `ES…`, `es…` y `Es…`.
- **Agrupación por emisor (LEI), no por ISIN.** La posición corta neta se calcula sobre el capital del emisor, y los ISIN cambian tras operaciones corporativas: contrasplits, derechos de suscripción, clases de acciones. Agrupar por LEI elimina las 7 discrepancias que daba agrupar por ISIN en la fase 0.
- **Conflictos.** Si un mismo fondo notifica dos porcentajes sobre el mismo emisor el mismo día (por ejemplo, en dos ISIN), se toma el mayor y se cuenta como incidencia. Hasta ahora: 0.
- **Serie diaria.** Cada notificación vale hasta la siguiente del mismo fondo y emisor. Por debajo del 0,5 % la posición deja de ser pública y cuenta como cerrada. Se expande a días hábiles.
- **Cierres sin aviso (caducidad de 365 días).** La CNMV no publica la mayoría de los avisos de cierre: en todo el fichero solo hay 774, frente a más de 11.000 tramos. Si se dejara cada aviso vivo hasta el siguiente, posiciones casi seguro cerradas seguirían abiertas durante años; por ejemplo, JPMorgan aparecería con un 0,599 % en Rovi de 2011 a 2025. Esos tramos sumaban la mitad de la serie diaria. Por eso, una posición que no sigue vigente y pasa más de 365 días sin ningún aviso se da por cerrada 365 días después del último y se marca como *cierre inferido* (204 tramos). El límite se basa en los datos: el 99 % de los cierres publicados llega antes de 301 días, y la posición viva más antigua lleva 578 días sin avisos. A las posiciones vigentes no se les aplica.
- **Dos fechas.** Cada notificación guarda la fecha de la posición y la de la primera captura en la que apareció. El histórico cargado el primer día no tiene fecha de captura, porque no se puede saber cuándo se publicó cada fila. Desde entonces, cada notificación nueva queda fechada; por ejemplo, el 3-nov-2026 llegaron 13.

**Hallazgo: la hoja de vigentes de la CNMV no son solo posiciones vivas.** Muestra durante un día las posiciones que acaban de bajar del 0,5 %. El 3-nov-2026, AQR en Ferrovial y BlackRock en Aena aparecían con un 0,49 %. El cuadre solo compara las posiciones ≥ 0,5 %.

**Grupos gestores.** La CNMV identifica a la entidad legal que notifica (por ejemplo, *Citadel Advisors LLC* o *Citadel Europe LLP*). A una cotizada le interesa la casa que hay detrás. Una tabla revisada a mano (`src/limpieza/grupos_gestores.csv`) asigna 52 entidades a 22 grupos con varias entidades; por ejemplo, Man Group reúne GLG, AHL y Man Investments. Ante la duda, no se une: *Polar Capital* y *Polar Asset Management Partners* son gestoras distintas, y *Citadel Securities* es una empresa distinta del fondo *Citadel*.

**Entidades nuevas.** Cuando aparece una entidad que no está en la tabla, nunca se bloquea nada: cuenta como su propio grupo y los datos se publican igual. En cada ejecución, el informe de calidad (`calidad.json`) lista:
- los **fondos nuevos**, los que no estaban en la captura anterior;
- los **grupos por revisar**: entidades no revisadas cuyo nombre comparte marca con otra de distinto grupo, junto con el grupo sugerido. Por ejemplo, un *Citadel Advisors III LLC* nuevo aparecería con la sugerencia «Citadel».

La marca es la primera palabra distintiva del nombre, sin formas jurídicas (LLC, LLP…) ni términos genéricos (Capital, Management…). No se agrupa de forma automática porque el nombre engaña, como muestran Polar o Two Sigma frente a Two Creeks. Una persona decide, añade la línea a la tabla y, en la siguiente ejecución, todo el histórico se recalcula con el grupo correcto. Una entidad independiente se marca como revisada asignándole su propio nombre como grupo. La Function registra el aviso `INGESTA_CNMV_REVISAR`, que la misma regla de alerta de la ingesta envía por correo; no hace falta una regla aparte ni tiene coste adicional.

**Controles de calidad.** En cada ejecución se comprueban:
- duplicados y conflictos;
- LEI con formato inválido, ISIN inválidos, porcentajes fuera de 0–100 % y fechas fuera de rango;
- el cuadre con la hoja de vigentes.

Si falla algún control crítico (LEI, porcentajes, fechas o cuadre), la silver no se sobrescribe, el informe se guarda aparte (`calidad_rechazada.json`) y salta la alerta por correo.

## 3.3 Fuentes complementarias

- **Operaciones de directivos y participaciones significativas:** registros públicos de la CNMV. Se consultan por emisor y se tratan en fases posteriores.
- **Cotización y volumen:** yfinance, solo para el prototipo académico. En producción haría falta un proveedor con licencia comercial (ver sección 9).

## 3.4 Condiciones legales de uso

He leído entera la Nota legal de la CNMV (consultada el 3-nov-2026; copia literal en `docs/fuentes/cnmv_nota_legal_2026-11-03.txt`). El uso que propone este proyecto encaja en ella con cuatro condiciones:

> **Cumplimiento de la Nota legal de la CNMV.** La CNMV permite usar la información de su web más allá de la consulta privada si se reproduce *fielmente, sin manipular ni alterar los contenidos*. Permite también *realizar cálculos que se difundan por el usuario*. La plataforma respeta ambas condiciones de tres formas. Guarda cada fichero descargado sin modificar en la capa bronze. Presenta los indicadores (sumas, variaciones, número de fondos, días para cubrir) como cálculos propios, identificados como tales y separados del dato original. Y no reproduce páginas de la CNMV dentro de la suya: los enlaces a la CNMV abren en una ventana independiente. Como el servicio se ofrecerá por suscripción, la consultora debe informar a sus clientes, *antes de que paguen cualquier suscripción o precio* y cada vez que les dé esta información, de que pueden obtenerla gratis en la web de la CNMV. Para ello, el panel y los correos de alerta llevan una nota fija con la fuente y el enlace, y el contrato incluye una cláusula. La CNMV no garantiza la exactitud del dato ni responde de las decisiones tomadas con él, así que la plataforma muestra la información con fines informativos y conserva la fecha de publicación de cada fichero. Por último, la nota dice que la CNMV, *con carácter general, no concede licencia de uso* sobre su propiedad intelectual *salvo acuerdo expreso por escrito*. Por eso, antes de comercializar el servicio se recomienda pedir a la CNMV una confirmación por escrito del uso previsto. El prototipo académico, sin fines comerciales, no necesita ese paso.

## 3.5 Limitaciones

- **Umbral del 0,5 %:** las posiciones entre el 0,1 % y el 0,5 % no se publican, así que la presión bajista real es mayor que la visible. Un fondo puede estar presente sin aparecer.
- **Retraso de un día:** se publica la posición del día hábil anterior.
- **Cierres no publicados:** la CNMV no publica la mayoría de las bajadas por debajo del 0,5 %. La regla de caducidad de 365 días corrige los huecos largos, pero no los cortos: una posición cerrada sin aviso que reaparece antes de un año se cuenta como viva todo ese tiempo. Por eso las sumas históricas son una cota superior de la presión bajista publicada.
- **Cambios de ISIN:** 9 emisores tienen varios ISIN por operaciones corporativas; el análisis se hace por emisor (LEI).
- **Formato:** el fichero es un Excel antiguo con fechas como texto y tres filas vacías arriba. Un cambio de formato rompería la lectura, por eso la ingesta tiene que detectarlo.
