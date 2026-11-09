/* =====================================================================
   El mapa de los bajistas · Fase 3 · Esquema de la base de datos (gold)
   ---------------------------------------------------------------------
   dw         datos públicos en estrella, iguales para todos los clientes
   cliente    datos confidenciales de cada cliente (protegidos con RLS)
   stg        tablas de paso para la carga diaria (se vacían en cada carga)
   seguridad  función y política de seguridad por filas

   Se puede ejecutar varias veces: solo crea lo que falta.
   El LEI y el nombre del fondo se comparan en binario (BIN2), igual que
   en Python: dos nombres que solo difieren en mayúsculas son fondos distintos.
   ===================================================================== */

IF SCHEMA_ID('dw') IS NULL EXEC('CREATE SCHEMA dw');
GO
IF SCHEMA_ID('cliente') IS NULL EXEC('CREATE SCHEMA cliente');
GO
IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg');
GO
IF SCHEMA_ID('seguridad') IS NULL EXEC('CREATE SCHEMA seguridad');
GO

/* ---------- dw: dimensiones ---------- */

IF OBJECT_ID('dw.dim_fecha') IS NULL
CREATE TABLE dw.dim_fecha (
    fecha_id          INT          NOT NULL CONSTRAINT pk_dim_fecha PRIMARY KEY,  -- AAAAMMDD
    fecha             DATE         NOT NULL CONSTRAINT uq_dim_fecha_fecha UNIQUE,
    anio              SMALLINT     NOT NULL,
    trimestre         TINYINT      NOT NULL,
    mes               TINYINT      NOT NULL,
    nombre_mes        NVARCHAR(12) NOT NULL,
    dia               TINYINT      NOT NULL,
    dia_semana        TINYINT      NOT NULL,  -- 1 = lunes
    nombre_dia        NVARCHAR(10) NOT NULL,
    semana_iso        TINYINT      NOT NULL,
    es_dia_bolsa      BIT          NOT NULL,
    origen_calendario VARCHAR(10)  NOT NULL   -- 'yahoo' (observado) o 'previsto' (regla de festivos)
);
GO

IF OBJECT_ID('dw.dim_emisor') IS NULL
CREATE TABLE dw.dim_emisor (
    emisor_id            INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_dim_emisor PRIMARY KEY,
    lei                  CHAR(20) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT uq_dim_emisor_lei UNIQUE,
    nombre               NVARCHAR(200) NOT NULL,
    isins                VARCHAR(400)  NOT NULL,  -- todos los ISIN con los que ha notificado, separados por comas
    ticker               VARCHAR(20)   NULL,      -- código de Yahoo Finance
    tiene_precios        BIT           NOT NULL,
    acciones_circulacion BIGINT        NULL,      -- dato actual de Yahoo (fase 4)
    nombre_corto         NVARCHAR(100) NULL,      -- «Grifols» en lugar de «GRIFOLS, S.A.» (fase 5)
    primera_notificacion DATE          NOT NULL,
    ultima_notificacion  DATE          NOT NULL,
    notificaciones       INT           NOT NULL
);
GO

IF OBJECT_ID('dw.dim_fondo') IS NULL
CREATE TABLE dw.dim_fondo (
    fondo_id             INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_dim_fondo PRIMARY KEY,
    tenedor              NVARCHAR(200) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT uq_dim_fondo_tenedor UNIQUE,
    grupo_gestor         NVARCHAR(200) NOT NULL,
    grupo_revisado       BIT           NOT NULL,
    primera_notificacion DATE          NOT NULL,
    ultima_notificacion  DATE          NOT NULL,
    notificaciones       INT           NOT NULL
);
GO

-- Fase 4: columna añadida a una tabla ya creada
IF COL_LENGTH('dw.dim_emisor', 'acciones_circulacion') IS NULL
    ALTER TABLE dw.dim_emisor ADD acciones_circulacion BIGINT NULL;
GO
IF COL_LENGTH('dw.dim_emisor', 'nombre_corto') IS NULL
    ALTER TABLE dw.dim_emisor ADD nombre_corto NVARCHAR(100) NULL;
GO

/* ---------- dw: hechos ---------- */

IF OBJECT_ID('dw.fact_posicion_diaria') IS NULL
CREATE TABLE dw.fact_posicion_diaria (
    emisor_id INT          NOT NULL CONSTRAINT fk_posicion_emisor REFERENCES dw.dim_emisor (emisor_id),
    fecha_id  INT          NOT NULL CONSTRAINT fk_posicion_fecha  REFERENCES dw.dim_fecha (fecha_id),
    fondo_id  INT          NOT NULL CONSTRAINT fk_posicion_fondo  REFERENCES dw.dim_fondo (fondo_id),
    pct       DECIMAL(7, 4) NOT NULL,  -- % del capital en corto (>= 0,5)
    CONSTRAINT pk_fact_posicion_diaria PRIMARY KEY (emisor_id, fecha_id, fondo_id)
);
GO

IF OBJECT_ID('dw.fact_precio_diario') IS NULL
CREATE TABLE dw.fact_precio_diario (
    emisor_id       INT            NOT NULL CONSTRAINT fk_precio_emisor REFERENCES dw.dim_emisor (emisor_id),
    fecha_id        INT            NOT NULL CONSTRAINT fk_precio_fecha  REFERENCES dw.dim_fecha (fecha_id),
    cierre          DECIMAL(19, 6) NOT NULL,
    cierre_ajustado DECIMAL(19, 6) NULL,      -- ajustado por dividendos y ampliaciones
    volumen         BIGINT         NOT NULL,  -- acciones negociadas
    CONSTRAINT pk_fact_precio_diario PRIMARY KEY (emisor_id, fecha_id)
);
GO

IF OBJECT_ID('dw.fact_notificacion') IS NULL
CREATE TABLE dw.fact_notificacion (
    emisor_id             INT           NOT NULL CONSTRAINT fk_notif_emisor REFERENCES dw.dim_emisor (emisor_id),
    fecha_id              INT           NOT NULL CONSTRAINT fk_notif_fecha  REFERENCES dw.dim_fecha (fecha_id),
    fondo_id              INT           NOT NULL CONSTRAINT fk_notif_fondo  REFERENCES dw.dim_fondo (fondo_id),
    isin                  CHAR(12)      NOT NULL,
    pct                   DECIMAL(7, 4) NOT NULL,  -- incluye avisos por debajo del 0,5 % (cierres)
    fecha_primera_captura DATETIME2(0)  NULL,      -- vacía en la carga histórica
    CONSTRAINT pk_fact_notificacion PRIMARY KEY (emisor_id, fecha_id, fondo_id)
);
GO

/* Fase 4: indicadores diarios por emisor (se calculan en Python, src/alertas/indicadores.py) */
IF OBJECT_ID('dw.fact_indicador_diario') IS NULL
CREATE TABLE dw.fact_indicador_diario (
    emisor_id         INT            NOT NULL CONSTRAINT fk_indicador_emisor REFERENCES dw.dim_emisor (emisor_id),
    fecha_id          INT            NOT NULL CONSTRAINT fk_indicador_fecha  REFERENCES dw.dim_fecha (fecha_id),
    suma_pct          DECIMAL(7, 4)  NOT NULL,  -- suma de posiciones cortas publicadas (%)
    num_fondos        SMALLINT       NOT NULL,
    fondos_nuevos     SMALLINT       NOT NULL,  -- sin posición en las 20 sesiones anteriores
    salidas           SMALLINT       NOT NULL,
    var_suma_5d       DECIMAL(7, 4)  NOT NULL,  -- puntos porcentuales
    var_suma_20d      DECIMAL(7, 4)  NOT NULL,
    peso_mayor_fondo  DECIMAL(7, 4)  NULL,      -- % de la suma en manos del mayor fondo
    cierre            DECIMAL(19, 6) NULL,
    var_precio_5d     DECIMAL(9, 4)  NULL,      -- %
    var_precio_20d    DECIMAL(9, 4)  NULL,
    volumen_medio_20d DECIMAL(19, 2) NULL,
    dias_cubrir       DECIMAL(9, 2)  NULL,      -- sesiones para recomprar con el volumen medio
    CONSTRAINT pk_fact_indicador_diario PRIMARY KEY (emisor_id, fecha_id)
);
GO

/* Registro de cargas: qué fichero de la CNMV y qué versión de las reglas hay en la base */
IF OBJECT_ID('dw.carga') IS NULL
CREATE TABLE dw.carga (
    carga_id            INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_carga PRIMARY KEY,
    fin_utc             DATETIME2(0)  NOT NULL CONSTRAINT df_carga_fin DEFAULT SYSUTCDATETIME(),
    origen_bronze       NVARCHAR(400) NOT NULL,
    version_reglas      NVARCHAR(100) NOT NULL,
    version_modelo      NVARCHAR(50)  NOT NULL,
    filas_posicion      INT           NOT NULL,
    filas_precio        INT           NOT NULL,
    filas_notificacion  INT           NOT NULL,
    ultimo_dia_posicion DATE          NULL,
    ultimo_dia_precio   DATE          NULL,
    filas_indicador     INT           NULL
);
GO
IF COL_LENGTH('dw.carga', 'filas_indicador') IS NULL
    ALTER TABLE dw.carga ADD filas_indicador INT NULL;
GO

/* ---------- cliente: datos confidenciales ---------- */

IF OBJECT_ID('cliente.dim_cliente') IS NULL
CREATE TABLE cliente.dim_cliente (
    cliente_id INT           NOT NULL CONSTRAINT pk_dim_cliente PRIMARY KEY,
    nombre     NVARCHAR(100) NOT NULL,
    sector     NVARCHAR(50)  NULL,
    alta_utc   DATETIME2(0)  NOT NULL CONSTRAINT df_cliente_alta DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID('cliente.cliente_emisor') IS NULL
CREATE TABLE cliente.cliente_emisor (
    cliente_id INT         NOT NULL CONSTRAINT fk_ce_cliente REFERENCES cliente.dim_cliente (cliente_id),
    emisor_id  INT         NOT NULL CONSTRAINT fk_ce_emisor  REFERENCES dw.dim_emisor (emisor_id),
    rol        VARCHAR(12) NOT NULL CONSTRAINT ck_ce_rol CHECK (rol IN ('propia', 'competidora')),
    CONSTRAINT pk_cliente_emisor PRIMARY KEY (cliente_id, emisor_id)
);
GO

IF OBJECT_ID('cliente.alerta') IS NULL
CREATE TABLE cliente.alerta (
    alerta_id  BIGINT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_alerta PRIMARY KEY,
    cliente_id INT           NOT NULL CONSTRAINT fk_alerta_cliente REFERENCES cliente.dim_cliente (cliente_id),
    emisor_id  INT           NOT NULL CONSTRAINT fk_alerta_emisor  REFERENCES dw.dim_emisor (emisor_id),
    fecha_id   INT           NOT NULL CONSTRAINT fk_alerta_fecha   REFERENCES dw.dim_fecha (fecha_id),
    tipo       VARCHAR(40)   NOT NULL,
    mensaje    NVARCHAR(500) NOT NULL,
    valor      DECIMAL(9, 4) NULL,
    creada_utc DATETIME2(0)  NOT NULL CONSTRAINT df_alerta_creada DEFAULT SYSUTCDATETIME()
    -- regla_id, fondo_id y enviada_utc se añaden más abajo (fase 4), después de crear regla_alerta
);
GO

IF OBJECT_ID('cliente.nota') IS NULL
CREATE TABLE cliente.nota (
    nota_id    INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_nota PRIMARY KEY,
    cliente_id INT            NOT NULL CONSTRAINT fk_nota_cliente REFERENCES cliente.dim_cliente (cliente_id),
    emisor_id  INT            NULL     CONSTRAINT fk_nota_emisor  REFERENCES dw.dim_emisor (emisor_id),
    fecha_id   INT            NOT NULL CONSTRAINT fk_nota_fecha   REFERENCES dw.dim_fecha (fecha_id),
    texto      NVARCHAR(2000) NOT NULL,
    autor      NVARCHAR(128)  NOT NULL CONSTRAINT df_nota_autor DEFAULT USER_NAME(),
    creada_utc DATETIME2(0)   NOT NULL CONSTRAINT df_nota_creada DEFAULT SYSUTCDATETIME()
);
GO

/* Fase 4: reglas de alerta de cada cliente (tipos en src/alertas/reglas.py) */
IF OBJECT_ID('cliente.regla_alerta') IS NULL
CREATE TABLE cliente.regla_alerta (
    regla_id    INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_regla_alerta PRIMARY KEY,
    cliente_id  INT           NOT NULL CONSTRAINT fk_regla_cliente REFERENCES cliente.dim_cliente (cliente_id),
    tipo        VARCHAR(30)   NOT NULL CONSTRAINT ck_regla_tipo CHECK (tipo IN (
                    'fondo_nuevo', 'suma_supera', 'suma_sube_5d', 'suma_sube_20d', 'fondos_supera',
                    'dias_cubrir_supera')),
    umbral      DECIMAL(9, 4) NULL,
    ambito      VARCHAR(12)   NOT NULL CONSTRAINT ck_regla_ambito CHECK (ambito IN ('propia', 'competidora', 'todas')),
    descripcion NVARCHAR(200) NOT NULL,
    activa      BIT           NOT NULL CONSTRAINT df_regla_activa DEFAULT 1,
    CONSTRAINT ck_regla_umbral CHECK (tipo = 'fondo_nuevo' OR umbral IS NOT NULL)
);
GO

-- Fase 4: columnas de cliente.alerta
--   regla_id     regla que la generó
--   fondo_id     fondo que entra (reglas fondo_nuevo)
--   enviada_utc  cuándo se envió por correo (en producción; el prototipo solo las registra)
IF COL_LENGTH('cliente.alerta', 'regla_id') IS NULL
    ALTER TABLE cliente.alerta ADD regla_id INT NULL CONSTRAINT fk_alerta_regla REFERENCES cliente.regla_alerta (regla_id),
                                   fondo_id INT NULL CONSTRAINT fk_alerta_fondo REFERENCES dw.dim_fondo (fondo_id),
                                   enviada_utc DATETIME2(0) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'uq_alerta_evento')
    CREATE UNIQUE INDEX uq_alerta_evento ON cliente.alerta (cliente_id, regla_id, emisor_id, fecha_id, fondo_id);
GO

/* Qué usuario de la base de datos pertenece a qué cliente. La consulta la regla de RLS. */
IF OBJECT_ID('cliente.usuario_cliente') IS NULL
CREATE TABLE cliente.usuario_cliente (
    usuario    NVARCHAR(128) NOT NULL CONSTRAINT pk_usuario_cliente PRIMARY KEY,
    cliente_id INT           NOT NULL CONSTRAINT fk_uc_cliente REFERENCES cliente.dim_cliente (cliente_id)
);
GO

/* ---------- stg: tablas de paso (claves naturales, sin restricciones) ----------
   Tipos sencillos (INT, FLOAT, NVARCHAR) que coinciden con los de Python; la
   conversión a los tipos definitivos la hace dw.usp_cargar. */

IF OBJECT_ID('stg.dim_fecha') IS NULL
CREATE TABLE stg.dim_fecha (
    fecha_id INT, fecha DATE, anio INT, trimestre INT, mes INT, nombre_mes NVARCHAR(12),
    dia INT, dia_semana INT, nombre_dia NVARCHAR(10), semana_iso INT,
    es_dia_bolsa BIT, origen_calendario NVARCHAR(10)
);
GO

IF OBJECT_ID('stg.dim_emisor') IS NULL
CREATE TABLE stg.dim_emisor (
    lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2, nombre NVARCHAR(200), isins NVARCHAR(400),
    ticker NVARCHAR(20), tiene_precios BIT, primera_notificacion DATE, ultima_notificacion DATE,
    notificaciones INT, acciones_circulacion BIGINT, nombre_corto NVARCHAR(100)
);
GO
IF COL_LENGTH('stg.dim_emisor', 'acciones_circulacion') IS NULL
    ALTER TABLE stg.dim_emisor ADD acciones_circulacion BIGINT;
GO
IF COL_LENGTH('stg.dim_emisor', 'nombre_corto') IS NULL
    ALTER TABLE stg.dim_emisor ADD nombre_corto NVARCHAR(100);
GO

IF OBJECT_ID('stg.dim_fondo') IS NULL
CREATE TABLE stg.dim_fondo (
    tenedor NVARCHAR(200) COLLATE Latin1_General_100_BIN2, grupo_gestor NVARCHAR(200), grupo_revisado BIT,
    primera_notificacion DATE, ultima_notificacion DATE, notificaciones INT
);
GO

IF OBJECT_ID('stg.posicion_diaria') IS NULL
CREATE TABLE stg.posicion_diaria (
    fecha DATE, lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2,
    tenedor NVARCHAR(200) COLLATE Latin1_General_100_BIN2, pct FLOAT
);
GO

IF OBJECT_ID('stg.precio_diario') IS NULL
CREATE TABLE stg.precio_diario (
    fecha DATE, lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2, cierre FLOAT, cierre_ajustado FLOAT,
    volumen BIGINT
);
GO

IF OBJECT_ID('stg.notificacion') IS NULL
CREATE TABLE stg.notificacion (
    fecha DATE, lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2,
    tenedor NVARCHAR(200) COLLATE Latin1_General_100_BIN2, isin NVARCHAR(12), pct FLOAT,
    fecha_primera_captura DATETIME2(0)
);
GO

IF OBJECT_ID('stg.indicador_diario') IS NULL
CREATE TABLE stg.indicador_diario (
    fecha DATE, lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2, suma_pct FLOAT, num_fondos INT,
    fondos_nuevos INT, salidas INT, var_suma_5d FLOAT, var_suma_20d FLOAT, peso_mayor_fondo FLOAT,
    cierre FLOAT, var_precio_5d FLOAT, var_precio_20d FLOAT, volumen_medio_20d FLOAT, dias_cubrir FLOAT
);
GO

IF OBJECT_ID('stg.alerta') IS NULL
CREATE TABLE stg.alerta (
    cliente_id INT, regla_id INT, lei NVARCHAR(20) COLLATE Latin1_General_100_BIN2, fecha DATE,
    tenedor NVARCHAR(200) COLLATE Latin1_General_100_BIN2, tipo NVARCHAR(40), valor FLOAT, mensaje NVARCHAR(500)
);
GO
