"""
CRUCE ENTRE LAS DOS HOJAS (lógica pura, sin pantalla ni Google: se puede probar sola)
=====================================================================================
El estadístico (FO-07) es un resumen por día de lo que está en el estatus de tarjetas (FO-06).
Esta pieza lee los dos y busca días donde NO cuadran: un valor escrito en la columna de otra cámara, una duración distinta,
clips que faltan, un día que está en una hoja y en la otra no…

Reglas (las mismas con las que la app escribe el estadístico, así que «cuadrar» significa exactamente lo que la app habría escrito):
  - Cámara = primera letra del BIN (A_0124… → A). El sonido va aparte (AUDIO).
  - GB y clips por letra; ROLLOS = cuántas tarjetas de video; DURACIÓN = suma de las tarjetas de video (sin audio).
  - El estatus de tarjetas es la FUENTE (viene de Silverstack); el estadístico se corrige a partir de él.
    Si el error está en el estatus y se sabe exactamente cuál celda es (una tarjeta sin peso o con un peso imposible, una tarjeta
    sin llenar, la fecha que contradice al archivo de la grabadora), se propone corregir ESA celda del estatus (`hoja: "estatus"`).
    Un día que falta en el estadístico se propone agregarlo entero (`propuesta`, como al registrar el día).

No escribe nada: solo devuelve hallazgos. Cada hallazgo trae las celdas del estadístico que se cambiarían, para que la persona decida.
"""

import re
from datetime import date, datetime

import estadistico_core as ec
import registro_core as rc
import resumen_core as rs

TOL_GB = 0.05          # GB
TOL_SEG = 5            # segundos de duración (el estadístico suele redondearse a mano)
TOL_COINCIDE = 0.5     # GB para decir que dos valores «son el mismo»
TOL_REDONDEO_GB = 1.0  # un GB escrito como número entero a menos de 1 GB del real es un redondeo a mano (1,122.15 → 1,122), no un error
TOL_REDONDEO_TB = 5.0  # GB escritos «en TB con dos decimales» (1.30 TB → 1,300): múltiplo de 10 a menos de 5 GB del real
TOL_REDONDEO_SEG = 30  # duraciones tecleadas «a ojo»: menos de 30 s no se marca


numero_de_dia = ec.numero_de_dia


def _columnas_f06(filas):
    return rs.columnas_f06(filas)


def leer_dias_f06(filas, cfg, claves=None):
    """Lista (en el orden de la hoja) de los días del estatus de tarjetas:
    [{'num', 'suf', 'etiqueta', 'fecha', 'filas': [{'nombre','cam','gb','clips','seg','sonido','fila'}]}].
    `claves`: las cámaras del estadístico (para saber que M001L es la columna ML)."""
    i0, col = _columnas_f06(filas)
    with ec.orden_de_fechas(ec.cel([f], 0, col["fecha_col"]) for f in filas[i0 + 1:]):     # el orden de fechas de ESTA pestaña
        return _leer_dias_f06(filas, cfg, claves, i0, col)


def _leer_dias_f06(filas, cfg, claves, i0, col):
    sonido = {g["nombre"] for g in cfg["grupos"] if rc.grupo_es_sonido(g)}
    fecha_col = col["fecha_col"]
    dias, por_clave, actual = [], {}, None
    for n, fila in enumerate(filas[i0 + 1:], start=i0 + 1):
        nombre = ec.cel([fila], 0, col["cam"])
        etiqueta = ec.cel([fila], 0, col["dia"])
        if not (isinstance(nombre, str) and nombre.strip()):
            continue
        if etiqueta not in ("", None):
            num, suf = ec.partir_dia(etiqueta)
            if num is not None:
                actual = por_clave.get((num, suf))
                if actual is None:
                    actual = por_clave[(num, suf)] = {"num": num, "suf": suf, "etiqueta": str(etiqueta).strip(),
                                                      "fecha": rs._fecha(ec.cel([fila], 0, fecha_col)), "filas": []}
                    dias.append(actual)
        if actual is None:
            continue
        modelo = ec.cel([fila], 0, col["modelo"]) if col.get("modelo") is not None else ""
        g = rc.grupo_de(nombre.strip(), cfg, audio=True if rc.es_modelo_de_audio(modelo) else None)
        gb = rs._num(ec.cel([fila], 0, col["gb"])) or 0.0
        clips = int(rs._num(ec.cel([fila], 0, col["clips"])) or 0)
        seg = rs._segundos(ec.cel([fila], 0, col["duracion"]))
        if not gb and not clips and not seg:
            actual.setdefault("vacias", []).append(nombre.strip())     # fila preparada de antemano (D007…) sin material todavía
            actual.setdefault("vacias_filas", []).append({
                "nombre": nombre.strip(), "fila": n + 1, "cam": rc.clave_de_bin(nombre, claves),
                "sonido": bool((g and g["nombre"] in sonido) or rc.es_nombre_de_sonido(nombre) or rc.es_modelo_de_audio(modelo))})
            continue
        con_letra = bool(re.match(r"^[A-Za-z]+_?\d", nombre.strip()))        # «BETACAM_TEST» no dice de qué cámara es
        actual["filas"].append({"nombre": nombre.strip(), "cam": rc.clave_de_bin(nombre, claves), "cam_dudosa": not con_letra, "gb": gb, "clips": clips, "seg": seg,
                                "sonido": bool((g and g["nombre"] in sonido) or rc.es_nombre_de_sonido(nombre)
                                               or rc.es_modelo_de_audio(modelo)), "fila": n + 1})
    for d in dias:                                     # día y mes al revés en la hoja: manda el archivo de la grabadora
        d["fecha"] = ec.fecha_segun_sonido(d["fecha"], [f["nombre"] for f in d["filas"] if f["sonido"]]
                                           + [f["nombre"] for f in d.get("vacias_filas", []) if f["sonido"]])
    return dias


# ---------------------------------------------------------------------------------------------
# Vistas previas: las dos hojas tal como se ven en Google Sheets, con lo malo en rojo y lo correcto en verde.
# Formato = el de la pantalla: {'titulos': [...], 'filas': [{'n', 'dia', 'celdas': [(texto, marca)]}]}; marca: False | "mal" | "bien".
# ---------------------------------------------------------------------------------------------
def _cols_vista06(col):
    return [c for c in (col.get("dia"), col.get("fecha_col"), col["cam"], col["clips"], col["duracion"], col["gb"]) if c is not None]


def _vista07(datos07, tabla, d07, celdas, corregible, tipo):
    """Fila del día en «Datos Generales» con los vecinos: las celdas malas en rojo y, debajo, cómo quedaría (verde)."""
    if d07 is None:
        return None
    r, enc = d07["fila"], tabla["fila_enc"]
    afectadas = sorted({c["col"] for c in celdas})
    if not afectadas:
        afectadas = sorted(c for c in tabla["gb"].values() if ec.es_numero(ec.cel(datos07, r, c)) and ec.cel(datos07, r, c))
    if not afectadas:
        return None
    ventana = list(range(max(0, afectadas[0] - 1), afectadas[-1] + 2))
    cols = ventana if len(ventana) <= 12 else sorted({x for c in afectadas for x in (c - 1, c, c + 1) if x >= 0})
    cols = sorted({tabla["dia"], tabla["fecha"], *cols})
    cols = [c for c in cols if str(ec.cel(datos07, enc, c)).strip() or c in afectadas]
    tipos = {tabla["fecha"]: "fecha", tabla["duracion"]: "hora"}
    tipos.update({c: "gb" for c in list(tabla["gb"].values()) + [tabla["audio_gb"], tabla["total"]] if c is not None})
    nuevos = {c["col"]: c["nuevo"] for c in celdas}
    malas = {c["col"] for c in celdas} if celdas else set(afectadas)

    def fila(rr, marcas, usar_nuevos=False, n=None):
        out = []
        for c in cols:
            v = nuevos[c] if usar_nuevos and c in nuevos else ec.cel(datos07, rr, c)
            out.append((ec._texto_celda(v, tipos.get(c)), marcas(c)))
        return {"n": rr + 1 if n is None else n, "dia": False, "celdas": out}

    previas = [d["fila"] for d in tabla["dias"] if d["fila"] < r][-1:]
    siguientes = [d["fila"] for d in tabla["dias"] if d["fila"] > r][:1]
    filas = [fila(x, lambda c: False) for x in previas]
    ahora = fila(r, lambda c: "mal" if c in malas else False)
    ahora["dia"] = True
    filas.append(ahora)
    if corregible and celdas:
        filas.append(fila(r, lambda c: "bien" if c in nuevos else False, True, "→"))
    filas += [fila(x, lambda c: False) for x in siguientes]
    return {"titulos": [str(ec.cel(datos07, enc, c)) for c in cols], "filas": filas}


def _vista06(g06, col, titulos, d06, celdas, tipo, malas=()):
    """Las filas del día en el estatus de tarjetas; en verde lo que corresponde a las celdas que se discuten."""
    claves = [c["clave"] for c in celdas if c.get("clave")] or ([("gb", "")] if tipo == "falta_en_07" else [])
    cols = _cols_vista06(col)

    def marca(f, medida):
        if medida == "gb" and f["nombre"] in malas:
            return "mal"
        for t, letra in claves:
            if t in ("gb", "clips"):
                if not f["sonido"] and f.get("cam") == letra and medida == t:
                    return "bien"
            elif t == "seg" and not f["sonido"] and medida == "duracion":
                return "bien"
            elif t == "rollos" and not f["sonido"] and medida == "cam":
                return "bien"
            elif t == "audio" and f["sonido"] and medida == "gb":
                return "bien"
            elif t == "audio_clips" and f["sonido"] and medida == "clips":
                return "bien"
        if tipo == "falta_en_07" and medida == "gb":
            return "bien"
        return False

    nombre_de = {col.get("dia"): "dia", col.get("fecha_col"): "fecha", col["cam"]: "cam", col["clips"]: "clips",
                 col["duracion"]: "duracion", col["gb"]: "gb"}
    # celdas del ESTATUS que se corregirían: se ven «antes → nuevo» en verde (también en filas sin llenar, que no están en d06["filas"])
    arreglo = {}
    for c in celdas:
        if c.get("hoja") == "estatus" and nombre_de.get(c["col"]):
            arreglo[(c["fila"] + 1, nombre_de[c["col"]])] = c
    lista = list(d06["filas"])
    vistas = {f["fila"] for f in lista}
    for v in d06.get("vacias_filas", []):
        if v["fila"] not in vistas and any(k[0] == v["fila"] for k in arreglo):
            lista.append({"nombre": v["nombre"], "fila": v["fila"], "sonido": v["sonido"], "cam": v["cam"], "gb": None, "clips": None, "seg": None})
    lista.sort(key=lambda f: f["fila"])
    filas = []
    for i, f in enumerate(lista[:16]):
        celdas_f = []
        for c in cols:
            medida = nombre_de.get(c)
            cc_ = arreglo.get((f["fila"], medida))
            if cc_ is not None:
                celdas_f.append((f"{cc_['antes_txt']} → {cc_['nuevo_txt']}", "bien"))
                continue
            if medida == "dia":
                texto = str(d06["etiqueta"]) if i == 0 else ""
            elif medida == "fecha":
                texto = d06["fecha"].strftime("%d/%m/%Y") if (i == 0 and d06["fecha"]) else ""
            elif medida == "cam":
                texto = f["nombre"]
            elif medida == "clips":
                texto = "" if f["clips"] is None else str(f["clips"])
            elif medida == "duracion":
                texto = "" if f["seg"] is None else rs.hms(f["seg"])
            else:
                texto = "" if f["gb"] is None else f"{f['gb']:,.2f}"
            celdas_f.append((texto, marca(f, medida)))
        filas.append({"n": f["fila"], "dia": False, "celdas": celdas_f})
    return {"titulos": titulos, "filas": filas, "recortado": len(lista) > 16}


def _casi(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def _ritmo_tipico(dias06):
    """GB por segundo que es normal en este proyecto (la mediana de las tarjetas de video de más de un minuto); 0 si no hay de dónde sacarlo."""
    r = sorted(f["gb"] / f["seg"] for d in dias06 for f in d["filas"] if not f["sonido"] and f["seg"] >= 60 and f["gb"] > 0)
    return r[len(r) // 2] if len(r) >= 8 else 0.0


def _tarjetas_raras(d06, d, ritmo):
    """Para una diferencia de GB: las tarjetas de esa cámara cuyo peso no cuadra con su duración (un GB mal tecleado):
    [(fila, 'pesa muchísimo' | 'pesa muy poco')]."""
    if not ritmo or d["clave"][0] != "gb" or not d06:
        return []
    raras = []
    for f in d06["filas"]:
        if f["sonido"] or f.get("cam") != d["clave"][1] or f["seg"] <= 0:
            continue
        if f["gb"] / f["seg"] > 6 * ritmo and f["gb"] > 10:
            raras.append((f, "pesa muchísimo"))
        elif f["seg"] >= 120 and f["gb"] / f["seg"] < ritmo / 6:
            raras.append((f, "pesa muy poco"))
    return raras


def marcar_audio_mezclado(filas06, datos07, r, tabla, claves=None):
    """Una tarjeta de cámara del estatus que trae también el audio del día (HDT DAY902: Y001_1028BD_1 = 100 clips, 390.31 GB en el
    estatus; el estadístico tiene CAM Y 389.76 GB / 64 clips y AUDIO 0.55 GB / 36 clips). Si lo que le SOBRA a una cámara en el estatus
    es justo lo que le FALTA al audio en el estadístico, esa tarjeta se marca con `audio_mezclado` (no es un error: se descargó junto).
    Devuelve {'nombre','cam','gb','clips','seg'} o None."""
    if tabla.get("audio_gb") is None:
        return None
    num = lambda c: (float(ec.cel(datos07, r, c)) if c is not None and ec.es_numero(ec.cel(datos07, r, c)) else 0.0)
    dgb = num(tabla["audio_gb"]) - sum(f["gb"] for f in filas06 if f["sonido"])
    dclips = (num(tabla["audio_clips"]) - sum(f["clips"] for f in filas06 if f["sonido"])) if tabla.get("audio_clips") is not None else None
    if dgb <= 0.005:
        return None
    candidatas = []
    for letra, col in tabla["gb"].items():
        suyas = [f for f in filas06 if not f["sonido"] and f.get("cam_forzada", f["cam"]) == letra]
        if not suyas:
            continue
        sobra_gb = sum(f["gb"] for f in suyas) - num(col)
        if abs(sobra_gb - dgb) > max(0.02, 0.002 * dgb):
            continue
        if dclips is not None and letra in tabla["clips"] and sum(f["clips"] for f in suyas) - num(tabla["clips"][letra]) != dclips:
            continue
        candidatas.append((letra, max(suyas, key=lambda f: f["clips"])))
    if len(candidatas) != 1:
        return None
    letra, f = candidatas[0]
    dseg = 0
    if tabla.get("duracion") is not None and ec.es_numero(ec.cel(datos07, r, tabla["duracion"])):
        dseg = max(0, round(sum(x["seg"] for x in filas06 if not x["sonido"]) - num(tabla["duracion"]) * 86400))
    f["audio_mezclado"] = {"gb": round(dgb, 2), "clips": int(dclips) if dclips is not None else 0, "seg": dseg}
    return {"nombre": f["nombre"], "cam": letra, **f["audio_mezclado"]}


def cruzar(g06, datos07, cfg, excluir_dias=(), agregar_dias=True):
    """Compara los días que están en las dos hojas. `g06`: valores reales del estatus; `datos07`: «Datos Generales».
    `excluir_dias`: números de día que no se miran (el que se está registrando ahora).
    `agregar_dias`: proponer agregar al estadístico los días que le faltan (en «Registrar día» no: se está escribiendo otra fila).
    Devuelve {'hallazgos': [...], 'comparados': n_días, 'avisos': [...]}.
    Cada hallazgo: {'id','dia','texto_dia','tipo','titulo','detalle','causa','corregible','celdas':[cambio…],'v06','v07'}."""
    tabla = ec.encontrar_tabla(datos07)
    claves07 = set(tabla["gb"]) | set(tabla["clips"])
    dias06 = leer_dias_f06(g06, cfg, claves07)
    pares = ec.emparejar_dias([(d["num"], d["suf"], d["fecha"]) for d in dias06],
                              [(d["num"], d["suf"], d.get("fecha")) for d in tabla["dias"]])
    filas07 = {i: tabla["dias"][j] for i, j in pares.items()}          # posición del día en el estatus → su fila en el estadístico
    emparejadas07 = {id(d) for d in filas07.values()}
    hallazgos, avisos, comparados = [], [], 0
    redondeos = []             # diferencias mínimas (un día = una entrada): no se marcan, pero se pueden ver y corregir si la persona quiere
    sin_columna = set()
    ritmo = _ritmo_tipico(dias06)
    ignoradas = [0]            # diferencias de redondeo que no se marcan (se avisa cuántas)
    cols06 = _columnas_f06(g06)[1]
    col_fecha06 = cols06.get("fecha_col")
    titulos06 = [str(ec.cel(g06, _columnas_f06(g06)[0], c)) for c in _cols_vista06(cols06)]

    ctx = {"d06": None}

    def nuevo(num, d07, tipo, titulo, detalle, causa, celdas, corregible, v06="", v07="", malas06=()):
        d06 = ctx["d06"]
        c07 = [c for c in celdas if c.get("hoja", "datos") == "datos"]
        hallazgos.append({"id": len(hallazgos) + 1, "dia": num, "texto_dia": d07["texto"] if d07 else f"día {num}", "tipo": tipo,
                          "titulo": titulo, "detalle": detalle, "causa": causa, "corregible": corregible and bool(celdas),
                          "celdas": celdas, "v06": v06, "v07": v07,
                          "vista07": _vista07(datos07, tabla, d07, c07, corregible and bool(c07), tipo) if (c07 or not celdas) else None,
                          "vista06": _vista06(g06, cols06, titulos06, d06, celdas, tipo, malas06) if d06 else None})
        return hallazgos[-1]

    def celda06(fila1, col, concepto, nuevo_v, tipo):
        """Una celda del ESTATUS que se corregiría (`fila1` = número de fila de la hoja, 1 = la primera)."""
        antes = ec.cel(g06, fila1 - 1, col)
        return {"hoja": "estatus", "celda": ec.a1(fila1 - 1, col), "fila": fila1 - 1, "col": col, "concepto": concepto,
                "antes": antes if ec.es_numero(antes) else (antes or ""), "antes_raw": antes, "nuevo": nuevo_v, "tipo": tipo,
                "antes_txt": ec._bonito(antes, tipo) if antes not in ("", None) else "vacía", "nuevo_txt": ec._bonito(nuevo_v, tipo)}

    def celda_fecha(hoja, rr, col, fecha, leida=None, concepto="FECHA"):
        raw = (g06 if hoja == "estatus" else datos07)
        antes = ec.cel(raw, rr, col)
        directa = rs._fecha(antes)
        if leida is not None and directa != leida and _fecha_o_none(leida.year, leida.day, leida.month) == directa:
            # la hoja guarda las fechas con día y mes al revés (Google en formato de EE. UU.: se teclea «09/11/2026» y guarda 11 de
            # septiembre, pero se VE como se tecleó): se escribe igual que quedaría al teclearla, para que se siga viendo bien
            al_reves = _fecha_o_none(fecha.year, fecha.day, fecha.month) if fecha.day <= 12 else None
            nuevo_v = _fecha_como(antes, al_reves) if al_reves else f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year}"
        else:
            nuevo_v = _fecha_como(antes, fecha)
        return {"hoja": hoja, "celda": ec.a1(rr, col), "fila": rr, "col": col, "concepto": concepto, "antes": antes, "antes_raw": antes,
                "nuevo": nuevo_v, "tipo": "fecha", "antes_txt": _texto_de_fecha(antes), "nuevo_txt": f"{fecha:%d/%m/%Y}"}

    for pos06, d06 in enumerate(dias06):
        num = d06["num"]
        ctx["d06"] = d06
        if num in excluir_dias or not d06["filas"]:        # los días preparados de antemano (sin material) no se comparan ni se cuentan
            continue
        d07 = filas07.get(pos06)
        if d07 is None:
            if any(f["gb"] > 0 for f in d06["filas"]):
                prop, motivo = _proponer_dia_faltante(datos07, tabla, d06) if agregar_dias else \
                    (None, "Puedes agregarlo desde el Resumen («Corregir»).")
                h = nuevo(num, None, "falta_en_07", f"El día {num} no tiene fila en el estadístico",
                          f"Está en el estatus de tarjetas ({d06['etiqueta']}), pero «Datos Generales» no tiene su fila.",
                          ("Lo agrego al estadístico con los datos del estatus de tarjetas, igual que al registrar un día: "
                           f"«{prop['texto_dia']}» en la fila {prop['fila'] + 1}"
                           + (" (fila nueva)" if prop.get("insertar_fila") else "") + "." if prop else
                           "Falta agregar la fila del día en el estadístico. " + motivo),
                          prop["cambios"] if prop else [], bool(prop))
                if prop:
                    h["propuesta"] = prop
            continue
        comparados += 1
        r = d07["fila"]
        f06, f07 = d06.get("fecha"), d07.get("fecha")
        if f06 and f07 and f06 != f07 and f06.day <= 12 and _fecha_o_none(f06.year, f06.day, f06.month) == f07:
            pass       # día y mes al revés: Google con formato de EE. UU. guardó «10/11/2026» como 11 de octubre; en la hoja se ve igual
        elif f06 and f07 and f06 != f07:
            pista, fs = "", None
            for f in d06["filas"] + d06.get("vacias_filas", []):   # el archivo de sonido lleva la fecha de la grabadora: 26Y10M09 = 09/10/2026
                mm = re.match(r"(\d{2})Y(\d{2})M(\d{2})", f["nombre"]) if f["sonido"] else None
                if mm:
                    try:
                        fs = date(2000 + int(mm[1]), int(mm[2]), int(mm[3]))
                    except ValueError:
                        continue
                    pista = (f" El archivo de sonido «{f['nombre']}» es del {fs:%d/%m/%Y}"
                             + (", como dice el estadístico." if fs == f07 else ", como dice el estatus de tarjetas." if fs == f06 else "."))
                    break
            if fs is not None and fs == f07:                # el archivo de la grabadora le da la razón al estadístico: se corrige el estatus
                filas_dia = sorted({f["fila"] for f in d06["filas"]} | {f["fila"] for f in d06.get("vacias_filas", [])})
                cols_f = col_fecha06
                celdas_f = [celda_fecha("estatus", x - 1, cols_f, f07, f06) for x in filas_dia
                            if cols_f is not None and f06 in _lecturas_de_fecha(ec.cel(g06, x - 1, cols_f))]
                nuevo(num, d07, "fecha", f"{d07['texto']}: la fecha no coincide",
                      f"Estatus de tarjetas: {f06:%d/%m/%Y} · estadístico: {f07:%d/%m/%Y}.",
                      "La fecha equivocada es la del estatus de tarjetas." + pista
                      + (" La corrijo en el estatus." if celdas_f else ""), celdas_f, bool(celdas_f))
            else:
                nuevo(num, d07, "fecha", f"{d07['texto']}: la fecha no coincide",
                      f"Estatus de tarjetas: {f06:%d/%m/%Y} · estadístico: {f07:%d/%m/%Y}.",
                      "Una de las dos hojas tiene la fecha equivocada. El estatus de tarjetas es la fuente (los reportes por fecha usan "
                      "la suya), así que la corrijo en el estadístico; si la buena es la del estadístico, déjala como está y corrige el estatus."
                      + pista, [celda_fecha("datos", r, tabla["fecha"], f06)] if tabla.get("fecha") is not None else [],
                      tabla.get("fecha") is not None)
        for f in d06["filas"]:                              # un equipo sin letra va a la columna del estadístico con esos mismos GB ese día
            if f.get("cam_dudosa") and not f["sonido"] and f["gb"] > 0:
                cols = [k for k, c in tabla["gb"].items()
                        if abs((rs._num(ec.cel(datos07, d07["fila"], c)) or 0.0) - f["gb"]) <= max(0.5, 0.02 * f["gb"])]
                if len(cols) == 1:
                    f["cam"] = cols[0]
                    f["cam_forzada"] = cols[0]
        mezclado = marcar_audio_mezclado(d06["filas"], datos07, r, tabla, claves07)
        if mezclado:
            d06["audio_mezclado"] = mezclado
        calc = ec.calcular_dia(d06["filas"], lambda f: f["sonido"], claves07)
        diferencias = []          # (concepto, col, tipo, esperado, actual, clave)
        redondeo_dia = []         # las diferencias de redondeo de ESTE día

        def mirar(col, concepto, esperado, tipo, clave, tol):
            actual = ec.cel(datos07, r, col)
            if tipo == "hora":
                bien = ec.es_numero(actual) and abs(float(actual) * 86400 - esperado * 86400) <= tol
                if not bien and not ec.es_numero(actual) and esperado == 0 and actual in ("", None):
                    bien = True
            elif tipo == "num":
                bien = (float(actual) if ec.es_numero(actual) else 0.0) == float(esperado)
            else:
                bien = abs((float(actual) if ec.es_numero(actual) else 0.0) - float(esperado)) <= tol
            if not bien and tipo == "gb" and ec.es_numero(actual) and float(actual) and float(actual) == round(float(actual)) \
                    and abs(float(actual) - esperado) <= TOL_REDONDEO_GB:
                ignoradas[0] += 1
                redondeo_dia.append({"concepto": concepto, "col": col, "tipo": tipo, "esperado": esperado,
                                     "actual": float(actual), "raw": actual, "clave": clave})
                bien = True
            elif not bien and tipo == "gb" and ec.es_numero(actual) and float(actual) >= 100 \
                    and abs(float(actual) / 10 - round(float(actual) / 10)) < 1e-6 and abs(float(actual) - esperado) <= TOL_REDONDEO_TB:
                ignoradas[0] += 1                           # «1.30 TB» escrito como 1,300 GB
                redondeo_dia.append({"concepto": concepto, "col": col, "tipo": tipo, "esperado": esperado,
                                     "actual": float(actual), "raw": actual, "clave": clave, "a_tb": True})
                bien = True
            elif not bien and tipo == "hora" and ec.es_numero(actual) and abs(float(actual) * 86400 - esperado * 86400) <= TOL_REDONDEO_SEG:
                ignoradas[0] += 1
                redondeo_dia.append({"concepto": concepto, "col": col, "tipo": tipo, "esperado": esperado,
                                     "actual": float(actual), "raw": actual, "clave": clave})
                bien = True
            if not bien:
                diferencias.append({"concepto": concepto, "col": col, "tipo": tipo, "esperado": esperado,
                                    "actual": actual if ec.es_numero(actual) else 0.0, "raw": actual, "clave": clave})

        for letra, col in tabla["gb"].items():
            mirar(col, f"CAM {letra} (GB)", calc["gb"].get(letra, 0.0), "gb", ("gb", letra), TOL_GB)
        for letra, col in tabla["clips"].items():
            mirar(col, f"CAM {letra} (clips)", calc["clips"].get(letra, 0), "num", ("clips", letra), 0)
        for letra in calc["gb"]:
            if letra not in tabla["gb"]:
                sin_columna.add(letra)
        if tabla["rollos"] is not None:
            mirar(tabla["rollos"], "ROLLOS", calc["rollos"], "num", ("rollos", ""), 0)
        if tabla["duracion"] is not None:
            mirar(tabla["duracion"], "DURACIÓN", calc["seg"] / 86400.0, "hora", ("seg", ""), TOL_SEG)
        if tabla["audio_gb"] is not None:
            mirar(tabla["audio_gb"], "AUDIO (GB)", calc["audio_gb"], "gb", ("audio", ""), TOL_GB)
        if tabla["audio_clips"] is not None:
            mirar(tabla["audio_clips"], "AUDIO (clips)", calc["audio_clips"], "num", ("audio_clips", ""), 0)

        usadas = set()

        def celda(df, esperado=None):
            nuevo_v = df["esperado"] if esperado is None else esperado
            return {"hoja": "datos", "celda": ec.a1(r, df["col"]), "fila": r, "col": df["col"], "concepto": df["concepto"],
                    "antes": df["actual"], "antes_raw": df["raw"], "nuevo": nuevo_v, "tipo": df["tipo"], "clave": df["clave"],
                    "antes_txt": ec._bonito(df["actual"], df["tipo"]), "nuevo_txt": ec._bonito(nuevo_v, df["tipo"])}

        # 1) valores que están en la columna de OTRA cámara (GB o clips): el esperado de una es lo que hay en la otra
        for tipo_c in ("gb", "clips"):
            por = [d for d in diferencias if d["clave"][0] == tipo_c]
            for a in por:
                for b in por:
                    if a is b or id(a) in usadas or id(b) in usadas or a["clave"][1] >= b["clave"][1]:
                        continue
                    if (a["esperado"] != a["actual"] and abs(a["esperado"] - b["actual"]) <= (TOL_COINCIDE if tipo_c == "gb" else 0)
                            and abs(b["esperado"] - a["actual"]) <= (TOL_COINCIDE if tipo_c == "gb" else 0)):
                        usadas.update({id(a), id(b)})
                        unidad = "GB" if tipo_c == "gb" else "clips"
                        mayor, menor = (a, b) if a["actual"] >= b["actual"] else (b, a)
                        nuevo(num, d07, "columnas_cambiadas",
                              f"{d07['texto']}: los {unidad} de la cámara {a['clave'][1]} y la {b['clave'][1]} están cruzados",
                              f"En el estadístico, {a['concepto']} dice {ec._bonito(a['actual'], a['tipo'])} y {b['concepto']} dice "
                              f"{ec._bonito(b['actual'], b['tipo'])}; en el estatus de tarjetas es al revés: {a['concepto']} = "
                              f"{ec._bonito(a['esperado'], a['tipo'])} y {b['concepto']} = {ec._bonito(b['esperado'], b['tipo'])}.",
                              f"Parece un valor escrito en la columna de la cámara equivocada (el de {b['clave'][1] if mayor is a else a['clave'][1]} "
                              f"quedó en la columna de {mayor['clave'][1]}).",
                              [celda(a), celda(b)], True, v06=a["esperado"], v07=a["actual"])
        # 1b) un día entero sin llenar en el estadístico: UN hallazgo (si no, saldrían 11 tarjetas por un día)
        pendientes = [d for d in diferencias if id(d) not in usadas]
        vacias = [d for d in pendientes if d["actual"] in (0, 0.0) and d["esperado"]]
        if len(pendientes) >= 3 and len(vacias) == len(pendientes) and d06.get("vacias"):
            sin = d06["vacias"]
            nuevo(num, d07, "dia_en_curso", f"{d07['texto']}: el día está a medias",
                  f"En el estatus de tarjetas faltan los datos de {len(sin)} {'tarjeta' if len(sin) == 1 else 'tarjetas'} ("
                  + ", ".join(sin[:5]) + ("…" if len(sin) > 5 else "") + ") y el estadístico todavía no tiene este día.",
                  "Es normal mientras se registra el día: cuando lo termines (con el PDF del día), se llenan las dos hojas. No hay nada que corregir.",
                  [], False)
            usadas.update(id(d) for d in pendientes)
        elif len(pendientes) >= 3 and len(vacias) == len(pendientes):
            nuevo(num, d07, "dia_sin_datos", f"{d07['texto']}: el estadístico no tiene los datos de este día",
                  f"El estatus de tarjetas tiene el día completo, pero en el estadístico {len(pendientes)} celdas están vacías o en cero: "
                  + ", ".join(d["concepto"] for d in pendientes[:6]) + ("…" if len(pendientes) > 6 else "") + ".",
                  "Parece que el día se registró en el estatus de tarjetas pero no en el estadístico.",
                  [celda(d) for d in pendientes], True)
            usadas.update(id(d) for d in pendientes)
        # 1c) una tarjeta del estatus SIN LLENAR (fila con nombre y sin números) y el estadístico tiene justo lo que le falta a esa
        #     cámara (o al sonido): CODT DIA 19, «26Y11M10» vacío y el estadístico con 2.09 GB / 44 clips de audio → se llena el estatus
        por_fila = {}
        for d in diferencias:
            if id(d) in usadas or not ec.es_numero(d["actual"]) or float(d["actual"]) <= float(d["esperado"]):
                continue
            t_, letra = d["clave"]
            if t_ in ("gb", "clips"):
                cand = [v for v in d06.get("vacias_filas", []) if not v["sonido"] and v["cam"] == letra]
            elif t_ in ("audio", "audio_clips"):
                cand = [v for v in d06.get("vacias_filas", []) if v["sonido"]]
            else:
                continue
            if len(cand) == 1:
                por_fila.setdefault(cand[0]["fila"], (cand[0], []))[1].append(d)
        for _fila, (v, ds) in sorted(por_fila.items()):
            celdas_v, partes = [], []
            for d in ds:
                medida = "gb" if d["clave"][0] in ("gb", "audio") else "clips"
                falta = float(d["actual"]) - float(d["esperado"])
                valor = round(falta, 2) if medida == "gb" else int(round(falta))
                if cols06.get(medida) is None or (medida == "clips" and abs(falta - round(falta)) > 1e-6):
                    continue
                celdas_v.append(celda06(v["fila"], cols06[medida], f"{'GB' if medida == 'gb' else 'Clips'} de «{v['nombre']}»", valor,
                                        "gb" if medida == "gb" else "num"))
                partes.append(f"{ec._bonito(valor, 'gb' if medida == 'gb' else 'num')} {'GB' if medida == 'gb' else 'clips'}")
                usadas.add(id(d))
            if celdas_v:
                nuevo(num, d07, "tarjeta_sin_llenar", f"{d07['texto']}: «{v['nombre']}» está sin llenar en el estatus",
                      f"En el estatus de tarjetas la fila de «{v['nombre']}» (fila {v['fila']}) no tiene números; el estadístico tiene "
                      + " y ".join(partes) + " más que el estatus para " + ("el sonido" if v["sonido"] else f"la cámara {v['cam']}") + ".",
                      "El estadístico ya tiene esa tarjeta y en el estatus quedó la fila vacía: paso esos números al estatus. "
                      "La duración no está en el estadístico por tarjeta: complétala tú con el PDF del día.",
                      celdas_v, True, malas06={v["nombre"]})
        # 2) la duración: si la diferencia es justo la de una tarjeta, se dice cuál
        for d in diferencias:
            if id(d) in usadas:
                continue
            if d["clave"][0] == "seg":
                usadas.add(id(d))
                dif = round((d["actual"] - d["esperado"]) * 86400)
                tarjetas = [f for f in d06["filas"] if not f["sonido"]]
                causa = "El estadístico tiene " + ("más" if dif > 0 else "menos") + f" duración que el estatus ({rs.hms(abs(dif))})."
                audio = next((f for f in d06["filas"] if f["sonido"] and f["seg"] > 0
                              and abs(d["actual"] * 86400 - f["seg"]) <= TOL_SEG), None)
                if audio:                                   # el estadístico tiene la duración del audio en vez de la del video
                    causa = (f"El estadístico tiene {rs.hms(d['actual'] * 86400)}, que es justo la duración del AUDIO «{audio['nombre']}»: "
                             "parece que se escribió la duración del audio en lugar de la del video.")
                else:
                    tarjeta = next((f for f in tarjetas if f["seg"] > 0 and abs(abs(dif) - f["seg"]) <= TOL_SEG), None)
                    if tarjeta:
                        causa += (f" Coincide con la duración de la tarjeta «{tarjeta['nombre']}»: "
                                  + ("parece que se sumó de más." if dif > 0 else "parece que no se sumó."))
                nuevo(num, d07, "valor", f"{d07['texto']}: la duración no coincide",
                      f"Estatus de tarjetas: {rs.hms(d['esperado'] * 86400)} · estadístico: {rs.hms(d['actual'] * 86400)}.",
                      causa, [celda(d)], True, v06=d["esperado"], v07=d["actual"])
        # 3) todo lo demás. Si son varias celdas del mismo día, un solo hallazgo (si no, saldrían 11 tarjetas por un día sin llenar)
        restantes = [d for d in diferencias if id(d) not in usadas]
        if len(restantes) >= 3:
            solo07 = [d for d in restantes if d["esperado"] == 0 and d["actual"] not in (0, 0.0)]
            nuevo(num, d07, "varios", f"{d07['texto']}: {len(restantes)} datos no coinciden",
                  "; ".join(f"{d['concepto']}: estatus {ec._bonito(d['esperado'], d['tipo'])} · estadístico "
                            f"{ec._bonito(d['actual'], d['tipo'])}" for d in restantes[:6]) + ("…" if len(restantes) > 6 else "") + ".",
                  "Varios datos del día son distintos; el estatus de tarjetas es la fuente."
                  + (" Hay datos en el estadístico que el estatus no tiene: esos no se borran solos." if solo07 else ""),
                  [celda(d) for d in restantes if d not in solo07], not (len(solo07) == len(restantes)))
            usadas.update(id(d) for d in restantes)
        for d in diferencias:
            if id(d) in usadas:
                continue
            falta = d["actual"] in (0, 0.0)
            solo07 = d["esperado"] == 0 and not falta          # el estadístico tiene un dato que el estatus no tiene: no se borra solo
            raras = _tarjetas_raras(d06, d, ritmo)             # tarjetas del estatus con un peso imposible para su duración
            if raras:
                causa = ("El problema parece estar en el estatus de tarjetas, no en el estadístico: "
                         + "; ".join(f"«{f['nombre']}» dice {f['gb']:,.2f} GB para {rs.hms(f['seg'])} de video ({m})" for f, m in raras)
                         + f" (lo normal en este proyecto son unos {ritmo * 60:,.1f} GB por minuto). ¿Un número mal escrito? "
                           "Corrígelo allí; por eso no lo cambio en el estadístico.")
                if len(raras) == 1 and d["tipo"] == "gb" and ec.es_numero(d["actual"]):
                    f, _m = raras[0]
                    debe = f["gb"] + float(d["actual"]) - float(d["esperado"])   # lo que tendría que pesar para cuadrar con el estadístico
                    if debe > 0 and ritmo and 0.5 <= debe / max(f["seg"] * ritmo, 0.01) <= 2 and cols06.get("gb") is not None:
                        # el peso que cuadra con el estadístico es normal para su duración: el número que falta (o está mal) es ESE
                        causa = ("El error está en el estatus de tarjetas: "
                                 + "; ".join(f"«{x['nombre']}» dice {x['gb']:,.2f} GB para {rs.hms(x['seg'])} de video ({m})" for x, m in raras)
                                 + f". Con {debe:,.2f} GB (lo que falta para llegar a lo del estadístico) pesa lo normal para su duración "
                                   f"(unos {ritmo * 60:,.1f} GB por minuto en este proyecto) y el día cuadra exacto: lo corrijo en el estatus.")
                        nuevo(num, d07, "valor", f"{d07['texto']}: {d['concepto']} no coincide",
                              f"Estatus de tarjetas: {ec._bonito(d['esperado'], d['tipo'])} · estadístico: {ec._bonito(d['actual'], d['tipo'])}.",
                              causa, [celda06(f["fila"], cols06["gb"], f"GB de «{f['nombre']}»", round(debe, 2), "gb")], True,
                              v06=d["esperado"], v07=d["actual"], malas06={f["nombre"]})
                        continue
                    if debe > 0 and ritmo and 0.5 <= debe / max(f["seg"] * ritmo, 0.01) <= 2:
                        causa += f" Si «{f['nombre']}» pesara {debe:,.2f} GB, el día cuadraría exacto con el estadístico."
            else:
                tecleo = _error_de_tecleo(d["esperado"], d["actual"], d["tipo"])
                causa = ("Falta ese dato en el estadístico." if falta and d["esperado"] else
                         ("El estadístico tiene un dato que el estatus de tarjetas no tiene (¿material de otra fuente?). "
                          "No lo borro solo: revísalo." if solo07 else
                          (f"Parece un error al teclear en el estadístico ({tecleo}); el estatus de tarjetas es la fuente." if tecleo else
                           "Los dos números son distintos; el estatus de tarjetas es la fuente.")))
            nuevo(num, d07, "valor", f"{d07['texto']}: {d['concepto']} no coincide",
                  f"Estatus de tarjetas: {ec._bonito(d['esperado'], d['tipo'])} · estadístico: {ec._bonito(d['actual'], d['tipo'])}.",
                  causa, [celda(d)], not solo07 and not raras, v06=d["esperado"], v07=d["actual"],
                  malas06={f["nombre"] for f, _m in raras})
        if redondeo_dia:                                    # un hallazgo por día con sus diferencias de redondeo (aparte: no cuentan como incongruencias)
            celdas_r = [celda(d) for d in redondeo_dia]
            redondeos.append({"id": 100000 + len(redondeos) + 1, "dia": num, "texto_dia": d07["texto"], "tipo": "redondeo",
                              "titulo": f"{d07['texto']}: diferencia de redondeo",
                              "detalle": "; ".join(f"{c['concepto']}: estatus {c['nuevo_txt']} · estadístico {c['antes_txt']}" for c in celdas_r) + ".",
                              "causa": ("El estadístico tiene el valor redondeado a TB (por ejemplo 1.30 TB escrito como 1,300 GB); el exacto es el "
                                        "del estatus de tarjetas." if any(d.get("a_tb") for d in redondeo_dia) else
                                        "Diferencia mínima: el estadístico tiene el número redondeado (o la duración con segundos de más o de menos)."),
                              "corregible": True, "celdas": celdas_r, "v06": "", "v07": "",
                              "vista07": None, "vista06": None})
    # días con datos en el estadístico que el estatus no tiene
    ctx["d06"] = None
    for d in tabla["dias"]:
        num = d["num"]
        if id(d) in emparejadas07 or num in excluir_dias:
            continue
        gb = sum(float(ec.cel(datos07, d["fila"], c)) for c in tabla["gb"].values() if ec.es_numero(ec.cel(datos07, d["fila"], c)))
        if gb > 0:
            nuevo(num, d, "falta_en_06", f"{d['texto']}: está en el estadístico pero no en el estatus de tarjetas",
                  f"El estadístico suma {gb:,.2f} GB ese día; el estatus de tarjetas no tiene ese día.",
                  "Falta registrar el día en el estatus (o el número del día no coincide).", [], False)
    if sin_columna:
        avisos.append("Cámaras con material en el estatus pero sin columna en el estadístico: " + ", ".join(sorted(sin_columna))
                      + ". No se pueden comparar.")
    return {"hallazgos": hallazgos, "comparados": comparados, "avisos": avisos, "redondeos": redondeos}


def _error_de_tecleo(bueno, malo, tipo):
    """«un número cambiado: 212.31 → 213.31» / «dos números al revés: 81.69 → 81.96», o "" si no parece un error al teclear."""
    if tipo not in ("gb", "num") or not ec.es_numero(bueno) or not ec.es_numero(malo):
        return ""
    fmt = "{:.2f}" if tipo == "gb" else "{:.0f}"
    a_, b_ = fmt.format(float(bueno)), fmt.format(float(malo))
    if len(a_) != len(b_) or a_ == b_:
        return ""
    dif = [i for i, (x, y) in enumerate(zip(a_, b_)) if x != y]
    if len(dif) == 1:
        return f"un número cambiado: {a_} → {b_}"
    if len(dif) == 2 and dif[1] == dif[0] + 1 and a_[dif[0]] == b_[dif[1]] and a_[dif[1]] == b_[dif[0]]:
        return f"dos números al revés: {a_} → {b_}"
    return ""


def _fecha_o_none(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _lecturas_de_fecha(v):
    """La fecha de una celda y, si es posible, la misma con día y mes al revés."""
    f = rs._fecha(v) if v not in ("", None) else None
    if not f:
        return set()
    otra = _fecha_o_none(f.year, f.day, f.month) if f.day <= 12 else None
    return {f} | ({otra} if otra else set())


def _texto_de_fecha(v):
    f = rs._fecha(v) if v not in ("", None) else None
    return f"{f:%d/%m/%Y}" if f else (str(v) if v not in ("", None) else "vacía")


def _fecha_como(antes, fecha):
    """La fecha escrita IGUAL que la que había en la celda (serial, 20240317, 17032024, «17/03/2024», «2024-03-17»…)."""
    if ec.es_numero(antes):
        r = ec._formato_de_numero(antes)
        return ec.valor_de_fecha(fecha, r[0] if r else "serial")
    if isinstance(antes, str):
        m = re.fullmatch(r"\s*(\d{1,2})([/.-])(\d{1,2})\2(\d{4})\s*", antes)
        if m:
            ceros = len(m[1]) == 2 or len(m[3]) == 2
            a, b = (fecha.month, fecha.day) if ec.ORDEN_FECHA["texto"] == "mdy" else (fecha.day, fecha.month)
            return (f"{a:02d}{m[2]}{b:02d}" if ceros else f"{a}{m[2]}{b}") + f"{m[2]}{fecha.year}"
        m = re.fullmatch(r"\s*(\d{4})([/.-])(\d{1,2})\2(\d{1,2})\s*", antes)
        if m:
            return f"{fecha.year}{m[2]}{fecha.month:02d}{m[2]}{fecha.day:02d}"
        if re.fullmatch(r"\s*\d{8}\s*", antes):
            return f"{fecha.year}{fecha.month:02d}{fecha.day:02d}"
    return ec.serial_de_fecha(fecha)


def _proponer_dia_faltante(datos07, tabla, d06, excluir=()):
    """El día del estatus que no tiene fila en el estadístico, armado como al registrarlo con el PDF. (propuesta, motivo si no)."""
    num, fecha = d06["num"], d06.get("fecha")
    otra = next((d for d in tabla["dias"] if d["num"] == num and (d.get("suf") or "") == (d06.get("suf") or "")), None) \
        or next((d for d in tabla["dias"] if fecha and d.get("fecha") == fecha), None)
    if otra is not None:                     # algo con ese número o esa fecha ya existe: no se agrega a ciegas una fila repetida
        return None, (f"Ya hay una fila «{otra['texto']}» con ese número o esa fecha; revisa cuál de las dos hojas tiene el número o la fecha "
                      "equivocados.")
    unidades = {d.get("unidad") for d in tabla["dias"]}
    dedicado = len(unidades) <= 1
    unidad = next(iter(unidades)) if dedicado and unidades and next(iter(unidades)) not in (None, "") else 1
    reporte = {"dia": f"D{num:03d}", "fecha": datetime.combine(fecha, datetime.min.time()) if fecha else None,
               "unidad": unidad if isinstance(unidad, int) else 1}
    try:
        prop = ec.proponer(datos07, None, d06["filas"], reporte, lambda f: f["sonido"], dedicado=dedicado)
    except Exception as e:                   # (ErrorRegistro u hoja rara) → se avisa como antes, sin corrección
        return None, str(e)
    if not prop.get("cambios"):
        return None, ""
    return prop, ""


def donde_corrige(h):
    """'el estatus de tarjetas', 'el estadístico' o 'las dos hojas' (para los botones y las preguntas)."""
    hojas = {c.get("hoja", "datos") for c in h.get("celdas", [])}
    if hojas == {"estatus"}:
        return "el estatus de tarjetas"
    return "las dos hojas" if "estatus" in hojas else "el estadístico"


def donde_corto(h):
    return {"el estatus de tarjetas": "el estatus"}.get(donde_corrige(h), donde_corrige(h))


def texto_cambios(h, maximo=8):
    """«estatus H145  GB de «A063»: vacía → 44.37   ·   E21  FECHA: …» para mostrar debajo de cada hallazgo."""
    cs = h.get("celdas", [])
    txt = "   ·   ".join(f"{'estatus ' if c.get('hoja') == 'estatus' else 'Resumen ' if c.get('hoja') == 'resumen' else ''}{c['celda']}  "
                           f"{c['concepto']}: {c['antes_txt']} → {c['nuevo_txt']}" for c in cs[:maximo])
    if len(cs) > maximo:
        txt += f"   ·   (y {len(cs) - maximo} más)"
    if h.get("propuesta"):
        p_ = h["propuesta"]
        txt = (f"fila nueva {p_['fila'] + 1} «{p_['texto_dia']}»: " if p_.get("insertar_fila") else f"fila {p_['fila'] + 1} «{p_['texto_dia']}»: ") + txt
    return f"Se cambiaría en {donde_corrige(h)}:  " + txt


def texto_confirmar(hall):
    """(título, texto) de la pregunta «¿Hago N correcciones…?»."""
    hojas = {donde_corrige(h) for h in hall}
    donde = hojas.pop() if len(hojas) == 1 else "las dos hojas"
    lineas = []
    for h in hall:
        cs = h["celdas"]
        lugar = {"estatus": "estatus ", "datos": "", "resumen": "Resumen "}
        txt = ", ".join(f"{lugar.get(c.get('hoja', 'datos'), '')}{c['celda']} {c['antes_txt']} → {c['nuevo_txt']}" for c in cs[:6])
        lineas.append(f"• {h['texto_dia']}: " + (f"agregar la fila del día ({len(cs)} celdas)" if h.get("propuesta") else
                                                 txt + ("…" if len(cs) > 6 else "")))
    return (f"Corregir {donde}",
            f"¿Hago {len(hall)} corrección(es) en {donde}?\n\n" + "\n".join(lineas)
            + "\n\nAntes de escribir vuelvo a leer esas celdas; si alguien las cambió, no toco nada.")


def aplicar_correcciones(servicio, rg, est, hoja06, hallazgos):
    """Escribe las correcciones aprobadas: celdas del estadístico (`est`) y del estatus de tarjetas (`hoja06` = cfg["hoja"],
    la pestaña sale de `h["pestana06"]`), y los días que faltaban en el estadístico (`h["propuesta"]`). Antes relee cada celda: si
    alguien la cambió, no escribe NADA. Después lee de vuelta. `rg` = registro_google (o el del celular). Devuelve [(estado, texto)]."""
    sid07 = rg.id_de_enlace(est["enlace"])
    sid06 = rg.id_de_enlace(hoja06["enlace"]) if hoja06 and hoja06.get("enlace") else None

    def destino(h, c):
        if c.get("hoja") == "estatus":
            if not sid06:
                raise ec.ErrorRegistro("No tengo conectado el estatus de tarjetas para corregirlo.")
            return sid06, h.get("pestana06") or hoja06.get("pestana")
        return sid07, (est.get("resumen") if c.get("hoja") == "resumen" else est["datos"])

    def mismo(a_, b, tipo):
        if tipo == "hora":
            return ec.es_numero(a_) and ec.es_numero(b) and abs(float(a_) - float(b)) < 1.0 / 86400
        if tipo == "fecha":
            return (a_ in ("", None) and b in ("", None)) or ec.igual(a_, b) or str(a_).strip() == str(b).strip()
        return ec.igual(a_ if a_ not in (None, "") else 0.0, b if b not in (None, "") else 0.0)

    simples = [h for h in hallazgos if not h.get("propuesta")]
    pares = [(h, c) + destino(h, c) for h in simples for c in h["celdas"]]
    por_sid = {}
    for _h, c, sid, pest in pares:
        por_sid.setdefault(sid, []).append((pest, c["celda"]))
    actuales = {sid: rg.leer_celdas(servicio, sid, claves) for sid, claves in por_sid.items()}
    if any(not mismo(actuales[sid].get((pest, c["celda"]), ""), c.get("antes_raw", c.get("antes")), c["tipo"]) for _h, c, sid, pest in pares):
        raise ec.ErrorRegistro("Las hojas cambiaron mientras tanto (alguien editó esas celdas). No corregí nada: pulsa «Actualizar» y vuelve a revisar.")
    for h in hallazgos:                      # los días que faltaban: se comprueba que su lugar siga igual antes de escribir nada
        p_ = h.get("propuesta")
        if p_:
            mirar = [((est["datos"], c["celda_antes"]), c) for c in p_["cambios"] if c.get("celda_antes")]
            act = rg.leer_celdas(servicio, sid07, [k for k, _c in mirar]) if mirar else {}
            if any(not ec.igual(act.get(k, ""), c["antes"]) for k, c in mirar):
                raise ec.ErrorRegistro("El estadístico cambió mientras tanto. No corregí nada: pulsa «Actualizar» y vuelve a revisar.")
    for sid in por_sid:
        rg.escribir_celdas(servicio, sid, [(pest, c["celda"], c["nuevo"]) for _h, c, s_, pest in pares if s_ == sid])
    leidos = {sid: rg.leer_celdas(servicio, sid, claves) for sid, claves in por_sid.items()}
    salida = []
    for h in simples:
        bien = all(mismo(leidos[sid].get((pest, c["celda"]), ""), c["nuevo"], c["tipo"]) for h2, c, sid, pest in pares if h2 is h)
        donde = donde_corrige(h)
        salida.append(("ok", f"Corregido {h['texto_dia']} en {donde}: ahora las dos hojas coinciden.") if bien else
                      ("aviso", f"Corregí {h['texto_dia']} en {donde}, pero al leerlo de vuelta no quedó como esperaba: revisa esa fila."))
    for h in hallazgos:
        p_ = h.get("propuesta")
        if not p_:
            continue
        pest = {"datos": est["datos"], "resumen": est.get("resumen", "")}
        if p_.get("estructura"):
            rg.aplicar_estructura(servicio, sid07, pest, p_["estructura"])
        rg.escribir_celdas(servicio, sid07, [(pest[c["hoja"]], c["celda"], c["nuevo"]) for c in p_["cambios"]])
        try:
            claves = [(pest[c["hoja"]], c["celda"]) for c in p_["cambios"]]
            tot = p_.get("lectura_total")
            lei = rg.leer_celdas(servicio, sid07, claves + ([(est["datos"], tot)] if tot else []))
            res = ec.comprobar(p_, {(c["hoja"], c["celda"]): lei.get(k) for k, c in zip(claves, p_["cambios"])},
                               lei.get((est["datos"], tot)) if tot else None)
            mal = [t for e_, t in res if e_ != "ok"]
            salida.append(("aviso", f"Agregué {h['texto_dia']} al estadístico, pero revisa: " + " ".join(mal)) if mal else
                          ("ok", f"Agregado {h['texto_dia']} al estadístico («{p_['texto_dia']}», fila {p_['fila'] + 1}) y comprobado."))
        except Exception as e:
            salida.append(("aviso", f"Agregué {h['texto_dia']} al estadístico, pero no pude comprobarlo: {e}"))
    return salida


def unir_cruces(partes):
    """Junta las revisiones de varias unidades (cada una con su estadístico) en una sola. `partes`: [(etiqueta, índice_del_estadístico, cruce)].
    Cada hallazgo conserva `est` (cuál estadístico se corregiría) y, si hay varias unidades, lleva la unidad delante del día."""
    if len(partes) == 1:
        etiqueta, j, cr = partes[0]
        for h in cr["hallazgos"] + cr.get("redondeos", []):
            h["est"] = j
            h["pestana06"] = etiqueta                  # (las correcciones del estatus van a ESTA pestaña)
        for k, h in enumerate(cr.get("redondeos", []), start=1):
            h["id"] = 100000 + k                       # los ids de redondeo no chocan con los de las incongruencias
        return cr
    hallazgos, redondeos, avisos, comparados = [], [], [], 0
    for etiqueta, j, cr in partes:
        comparados += cr["comparados"]
        avisos += [f"{etiqueta}: {a}" for a in cr["avisos"]]
        for h in cr["hallazgos"]:
            hallazgos.append(dict(h, id=len(hallazgos) + 1, est=j, unidad=etiqueta, pestana06=etiqueta,
                                  texto_dia=f"{etiqueta} · {h['texto_dia']}"))
        for h in cr.get("redondeos", []):
            redondeos.append(dict(h, id=100000 + len(redondeos) + 1, est=j, unidad=etiqueta, texto_dia=f"{etiqueta} · {h['texto_dia']}",
                                  titulo=f"{etiqueta} · {h['titulo']}"))
    return {"hallazgos": hallazgos, "comparados": comparados, "avisos": avisos, "redondeos": redondeos}
