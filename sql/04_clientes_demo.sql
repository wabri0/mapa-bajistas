/* =====================================================================
   Fase 3 · Dos clientes ficticios para la demostración
   ---------------------------------------------------------------------
   Se ejecuta después de la primera carga (necesita dw.dim_emisor y dw.dim_fecha).
   Los clientes y sus notas son inventados; las empresas que siguen son reales.
     Cliente demo A (farmacéutica): sigue a Grifols y a tres competidoras
     Cliente demo B (renovables):   sigue a Solaria y a tres competidoras
   Usuarios de prueba sin inicio de sesión (solo para EXECUTE AS en las pruebas):
     demo_cliente_a, demo_cliente_b (rol_cliente) y demo_consultora (rol_consultora).
   En producción, cada persona entraría con su cuenta de Microsoft Entra
   (CREATE USER [persona@cliente.com] FROM EXTERNAL PROVIDER) y se añadiría aquí.
   ===================================================================== */

MERGE cliente.dim_cliente AS d
USING (VALUES (1, N'Cliente demo A', N'Farmacéutica'),
              (2, N'Cliente demo B', N'Energías renovables')) AS s (cliente_id, nombre, sector)
ON d.cliente_id = s.cliente_id
WHEN MATCHED THEN UPDATE SET nombre = s.nombre, sector = s.sector
WHEN NOT MATCHED THEN INSERT (cliente_id, nombre, sector) VALUES (s.cliente_id, s.nombre, s.sector);
GO

MERGE cliente.cliente_emisor AS d
USING (
    SELECT v.cliente_id, e.emisor_id, v.rol
    FROM (VALUES
        (1, '959800HSSNXWRKBK4N60', 'propia'),       -- Grifols
        (1, '95980020140005007996', 'competidora'),  -- Almirall
        (1, '95980020140005936480', 'competidora'),  -- Rovi
        (1, '959800FXZQY7U3P1G969', 'competidora'),  -- Faes Farma
        (2, '959800PM2YJU406K2789', 'propia'),       -- Solaria
        (2, '959800L6L2B2GGN73292', 'competidora'),  -- Grenergy
        (2, '254900UPX0OEHTKB9Y44', 'competidora'),  -- Acciona Energía
        (2, '959800M1FVPL5BMW3R13', 'competidora')   -- Soltec
    ) AS v (cliente_id, lei, rol)
    JOIN dw.dim_emisor AS e ON e.lei = v.lei
) AS s ON d.cliente_id = s.cliente_id AND d.emisor_id = s.emisor_id
WHEN MATCHED THEN UPDATE SET rol = s.rol
WHEN NOT MATCHED THEN INSERT (cliente_id, emisor_id, rol) VALUES (s.cliente_id, s.emisor_id, s.rol);
GO

IF DATABASE_PRINCIPAL_ID('demo_cliente_a') IS NULL CREATE USER demo_cliente_a WITHOUT LOGIN;
IF DATABASE_PRINCIPAL_ID('demo_cliente_b') IS NULL CREATE USER demo_cliente_b WITHOUT LOGIN;
IF DATABASE_PRINCIPAL_ID('demo_consultora') IS NULL CREATE USER demo_consultora WITHOUT LOGIN;
GO
ALTER ROLE rol_cliente ADD MEMBER demo_cliente_a;
ALTER ROLE rol_cliente ADD MEMBER demo_cliente_b;
ALTER ROLE rol_consultora ADD MEMBER demo_consultora;
GO

MERGE cliente.usuario_cliente AS d
USING (VALUES (N'demo_cliente_a', 1), (N'demo_cliente_b', 2)) AS s (usuario, cliente_id)
ON d.usuario = s.usuario
WHEN MATCHED THEN UPDATE SET cliente_id = s.cliente_id
WHEN NOT MATCHED THEN INSERT (usuario, cliente_id) VALUES (s.usuario, s.cliente_id);
GO

/* Notas de ejemplo (solo si el cliente aún no tiene ninguna) */
IF NOT EXISTS (SELECT 1 FROM cliente.nota WHERE cliente_id = 1)
INSERT cliente.nota (cliente_id, emisor_id, fecha_id, texto, autor)
SELECT 1, e.emisor_id, v.fecha_id, v.texto, N'demo_cliente_a'
FROM (VALUES
    (20240109, N'Informe de un fondo bajista publicado hoy. Preparar con el equipo financiero la respuesta al mercado.'),
    (20240314, N'Las posiciones cortas siguen subiendo. Revisar el mensaje para la presentación de resultados.')
) AS v (fecha_id, texto)
JOIN dw.dim_emisor AS e ON e.lei = '959800HSSNXWRKBK4N60';

IF NOT EXISTS (SELECT 1 FROM cliente.nota WHERE cliente_id = 2)
INSERT cliente.nota (cliente_id, emisor_id, fecha_id, texto, autor)
SELECT 2, e.emisor_id, v.fecha_id, v.texto, N'demo_cliente_b'
FROM (VALUES
    (20241219, N'Máximo de posiciones cortas. Preparar preguntas y respuestas para la reunión con inversores.')
) AS v (fecha_id, texto)
JOIN dw.dim_emisor AS e ON e.lei = '959800PM2YJU406K2789';
GO
