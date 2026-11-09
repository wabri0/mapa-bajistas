/* =====================================================================
   Fase 3 · Prueba de la seguridad por filas
   ---------------------------------------------------------------------
   El administrador se hace pasar por cada usuario de prueba (EXECUTE AS) y
   cuenta lo que ve. Resultado esperado:
     demo_cliente_a   1 cliente, 4 empresas seguidas, solo sus notas
     demo_cliente_b   1 cliente, 4 empresas seguidas, solo sus notas
     demo_consultora  todos los clientes y todas las notas
   Las tablas públicas (dw) se ven enteras con cualquier usuario.
   ===================================================================== */

CREATE TABLE #resultado (usuario SYSNAME, clientes INT, empresas_seguidas INT, notas INT,
                         notas_de_otros INT, posiciones_publicas INT);

EXECUTE AS USER = 'demo_cliente_a';
INSERT #resultado
SELECT USER_NAME(), (SELECT COUNT(*) FROM cliente.dim_cliente), (SELECT COUNT(*) FROM cliente.cliente_emisor),
       (SELECT COUNT(*) FROM cliente.nota), (SELECT COUNT(*) FROM cliente.nota WHERE cliente_id <> 1),
       (SELECT COUNT(*) FROM dw.fact_posicion_diaria);
REVERT;

EXECUTE AS USER = 'demo_cliente_b';
INSERT #resultado
SELECT USER_NAME(), (SELECT COUNT(*) FROM cliente.dim_cliente), (SELECT COUNT(*) FROM cliente.cliente_emisor),
       (SELECT COUNT(*) FROM cliente.nota), (SELECT COUNT(*) FROM cliente.nota WHERE cliente_id <> 2),
       (SELECT COUNT(*) FROM dw.fact_posicion_diaria);
REVERT;

EXECUTE AS USER = 'demo_consultora';
INSERT #resultado
SELECT USER_NAME(), (SELECT COUNT(*) FROM cliente.dim_cliente), (SELECT COUNT(*) FROM cliente.cliente_emisor),
       (SELECT COUNT(*) FROM cliente.nota), NULL, (SELECT COUNT(*) FROM dw.fact_posicion_diaria);
REVERT;

SELECT * FROM #resultado;
DROP TABLE #resultado;
GO

/* Un cliente no puede escribir una nota a nombre de otro: la política lo bloquea */
EXECUTE AS USER = 'demo_cliente_a';
BEGIN TRY
    INSERT cliente.nota (cliente_id, emisor_id, fecha_id, texto) VALUES (2, NULL, 20241219, N'Intento de escribir en otro cliente');
    SELECT N'FALLO: el cliente A ha podido escribir en el cliente B' AS prueba_bloqueo;
END TRY
BEGIN CATCH
    SELECT N'OK: bloqueado (' + ERROR_MESSAGE() + N')' AS prueba_bloqueo;
END CATCH;
REVERT;
GO

/* Ni puede leer la tabla de usuarios */
EXECUTE AS USER = 'demo_cliente_a';
BEGIN TRY
    SELECT COUNT(*) AS usuarios_visibles FROM cliente.usuario_cliente;
END TRY
BEGIN CATCH
    SELECT N'OK: sin permiso (' + ERROR_MESSAGE() + N')' AS prueba_usuarios;
END CATCH;
REVERT;
GO
