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
    ultimo_dia_precio   DATE          NULL
);
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
    notificaciones INT
);
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
