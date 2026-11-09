/* =====================================================================
   Fase 3 · Acceso de la Azure Function a la base de datos
   ---------------------------------------------------------------------
   La Function entra con su identidad administrada (sin contraseña). Aquí se
   crea su usuario en la base de datos y se le da solo el rol de carga.
   Lo debe ejecutar un usuario de Microsoft Entra (el administrador del servidor).
   ===================================================================== */

IF DATABASE_PRINCIPAL_ID('func-mapa-bajistas') IS NULL
    CREATE USER [func-mapa-bajistas] FROM EXTERNAL PROVIDER;
GO
ALTER ROLE rol_carga ADD MEMBER [func-mapa-bajistas];
GO
