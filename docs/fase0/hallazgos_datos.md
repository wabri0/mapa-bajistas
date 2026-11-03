# Fase 0 · Hallazgos sobre los datos de la CNMV

Fichero analizado: `data/raw/NetShortPositions_2026-11-02.xls` (publicado el 2 de noviembre de 2026).
Todas las cifras salen de `scripts/fase0_explorar.py`; la salida completa está en `salida_fase0_explorar.txt`.

## 1. Estructura del Excel

| Hoja | Filas | Contenido | Fechas de posición |
| --- | --- | --- | --- |
| `Fecha_-_Date` | 1 dato | Fecha de publicación del fichero (texto con espacios: `" 2026-11-02 "`) | — |
| `Última_-_Current` | 63 | Última posición de cada fondo vivo (≥ 0,5 %) | 2025-04-04 → 2026-10-30 |
| `Serie_-_Series` | 1.720 | Historial completo de las posiciones vivas | 2011-02-02 → 2026-10-30 |
| `Anteriores_-_Previous` | 12.887 | Historial de posiciones ya cerradas | 2010-06-10 → 2026-10-29 |
| `Hoja2` … `Hoja7` | 0 | Vacías | — |

- Las tres hojas de datos tienen las mismas 6 columnas: LEI, ISIN, Emisor, Tenedor, Fecha de posición, Posición corta (%).
- Las 3 primeras filas están vacías; la cabecera bilingüe está en la fila 4.
- Las fechas son texto con espacios a los lados, no fechas de Excel. Todas se convierten sin errores.
- No hay valores nulos.
- **Histórico único (Serie + Anteriores, sin duplicados): 12.360 notificaciones, 80 emisores, 229 fondos, 90 ISIN, desde junio de 2010.**
- Hoy hay 31 emisores con al menos una posición viva, sumando 63 posiciones de 36 fondos.

## 2. Problemas de calidad (entrada para la fase 2)

| Problema | Magnitud | Tratamiento propuesto |
| --- | --- | --- |
| Filas duplicadas exactas | 1.892 en Anteriores (bloques enteros repetidos), 2 en Serie, 1 en Vigentes | `drop_duplicates` sobre las 6 columnas |
| ISIN en minúsculas o mezcla (`es0126775032`, `eS0118594417`) | 90 filas; 115 ISIN escritos → 90 reales | Pasar a mayúsculas |
| Una misma posición en Serie y en Anteriores | 359 filas, mismo % en el 100 % | Unir ambas hojas y deduplicar |
| Emisores con varios ISIN por operaciones corporativas | 9 emisores (Amper, Grifols, Pharma Mar, Redeia, Colonial…) | Agregar por LEI (emisor), no por ISIN |
| Nombres de fondo con variantes | 6 grupos (p. ej. `Two Sigma Investments, LLC` / `LP`, `Eminence Capital, LLC` / `LP`) | Tabla de equivalencias revisada a mano; ojo, algunos pueden ser entidades distintas |
| Errata en el nombre de un fondo | `Ennismore Fund Mangement Limited` | Normalizar en la tabla de equivalencias |
| Registros por debajo del umbral | 778 filas < 0,5 % y 93 filas a 0 % en Anteriores | Son la notificación de cierre: la posición pasa a 0 publicado |

## 3. Validación de la serie diaria reconstruida

Regla usada: cada fondo mantiene su última posición notificada hasta la siguiente; si baja de 0,5 %, cuenta como 0.
Comprobación: la reconstrucción a la última fecha debe dar la hoja de Vigentes.

- **31 de 38 ISIN cuadran exactamente.** Por ejemplo, Solaria: 8 fondos y 8,13 %, igual que la CNMV.
- Las 7 discrepancias son todas ISIN antiguos o de derechos (Amper `ES0609260973` y `ES0109260531`, Grifols clase B `ES0171996012`, Pharma Mar `ES0169501030`, Redeia, Prosegur, Colonial). Las posiciones se cerraron por cambio de ISIN o por un cierre que no figura en el fichero, sin notificación por debajo de 0,5 %.
- **Regla para la fase 2:** una posición de la hoja Anteriores cuyo último registro sea ≥ 0,5 % se considera cerrada aunque falte la notificación de cierre. Hay que decidir y documentar la fecha de cierre supuesta.
- **Ambigüedad conocida:** algunos fondos notifican el mismo 0,50 % con años de diferencia y nada en medio (AQR en Grifols: agosto de 2018 y después agosto de 2024). Con la regla de arrastre cuentan como vivos todo ese tiempo. En Grifols supone una incertidumbre de ±0,5 puntos en la suma de 2018 a 2024.

## 4. Caso Grifols (clase A, `ES0171996087`)

214 notificaciones desde 2010 y 17 fondos distintos. Hoy solo queda una posición viva: Kintbury Capital, 1,78 % (29-oct-2026).

| Fecha | Suma publicada | Fondos | Qué pasa |
| --- | --- | --- | --- |
| Media sep–dic 2023 | 2,09 % | 4 | Estable, sin entradas nuevas relevantes |
| 8-ene-2024 | 2,69 % | 5 | Entra General Industrial Partners (0,57 %) |
| 9-ene-2024 | 2,12 % | 4 | General Industrial Partners baja a 0,06 %, el mismo día del informe de Gotham* |
| 29-ene → 14-mar-2024 | sube a 4,38 % | 6 | Qube pasa de 0,50 % a 1,66 %; entran WorldQuant, AKO y Marshall Wace |
| 14-mar-2024 | **4,38 % (máximo)** | 6 | Pico del periodo |
| 26-mar-2024 | — | — | Qube sale (0,34 %) |
| 31-may-2024 | 2,39 % | 4 | Vuelta a niveles previos |

\* La fecha del informe de Gotham City Research (9-ene-2024) no está en el Excel: hay que citar una fuente externa en el informe.

**Conclusión:** los datos **no muestran una escalada antes del informe**. La subida llega después: media de 3,53 % en febrero y marzo frente a 2,09 % antes. Además, la CNMV publica con un día de retraso, así que la entrada del 8 de enero solo era visible el 9. El caso debe contarse como **respuesta a la crisis** (quién entra después, cuánto y cuándo sale), no como detección previa. Es la contingencia prevista en el planning.
Nota: la ventana del planning (noviembre de 2023 a marzo de 2024) es correcta, pero lo relevante pasa entre enero y marzo de 2024.

## 5. Caso Solaria (`ES0165386014`)

- Primera notificación: 7-jun-2018. 894 notificaciones y 42 fondos distintos: segundo emisor del histórico por número de notificaciones, por detrás de DIA (1.158 notificaciones, 55 fondos).
- **Máximo de la suma: 16,57 % el 19-dic-2024. Máximo de fondos: 19 el 12-dic-2024.**
- Hoy es **el emisor con más posiciones cortas de España: 8,13 % repartido entre 8 fondos**, casi el doble que el segundo (Enagás, 4,21 %).
- Máximo anual de la suma: 1,6 % (2018) → 8,8 % (2021) → 10,9 % (2023) → 16,6 % (2024) → 16,5 % (2025) → 9,2 % (2026).
- Sirve para contar el caso opuesto a Grifols: una posición bajista persistente y de muchos fondos, que dura años.

## 6. Descarga automática (entrada para la fase 1)

- URL directa del Excel: `https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls`. Devuelve 200 con `curl`, con o sin User-Agent. Cabeceras útiles: `Last-Modified` y `ETag`.
- La página HTML de consulta (`/portal/consultas/datosgenerales/posicionescortas`) devuelve **403** a clientes automáticos: no hay que hacer scraping de ella.
- Dos descargas seguidas del servidor dan el mismo SHA-256. La copia abierta en local difiere en 16 bytes de la cabecera OLE, con contenido idéntico. Para detectar cambios hay que usar el hash del fichero descargado (nunca de una copia abierta en Excel) y, además, un hash del contenido normalizado para evitar falsos positivos.
