"""Genera el panel de Power BI como proyecto en texto (PBIP): modelo TMDL + informe PBIR.

Uso:  python scripts/generar_powerbi.py     → crea powerbi/MapaBajistas.pbip y sus carpetas

El modelo importa las tablas de Azure SQL (esquemas dw y cliente) y define:
- relaciones del modelo en estrella, medidas en DAX y roles de seguridad por cliente
  (Cliente demo A, Cliente demo B y Consultora), que se prueban con «Ver como» en Power BI Desktop.
El informe tiene cuatro páginas: Mercado, Empresa, Fondos y gestoras, y Alertas del cliente.

Si se edita el panel en Power BI Desktop y se guarda, Desktop reescribe estos ficheros:
volver a ejecutar el generador sobrescribe esos cambios.
"""
import json
import re
import shutil
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "powerbi"
NOMBRE = "MapaBajistas"
TEMA = Path(__file__).with_name("powerbi_tema_CY24SU10.json")
SERVIDOR = "sql-mapa-bajistas.database.windows.net"
BASE_DATOS = "sqldb-mapa-bajistas"
ESQUEMA = "https://developer.microsoft.com/json-schemas/fabric/"
NOTA_CNMV = ("Fuente: CNMV, posiciones cortas netas (información gratuita en www.cnmv.es). "
             "Precios: Yahoo Finance. Indicadores y alertas: cálculo propio.")
ROJO, GRIS, TINTA = "#B13A2C", "#5B6875", "#15212C"


def guid(texto):
    """GUID estable a partir de un texto: regenerar no cambia los identificadores."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mapa-bajistas/{texto}"))


def escribir(ruta, contenido):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenido, (dict, list)):
        contenido = json.dumps(contenido, indent=2, ensure_ascii=False)
    ruta.write_text(contenido, encoding="utf-8", newline="\n")


# =====================================================================
# Modelo semántico (TMDL)
# =====================================================================

# tabla → (esquema SQL, [(columna, tipo TMDL, opciones)], columnas calculadas en Power Query)
ENTERO, TEXTO, DECIMAL, FECHA, LOGICO = "int64", "string", "double", "dateTime", "boolean"
TABLAS = {
    "dim_fecha": ("dw", [("fecha_id", ENTERO, {"oculta": True}), ("fecha", FECHA, {}), ("anio", ENTERO, {}),
                         ("trimestre", ENTERO, {}), ("mes", ENTERO, {}), ("nombre_mes", TEXTO, {"orden": "mes"}),
                         ("es_dia_bolsa", LOGICO, {}), ("anio_mes", TEXTO, {"calculada": True})]),
    "dim_emisor": ("dw", [("emisor_id", ENTERO, {"oculta": True}), ("lei", TEXTO, {}), ("nombre", TEXTO, {}),
                          ("nombre_corto", TEXTO, {}), ("ticker", TEXTO, {}), ("tiene_precios", LOGICO, {})]),
    "dim_fondo": ("dw", [("fondo_id", ENTERO, {"oculta": True}), ("tenedor", TEXTO, {}),
                         ("grupo_gestor", TEXTO, {}), ("grupo_revisado", LOGICO, {})]),
    "fact_posicion_diaria": ("dw", [("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                                    ("fondo_id", ENTERO, {"oculta": True}), ("pct", DECIMAL, {"oculta": True})]),
    "fact_precio_diario": ("dw", [("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                                  ("cierre", DECIMAL, {"oculta": True}), ("volumen", ENTERO, {"oculta": True})]),
    "fact_indicador_diario": ("dw", [("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                                     ("suma_pct", DECIMAL, {"oculta": True}), ("num_fondos", ENTERO, {"oculta": True}),
                                     ("fondos_nuevos", ENTERO, {"oculta": True}), ("salidas", ENTERO, {"oculta": True}),
                                     ("var_suma_5d", DECIMAL, {"oculta": True}),
                                     ("var_suma_20d", DECIMAL, {"oculta": True}),
                                     ("peso_mayor_fondo", DECIMAL, {"oculta": True}),
                                     ("var_precio_20d", DECIMAL, {"oculta": True}),
                                     ("dias_cubrir", DECIMAL, {"oculta": True})]),
    "fact_notificacion": ("dw", [("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                                 ("fondo_id", ENTERO, {"oculta": True}), ("isin", TEXTO, {}),
                                 ("pct", DECIMAL, {"oculta": True})]),
    "dim_cliente": ("cliente", [("cliente_id", ENTERO, {"oculta": True}), ("nombre", TEXTO, {}), ("sector", TEXTO, {})]),
    "cliente_emisor": ("cliente", [("cliente_id", ENTERO, {"oculta": True}), ("emisor_id", ENTERO, {"oculta": True}),
                                   ("rol", TEXTO, {})]),
    "alerta": ("cliente", [("alerta_id", ENTERO, {"oculta": True}), ("cliente_id", ENTERO, {"oculta": True}),
                           ("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                           ("tipo", TEXTO, {}), ("mensaje", TEXTO, {}), ("fecha", FECHA, {"calculada": True})]),
    "nota": ("cliente", [("nota_id", ENTERO, {"oculta": True}), ("cliente_id", ENTERO, {"oculta": True}),
                         ("emisor_id", ENTERO, {"oculta": True}), ("fecha_id", ENTERO, {"oculta": True}),
                         ("texto", TEXTO, {}), ("autor", TEXTO, {}), ("fecha", FECHA, {"calculada": True})]),
    "regla_alerta": ("cliente", [("regla_id", ENTERO, {"oculta": True}), ("cliente_id", ENTERO, {"oculta": True}),
                                 ("tipo", TEXTO, {}), ("umbral", DECIMAL, {}), ("ambito", TEXTO, {}),
                                 ("descripcion", TEXTO, {}), ("activa", LOGICO, {})]),
}

# (desde: tabla.columna del lado «muchos», hasta: tabla.columna del lado «uno»)
RELACIONES = [
    ("fact_posicion_diaria.emisor_id", "dim_emisor.emisor_id"),
    ("fact_posicion_diaria.fecha_id", "dim_fecha.fecha_id"),
    ("fact_posicion_diaria.fondo_id", "dim_fondo.fondo_id"),
    ("fact_precio_diario.emisor_id", "dim_emisor.emisor_id"),
    ("fact_precio_diario.fecha_id", "dim_fecha.fecha_id"),
    ("fact_indicador_diario.emisor_id", "dim_emisor.emisor_id"),
    ("fact_indicador_diario.fecha_id", "dim_fecha.fecha_id"),
    ("fact_notificacion.emisor_id", "dim_emisor.emisor_id"),
    ("fact_notificacion.fecha_id", "dim_fecha.fecha_id"),
    ("fact_notificacion.fondo_id", "dim_fondo.fondo_id"),
    ("cliente_emisor.cliente_id", "dim_cliente.cliente_id"),
    ("cliente_emisor.emisor_id", "dim_emisor.emisor_id"),
    ("alerta.cliente_id", "dim_cliente.cliente_id"),
    ("alerta.emisor_id", "dim_emisor.emisor_id"),
    ("alerta.fecha_id", "dim_fecha.fecha_id"),
    ("nota.cliente_id", "dim_cliente.cliente_id"),
    ("nota.emisor_id", "dim_emisor.emisor_id"),
    ("nota.fecha_id", "dim_fecha.fecha_id"),
    ("regla_alerta.cliente_id", "dim_cliente.cliente_id"),
]

ULTIMO = "VAR f = [Último día] RETURN"
# tabla → [(nombre, DAX en una línea, formato, oculta)]
MEDIDAS = {
    "fact_indicador_diario": [
        ("Cortas %", "AVERAGEX(VALUES(dim_fecha[fecha_id]), CALCULATE(SUM(fact_indicador_diario[suma_pct])))",
         "0.00", False),
        ("Cortas máx %", "MAXX(VALUES(dim_fecha[fecha_id]), CALCULATE(SUM(fact_indicador_diario[suma_pct])))",
         "0.00", False),
        ("Fondos con posición", "AVERAGEX(VALUES(dim_fecha[fecha_id]), "
                                "CALCULATE(SUM(fact_indicador_diario[num_fondos])))", "0.0", False),
        ("Días para cubrir", "AVERAGE(fact_indicador_diario[dias_cubrir])", "0.0", False),
        ("Color calor", "VAR v = [Cortas %] RETURN SWITCH(TRUE(), ISBLANK(v), BLANK(), v >= 10, \"#7F1D1D\", "
                        "v >= 5, \"#B91C1C\", v >= 3, \"#DC2626\", v >= 2, \"#F87171\", v >= 1, \"#FCA5A5\", "
                        "v > 0, \"#FEE2E2\", \"#FFFFFF\")", None, True),
        ("Color texto calor", "IF([Cortas %] >= 3, \"#FFFFFF\", \"#15212C\")", None, True),
    ],
    "fact_posicion_diaria": [
        ("Último día", "CALCULATE(MAX(fact_posicion_diaria[fecha_id]), REMOVEFILTERS())", "0", True),
        ("Cortas hoy %", f"{ULTIMO} CALCULATE(SUM(fact_posicion_diaria[pct]), REMOVEFILTERS(dim_fecha), "
                         "dim_fecha[fecha_id] = f)", "0.00", False),
        ("Fondos hoy", f"{ULTIMO} CALCULATE(DISTINCTCOUNT(fact_posicion_diaria[fondo_id]), REMOVEFILTERS(dim_fecha), "
                       "dim_fecha[fecha_id] = f)", "0", False),
        ("Empresas con cortos hoy", f"{ULTIMO} CALCULATE(DISTINCTCOUNT(fact_posicion_diaria[emisor_id]), "
                                    "REMOVEFILTERS(dim_fecha), dim_fecha[fecha_id] = f)", "0", False),
        ("Gestoras hoy", f"{ULTIMO} CALCULATE(CALCULATE(DISTINCTCOUNT(dim_fondo[grupo_gestor]), fact_posicion_diaria), "
                         "REMOVEFILTERS(dim_fecha), dim_fecha[fecha_id] = f)", "0", False),
        ("Fecha de los datos", f"{ULTIMO} \"Posiciones publicadas hasta el \" & "
                               "FORMAT(LOOKUPVALUE(dim_fecha[fecha], dim_fecha[fecha_id], f), \"dd/mm/yyyy\")",
         None, False),
        ("Color calor hoy", "VAR v = [Cortas hoy %] RETURN SWITCH(TRUE(), ISBLANK(v), BLANK(), v >= 3, \"#B91C1C\", "
                            "v >= 2, \"#DC2626\", v >= 1, \"#F87171\", v > 0, \"#FCA5A5\", \"#FFFFFF\")", None, True),
        ("Color texto calor hoy", "IF([Cortas hoy %] >= 2, \"#FFFFFF\", \"#15212C\")", None, True),
    ],
    "fact_precio_diario": [
        ("Cotización €", "AVERAGE(fact_precio_diario[cierre])", "0.00", False),
    ],
    "alerta": [
        ("Alertas", "COUNTROWS(alerta)", "0", False),
    ],
}

# Seguridad: cada rol ve solo su cliente en las tablas del esquema cliente (los datos públicos, enteros)
ROLES = {"Cliente demo A": "dim_cliente[cliente_id] = 1", "Cliente demo B": "dim_cliente[cliente_id] = 2",
         "Consultora": None}


def partition_m(tabla, esquema, columnas):
    origen = [c for c, _, o in columnas if not o.get("calculada")]
    lista = ", ".join(f'"{c}"' for c in origen)
    tipos = {ENTERO: "Int64.Type", TEXTO: "type text", DECIMAL: "type number", FECHA: "type date",
             LOGICO: "type logical"}
    tipos_origen = ", ".join(f'{{"{c}", {tipos[t]}}}' for c, t, o in columnas if not o.get("calculada"))
    pasos = [
        "Origen = Sql.Database(Servidor, BaseDatos)",
        f'Tabla = Origen{{[Schema = "{esquema}", Item = "{tabla}"]}}[Data]',
        f"Columnas = Table.SelectColumns(Tabla, {{{lista}}})",
        f"Tipos = Table.TransformColumnTypes(Columnas, {{{tipos_origen}}})",
    ]
    ultimo = "Tipos"
    if tabla == "dim_fecha":
        pasos.append('ConMes = Table.AddColumn(Tipos, "anio_mes", each Text.From([anio]) & "-" & '
                     'Text.PadStart(Text.From([mes]), 2, "0"), type text)')
        ultimo = "ConMes"
    if tabla in ("alerta", "nota"):
        pasos.append('ConFecha = Table.AddColumn(Tipos, "fecha", each #date(Number.IntegerDivide([fecha_id], 10000), '
                     'Number.Mod(Number.IntegerDivide([fecha_id], 100), 100), Number.Mod([fecha_id], 100)), type date)')
        ultimo = "ConFecha"
    cuerpo = ",\n".join("\t\t\t\t\t" + p for p in pasos)
    return f"\t\t\t\tlet\n{cuerpo}\n\t\t\t\tin\n\t\t\t\t\t{ultimo}"


def nombre_tmdl(nombre):
    """Los nombres con espacios, acentos o símbolos van entre comillas simples en TMDL."""
    return nombre if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre) else f"'{nombre}'"


def tabla_tmdl(tabla, esquema, columnas):
    lineas = [f"table {tabla}", f"\tlineageTag: {guid(tabla)}", ""]
    for nombre, dax, formato, oculta in MEDIDAS.get(tabla, []):
        lineas.append(f"\tmeasure {nombre_tmdl(nombre)} = {dax}")
        if formato:
            lineas.append(f"\t\tformatString: {formato}")
        if oculta:
            lineas.append("\t\tisHidden")
        lineas += [f"\t\tlineageTag: {guid(tabla + '/' + nombre)}", ""]
    for col, tipo, opc in columnas:
        lineas.append(f"\tcolumn {col}")
        lineas.append(f"\t\tdataType: {tipo}")
        if tipo == FECHA:
            lineas.append("\t\tformatString: dd/mm/yyyy")
        elif tipo == DECIMAL:
            lineas.append("\t\tformatString: 0.00")
        elif tipo == ENTERO:
            lineas.append("\t\tformatString: 0")
        if opc.get("oculta"):
            lineas.append("\t\tisHidden")
        lineas += [f"\t\tlineageTag: {guid(tabla + '.' + col)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {col}"]
        if opc.get("orden"):
            lineas.append(f"\t\tsortByColumn: {opc['orden']}")
        lineas += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
        if tipo == FECHA:
            lineas += ["\t\tannotation UnderlyingDateTimeDataType = Date", ""]
    lineas += [f"\tpartition {tabla} = m", "\t\tmode: import", "\t\tsource =", partition_m(tabla, esquema, columnas), ""]
    return "\n".join(lineas) + "\n"


def parametro(nombre, valor):
    return (f'expression {nombre} = "{valor}" meta [IsParameterQuery = true, Type = "Text", '
            f"IsParameterQueryRequired = true]\n\tlineageTag: {guid('param/' + nombre)}\n\n"
            "\tannotation PBI_ResultType = Text\n")


def generar_modelo(carpeta):
    escribir(carpeta / ".platform", {
        "$schema": ESQUEMA + "gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NOMBRE},
        "config": {"version": "2.0", "logicalId": guid("modelo")}})
    escribir(carpeta / "definition.pbism", {
        "$schema": ESQUEMA + "item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.1", "settings": {}})
    d = carpeta / "definition"
    escribir(d / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    orden = json.dumps(["Servidor", "BaseDatos", *TABLAS], ensure_ascii=False)
    modelo = ["model Model", "\tculture: es-ES", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
              "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: es-ES", "\tdataAccessOptions",
              "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
              "annotation __PBI_TimeIntelligenceEnabled = 0", "", f"annotation PBI_QueryOrder = {orden}", ""]
    modelo += [f"ref table {t}" for t in TABLAS] + [""] + [f"ref role {nombre_tmdl(r)}" for r in ROLES]
    escribir(d / "model.tmdl", "\n".join(modelo) + "\n")
    escribir(d / "expressions.tmdl", parametro("Servidor", SERVIDOR) + "\n" + parametro("BaseDatos", BASE_DATOS))
    rel = []
    for desde, hasta in RELACIONES:
        rel += [f"relationship {guid(desde + '>' + hasta)}", f"\tfromColumn: {desde}", f"\ttoColumn: {hasta}", ""]
    escribir(d / "relationships.tmdl", "\n".join(rel))
    for tabla, (esquema, columnas) in TABLAS.items():
        escribir(d / "tables" / f"{tabla}.tmdl", tabla_tmdl(tabla, esquema, columnas))
    for rol, filtro in ROLES.items():
        lineas = [f"role {nombre_tmdl(rol)}", "\tmodelPermission: read", ""]
        if filtro:
            lineas += [f"\ttablePermission dim_cliente = {filtro}", ""]
        escribir(d / "roles" / f"{rol}.tmdl", "\n".join(lineas))


# =====================================================================
# Informe (PBIR)
# =====================================================================

def columna(tabla, col):
    return {"Column": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": col}}


def medida(tabla, nombre):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": nombre}}


def proyeccion(campo, activa=None):
    tipo = "Column" if "Column" in campo else "Measure"
    tabla = campo[tipo]["Expression"]["SourceRef"]["Entity"]
    nombre = campo[tipo]["Property"]
    p = {"field": campo, "queryRef": f"{tabla}.{nombre}", "nativeQueryRef": nombre}
    if activa is not None:
        p["active"] = activa
    return p


def literal(valor):
    if isinstance(valor, bool):
        valor = "true" if valor else "false"
    elif isinstance(valor, (int, float)):
        valor = f"{valor}D"
    else:
        valor = "'" + str(valor).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": valor}}}


def titulo(texto):
    return {"title": [{"properties": {"show": literal(True), "text": literal(texto), "fontSize": literal(12)}}]}


def visual(nombre, x, y, ancho, alto, tipo, roles=None, orden=None, objetos=None, contenedor=None, z=0):
    v = {"visualType": tipo}
    if roles:
        v["query"] = {"queryState": {rol: {"projections": proy} for rol, proy in roles.items()}}
        if orden:
            campo, direccion = orden
            v["query"]["sortDefinition"] = {"sort": [{"field": campo, "direction": direccion}], "isDefaultSort": True}
    if objetos:
        v["objects"] = objetos
    if contenedor:
        v["visualContainerObjects"] = contenedor
    v["drillFilterOtherVisuals"] = True
    return {"$schema": ESQUEMA + "item/report/definition/visualContainer/2.0.0/schema.json", "name": nombre,
            "position": {"x": x, "y": y, "z": z, "width": ancho, "height": alto, "tabOrder": z}, "visual": v}


def texto(nombre, x, y, ancho, alto, contenido, tam="20pt", negrita=True, color=TINTA):
    estilo = {"fontFamily": "Segoe UI", "fontSize": tam, "color": color}
    if negrita:
        estilo["fontWeight"] = "bold"
    parrafos = [{"textRuns": [{"value": contenido, "textStyle": estilo}]}]
    return visual(nombre, x, y, ancho, alto, "textbox", objetos={"general": [{"properties": {"paragraphs": parrafos}}]})


def tarjeta(nombre, x, y, campo, etiqueta):
    return visual(nombre, x, y, 230, 90, "card", roles={"Values": [proyeccion(campo)]},
                  contenedor=titulo(etiqueta))


def segmentador_fecha(nombre, x, y, desde):
    campo = columna("dim_fecha", "fecha")
    filtro = {"Version": 2, "From": [{"Name": "f", "Entity": "dim_fecha", "Type": 0}],
              "Where": [{"Condition": {"Comparison": {
                  "ComparisonKind": 2,
                  "Left": {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": "fecha"}},
                  "Right": {"Literal": {"Value": f"datetime'{desde}T00:00:00'"}}}}}]}
    objetos = {"data": [{"properties": {"mode": literal("Between"),
                                        "startDate": {"expr": {"Literal": {"Value": f"datetime'{desde}T00:00:00'"}}}}}],
               "general": [{"properties": {"filter": {"filter": filtro}}}]}
    return visual(nombre, x, y, 380, 70, "slicer", roles={"Values": [proyeccion(campo, True)]},
                  orden=(campo, "Ascending"), objetos=objetos, contenedor=titulo("Periodo"))


def segmentador_lista(nombre, x, y, ancho, campo, etiqueta, seleccion=None):
    tabla = campo["Column"]["Expression"]["SourceRef"]["Entity"]
    objetos = {"data": [{"properties": {"mode": literal("Dropdown")}}]}
    if seleccion:
        objetos["selection"] = [{"properties": {"singleSelect": literal(True)}}]
        filtro = {"Version": 2, "From": [{"Name": "e", "Entity": tabla, "Type": 0}],
                  "Where": [{"Condition": {"In": {
                      "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "e"}},
                                                  "Property": campo["Column"]["Property"]}}],
                      "Values": [[{"Literal": {"Value": "'" + seleccion + "'"}}]]}}}]}
        objetos["general"] = [{"properties": {"filter": {"filter": filtro}}}]
    return visual(nombre, x, y, ancho, 70, "slicer", roles={"Values": [proyeccion(campo, True)]},
                  orden=(campo, "Ascending"), objetos=objetos, contenedor=titulo(etiqueta))


def colores_matriz(medida_valor, medida_fondo, medida_texto):
    tabla = medida_valor["Measure"]["Expression"]["SourceRef"]["Entity"]
    ref = f"{tabla}.{medida_valor['Measure']['Property']}"
    return {"values": [{"properties": {
        "backColor": {"solid": {"color": {"expr": medida_fondo}}},
        "fontColor": {"solid": {"color": {"expr": medida_texto}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": ref}}]}


def pie(nombre):
    return texto(nombre, 20, 692, 1240, 26, NOTA_CNMV, tam="9pt", negrita=False, color=GRIS)


def paginas():
    em_nombre = columna("dim_emisor", "nombre_corto")
    cortas = medida("fact_indicador_diario", "Cortas %")
    cortas_hoy = medida("fact_posicion_diaria", "Cortas hoy %")

    mercado = [
        texto("mercado_titulo", 20, 8, 760, 44, "El mapa de los bajistas · Mercado"),
        visual("mercado_fecha", 20, 50, 760, 30, "card", roles={"Values": [proyeccion(
            medida("fact_posicion_diaria", "Fecha de los datos"))]},
            objetos={"labels": [{"properties": {"fontSize": literal(11), "color": {"solid": {"color": literal(GRIS)}}}}],
                     "categoryLabels": [{"properties": {"show": literal(False)}}]}),
        segmentador_fecha("mercado_periodo", 880, 10, "2025-11-01"),
        tarjeta("mercado_empresas", 20, 90, medida("fact_posicion_diaria", "Empresas con cortos hoy"),
                "Empresas con cortos hoy"),
        tarjeta("mercado_fondos", 270, 90, medida("fact_posicion_diaria", "Fondos hoy"), "Fondos con posición hoy"),
        tarjeta("mercado_gestoras", 520, 90, medida("fact_posicion_diaria", "Gestoras hoy"), "Gestoras hoy"),
        tarjeta("mercado_alertas", 770, 90, medida("alerta", "Alertas"), "Alertas del cliente (histórico)"),
        visual("mercado_ranking", 20, 190, 400, 495, "clusteredBarChart",
               roles={"Category": [proyeccion(em_nombre, True)], "Y": [proyeccion(cortas_hoy)]},
               orden=(cortas_hoy, "Descending"), contenedor=titulo("Posiciones cortas hoy (% del capital)")),
        visual("mercado_calor", 440, 190, 820, 495, "pivotTable",
               roles={"Rows": [proyeccion(em_nombre, True)],
                      "Columns": [proyeccion(columna("dim_fecha", "anio_mes"), True)],
                      "Values": [proyeccion(cortas)]},
               objetos=colores_matriz(cortas, medida("fact_indicador_diario", "Color calor"),
                                      medida("fact_indicador_diario", "Color texto calor")),
               contenedor=titulo("Mapa de calor: media mensual de posiciones cortas (%)")),
        pie("mercado_pie"),
    ]

    empresa = [
        texto("empresa_titulo", 20, 8, 600, 44, "Detalle por empresa"),
        segmentador_lista("empresa_selector", 620, 10, 250, em_nombre, "Empresa", seleccion="Grifols"),
        segmentador_fecha("empresa_periodo", 880, 10, "2023-09-01"),
        visual("empresa_cortas", 20, 90, 820, 295, "lineChart",
               roles={"Category": [proyeccion(columna("dim_fecha", "fecha"), True)], "Y": [proyeccion(cortas)]},
               contenedor=titulo("Suma de posiciones cortas (% del capital)")),
        visual("empresa_precio", 20, 392, 820, 295, "lineChart",
               roles={"Category": [proyeccion(columna("dim_fecha", "fecha"), True)],
                      "Y": [proyeccion(medida("fact_precio_diario", "Cotización €"))]},
               contenedor=titulo("Cotización (€)")),
        visual("empresa_fondos", 860, 90, 400, 295, "tableEx",
               roles={"Values": [proyeccion(columna("dim_fondo", "tenedor")),
                                 proyeccion(columna("dim_fondo", "grupo_gestor")), proyeccion(cortas_hoy)]},
               orden=(cortas_hoy, "Descending"), contenedor=titulo("Fondos con posición hoy")),
        visual("empresa_alertas", 860, 392, 400, 295, "tableEx",
               roles={"Values": [proyeccion(columna("alerta", "fecha")), proyeccion(columna("alerta", "mensaje"))]},
               orden=(columna("alerta", "fecha"), "Descending"), contenedor=titulo("Alertas del cliente")),
        pie("empresa_pie"),
    ]

    fondos = [
        texto("fondos_titulo", 20, 8, 900, 44, "Fondos y gestoras: quién está en corto hoy"),
        visual("fondos_matriz", 20, 60, 860, 625, "pivotTable",
               roles={"Rows": [proyeccion(columna("dim_fondo", "grupo_gestor"), True)],
                      "Columns": [proyeccion(em_nombre, True)], "Values": [proyeccion(cortas_hoy)]},
               objetos=colores_matriz(cortas_hoy, medida("fact_posicion_diaria", "Color calor hoy"),
                                      medida("fact_posicion_diaria", "Color texto calor hoy")),
               contenedor=titulo("Posición corta hoy por gestora y empresa (%)")),
        visual("fondos_ranking", 900, 60, 360, 625, "clusteredBarChart",
               roles={"Category": [proyeccion(columna("dim_fondo", "grupo_gestor"), True)],
                      "Y": [proyeccion(medida("fact_posicion_diaria", "Empresas con cortos hoy"))]},
               orden=(medida("fact_posicion_diaria", "Empresas con cortos hoy"), "Descending"),
               contenedor=titulo("Empresas en corto por gestora")),
        pie("fondos_pie"),
    ]

    alertas = [
        texto("alertas_titulo", 20, 8, 700, 44, "Alertas del cliente"),
        texto("alertas_explicacion", 20, 50, 820, 34,
              "Cada cliente solo ve sus alertas, reglas y notas (seguridad por filas). "
              "En Power BI Desktop: Modelado > Ver como > Cliente demo A / B.", tam="10pt", negrita=False, color=GRIS),
        segmentador_lista("alertas_cliente", 880, 10, 380, columna("dim_cliente", "nombre"), "Cliente"),
        tarjeta("alertas_total", 20, 90, medida("alerta", "Alertas"), "Alertas"),
        visual("alertas_tabla", 20, 190, 800, 495, "tableEx",
               roles={"Values": [proyeccion(columna("alerta", "fecha")), proyeccion(columna("alerta", "tipo")),
                                 proyeccion(columna("alerta", "mensaje"))]},
               orden=(columna("alerta", "fecha"), "Descending"), contenedor=titulo("Alertas (más recientes primero)")),
        visual("alertas_reglas", 840, 90, 420, 290, "tableEx",
               roles={"Values": [proyeccion(columna("regla_alerta", "descripcion"))]},
               contenedor=titulo("Reglas de alerta")),
        visual("alertas_notas", 840, 392, 420, 293, "tableEx",
               roles={"Values": [proyeccion(columna("nota", "fecha")), proyeccion(columna("nota", "texto"))]},
               orden=(columna("nota", "fecha"), "Descending"), contenedor=titulo("Notas internas")),
        pie("alertas_pie"),
    ]
    return [("mercado", "Mercado", mercado), ("empresa", "Empresa", empresa),
            ("fondos", "Fondos y gestoras", fondos), ("alertas", "Alertas del cliente", alertas)]


def generar_informe(carpeta):
    escribir(carpeta / ".platform", {
        "$schema": ESQUEMA + "gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NOMBRE},
        "config": {"version": "2.0", "logicalId": guid("informe")}})
    escribir(carpeta / "definition.pbir", {
        "$schema": ESQUEMA + "item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NOMBRE}.SemanticModel"}}})
    tema = carpeta / "StaticResources" / "SharedResources" / "BaseThemes" / "CY24SU10.json"
    tema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMA, tema)
    d = carpeta / "definition"
    escribir(d / "version.json", {"$schema": ESQUEMA + "item/report/definition/versionMetadata/1.0.0/schema.json",
                                  "version": "2.0.0"})
    escribir(d / "report.json", {
        "$schema": ESQUEMA + "item/report/definition/report/1.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.61",
                                          "type": "SharedResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True}})
    lista = paginas()
    escribir(d / "pages" / "pages.json", {
        "$schema": ESQUEMA + "item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p for p, _, _ in lista], "activePageName": lista[0][0]})
    for pagina, nombre, visuales in lista:
        escribir(d / "pages" / pagina / "page.json", {
            "$schema": ESQUEMA + "item/report/definition/page/1.4.0/schema.json",
            "name": pagina, "displayName": nombre, "displayOption": "FitToPage", "height": 720, "width": 1280})
        for i, v in enumerate(visuales):
            v["position"]["z"] = v["position"]["tabOrder"] = i * 1000
            escribir(d / "pages" / pagina / "visuals" / v["name"] / "visual.json", v)


def generar():
    for sub in (f"{NOMBRE}.SemanticModel/definition", f"{NOMBRE}.Report/definition"):
        if (DESTINO / sub).exists():
            shutil.rmtree(DESTINO / sub)  # sin restos de visuales o tablas que ya no existen
    escribir(DESTINO / f"{NOMBRE}.pbip", {
        "$schema": ESQUEMA + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}], "settings": {"enableAutoRecovery": True}})
    generar_modelo(DESTINO / f"{NOMBRE}.SemanticModel")
    generar_informe(DESTINO / f"{NOMBRE}.Report")
    return DESTINO


if __name__ == "__main__":
    print(f"Proyecto generado en {generar()}")
