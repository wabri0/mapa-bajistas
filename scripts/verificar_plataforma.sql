/* Consultas de la verificación (scripts/verificar_plataforma.py). Solo leen. */

SELECT TOP 1 carga_id, fin_utc, RIGHT(origen_bronze, 55) AS fichero, version_reglas, version_modelo
FROM dw.carga ORDER BY carga_id DESC;
GO

SELECT 'posiciones' AS tabla, COUNT(*) AS filas, MAX(f.fecha) AS ultimo_dia
FROM dw.fact_posicion_diaria p JOIN dw.dim_fecha f ON f.fecha_id = p.fecha_id
UNION ALL
SELECT 'precios', COUNT(*), MAX(f.fecha) FROM dw.fact_precio_diario p JOIN dw.dim_fecha f ON f.fecha_id = p.fecha_id
UNION ALL
SELECT 'indicadores', COUNT(*), MAX(f.fecha) FROM dw.fact_indicador_diario i JOIN dw.dim_fecha f ON f.fecha_id = i.fecha_id
UNION ALL
SELECT 'notificaciones', COUNT(*), MAX(f.fecha) FROM dw.fact_notificacion n JOIN dw.dim_fecha f ON f.fecha_id = n.fecha_id;
GO

SELECT (SELECT COUNT(*) FROM dw.dim_emisor) AS emisores,
       (SELECT COUNT(DISTINCT emisor_id) FROM dw.fact_notificacion) AS emisores_con_avisos,
       (SELECT COUNT(*) FROM dw.dim_fondo) AS fondos,
       (SELECT COUNT(*) FROM cliente.alerta) AS alertas,
       (SELECT CAST(MAX(creada_utc) AS DATE) FROM cliente.alerta) AS ultima_alerta_creada,
       (SELECT COUNT(*) FROM cliente.regla_alerta WHERE activa = 1) AS reglas_activas;
