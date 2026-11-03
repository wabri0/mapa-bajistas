# Fase 0 · Tareas manuales pendientes

Estas tareas necesitan tu cuenta o tu contacto directo. Al terminar cada una, marca la casilla.

## Paso 4 · Azure for Students

- [ ] Entra en https://azure.microsoft.com/free/students con el correo de la universidad. Comprueba que **no pide tarjeta** y anota el crédito y la fecha de caducidad que te dan.
      Si pide tarjeta o no la aprueban → plan B (GitHub Actions + SQLite) y apúntalo aquí.
- [ ] Crea un grupo de recursos: Portal → *Resource groups* → *Create*.
      - Nombre: `rg-mapa-bajistas`
      - Región: **West Europe**. Si la política de la suscripción no la permite, usa la que te deje y anótala, porque afecta a los costes de la fase 6.
      - Etiquetas: `proyecto=mapa-bajistas`, `entorno=prototipo`
- [ ] Crea la alerta de presupuesto: *Cost Management* → *Budgets* → *Add*.
      - Ámbito: la suscripción
      - Importe: 1, con reinicio mensual (la moneda puede ser USD; da igual)
      - Alertas: 50 %, 100 % y previsión del 100 %, con aviso a tu correo
- [ ] Haz una captura del presupuesto creado para el informe.
- [ ] Recuerda: nunca crear una capacidad de Power BI (F2/A1) y usar siempre el nivel gratuito o el más básico.

## Paso 5 · Repositorio en GitHub

El repositorio local ya existe, con la primera versión guardada en `main`. Falta publicarlo:

1. Crea un repositorio vacío en https://github.com/new llamado `mapa-bajistas`, sin README ni .gitignore.
   Privado de momento; el plan B necesita que sea público.
2. Desde la carpeta del proyecto:
   ```
   git remote add origin https://github.com/<tu-usuario>/mapa-bajistas.git
   git push -u origin main
   ```
3. Los datos de `data/` no se suben (están en `.gitignore`). Se pueden volver a descargar de la CNMV en cualquier momento.

## Paso 6 · Confirmar el enfoque con el profesor

- [ ] Envía el correo (borrador abajo) y anota la respuesta y la extensión del informe que fije.

> **Asunto:** Proyecto final – validación del enfoque (Track B, «El mapa de los bajistas»)
>
> Hola, [nombre del profesor]:
>
> Le escribo para confirmar el enfoque de mi proyecto final antes de empezar a construir.
>
> **Tema:** una plataforma en la nube que descarga a diario las posiciones cortas netas que publica la CNMV (las que superan el 0,5 % del capital) y las cruza con la cotización. Una consultora de relación con inversores la ofrecería por suscripción a varias cotizadas, con las alertas y notas de cada cliente separadas.
>
> **Enfoque:** propongo dos entregables:
> 1. Un **prototipo funcional a coste cero** en Azure: ingesta diaria, base de datos con seguridad por cliente, alertas y un panel en Power BI.
> 2. Un **informe ejecutivo** que diseña y presupuesta la versión de producción (inicio de sesión de clientes externos, Power BI Embedded, otros supervisores europeos) con la calculadora de Azure en tres escenarios, y calcula el punto de equilibrio frente al seguimiento manual.
>
> Ya he validado los datos: el fichero de la CNMV tiene 12.360 notificaciones desde 2010, y sobre él he comprobado el caso Grifols de 2024 (la suma de posiciones cortas pasó del 2,1 % al 4,4 % del capital tras el informe de Gotham).
>
> Mis preguntas:
> - ¿Le parece válido que lo más caro o complejo quede diseñado y presupuestado en el informe, en lugar de construido?
> - ¿Qué extensión y formato espera para el informe y la presentación?
>
> Muchas gracias,
> Gabriel

## Paso 7 · Estimación de horas de seguimiento manual

- [ ] Envía el mensaje a una o dos personas de relación con inversores o de tu red. Anota cada respuesta con su cargo y fecha: es la fuente del caso de negocio de la fase 6.

> Hola, [nombre]:
>
> Estoy haciendo mi proyecto final sobre una herramienta que vigila a diario las posiciones cortas que publica la CNMV sobre una cotizada y avisa cuando cambian. Me ayudaría mucho tu experiencia, son dos minutos:
>
> 1. ¿Sigue tu equipo (o el de tu cliente) las posiciones cortas de la CNMV? ¿Con qué frecuencia y cómo (a mano, con un proveedor, con un informe de un banco)?
> 2. Más o menos, **¿cuántas horas al mes** dedica alguien a ese seguimiento: descargar, revisar, preparar un resumen para dirección?
> 3. ¿En qué momentos se dispara ese trabajo (resultados, ampliaciones, un informe bajista)?
> 4. ¿Pagaríais por un servicio que lo hiciera solo y avisara por correo? ¿Tienes una idea de cuánto?
>
> No citaré tu nombre ni tu empresa si no quieres. ¡Gracias!
> Gabriel
