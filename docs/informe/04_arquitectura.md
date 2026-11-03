# 4. Arquitectura propuesta

> Borrador por fases. Fase 1 (ingesta y capa bronze) escrita el 3-nov-2026; las fases 2 a 5 añaden sus apartados.

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

La regla de alerta `alerta-ingesta-cnmv-fallo` de Application Insights vigila ese texto y cualquier ejecución fallida. Se evalúa cada hora y envía un correo al grupo de acciones `ag-mapa-bajistas-correo`. Avisa una vez cuando empieza el problema y otra cuando se resuelve. Coste: 0,50 US$ al mes.

**Calidad.** 9 pruebas automáticas cubren:
- El fichero real es válido.
- El hash de contenido ignora los metadatos.
- Se detectan los cambios de formato: hoja que falta, cabecera distinta, fecha o porcentaje ilegible y fichero HTML.
- No se guardan duplicados.
- Los ficheros rechazados se apartan.
- Se avisa cuando el fichero está desactualizado.
