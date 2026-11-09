/* =====================================================================
   Fase 4 · Reglas de alerta de los dos clientes de demostración
   ---------------------------------------------------------------------
   Dos perfiles distintos, para que cada cliente reciba avisos diferentes:

   Cliente demo A (farmacéutica, Grifols): quiere enterarse pronto.
     - cualquier fondo nuevo en su empresa
     - subida de 0,5 puntos en 5 sesiones
     - la suma supera el 2 %
     - en sus competidoras, solo subidas de 1 punto en 20 sesiones

   Cliente demo B (renovables, Solaria): convive con muchos cortos y solo
   quiere los movimientos grandes.
     - subida de 1,5 puntos en 20 sesiones
     - 15 fondos o más
     - más de 20 sesiones para recomprar (días para cubrir)
     - en sus competidoras, la suma supera el 5 %

   Una regla se identifica por cliente, tipo y ámbito: volver a ejecutar el
   script actualiza el umbral en lugar de duplicarla.
   ===================================================================== */

MERGE cliente.regla_alerta AS d
USING (VALUES
    (1, 'fondo_nuevo',        NULL, 'propia',      N'Entra un fondo nuevo en mi empresa'),
    (1, 'suma_sube_5d',       0.5,  'propia',      N'Mi empresa: los cortos suben 0,5 puntos en 5 sesiones'),
    (1, 'suma_supera',        2.0,  'propia',      N'Mi empresa: los cortos superan el 2 %'),
    (1, 'suma_sube_20d',      1.0,  'competidora', N'Competidoras: los cortos suben 1 punto en 20 sesiones'),
    (2, 'suma_sube_20d',      1.5,  'propia',      N'Mi empresa: los cortos suben 1,5 puntos en 20 sesiones'),
    (2, 'fondos_supera',      15,   'propia',      N'Mi empresa: 15 fondos o más'),
    (2, 'dias_cubrir_supera', 20,   'propia',      N'Mi empresa: más de 20 sesiones para recomprar'),
    (2, 'suma_supera',        5.0,  'competidora', N'Competidoras: los cortos superan el 5 %')
) AS s (cliente_id, tipo, umbral, ambito, descripcion)
ON d.cliente_id = s.cliente_id AND d.tipo = s.tipo AND d.ambito = s.ambito
WHEN MATCHED THEN UPDATE SET umbral = s.umbral, descripcion = s.descripcion, activa = 1
WHEN NOT MATCHED THEN INSERT (cliente_id, tipo, umbral, ambito, descripcion)
                      VALUES (s.cliente_id, s.tipo, s.umbral, s.ambito, s.descripcion);
GO

SELECT r.regla_id, c.nombre AS cliente, r.tipo, r.umbral, r.ambito, r.descripcion
FROM cliente.regla_alerta AS r
JOIN cliente.dim_cliente AS c ON c.cliente_id = r.cliente_id
ORDER BY r.cliente_id, r.regla_id;
GO
