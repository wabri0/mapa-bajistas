# Planning del proyecto: El mapa de los bajistas

Nov 2, 2026 · @Gabriel

## Resumen del proyecto

El proyecto se organiza en 8 fases a lo largo de 10 semanas, del 2 de noviembre de 2026 a la entrega del 10 de enero de 2027. El resultado son dos piezas: un prototipo funcional en la nube, construido a coste cero, y un informe ejecutivo que diseña y presupuesta la versión de producción.

- **Track:** B · Arquitectura técnica.
- **Tema:** plataforma en la nube que descarga a diario las posiciones cortas netas que publica la CNMV (las que superan el 0,5 % del capital) sobre las cotizadas españolas, y las cruza con su cotización, las operaciones de directivos y las participaciones significativas. Una consultora de relación con inversores la ofrece por suscripción a varias cotizadas, cada una con sus alertas, notas y datos confidenciales separados.
- **Problema:** las cotizadas no tienen una forma sencilla de vigilar quién apuesta contra ellas, entenderlo en contexto y responder rápido. Hoy se consulta a mano en la web de la CNMV y la consultora repite el trabajo para cada cliente.
- **Por qué:** orientarme al análisis financiero con datos, combinando mercados de capitales con ingesta, almacenamiento, seguridad y visualización en la nube.
- **Pregunta:** ¿qué arquitectura en la nube permite recoger y analizar estas posiciones a diario, avisar a cada cliente según sus criterios y aislar su información confidencial? ¿Cuánto costaría en producción frente al seguimiento manual y a partir de cuántos clientes es rentable?

## Principios de trabajo

El proyecto se guía por cinco reglas que deciden qué se construye, qué se diseña y cuánto se gasta.

1. **Coste cero.** Solo se usan herramientas gratuitas y créditos de estudiante. Los costes de producción se calculan con la calculadora de Azure, no se pagan.
2. **Prototipo frente a producción.** Se construye lo mínimo que demuestra que la arquitectura funciona: ingesta, base de datos, alertas y panel con seguridad por cliente. Lo caro o complejo (Power BI Embedded, inicio de sesión de clientes externos, varios supervisores europeos) queda diseñado y presupuestado en el informe.
3. **El dato manda.** Cualquier afirmación del informe (casos Grifols y Solaria, umbrales, volúmenes) se comprueba en el Excel de la CNMV antes de escribirse.
4. **Construir pequeño y de forma incremental.** Cada fase termina con algo que funciona y se puede enseñar, aunque sea simple. Si falta tiempo, se recorta alcance, no calidad.
5. **Documentar mientras se trabaja.** Al cerrar cada fase se escribe la parte del informe que le corresponde, con capturas. Así la redacción final es montar piezas, no empezar de cero.

Para no llevarse sustos con Azure: alerta de presupuesto de 1 € el primer día, siempre el nivel gratuito o el más básico, nunca crear una capacidad de Power BI (F2 o A1), y borrar los recursos al terminar.

## Herramientas y stack tecnológico

Todo el prototipo se monta con herramientas gratuitas, y Azure es la nube elegida porque encaja de forma natural con Power BI. GitHub Actions queda como plan B si Azure for Students no estuviera disponible.

| Capa | Herramienta | Para qué se usa | Coste para ti |
| --- | --- | --- | --- |
| Fuente principal | Excel NetShortPositions.xls de la CNMV | Posiciones cortas netas vigentes e históricas desde 2010 | Gratis |
| Fuentes complementarias | Web de la CNMV (directivos, participaciones significativas) | Contexto de cada emisor | Gratis |
| Cotizaciones | yfinance (Python) | Precios y volumen diarios para el prototipo | Gratis (uso académico) |
| Desarrollo | Python, pandas, xlrd, requests, SQLAlchemy | Descarga, limpieza y carga de datos | Gratis |
| Editor y versiones | VS Code, Git, GitHub | Escribir código y guardar su historial | Gratis |
| Cuenta en la nube | Azure for Students | Crédito inicial sin tarjeta (comprobar condiciones) | Gratis |
| Ingesta programada | Azure Functions (Python, temporizador) | Descarga diaria del Excel a las 16:15 | Gratis (nivel gratuito) |
| Almacenamiento bruto | Azure Blob Storage / Data Lake Gen2 | Capa bronze: ficheros originales sin tocar | Céntimos, cubiertos por el crédito |
| Base de datos | Azure SQL Database (oferta gratuita) | Capa gold: modelo en estrella y tablas por cliente | Gratis (comprobar límites) |
| Secretos | Azure Key Vault | Guardar contraseñas y cadenas de conexión | Céntimos, cubiertos por el crédito |
| Monitorización | Application Insights | Ver si la ejecución diaria falla | Gratis en este volumen |
| Control de gasto | Azure Cost Management | Alerta de presupuesto de 1 € | Gratis |
| Visualización | Power BI Desktop | Panel y seguridad por cliente (RLS) con "Ver como" | Gratis |
| Costes de producción | Calculadora de precios de Azure | Estimar escenarios de 5, 20 y 60 clientes | Gratis |
| Caso de negocio | Excel | Punto de equilibrio y análisis de sensibilidad | Gratis |
| Diagramas | diagrams.net (draw.io) | Diagrama de arquitectura para el informe | Gratis |
| Plan B | GitHub Actions + SQLite | Ejecución diaria sin Azure | Gratis (repo público) |

El flujo de datos del prototipo sigue el patrón de capas bronze, silver y gold:

&#91;embedded content: arquitectura del prototipo · 8 componentes\]

La ingesta guarda el Excel original sin tocar, la limpieza lo convierte en una serie diaria por fondo y empresa, y la base de datos alimenta tanto el panel como las alertas de cada cliente.

## Fases y cronograma

El prototipo se termina en las seis primeras semanas, antes de Navidad, y las cuatro restantes se dedican al negocio, los costes y la redacción.

&#91;embedded content: cronograma · 8 fases en 10 semanas\]

Las fases 1 a 5 construyen el prototipo; la 6 coincide con Navidad y lleva menos carga técnica; la 7 deja una semana de margen antes de la entrega.

## Procedimiento por fase

Cada fase tiene unos pasos concretos y termina con un resultado que se puede enseñar y una parte del informe escrita.

### Fase 0 · Validación y preparación (semana 1)

1. Descargar el Excel de la CNMV y revisar hojas, columnas y profundidad del histórico.
2. Comprobar en los datos el caso Grifols (noviembre de 2023 a marzo de 2024) y el de Solaria.
3. Leer entera la nota legal de la CNMV y redactar el párrafo de cumplimiento.
4. Darse de alta en Azure for Students, crear un grupo de recursos y fijar la alerta de presupuesto.
5. Crear el repositorio en GitHub con la estructura de carpetas.
6. Confirmar con el profesor que el enfoque prototipo + diseño de producción es válido.
7. Pedir a una o dos personas de relación con inversores (o de tu red) una estimación de las horas de seguimiento manual.

**Resultado:** datos verificados, cuenta lista y luz verde del profesor.

### Fase 1 · Ingesta y capa bronze (semana 2)

1. Escribir en local un script que descargue el Excel y calcule su huella digital (hash) para detectar si ha cambiado.
2. Convertirlo en una Azure Function con temporizador de lunes a viernes a las 16:15.
3. Guardar cada descarga sin modificar en Blob Storage, con la fecha en el nombre.
4. Cargar el histórico completo una sola vez.
5. Añadir avisos si la descarga falla o el formato cambia.

**Resultado:** el Excel llega solo cada día a la nube.

### Fase 2 · Limpieza y capa silver (semana 3)

1. Leer el Excel con pandas y unificar nombres de fondos escritos de formas distintas.
2. Asociar cada código ISIN a su empresa.
3. Reconstruir una serie diaria por fondo y empresa a partir de las notificaciones.
4. Registrar dos fechas: la de la posición y la de captura.
5. Escribir controles de calidad: duplicados, porcentajes fuera de rango, fechas imposibles.

**Resultado:** una tabla limpia y fiable de posiciones diarias.

### Fase 3 · Base de datos gold y precios (semana 4)

1. Diseñar el modelo en estrella: hechos de posiciones y precios; dimensiones de emisor, fondo, fecha y cliente.
2. Crear la base de datos en Azure SQL y cargar los datos.
3. Descargar precios y volumen diarios con yfinance para los emisores con posiciones.
4. Crear las tablas confidenciales por cliente (alertas, notas) con un identificador de cliente.
5. Activar la seguridad por filas (RLS) en SQL para esas tablas.

**Resultado:** base de datos con datos públicos compartidos y datos de clientes aislados.

### Fase 4 · Indicadores y alertas (semana 5)

1. Calcular los indicadores: suma de posiciones cortas, número de bajistas, nuevos fondos, variación a 5 y 20 días, concentración entre fondos y días para cubrir.
2. Definir dos clientes ficticios con reglas de alerta distintas.
3. Programar la función que evalúa las reglas cada día después de la ingesta.
4. Enviar las alertas por correo o, si no es posible gratis, registrarlas en una tabla que muestre el panel.

**Resultado:** cada cliente recibe solo sus avisos.

### Fase 5 · Panel en Power BI (semana 6)

1. Conectar Power BI Desktop a Azure SQL.
2. Construir tres páginas: mapa de calor del mercado, detalle por empresa (posiciones frente a cotización) y red de fondos y empresas.
3. Configurar los roles de seguridad por cliente y probarlos con "Ver como".
4. Hacer capturas y grabar un vídeo corto de la demo como respaldo.

**Resultado:** el panel que enseñarás en la presentación.

### Fase 6 · Costes, caso de negocio y casos reales (semanas 7 y 8)

1. Calcular con la calculadora de Azure, región West Europe, tres escenarios: 5, 20 y 60 clientes.
2. Construir en Excel el coste del seguimiento manual, el punto de equilibrio y un análisis de sensibilidad (6, 12 y 20 horas al mes por cliente).
3. Preparar los casos Grifols, Solaria y Wirecard con gráficos sacados de los datos.
4. Diseñar la seguridad de producción: acceso de clientes, cifrado, auditoría y RGPD.
5. Diseñar la ampliación a otros supervisores europeos.

**Resultado:** el bloque de negocio y seguridad del informe. La semana de Navidad se plantea con menos carga.

### Fase 7 · Redacción, presentación y entrega (semanas 9 y 10)

1. Montar el informe a partir de las piezas escritas en cada fase.
2. Escribir el resumen ejecutivo al final, cuando todo esté claro.
3. Preparar la presentación y ensayarla en voz alta.
4. Revisar cifras, fuentes y ortografía.
5. Borrar los recursos de Azure que no hagan falta y entregar antes del 10 de enero.

**Resultado:** informe y presentación entregados.

### Ampliación opcional · Indicador de riesgo de escalada (solo si da tiempo)

Esta parte no es prioritaria: solo se empieza cuando las fases 0 a 6 estén cerradas y el informe tenga su estructura completa. Si no da tiempo, se describe en la hoja de ruta del informe como siguiente paso.

1. Con el histórico de la CNMV desde 2010, localizar cada primera publicación de una posición corta sobre una empresa.
2. Medir qué pasó después: si llegaron más bajistas en los 30 y 90 días siguientes y cómo se movió la cotización.
3. Construir un indicador sencillo de riesgo de escalada (verde, amarillo o rojo) con reglas puntuadas o una regresión logística: entrada de un fondo nuevo, número de fondos, crecimiento de la suma, caída de la cotización con volumen alto y días para cubrir.
4. Comprobar contra el histórico cuántas veces acierta y cuántas falla.
5. Añadirlo al panel y a las reglas de alerta.

**Resultado:** el proyecto pasa de describir a anticipar si un ataque va a ir a más. Momento: la semana de margen de la fase 7, si el resto está terminado.

## Estructura del informe y de la presentación

El informe sigue el orden de una recomendación de consultoría: primero la respuesta, después la justificación. Ajusta la extensión a la que fije el profesor.

### Informe ejecutivo

| Sección | Contenido | Se escribe en |
| --- | --- | --- |
| 1. Resumen ejecutivo | Recomendación, coste y punto de equilibrio en una página | Fase 7 |
| 2. Contexto y problema | Qué son las posiciones cortas, caso Grifols, cómo se trabaja hoy | Fase 0 |
| 3. Datos | Fuentes, umbrales, frecuencia, condiciones legales de la CNMV, limitaciones | Fases 0 y 2 |
| 4. Arquitectura propuesta | Diagrama, componentes y por qué cada uno | Fases 1 a 5 |
| 5. Escalabilidad | Más clientes y otros supervisores europeos sin rediseñar | Fase 6 |
| 6. Seguridad y modelo multicliente | Aislamiento por cliente, acceso, cifrado, auditoría, RGPD | Fases 3 y 6 |
| 7. Costes y caso de negocio | Tres escenarios, coste manual, punto de equilibrio, sensibilidad | Fase 6 |
| 8. Prototipo y resultados | Lo construido, capturas del panel, casos Grifols, Solaria y Wirecard | Fases 5 y 6 |
| 9. Riesgos y limitaciones | Umbral del 0,5 %, licencia de precios, formato del fichero | Fase 6 |
| 10. Recomendación y hoja de ruta | Pasos para pasar del prototipo a producción, incluido el indicador de escalada si no se ha construido | Fase 7 |
| Anexos | Código, modelo de datos, detalle de costes | Fase 7 |

### Presentación

La presentación sigue el hilo del discurso que ya preparamos: historia, revelación, solución y dinero.

1. **Gancho:** el caso Grifols contado como historia.
2. **Revelación:** estos datos son públicos, pero casi nadie los sigue.
3. **El cliente:** la consultora y sus cotizadas, y qué decisión toman.
4. **Demo:** el panel en directo o en vídeo, con dos clientes que ven cosas distintas.
5. **Arquitectura:** el diagrama en una diapositiva.
6. **Dinero:** prototipo a 0 € frente a producción, y el punto de equilibrio.
7. **Riesgos:** lo que el sistema no ve y cómo se mitiga.
8. **Cierre:** volver a Grifols con una pregunta.

## Riesgos del proyecto y contingencia

El mayor riesgo es el tiempo, no la tecnología: con la Navidad en medio, cada fase debe cerrarse en su semana. Estos son los riesgos previsibles y qué hacer si ocurren.

| Riesgo | Qué hacer si ocurre |
| --- | --- |
| Azure for Students no está disponible o pide tarjeta | Pasar al plan B: GitHub Actions + SQLite, y describir Azure en el informe como producción |
| La oferta gratuita de Azure SQL no basta | Usar SQLite en la nube del plan B o el nivel Basic con el crédito de estudiante |
| El formato del Excel de la CNMV cambia | El hash y los controles lo detectan; se ajusta el lector y se documenta como ejemplo de robustez |
| yfinance falla o le faltan valores | Descargar los precios una vez y guardarlos; buscar los tickers en Yahoo a mano |
| Los datos de Grifols no muestran lo esperado | Contar el caso como respuesta a la crisis, no como detección previa |
| El correo de alertas no es gratuito | Mostrar las alertas en una tabla del panel |
| No se puede publicar el panel en Power BI Service | Enseñarlo desde Power BI Desktop o con el vídeo de respaldo |
| El alcance crece (más países, más indicadores) | Dejarlo en la hoja de ruta del informe, no en el prototipo |
| Retraso acumulado en diciembre | Recortar el prototipo a ingesta, base de datos y panel; las alertas pasan a diseño |
| El tribunal ve la nube injustificada por el poco volumen | Argumentar con modelo multicliente, seguridad, ejecución desatendida y escala europea |

## Lista de comprobación

Marca cada punto al completarlo; los de control de calidad se revisan en la fase 7 antes de entregar.

### Entregables

- [ ] Datos de la CNMV verificados y caso Grifols comprobado
- [ ] Párrafo de cumplimiento de la nota legal de la CNMV
- [ ] Visto bueno del profesor al enfoque
- [ ] Ingesta diaria funcionando en la nube
- [ ] Tabla limpia de posiciones diarias
- [ ] Base de datos con modelo en estrella y RLS
- [ ] Indicadores calculados
- [ ] Alertas para dos clientes ficticios
- [ ] Panel de Power BI con tres páginas y roles por cliente
- [ ] Vídeo de respaldo de la demo
- [ ] Diagrama de arquitectura de producción
- [ ] Costes en tres escenarios (calculadora de Azure, West Europe)
- [ ] Punto de equilibrio y análisis de sensibilidad en Excel
- [ ] Casos Grifols, Solaria y Wirecard con gráficos
- [ ] Informe ejecutivo completo
- [ ] Presentación ensayada

### Opcional (solo si da tiempo)

- [ ] Indicador de riesgo de escalada validado con el histórico y añadido al panel

### Control de calidad

- [ ] Cada cifra del informe tiene su fuente
- [ ] El umbral del 0,5 % y sus limitaciones están explicados
- [ ] El prototipo y la producción están claramente separados
- [ ] Los costes indican región, fecha y supuestos
- [ ] El resumen ejecutivo se entiende sin leer el resto
- [ ] Ortografía y formato revisados
- [ ] Recursos de Azure borrados tras la entrega
