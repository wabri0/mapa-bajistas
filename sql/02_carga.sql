/* =====================================================================
   Fase 3 · Procedimientos de carga
   ---------------------------------------------------------------------
   Cada día, después de reconstruir la capa silver, la Azure Function:
     1. vacía las tablas stg            (EXEC stg.usp_vaciar)
     2. copia en stg las tablas gold    (carga masiva desde Python)
     3. ejecuta dw.usp_cargar, que en una sola transacción:
        - actualiza las dimensiones (MERGE por clave natural: los *_id no cambian
          nunca, porque las tablas de clientes los usan)
        - sustituye por completo los hechos (la silver se reconstruye entera y
          una regla nueva puede cambiar el pasado: «el dato manda»)
        - comprueba que no se ha perdido ninguna fila en los cruces
        - deja constancia en dw.carga
   Si algo falla, la transacción se deshace y la base queda como estaba.
   EXECUTE AS OWNER: la identidad de la Function solo necesita permiso para
   ejecutar estos procedimientos, no para vaciar tablas de dw.
   ===================================================================== */

CREATE OR ALTER PROCEDURE stg.usp_vaciar
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    TRUNCATE TABLE stg.dim_fecha;
    TRUNCATE TABLE stg.dim_emisor;
    TRUNCATE TABLE stg.dim_fondo;
    TRUNCATE TABLE stg.posicion_diaria;
    TRUNCATE TABLE stg.precio_diario;
    TRUNCATE TABLE stg.notificacion;
END;
GO

CREATE OR ALTER PROCEDURE dw.usp_cargar
    @origen_bronze  NVARCHAR(400),
    @version_reglas NVARCHAR(100),
    @version_modelo NVARCHAR(50)
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @esperadas INT, @cargadas INT, @mensaje NVARCHAR(400);
    DECLARE @posiciones INT, @precios INT, @notificaciones INT;

    IF NOT EXISTS (SELECT 1 FROM stg.posicion_diaria) OR NOT EXISTS (SELECT 1 FROM stg.dim_fecha)
        THROW 50000, N'Las tablas stg están vacías: no se carga nada', 1;

    BEGIN TRANSACTION;

    /* --- Dimensiones --- */
    MERGE dw.dim_fecha AS d
    USING stg.dim_fecha AS s ON d.fecha_id = s.fecha_id
    WHEN MATCHED AND (d.es_dia_bolsa <> s.es_dia_bolsa OR d.origen_calendario <> s.origen_calendario) THEN
        UPDATE SET es_dia_bolsa = s.es_dia_bolsa, origen_calendario = s.origen_calendario
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (fecha_id, fecha, anio, trimestre, mes, nombre_mes, dia, dia_semana, nombre_dia, semana_iso,
                es_dia_bolsa, origen_calendario)
        VALUES (s.fecha_id, s.fecha, s.anio, s.trimestre, s.mes, s.nombre_mes, s.dia, s.dia_semana,
                s.nombre_dia, s.semana_iso, s.es_dia_bolsa, s.origen_calendario);

    MERGE dw.dim_emisor AS d
    USING stg.dim_emisor AS s ON d.lei = s.lei
    WHEN MATCHED THEN
        UPDATE SET nombre = s.nombre, isins = s.isins, ticker = s.ticker, tiene_precios = s.tiene_precios,
                   primera_notificacion = s.primera_notificacion, ultima_notificacion = s.ultima_notificacion,
                   notificaciones = s.notificaciones
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (lei, nombre, isins, ticker, tiene_precios, primera_notificacion, ultima_notificacion, notificaciones)
        VALUES (s.lei, s.nombre, s.isins, s.ticker, s.tiene_precios, s.primera_notificacion,
                s.ultima_notificacion, s.notificaciones);

    MERGE dw.dim_fondo AS d
    USING stg.dim_fondo AS s ON d.tenedor = s.tenedor
    WHEN MATCHED THEN
        UPDATE SET grupo_gestor = s.grupo_gestor, grupo_revisado = s.grupo_revisado,
                   primera_notificacion = s.primera_notificacion, ultima_notificacion = s.ultima_notificacion,
                   notificaciones = s.notificaciones
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (tenedor, grupo_gestor, grupo_revisado, primera_notificacion, ultima_notificacion, notificaciones)
        VALUES (s.tenedor, s.grupo_gestor, s.grupo_revisado, s.primera_notificacion, s.ultima_notificacion,
                s.notificaciones);

    /* --- Hechos: se sustituyen enteros --- */
    TRUNCATE TABLE dw.fact_posicion_diaria;
    INSERT dw.fact_posicion_diaria (emisor_id, fecha_id, fondo_id, pct)
    SELECT e.emisor_id, f.fecha_id, o.fondo_id, CAST(s.pct AS DECIMAL(7, 4))
    FROM stg.posicion_diaria AS s
    JOIN dw.dim_fecha  AS f ON f.fecha = s.fecha
    JOIN dw.dim_emisor AS e ON e.lei = s.lei
    JOIN dw.dim_fondo  AS o ON o.tenedor = s.tenedor;
    SET @cargadas = @@ROWCOUNT;
    SELECT @esperadas = COUNT(*) FROM stg.posicion_diaria;
    IF @cargadas <> @esperadas
    BEGIN
        SET @mensaje = CONCAT(N'Posiciones: se esperaban ', @esperadas, N' filas y se han cargado ', @cargadas);
        THROW 50001, @mensaje, 1;
    END;
    SET @posiciones = @cargadas;

    TRUNCATE TABLE dw.fact_precio_diario;
    INSERT dw.fact_precio_diario (emisor_id, fecha_id, cierre, cierre_ajustado, volumen)
    SELECT e.emisor_id, f.fecha_id, CAST(s.cierre AS DECIMAL(19, 6)), CAST(s.cierre_ajustado AS DECIMAL(19, 6)),
           s.volumen
    FROM stg.precio_diario AS s
    JOIN dw.dim_fecha  AS f ON f.fecha = s.fecha
    JOIN dw.dim_emisor AS e ON e.lei = s.lei;
    SET @cargadas = @@ROWCOUNT;
    SELECT @esperadas = COUNT(*) FROM stg.precio_diario;
    IF @cargadas <> @esperadas
    BEGIN
        SET @mensaje = CONCAT(N'Precios: se esperaban ', @esperadas, N' filas y se han cargado ', @cargadas);
        THROW 50002, @mensaje, 1;
    END;
    SET @precios = @cargadas;

    TRUNCATE TABLE dw.fact_notificacion;
    INSERT dw.fact_notificacion (emisor_id, fecha_id, fondo_id, isin, pct, fecha_primera_captura)
    SELECT e.emisor_id, f.fecha_id, o.fondo_id, s.isin, CAST(s.pct AS DECIMAL(7, 4)), s.fecha_primera_captura
    FROM stg.notificacion AS s
    JOIN dw.dim_fecha  AS f ON f.fecha = s.fecha
    JOIN dw.dim_emisor AS e ON e.lei = s.lei
    JOIN dw.dim_fondo  AS o ON o.tenedor = s.tenedor;
    SET @cargadas = @@ROWCOUNT;
    SELECT @esperadas = COUNT(*) FROM stg.notificacion;
    IF @cargadas <> @esperadas
    BEGIN
        SET @mensaje = CONCAT(N'Notificaciones: se esperaban ', @esperadas, N' filas y se han cargado ', @cargadas);
        THROW 50003, @mensaje, 1;
    END;
    SET @notificaciones = @cargadas;

    INSERT dw.carga (origen_bronze, version_reglas, version_modelo, filas_posicion, filas_precio,
                     filas_notificacion, ultimo_dia_posicion, ultimo_dia_precio)
    VALUES (@origen_bronze, @version_reglas, @version_modelo, @posiciones, @precios, @notificaciones,
            (SELECT MAX(fecha) FROM stg.posicion_diaria), (SELECT MAX(fecha) FROM stg.precio_diario));

    COMMIT TRANSACTION;

    SELECT TOP (1) * FROM dw.carga ORDER BY carga_id DESC;
END;
GO
