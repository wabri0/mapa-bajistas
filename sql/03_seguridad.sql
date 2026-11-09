/* =====================================================================
   Fase 3 · Roles, permisos y seguridad por filas (RLS)
   ---------------------------------------------------------------------
   Roles:
     rol_cliente     usuarios de un cliente: leen los datos públicos (dw) y solo
                     las filas de su cliente en el esquema cliente; escriben notas
     rol_consultora  equipo de la consultora: ve y gestiona todos los clientes
     rol_carga       identidad de la Azure Function: carga dw y, en la fase 4,
                     escribe alertas para todos los clientes
   La regla de RLS (seguridad.fn_cliente_visible) deja ver una fila si:
     - el usuario es de la consultora, de la carga o administrador (db_owner), o
     - el usuario figura en cliente.usuario_cliente con el cliente de esa fila.
   Los clientes no tienen permiso sobre cliente.usuario_cliente: la función la lee
   gracias al encadenamiento de propiedad (mismo propietario, dbo).
   ===================================================================== */

IF DATABASE_PRINCIPAL_ID('rol_cliente') IS NULL CREATE ROLE rol_cliente;
IF DATABASE_PRINCIPAL_ID('rol_consultora') IS NULL CREATE ROLE rol_consultora;
IF DATABASE_PRINCIPAL_ID('rol_carga') IS NULL CREATE ROLE rol_carga;
GO

/* --- Permisos --- */
GRANT SELECT ON SCHEMA::dw TO rol_cliente;
GRANT SELECT ON cliente.dim_cliente TO rol_cliente;
GRANT SELECT ON cliente.cliente_emisor TO rol_cliente;
GRANT SELECT ON cliente.alerta TO rol_cliente;
GRANT SELECT, INSERT, UPDATE, DELETE ON cliente.nota TO rol_cliente;

GRANT SELECT ON SCHEMA::dw TO rol_consultora;
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::cliente TO rol_consultora;

GRANT SELECT ON SCHEMA::dw TO rol_carga;
GRANT SELECT, INSERT, ALTER ON SCHEMA::stg TO rol_carga;  -- carga masiva en las tablas de paso
GRANT EXECUTE ON OBJECT::stg.usp_vaciar TO rol_carga;
GRANT EXECUTE ON OBJECT::dw.usp_cargar TO rol_carga;
GRANT SELECT ON cliente.dim_cliente TO rol_carga;
GRANT SELECT ON cliente.cliente_emisor TO rol_carga;
GRANT SELECT, INSERT, DELETE ON cliente.alerta TO rol_carga;
GO

/* --- Seguridad por filas --- */
-- La política se borra antes de cambiar la función a la que está ligada
DROP SECURITY POLICY IF EXISTS seguridad.politica_cliente;
GO

CREATE OR ALTER FUNCTION seguridad.fn_cliente_visible (@cliente_id INT)
RETURNS TABLE
WITH SCHEMABINDING
AS
RETURN
    SELECT 1 AS visible
    WHERE IS_MEMBER('rol_consultora') = 1
       OR IS_MEMBER('rol_carga') = 1
       OR IS_MEMBER('db_owner') = 1
       OR EXISTS (SELECT 1
                  FROM cliente.usuario_cliente AS u
                  WHERE u.usuario = USER_NAME() AND u.cliente_id = @cliente_id);
GO

/* FILTER: al leer, cada usuario solo ve sus filas.
   BLOCK: al escribir, nadie puede crear o mover una fila a otro cliente. */
CREATE SECURITY POLICY seguridad.politica_cliente
    ADD FILTER PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.dim_cliente,
    ADD FILTER PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.cliente_emisor,
    ADD FILTER PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.alerta,
    ADD BLOCK  PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.alerta AFTER INSERT,
    ADD FILTER PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.nota,
    ADD BLOCK  PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.nota AFTER INSERT,
    ADD BLOCK  PREDICATE seguridad.fn_cliente_visible(cliente_id) ON cliente.nota AFTER UPDATE
WITH (STATE = ON);
GO
