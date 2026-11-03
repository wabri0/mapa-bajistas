# 2. Contexto y problema

> Borrador de la fase 0 (3-nov-2026). Las cifras salen de `scripts/fase0_explorar.py`. Lo marcado con [FUENTE] necesita una cita externa antes de la entrega.

## 2.1 Qué es una posición corta neta

Un inversor tiene una posición corta cuando gana si baja el precio de una acción: normalmente toma prestados títulos, los vende y los recompra más tarde, más baratos. La posición corta *neta* descuenta las posiciones largas que el mismo inversor tenga sobre esa empresa.

El Reglamento (UE) 236/2012 sobre ventas en corto obliga a comunicarlas al supervisor nacional [FUENTE]:

- A partir del 0,1 % del capital, se comunican de forma privada a la CNMV.
- A partir del **0,5 %**, la CNMV las **publica** con el nombre del fondo. También publica cada cambio de 0,1 puntos por encima de ese nivel y la bajada por debajo del 0,5 %.
- La comunicación se hace como tarde a las 15:30 del día hábil siguiente, así que lo que se publica hoy es la posición de ayer.

## 2.2 Por qué le importa a una cotizada: el caso Grifols

El 9 de enero de 2024, Gotham City Research publicó un informe muy crítico con las cuentas de Grifols [FUENTE: fecha y caída de la cotización]. Los datos de la CNMV muestran cómo reaccionaron los fondos bajistas:

- **Antes del informe**, la presión bajista era estable: de media, 2,09 % del capital entre septiembre y diciembre de 2023, repartido entre 4 fondos.
- **El mismo 9 de enero**, un fondo que había abierto un 0,57 % el día anterior (General Industrial Partners) lo redujo al 0,06 %.
- **En las semanas siguientes**, la presión creció. Qube Research & Technologies pasó del 0,50 % al 1,66 %, y entraron o volvieron WorldQuant, AKO Capital y Marshall Wace. La suma publicada llegó a un **máximo del 4,38 % con 6 fondos el 14 de marzo de 2024**, el doble que antes de la crisis.
- A finales de marzo, Qube cerró y la suma volvió al 2,4 % en mayo.

Lo que enseña el caso: las posiciones públicas no anticiparon el ataque, pero sí mostraron, día a día, quién aprovechaba la crisis, con cuánto y cuándo salía. Esa es la información que necesita el equipo de relación con inversores para responder.

## 2.3 Un patrón distinto: Solaria

Solaria muestra el caso opuesto: una presión bajista persistente durante años. Desde la primera notificación en junio de 2018 han tomado posiciones cortas sobre ella 42 fondos distintos. La suma publicada llegó al **16,57 % del capital el 19 de diciembre de 2024**, y el **12 de diciembre de 2024** había **19 fondos** a la vez. Hoy (30-oct-2026) sigue siendo la cotizada española con más posiciones cortas: **8,13 % entre 8 fondos**, casi el doble que la segunda (Enagás, 4,21 %).

## 2.4 Cómo se trabaja hoy

La información es pública y gratuita, pero poco práctica:

- La CNMV publica un Excel que se actualiza cada día hábil. Contiene la última posición de cada fondo y el historial desde 2010: 12.360 notificaciones únicas sobre 80 emisores.
- No hay alertas, ni gráficos, ni cruce con la cotización, las operaciones de directivos o las participaciones significativas.
- El fichero tiene problemas que dificultan usarlo directamente: 1.892 filas duplicadas, ISIN escritos de varias formas, fondos con nombres distintos y emisores que cambian de ISIN tras una operación corporativa.
- Una consultora de relación con inversores tiene que descargarlo, limpiarlo e interpretarlo a mano para cada cliente cotizado, todos los días. [FUENTE: estimación de horas de seguimiento manual, pendiente de las entrevistas de la fase 0]

## 2.5 El problema

Las cotizadas no tienen una forma sencilla de saber quién apuesta contra ellas, entenderlo en contexto y reaccionar a tiempo. Para la consultora, repetir el trabajo con cada cliente no escala, y las alertas, notas y datos confidenciales de cada cliente tienen que quedar separados.
