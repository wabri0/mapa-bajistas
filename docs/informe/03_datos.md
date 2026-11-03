# 3. Datos

> Borrador de la fase 0 (3-nov-2026). Se completa en la fase 2 con la limpieza. Lo marcado con [FUENTE] necesita una cita externa.

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

## 3.2 Calidad del dato

Se ha comprobado que la serie diaria reconstruida a partir del historial reproduce exactamente las posiciones vigentes que publica la CNMV en 31 de 38 ISIN. Las 7 diferencias son ISIN antiguos tras operaciones corporativas o posiciones cerradas sin notificación de cierre. Los problemas detectados y su tratamiento están en `docs/fase0/hallazgos_datos.md`.

## 3.3 Fuentes complementarias

- **Operaciones de directivos y participaciones significativas:** registros públicos de la CNMV. Se consultan por emisor y se tratan en fases posteriores.
- **Cotización y volumen:** yfinance, solo para el prototipo académico. En producción haría falta un proveedor con licencia comercial (ver sección 9).

## 3.4 Condiciones legales de uso

He leído entera la Nota legal de la CNMV (consultada el 3-nov-2026; copia literal en `docs/fuentes/cnmv_nota_legal_2026-11-03.txt`). El uso que propone este proyecto encaja en ella con cuatro condiciones:

> **Cumplimiento de la Nota legal de la CNMV.** La CNMV permite usar la información de su web más allá de la consulta privada si se reproduce *fielmente, sin manipular ni alterar los contenidos*. Permite también *realizar cálculos que se difundan por el usuario*. La plataforma respeta ambas condiciones de tres formas. Guarda cada fichero descargado sin modificar en la capa bronze. Presenta los indicadores (sumas, variaciones, número de fondos, días para cubrir) como cálculos propios, identificados como tales y separados del dato original. Y no reproduce páginas de la CNMV dentro de la suya: los enlaces a la CNMV abren en una ventana independiente. Como el servicio se ofrecerá por suscripción, la consultora debe informar a sus clientes, *antes de que paguen cualquier suscripción o precio* y cada vez que les dé esta información, de que pueden obtenerla gratis en la web de la CNMV. Para ello, el panel y los correos de alerta llevan una nota fija con la fuente y el enlace, y el contrato incluye una cláusula. La CNMV no garantiza la exactitud del dato ni responde de las decisiones tomadas con él, así que la plataforma muestra la información con fines informativos y conserva la fecha de publicación de cada fichero. Por último, la nota dice que la CNMV, *con carácter general, no concede licencia de uso* sobre su propiedad intelectual *salvo acuerdo expreso por escrito*. Por eso, antes de comercializar el servicio se recomienda pedir a la CNMV una confirmación por escrito del uso previsto. El prototipo académico, sin fines comerciales, no necesita ese paso.

## 3.5 Limitaciones

- **Umbral del 0,5 %:** las posiciones entre el 0,1 % y el 0,5 % no se publican, así que la presión bajista real es mayor que la visible. Un fondo puede estar presente sin aparecer.
- **Retraso de un día:** se publica la posición del día hábil anterior.
- **Huecos en el historial:** algunos fondos repiten el mismo 0,50 % con años de diferencia y sin registros intermedios (por ejemplo, AQR en Grifols entre 2018 y 2024). No se puede saber si la posición siguió viva.
- **Cambios de ISIN:** 9 emisores tienen varios ISIN por operaciones corporativas; el análisis se hace por emisor (LEI).
- **Formato:** el fichero es un Excel antiguo con fechas como texto y tres filas vacías arriba. Un cambio de formato rompería la lectura, por eso la ingesta tiene que detectarlo.
