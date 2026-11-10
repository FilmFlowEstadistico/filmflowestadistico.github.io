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
    Si el error está en el estatus, la app lo avisa pero no lo toca (no puede saber cuál fila es la mala).

No escribe nada: solo devuelve hallazgos. Cada hallazgo trae las celdas del estadístico que se cambiarían, para que la persona decida.
"""

import re
from datetime import date

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
            continue
        con_letra = bool(re.match(r"^[A-Za-z]+_?\d", nombre.strip()))        # «BETACAM_TEST» no dice de qué cámara es
        actual["filas"].append({"nombre": nombre.strip(), "cam": rc.clave_de_bin(nombre, claves), "cam_dudosa": not con_letra, "gb": gb, "clips": clips, "seg": seg,
                                "sonido": bool((g and g["nombre"] in sonido) or rc.es_nombre_de_sonido(nombre)
                                               or rc.es_modelo_de_audio(modelo)), "fila": n + 1})
    for d in dias:                                     # día y mes al revés en la hoja: manda el archivo de la grabadora
        d["fecha"] = ec.fecha_segun_sonido(d["fecha"], [f["nombre"] for f in d["filas"] if f["sonido"]])
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
    filas = []
    for i, f in enumerate(d06["filas"][:16]):
        celdas_f = []
        for c in cols:
            medida = nombre_de.get(c)
            if medida == "dia":
                texto = str(d06["etiqueta"]) if i == 0 else ""
            elif medida == "fecha":
                texto = d06["fecha"].strftime("%d/%m/%Y") if (i == 0 and d06["fecha"]) else ""
            elif medida == "cam":
                texto = f["nombre"]
            elif medida == "clips":
                texto = str(f["clips"])
            elif medida == "duracion":
                texto = rs.hms(f["seg"])
            else:
                texto = f"{f['gb']:,.2f}"
            celdas_f.append((texto, marca(f, medida)))
        filas.append({"n": f["fila"], "dia": False, "celdas": celdas_f})
    return {"titulos": titulos, "filas": filas, "recortado": len(d06["filas"]) > 16}


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


def cruzar(g06, datos07, cfg, excluir_dias=()):
    """Compara los días que están en las dos hojas. `g06`: valores reales del estatus; `datos07`: «Datos Generales».
    `excluir_dias`: números de día que no se miran (el que se está registrando ahora).
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
    titulos06 = [str(ec.cel(g06, _columnas_f06(g06)[0], c)) for c in _cols_vista06(cols06)]

    ctx = {"d06": None}

    def nuevo(num, d07, tipo, titulo, detalle, causa, celdas, corregible, v06="", v07="", malas06=()):
        d06 = ctx["d06"]
        hallazgos.append({"id": len(hallazgos) + 1, "dia": num, "texto_dia": d07["texto"] if d07 else f"día {num}", "tipo": tipo,
                          "titulo": titulo, "detalle": detalle, "causa": causa, "corregible": corregible and bool(celdas),
                          "celdas": celdas, "v06": v06, "v07": v07,
                          "vista07": _vista07(datos07, tabla, d07, celdas, corregible and bool(celdas), tipo),
                          "vista06": _vista06(g06, cols06, titulos06, d06, celdas, tipo, malas06) if d06 else None})

    for pos06, d06 in enumerate(dias06):
        num = d06["num"]
        ctx["d06"] = d06
        if num in excluir_dias or not d06["filas"]:        # los días preparados de antemano (sin material) no se comparan ni se cuentan
            continue
        d07 = filas07.get(pos06)
        if d07 is None:
            if any(f["gb"] > 0 for f in d06["filas"]):
                nuevo(num, None, "falta_en_07", f"El día {num} no tiene fila en el estadístico",
                      f"Está en el estatus de tarjetas ({d06['etiqueta']}), pero «Datos Generales» no tiene su fila.",
                      "Falta agregar la fila del día en el estadístico.", [], False)
            continue
        comparados += 1
        r = d07["fila"]
        f06, f07 = d06.get("fecha"), d07.get("fecha")
        if f06 and f07 and f06 != f07:
            pista = ""
            for f in d06["filas"]:                          # el archivo de sonido lleva la fecha de la grabadora: 26Y10M09 = 09/10/2026
                mm = re.match(r"(\d{2})Y(\d{2})M(\d{2})", f["nombre"]) if f["sonido"] else None
                if mm:
                    try:
                        fs = date(2000 + int(mm[1]), int(mm[2]), int(mm[3]))
                    except ValueError:
                        continue
                    pista = (f" El archivo de sonido «{f['nombre']}» es del {fs:%d/%m/%Y}"
                             + (", como dice el estadístico." if fs == f07 else ", como dice el estatus de tarjetas." if fs == f06 else "."))
                    break
            nuevo(num, d07, "fecha", f"{d07['texto']}: la fecha no coincide",
                  f"Estatus de tarjetas: {f06:%d/%m/%Y} · estadístico: {f07:%d/%m/%Y}.",
                  "Una de las dos hojas tiene la fecha equivocada; los reportes por fecha usan la del estatus de tarjetas." + pista,
                  [], False)
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
                    if debe > 0 and ritmo and 0.5 <= debe / max(f["seg"] * ritmo, 0.01) <= 2:
                        causa += f" Si «{f['nombre']}» pesara {debe:,.2f} GB, el día cuadraría exacto con el estadístico."
            else:
                causa = ("Falta ese dato en el estadístico." if falta and d["esperado"] else
                         ("El estadístico tiene un dato que el estatus de tarjetas no tiene (¿material de otra fuente?). "
                          "No lo borro solo: revísalo." if solo07 else
                          "Los dos números son distintos; el estatus de tarjetas es la fuente."))
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


def unir_cruces(partes):
    """Junta las revisiones de varias unidades (cada una con su estadístico) en una sola. `partes`: [(etiqueta, índice_del_estadístico, cruce)].
    Cada hallazgo conserva `est` (cuál estadístico se corregiría) y, si hay varias unidades, lleva la unidad delante del día."""
    if len(partes) == 1:
        etiqueta, j, cr = partes[0]
        for h in cr["hallazgos"] + cr.get("redondeos", []):
            h["est"] = j
        for k, h in enumerate(cr.get("redondeos", []), start=1):
            h["id"] = 100000 + k                       # los ids de redondeo no chocan con los de las incongruencias
        return cr
    hallazgos, redondeos, avisos, comparados = [], [], [], 0
    for etiqueta, j, cr in partes:
        comparados += cr["comparados"]
        avisos += [f"{etiqueta}: {a}" for a in cr["avisos"]]
        for h in cr["hallazgos"]:
            hallazgos.append(dict(h, id=len(hallazgos) + 1, est=j, unidad=etiqueta, texto_dia=f"{etiqueta} · {h['texto_dia']}"))
        for h in cr.get("redondeos", []):
            redondeos.append(dict(h, id=100000 + len(redondeos) + 1, est=j, unidad=etiqueta, texto_dia=f"{etiqueta} · {h['texto_dia']}",
                                  titulo=f"{etiqueta} · {h['titulo']}"))
    return {"hallazgos": hallazgos, "comparados": comparados, "avisos": avisos, "redondeos": redondeos}
