"""
RESUMEN DEL PROYECTO (lógica pura, sin pantalla ni Google: se puede probar sola)
================================================================================
Convierte lo que se LEE de tus hojas de Google en un resumen del proyecto:
  - Estatus de tarjetas (FO-06): una fila por tarjeta → TB por cámara, rollo en el que va cada cámara, clips, duración, días.
  - Estadístico (FO-07): totales por cámara, días previstos, espacio previsto, equipo y formato de grabación.
No inventa nada: si un dato no está en las hojas conectadas, queda vacío («—»).

Unidades: las hojas están en GB DECIMALES. 1 TB = 1.000 GB (no 1.024). Todo el programa usa la misma regla.
"""
import re
from datetime import datetime, time, timedelta

import estadistico_core as ec
import registro_core as rc

GB_POR_TB = 1000.0
TOLERANCIA_COINCIDENCIA = 0.02       # si FO-06 y FO-07 difieren más de 2 %, se avisa


# ---------------------------------------------------------------------------------------------
# Lectura tolerante de celdas (Google entrega números; los Excel de prueba traen fechas y horas)
# ---------------------------------------------------------------------------------------------
def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(" ", "")
        if re.fullmatch(r"-?\d+(\.\d+)?", t):
            return float(t)
        if re.fullmatch(r"-?\d+(,\d+)?", t):
            return float(t.replace(",", "."))
    return None


def _segundos(v):
    """Duración en segundos: acepta fracción de día (Google), horas:minutos:segundos, timedelta o time."""
    if isinstance(v, timedelta):
        return v.total_seconds()
    if isinstance(v, time):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, datetime):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d+)[:;](\d{1,2})[:;](\d{1,2})\s*", v)
        if m:
            return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        return 0.0
    n = _num(v)
    return round(n * 86400) if n is not None else 0.0


def _fecha(v):
    """La fecha de una celda (fecha real, número de Excel, 20260803, 28092026 o «28/09/2026»), o None. Nunca falla."""
    return ec.fecha_de_celda(v)


# Teclas de los números con Mayús (así se escribe «!» queriendo «1»): teclado en español y en inglés. Solo se usan dentro de un número u hora.
_TECLAS = {"!": "1", '"': "2", "@": "2", "#": "3", "·": "3", "$": "4", "%": "5", "&": "6", "/": "7", "(": "8", ")": "9", "=": "0",
           "O": "0", "o": "0", "l": "1", "I": "1", "|": "1", ";": ":"}


def sugerir_celda(clave, texto):
    """Lo que probablemente quiso escribir quien tecleó `texto` en una columna numérica del estatus: «00:23:!4» → 0:23:14 (el «!» es la tecla
    del 1). Devuelve (valor para escribir, cómo se verá, motivo) o None si no se puede adivinar con seguridad (no se inventa nada)."""
    t = str(texto).strip()
    if clave == "clips" and re.search(r"(?i)\d\s*clips?\s*$", t):          # «12 clips»
        t = re.sub(r"(?i)\s*clips?\s*$", "", t)
    cambios = []
    limpio = ""
    for ch in t:
        if ch in _TECLAS:
            cambios.append(f"«{ch}» por {_TECLAS[ch]}")
            limpio += _TECLAS[ch]
        else:
            limpio += ch
    if len(cambios) > 2:
        return None
    motivo = ("cambié " + " y ".join(cambios) + " (son teclas que se confunden con ese número)") if cambios else "quité lo que sobraba"
    if clave == "duracion":
        m = re.fullmatch(r"\s*(\d{1,3})[:.;](\d{1,2})[:.;](\d{1,2})\s*", limpio)
        if m and not cambios and ":" not in limpio:
            motivo = "los separadores eran puntos (o punto y coma) en vez de «:»"
        if not m:
            m2 = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", limpio)                       # «23:14» = minutos:segundos
            if m2 and int(m2[1]) < 60 and int(m2[2]) < 60:
                seg = int(m2[1]) * 60 + int(m2[2])
                return seg / 86400.0, hms(seg), (motivo + "; " if cambios else "") + "faltaban las horas (23:14 = 0:23:14)"
            m3 = re.fullmatch(r"\s*(?:(\d{1,3})\s*h)?\s*(?:(\d{1,2})\s*m(?:in)?)?\s*(?:(\d{1,2})\s*s(?:eg)?)?\s*", limpio, re.I)
            if m3 and any(m3.groups()):                                                  # «1h 20m 5s»
                seg = int(m3[1] or 0) * 3600 + int(m3[2] or 0) * 60 + int(m3[3] or 0)
                return seg / 86400.0, hms(seg), "estaba escrita con h/m/s"
            return None
        if int(m[2]) >= 60 or int(m[3]) >= 60:
            return None
        seg = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        return seg / 86400.0, hms(seg), motivo
    n = limpio.replace(" ", "")
    if clave == "clips":
        m = re.fullmatch(r"(\d{1,5})(?:clips?)?", n, re.I)
        return (int(m[1]), m[1], motivo) if m else None
    unidad = re.fullmatch(r"(.*?)(TB|GB|MB)", n, re.I)              # «12.5 GB», «1,3TB», «500 MB»: a GB
    factor = 1.0
    if unidad:
        n, u = unidad[1], unidad[2].upper()
        factor = {"TB": 1000.0, "GB": 1.0, "MB": 0.001}[u]
        motivo = f"pasé {u} a GB" if u != "GB" else "quité «GB»"
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", n):                  # «1.300,52» (puntos de miles y coma decimal)
        v = float(n.replace(".", "").replace(",", ".")) * factor
        return v, f"{v:,.2f}", "puntos de miles y coma decimal (1.300,52 = 1,300.52)"
    if factor != 1.0 or unidad:
        if re.fullmatch(r"\d+(?:[.,]\d+)?", n):
            v = round(float(n.replace(",", ".")) * factor, 2)
            return v, f"{v:,.2f}", motivo
    if re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?|\d+(\.\d+)?", n):          # «1,300.52» escrito como texto
        v = float(n.replace(",", ""))
        return v, f"{v:,.2f}", "quité las comas de miles" if "," in n and not cambios else motivo
    if re.fullmatch(r"\d+,\d{1,2}", n):
        v = float(n.replace(",", "."))
        return v, f"{v:,.2f}", "la coma era el punto decimal"
    return None


def hms(seg):
    seg = int(round(seg or 0))
    return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def texto_peso(gb):
    """«1.07 TB» o «620 GB»: TB desde 1.000 GB."""
    gb = gb or 0
    return f"{gb / GB_POR_TB:,.2f} TB" if gb >= GB_POR_TB else f"{gb:,.0f} GB" if gb >= 10 else f"{gb:,.2f} GB"


def numero_de_rollo(bin_):
    """'A_0124_1EOH_hde' → 124; 'D005_E00N15' → 5; 'I003' → 3; el sonido ('26Y10M08') no tiene → None."""
    texto = str(bin_ or "").strip()
    m = re.match(r"^[A-Za-z]_?(\d+)", texto) or re.match(r"^[A-Za-z]{2,}_?\d{1,4}_[A-Za-z](\d+)", texto)   # DJI_001_H15 → 15
    return int(m.group(1)) if m else None


def es_repeticion_de(nombre, conocidos):
    """True si `nombre` es una versión de un rollo que ya vimos: 'N004_1' (o 'N004_2'…) repite 'N004'. Esa versión no es un rollo
    más avanzado: aunque aparezca después en la hoja, 'el rollo en el que va' sigue siendo el de mayor número (N006)."""
    base = re.sub(r"[_\- ]\d{1,2}$", "", str(nombre or "").strip())
    return base != str(nombre or "").strip() and base in conocidos


def dia_corto(texto):
    """'20261009_DAY051' → 'D051'; el día escrito solo con su número ('8', 8.0) → 'D008'; 'D043' o 'DIA 40' se quedan como están."""
    m = re.search(r"DAY0*(\d+)", str(texto), re.IGNORECASE)
    if m:
        return f"D{int(m.group(1)):03d}"
    n = re.fullmatch(r"\s*(\d{1,3})(?:\.0+)?\s*", str(texto))
    return f"D{int(n.group(1)):03d}" if n else str(texto)


def _titulos(fila):
    return [ec._n(x) for x in fila]


# ---------------------------------------------------------------------------------------------
# Estatus de tarjetas (FO-06)
# ---------------------------------------------------------------------------------------------
def columnas_f06(filas):
    """(fila_de_títulos, columnas) del estatus de tarjetas, con títulos en español o inglés:
    dia, fecha_col, rental, cam, modelo, mag, clips, duracion, gb. Lanza ErrorRegistro si no encuentra la tabla."""
    hallado = rc.encontrar_encabezado(filas)
    if not hallado:
        raise rc.ErrorRegistro("No encontré los títulos de la tabla de estatus de tarjetas (DIA RODAJE, CAM, RENTAL…). "
                               "¿Es la pestaña correcta?")
    i0, col = hallado
    t = _titulos(filas[i0])
    col = dict(col)
    for clave, prueba in (("clips", lambda x: "clips" in x),
                          ("duracion", lambda x: x.startswith("duracion") or x.startswith("duration")),
                          ("gb", lambda x: x.startswith("total") and "gb" in x)):
        for j, x in enumerate(t):
            if prueba(x):
                col[clave] = j
                break
    col.setdefault("dia", 0)                       # sin título de día se usa la primera columna
    col.setdefault("clips", 6)
    col.setdefault("duracion", 7)
    col.setdefault("gb", 8)
    col.setdefault("fecha_col", next((j for j, x in enumerate(t) if x.startswith("fecha") or x == "date"), 1))
    return i0, col


def _clave_modelo(modelo):
    """«SOUND DEVICE 788T» y «Sound Devices 788T» son la misma grabadora: 788t."""
    t = re.sub(r"sound\s*devices?", "", str(modelo).lower())
    return re.sub(r"[^a-z0-9]+", "", t) or "audio"


def modelo_corto(modelo):
    """«SOUND DEVICES 633» → «633» (para rotular el sonido por grabadora)."""
    t = re.sub(r"(?i)sound\s*devices?\s*", "", str(modelo)).strip()
    return t or str(modelo).strip()


def resumir_f06(filas, cfg, unidad=""):
    """`filas`: toda la pestaña (valores reales). Devuelve un diccionario con rollos, días y avisos, o lanza ErrorRegistro."""
    i0, col = columnas_f06(filas)
    with ec.orden_de_fechas(ec.cel([f], 0, col["fecha_col"]) for f in filas[i0 + 1:]):     # el orden de fechas de ESTA pestaña
        return _resumir_f06(filas, cfg, unidad, i0, col)


def _resumir_f06(filas, cfg, unidad, i0, col):
    fecha_col = col["fecha_col"]

    por_grupo, sin_grupo, dias = {}, {}, []
    celdas_texto = []             # números/horas escritos con un error de dedo («00:23:!4»): la suma los ignora y nadie lo nota
    dia_vigente = None            # el día en curso solo entra a la lista cuando tiene material (los días preparados de antemano NO cuentan como rodados)
    for n_fila, fila in enumerate(filas[i0 + 1:], start=i0 + 2):          # n_fila = número de fila en la hoja
        nombre = ec.cel([fila], 0, col["cam"])
        gb = _num(ec.cel([fila], 0, col["gb"]))
        etiqueta_dia = ec.cel([fila], 0, col["dia"])
        if not (isinstance(nombre, str) and nombre.strip()):
            continue                                  # filas de total del día o vacías
        if etiqueta_dia not in ("", None) and (dia_vigente is None or dia_vigente["dia"] != str(etiqueta_dia).strip()):
            dia_vigente = {"dia": str(etiqueta_dia).strip(), "fecha": _fecha(ec.cel([fila], 0, fecha_col)),
                           "gb": 0.0, "clips": 0, "seg": 0.0, "tarjetas": 0, "clips_audio": 0, "seg_audio": 0.0, "_en_lista": False,
                           "detalle": []}            # cada tarjeta del día (para el reporte por fechas)
        if dia_vigente is None:
            continue
        dia = dia_vigente
        nombre = nombre.strip()
        clips = int(_num(ec.cel([fila], 0, col["clips"])) or 0)
        seg = _segundos(ec.cel([fila], 0, col["duracion"]))
        for nom_col, clave_col, ok in (("# of Clips", "clips", _num), ("Duración", "duracion", None), ("Total GB", "gb", _num)):
            crudo = ec.cel([fila], 0, col[clave_col])
            if isinstance(crudo, str) and re.search(r"\d", crudo) and (_segundos(crudo) == 0 or ";" in crudo if ok is None else ok(crudo) is None):
                # («1:36;21»: la app la entiende, pero en Google es texto y las sumas de la hoja no la cuentan)
                celdas_texto.append({"unidad": unidad, "fila": n_fila, "col": col[clave_col], "columna": nom_col, "clave": clave_col,
                                     "valor": crudo.strip(), "bin": nombre.strip(), "dia": dia_vigente["dia"]})
        gb = gb or 0.0
        if not gb and not clips and not seg:
            continue                                  # fila preparada de antemano (D007…) sin material todavía
        if not dia["_en_lista"]:
            dia["_en_lista"] = True
            dias.append(dia)
        mag = _num(ec.cel([fila], 0, col["mag"])) if col.get("mag") is not None else None     # sin columna «# Mag» (SSSHP4) no se lee otra en su lugar
        modelo_f = ec.cel([fila], 0, col["modelo"]) if col.get("modelo") is not None else ""
        audio_f = rc.es_modelo_de_audio(modelo_f) or rc.es_nombre_de_sonido(nombre)
        # La grabadora (ZOOM…) comparte letra con un dron: manda el equipo. Un BIN de audio con un nombre que ningún rollo reconoce
        # («AMBIENTES_U2») igual es audio: va al rollo de Sonido (o a uno provisional) en vez de quedar suelto.
        g = (rc.grupo_de_audio(nombre, cfg, modelo_f) or rc.grupo_de_sonido(cfg)) if audio_f \
            else rc.grupo_de(nombre, cfg, audio=False if modelo_f else None)
        if g is None:
            g = rc.grupo_por_modelo(modelo_f, cfg)             # si el nombre no dice nada, el equipo de la fila dice a qué rollo va
        if g is None:
            r = sin_grupo.setdefault(nombre[:1].upper() + "…" if nombre else "?", {"gb": 0.0, "filas": 0, "ej": []})
            if nombre and nombre not in r["ej"] and len(r["ej"]) < 2:
                r["ej"].append(nombre)                # nombres reales de BIN, para que el aviso diga cuáles son
            r["gb"] += gb
            r["filas"] += 1
            continue
        clave_g = g["id"] if "id" in g else g["nombre"]
        if (g.get("tipo") == "sonido" or rc.grupo_es_sonido(g)) and isinstance(modelo_f, str) and modelo_f.strip():
            clave_g += "|" + _clave_modelo(modelo_f)          # dos grabadoras distintas (788T y 633) son dos líneas de sonido
        r = por_grupo.setdefault(clave_g, {
            "grupo": g, "gb": 0.0, "clips": 0, "seg": 0.0, "tarjetas": 0, "ultimo_bin": "", "ultimo_rollo": None,
            "ultima_mag": None, "ultimo_dia": "", "ultima_fecha": None, "dias": set(), "modelo": "", "rental": "",
            "bins": set(), "por_dia": {}, "gb_principal": 0.0, "rollos": {}})
        r["gb"] += gb
        r["gb_principal"] += gb
        r["clips"] += clips
        r["seg"] += seg
        llave_dia = dia["fecha"] or dia_corto(dia["dia"])
        r["por_dia"][llave_dia] = r["por_dia"].get(llave_dia, 0.0) + gb
        r["tarjetas"] += 1
        n_rollo = numero_de_rollo(nombre)
        repite = es_repeticion_de(nombre, r["bins"]) and n_rollo is not None and r["ultimo_rollo"] is not None \
            and n_rollo < r["ultimo_rollo"]
        r["bins"].add(nombre)
        if n_rollo is not None and not audio_f:              # para avisar si dos rollos distintos de una cámara tienen el mismo consecutivo
            base_n = re.sub(r"[_\-]\d{1,2}$", "", nombre)                   # N004_1 es el mismo rollo N004 con algo más
            e_ = r["rollos"].setdefault(n_rollo, {}).setdefault(base_n.upper(), {"nombre": base_n, "pestanas": set(), "dias": []})
            e_["pestanas"].add(unidad)
            if (unidad, dia_corto(dia["dia"])) not in e_["dias"]:
                e_["dias"].append((unidad, dia_corto(dia["dia"])))
        if not repite:                                       # N004_1 después de N006 no cambia «el rollo en el que va»
            r["ultimo_bin"] = nombre
            r["ultimo_rollo"] = n_rollo
            r["ultima_mag"] = int(mag) if mag is not None else r["ultima_mag"]
            r["ultimo_dia"], r["ultima_fecha"] = dia["dia"], dia["fecha"]       # el día va con el rollo mostrado (no con la versión repetida)
        r["dias"].add(dia["dia"])
        for clave, c in (("modelo", col.get("modelo")), ("rental", col.get("rental"))):
            v = ec.cel([fila], 0, c) if c is not None else ""
            if isinstance(v, str) and v.strip():
                r[clave] = v.strip()
        dia["gb"] += gb
        if g.get("tipo") == "sonido" or rc.grupo_es_sonido(g):      # el sonido se graba a la vez que el video: su duración y sus clips van aparte
            dia["clips_audio"] += clips
            dia["seg_audio"] += seg
        else:
            dia["clips"] += clips
            dia["seg"] += seg
        dia["tarjetas"] += 1
        dia["detalle"].append({"cam": clave_g, "bin": nombre, "gb": gb, "clips": clips, "seg": seg,
                               "mag": int(mag) if mag is not None else None, "modelo": modelo_f.strip() if isinstance(modelo_f, str) else "",
                               "unidad": unidad, "audio": bool(g.get("tipo") == "sonido" or rc.grupo_es_sonido(g))})
    for d in dias:
        d.pop("_en_lista", None)
        nueva = ec.fecha_segun_sonido(d["fecha"], [x["bin"] for x in d["detalle"] if x.get("audio")])
        if nueva != d["fecha"]:                       # día y mes al revés en la hoja: manda el archivo de la grabadora
            for r in por_grupo.values():
                if r.get("ultimo_dia") == d["dia"] and r.get("ultima_fecha") == d["fecha"]:
                    r["ultima_fecha"] = nueva
            d["fecha"] = nueva
    return {"por_grupo": por_grupo, "sin_grupo": sin_grupo, "dias": dias, "unidades": [unidad] if unidad else [],
            "gb_principal": sum(d["gb"] for d in dias), "celdas_texto": celdas_texto}


def resumir_f06_pestanas(valores, principal, cfg):
    """`valores`: {pestaña: filas}. Lee la pestaña principal y, además, cualquier otra pestaña del mismo archivo que sea un estatus de
    tarjetas con material (segunda unidad, etc.); las que no tienen ese formato, están vacías o son copia exacta de otra se ignoran."""
    base = resumir_f06(valores[principal], cfg, principal)
    otros, vistas, omitidas = [], [repr(valores[principal])], []
    for nombre, filas in valores.items():
        if nombre == principal:
            continue
        if not any(any(str(c).strip() for c in f) for f in filas):
            continue                                       # pestaña vacía
        if repr(filas) in vistas:
            omitidas.append((nombre, "es una copia exacta de otra pestaña"))
            continue
        try:
            r = resumir_f06(filas, cfg, nombre)
        except Exception as e:                             # no es un estatus de tarjetas (otro formato)
            omitidas.append((nombre, "no tiene el formato del estatus de tarjetas"))
            continue
        if r["dias"]:
            otros.append(r)
            vistas.append(repr(filas))
        else:
            omitidas.append((nombre, "no tiene material registrado todavía"))
    res = unir_f06(base, otros)
    res = dict(res, celdas_texto=list(base.get("celdas_texto", [])) + [c for o in otros for c in o.get("celdas_texto", [])])
    res["omitidas"] = omitidas
    return res


def _candidato(v):
    return {"unidad": v.get("ultima_unidad", ""), "bin": v.get("ultimo_bin", ""), "rollo": v.get("ultimo_rollo"),
            "fecha": v.get("ultima_fecha"), "dia": v.get("ultimo_dia", "")}


def ultimos_en_conflicto(por_grupo):
    """El último rollo de cada cámara casi siempre es a la vez el de número más alto y el de fecha más reciente. Si en el proyecto
    (varias pestañas) cada criterio apunta a un rollo distinto, algo no cuadra: se avisa para que la persona confirme cuál es."""
    avisos = []
    for r in por_grupo.values():
        g, cand = r["grupo"], r.get("candidatos") or []
        if len(cand) < 2 or g.get("tipo") == "sonido" or rc.grupo_es_sonido(g):
            continue
        con_num = [c for c in cand if c["rollo"] is not None]
        con_fecha = [c for c in cand if c["fecha"]]
        if len(con_num) < 2 or len(con_fecha) < 2:
            continue
        por_num = max(con_num, key=lambda c: (c["rollo"], c["fecha"] or datetime.min.date()))
        por_fecha = max(con_fecha, key=lambda c: (c["fecha"], c["rollo"] if c["rollo"] is not None else -1))
        if por_num["rollo"] == por_fecha["rollo"] or por_num["fecha"] == por_fecha["fecha"]:
            continue

        def txt(c):
            f = c["fecha"].strftime("%d/%m") if c["fecha"] else "—"
            return f"«{c['bin']}» ({c['unidad']} · {c['dia']} · {f})"
        avisos.append(("aviso", f"Revisa el último rollo de {g['nombre']}: el de número más alto es {txt(por_num)}, pero el más reciente por "
                                f"fecha es {txt(por_fecha)}. En el resumen puse el de número más alto; confirma cuál es el correcto."))
    return avisos


def _copiar_rollos(rollos):
    return {n: {k: {"nombre": e["nombre"], "pestanas": set(e["pestanas"]), "dias": list(e["dias"])} for k, e in nombres.items()}
            for n, nombres in (rollos or {}).items()}


def _juntar_rollos(destino, otro):
    for n, nombres in (otro or {}).items():
        for k, e in nombres.items():
            d = destino.setdefault(n, {}).setdefault(k, {"nombre": e["nombre"], "pestanas": set(), "dias": []})
            d["pestanas"] |= e["pestanas"]
            d["dias"] += [x for x in e["dias"] if x not in d["dias"]]


def rollos_repetidos(por_grupo):
    """Avisos de rollos con el mismo consecutivo: en una cámara, cada número de rollo es de UN solo rollo y de UNA sola unidad.
    Es un error si el número lo tienen dos nombres distintos (H004 y H004B) o si el mismo rollo aparece en dos unidades.
    N004_1 cuenta como el mismo N004 (una versión del mismo rollo)."""
    avisos = []
    for r in por_grupo.values():
        g = r["grupo"]
        if g.get("tipo") == "sonido" or rc.grupo_es_sonido(g):
            continue
        for n in sorted(r.get("rollos", {})):
            nombres = r["rollos"][n]
            pestanas = set().union(*(e["pestanas"] for e in nombres.values()))
            if len(nombres) <= 1 and len(pestanas) <= 1:
                continue
            partes = []
            for e in sorted(nombres.values(), key=lambda e: e["nombre"]):
                dias = [f"{p} {d}".strip() for p, d in e["dias"][:3]]
                partes.append(f"«{e['nombre']}»" + (f" ({', '.join(dias)}{'…' if len(e['dias']) > 3 else ''})" if dias else ""))
            aviso = (f"el mismo consecutivo {n} lo tienen " + " y ".join(partes)) if len(nombres) > 1 else \
                (f"el rollo {partes[0]} aparece en {len(pestanas)} unidades")
            avisos.append(("aviso", f"Rollo repetido en {g['nombre']}: {aviso}. Cada rollo debe tener un número único; revisa cuál está mal escrito."))
    return avisos


def es_mas_reciente(nuevo, actual):
    """¿El rollo `nuevo` (de otra unidad) va DESPUÉS del `actual` de la misma cámara? Manda el NÚMERO del rollo de esa cámara
    (H004 va después de H003 aunque las dos unidades grabaran el mismo día). Si no hay número que comparar (sonido, nombres raros)
    o es el mismo rollo, decide el día de calendario y, si empatan, la mag más alta."""
    n_nuevo, n_actual = nuevo.get("ultimo_rollo"), actual.get("ultimo_rollo")
    if n_nuevo is not None and n_actual is not None and n_nuevo != n_actual:
        return n_nuevo > n_actual
    f_n, f_a = nuevo.get("ultima_fecha"), actual.get("ultima_fecha")
    if f_n and f_a and f_n != f_a:
        return f_n > f_a
    if f_n and not f_a:
        return True
    if not nuevo.get("ultimo_bin"):
        return False
    m_n, m_a = nuevo.get("ultima_mag"), actual.get("ultima_mag")
    return m_n is not None and (m_a is None or m_n > m_a)


def unir_f06(base, otros):
    """Junta el estatus de la pestaña principal con el de otras pestañas del mismo archivo (segunda unidad…): suma rollos y días
    (un mismo día de calendario es un solo día de rodaje). `gb_principal` queda con lo que trae SOLO la pestaña principal: es lo que
    se compara con el estadístico."""
    if not otros:
        return base
    separadas = [{"pestana": (base.get("unidades") or [""])[0], "por_grupo": base["por_grupo"], "dias": [dict(d) for d in base["dias"]],
                  "sin_grupo": base["sin_grupo"]}]
    por_grupo = {k: dict(v, dias=set(v["dias"]), bins=set(v["bins"]), por_dia=dict(v["por_dia"])) for k, v in base["por_grupo"].items()}
    for v_ in por_grupo.values():
        v_["rollos"] = _copiar_rollos(v_.get("rollos"))
    for v_ in por_grupo.values():                            # de qué pestaña es «el rollo en el que va» (el del día más reciente de todo el proyecto)
        v_["ultima_unidad"] = (base.get("unidades") or [""])[0]
        v_["candidatos"] = [_candidato(v_)]
    sin_grupo = {k: dict(v) for k, v in base["sin_grupo"].items()}
    dias = [dict(d) for d in base["dias"]]
    unidades = list(base.get("unidades", []))
    for o in otros:
        unidades += o.get("unidades", [])
        etiqueta = {d["fecha"]: d["dia"] for d in base["dias"] if d["fecha"]}
        for v in o["por_grupo"].values():
            v["ultima_unidad"] = (o.get("unidades") or [""])[0]
        # la unidad vista sola (Resumen y reporte de esa unidad) conserva SU numeración de días (1, 2, 3…), no la de la principal
        propios = {"por_grupo": {k: dict(v) for k, v in o["por_grupo"].items()}, "dias": [dict(d) for d in o["dias"]]}
        for v in o["por_grupo"].values():                      # «8» de la segunda unidad = el mismo día de calendario de la principal (D053)
            if v["ultima_fecha"] in etiqueta:
                v["ultimo_dia"] = etiqueta[v["ultima_fecha"]]
        for d in o["dias"]:
            if d["fecha"] in etiqueta:
                d["dia"] = etiqueta[d["fecha"]]
        separadas.append({"pestana": (o.get("unidades") or [""])[0], "por_grupo": propios["por_grupo"],
                          "dias": propios["dias"], "sin_grupo": o["sin_grupo"]})
        for k, v in o["por_grupo"].items():
            r = por_grupo.get(k)
            if r is None:
                por_grupo[k] = dict(v, dias=set(v["dias"]), bins=set(v["bins"]), por_dia=dict(v["por_dia"]), gb_principal=0.0,
                                    rollos=_copiar_rollos(v.get("rollos")), candidatos=[_candidato(v)])
                continue
            _juntar_rollos(r["rollos"], v.get("rollos"))
            r["candidatos"].append(_candidato(v))
            for c in ("gb", "clips", "seg", "tarjetas"):
                r[c] += v[c]
            r["bins"] |= v["bins"]
            r["dias"] |= v["dias"]
            for d_, g_ in v["por_dia"].items():
                r["por_dia"][d_] = r["por_dia"].get(d_, 0.0) + g_
            nueva = es_mas_reciente(v, r)
            if nueva or not r["ultimo_bin"]:                 # «el rollo en el que va» es el de número más alto (H004 > H003), aunque otra unidad grabe el mismo día
                for c in ("ultimo_bin", "ultimo_rollo", "ultima_mag", "ultimo_dia", "ultima_fecha", "ultima_unidad"):
                    r[c] = v.get(c, "")
            for c in ("modelo", "rental"):
                r[c] = r[c] or v[c]
        for k, v in o["sin_grupo"].items():
            r = sin_grupo.setdefault(k, {"gb": 0.0, "filas": 0, "ej": []})
            r["ej"] = (r.get("ej", []) + [e for e in v.get("ej", []) if e not in r.get("ej", [])])[:2]
            r["gb"] += v["gb"]
            r["filas"] += v["filas"]
        for d in o["dias"]:
            igual = next((x for x in dias if d["fecha"] and x["fecha"] == d["fecha"]), None)
            if igual is None:
                dias.append(dict(d))
                continue
            for c in ("gb", "clips", "seg", "tarjetas", "clips_audio", "seg_audio"):
                igual[c] = igual.get(c, 0) + d.get(c, 0)
            igual["detalle"] = list(igual.get("detalle", [])) + list(d.get("detalle", []))
    if all(d["fecha"] for d in dias):
        dias.sort(key=lambda d: d["fecha"])
    return {"por_grupo": por_grupo, "sin_grupo": sin_grupo, "dias": dias, "unidades": unidades, "por_unidad": separadas,
            "gb_principal": base.get("gb_principal", sum(d["gb"] for d in base["dias"]))}


# ---------------------------------------------------------------------------------------------
# Estadístico (FO-07)
# ---------------------------------------------------------------------------------------------
_ROTULOS = {"total dias de rodaje": "dias_previstos", "dias rodados": "dias_rodados", "promedio por dia": "promedio",
            "espacio aprox. total": "espacio_previsto", "espacio aprox total": "espacio_previsto",
            "espacio utilizado ocf": "utilizado", "espacio utilizado": "utilizado", "audio": "audio",
            # cómo lo escriben otros proyectos (LC): «Total días rodaje», «Espacio total Aprox.», «Total shooting days»…
            "total dias rodaje": "dias_previstos", "total dias": "dias_previstos", "total shooting days": "dias_previstos",
            "shooting days": "dias_rodados", "espacio total aprox.": "espacio_previsto", "espacio total aprox": "espacio_previsto"}
_EQUIPO = {"produccion": "Producción", "direccion": "Dirección", "dop": "DOP", "dit": "DIT",
           "data manager": "Data manager", "dit/data": "DIT / Data", "dit / data": "DIT / Data", "dit/data manager": "DIT / Data",
           "data": "Data manager", "dmt": "Data manager", "production": "Producción", "director": "Dirección"}


def _valor_a_la_derecha(fila, desde):
    for v in fila[desde + 1:]:
        if v not in ("", None):
            return v
    return None


def _etiqueta_de_unidad07(resumen):
    """El texto que el «Resumen General» pone justo arriba de «RESUMEN GENERAL» («CEL UB»): dice de qué unidad es ese estadístico."""
    for i, fila in enumerate(resumen or []):
        if any(isinstance(x, str) and ec._n(x) == "resumen general" for x in fila):
            for previa in reversed((resumen or [])[max(0, i - 3):i]):
                textos = [str(x).strip() for x in previa if isinstance(x, str) and x.strip()]
                if textos:
                    return textos[0]
            break
    return ""


def resumir_f07(datos, resumen):
    """`datos`: cuadrícula de «Datos Generales»; `resumen`: cuadrícula de «Resumen General» (puede ser None)."""
    tabla = ec.encontrar_tabla(datos)
    dias = []
    semana = ""                                     # la columna A marca el comienzo de cada semana («1 PILOTO», 1, 2…)
    for d in tabla["dias"]:
        fila = d["fila"]
        marca = ec.cel(datos, fila, 0) if tabla["dia"] != 0 else ""       # (si la columna A es la del día, no hay semanas)
        if marca not in ("", None) and re.search(r"\d", str(marca)):
            semana = str(int(marca)) if isinstance(marca, float) and marca.is_integer() else str(marca).strip()
        gb = {k: _num(ec.cel(datos, fila, c)) or 0.0 for k, c in tabla["gb"].items()}
        audio = _num(ec.cel(datos, fila, tabla["audio_gb"])) or 0.0 if tabla["audio_gb"] is not None else 0.0
        clips = sum(_num(ec.cel(datos, fila, c)) or 0 for c in tabla["clips"].values())
        a_clips = int(_num(ec.cel(datos, fila, tabla["audio_clips"])) or 0) if tabla.get("audio_clips") is not None else 0
        seg = _segundos(ec.cel(datos, fila, tabla["duracion"])) if tabla["duracion"] is not None else 0.0
        total = sum(gb.values()) + audio
        dias.append({"dia": str(d["texto"]).strip(), "fecha": _fecha(ec.cel(datos, fila, tabla["fecha"])),
                     "gb_por_camara": gb, "audio": audio, "audio_clips": a_clips, "gb": total, "clips": int(clips), "seg": seg,
                     "semana": semana})
    con_datos = [d for d in dias if d["gb"] > 0]
    camaras = {}
    for d in con_datos:
        for k, v in d["gb_por_camara"].items():
            camaras[k] = camaras.get(k, 0.0) + v
    r = {"dias": dias, "con_datos": con_datos, "camaras": {k: v for k, v in camaras.items() if v > 0},
         "columnas": list(tabla["gb"]),
         "audio": sum(d["audio"] for d in con_datos), "audio_clips": sum(d.get("audio_clips", 0) for d in con_datos), "equipo": {}, "formato": [], "extras": {}, "semana": "",
         "etiqueta": _etiqueta_de_unidad07(resumen)}
    if resumen:
        formato = False
        for fila in resumen:
            etiquetas = [(j, ec._n(x)) for j, x in enumerate(fila) if isinstance(x, str) and x.strip()]
            if not etiquetas:
                continue
            j, e = etiquetas[0]
            if e.startswith("semana") and ":" in str(fila[j]) and not r["semana"]:
                r["semana"] = str(fila[j]).strip()
            elif e in _EQUIPO:
                v = _valor_a_la_derecha(fila, j)
                if isinstance(v, str) and v.strip():
                    r["equipo"][_EQUIPO[e]] = v.strip()
            elif e in _ROTULOS:
                v = _num(_valor_a_la_derecha(fila, j))
                if v is not None:
                    r["extras"][_ROTULOS[e]] = v
            elif e == "resolution":
                formato = True
            if formato and len(etiquetas) >= 1:
                v = _valor_a_la_derecha(fila, j)
                if isinstance(v, str) and v.strip() and ec._n(fila[j]) in (
                        "resolution", "bitdepth", "video codec", "wrapper", "audio", "camera"):
                    r["formato"].append((str(fila[j]).strip(), v.strip()))
    return r


def unir_f07(partes):
    """Junta los estadísticos de varias unidades (cada uno con su «Datos Generales») en uno solo para el proyecto: suma cámaras, audio y
    días (un mismo día de calendario es un solo día de rodaje). `partes`: [(nombre, resultado de resumir_f07[, índice del estadístico])].
    `unidades07` conserva cada uno por separado. Con uno solo, queda igual."""
    partes = [(t[0], t[1], t[2] if len(t) > 2 else k) for k, t in enumerate(partes)]
    unidades07 = [{"nombre": n, "f07": f, "indice": j} for n, f, j in partes]
    if len(partes) == 1:
        return dict(partes[0][1], unidades07=unidades07)
    dias, columnas = [], []
    for _n, f, _j in partes:
        for c in f["columnas"]:
            if c not in columnas:
                columnas.append(c)
        for d in f["dias"]:
            igual = next((x for x in dias if d["fecha"] and x["fecha"] == d["fecha"]), None)
            if igual is None:
                dias.append(dict(d, gb_por_camara=dict(d["gb_por_camara"])))
                continue
            for k, v in d["gb_por_camara"].items():
                igual["gb_por_camara"][k] = igual["gb_por_camara"].get(k, 0.0) + v
            for c in ("audio", "audio_clips", "gb", "clips", "seg"):
                igual[c] = igual.get(c, 0) + d.get(c, 0)
    if all(d["fecha"] for d in dias):
        dias.sort(key=lambda d: d["fecha"])
    camaras = {}
    for _n, f, _j in partes:
        for k, v in f["camaras"].items():
            camaras[k] = camaras.get(k, 0.0) + v
    extras = {}
    for _n, f, _j in partes:
        for k in ("espacio_previsto", "utilizado"):
            if k in f["extras"]:
                extras[k] = extras.get(k, 0.0) + f["extras"][k]
    return {"dias": dias, "con_datos": [d for d in dias if d["gb"] > 0], "camaras": camaras, "columnas": columnas,
            "audio": sum(f["audio"] for _n, f, _j in partes),
            "audio_clips": sum(f.get("audio_clips", 0) for _n, f, _j in partes),
            "equipo": next((f["equipo"] for _n, f, _j in partes if f["equipo"]), {}),
            "formato": next((f["formato"] for _n, f, _j in partes if f["formato"]), []),
            "extras": extras, "semana": next((f["semana"] for _n, f, _j in partes if f["semana"]), ""),
            "etiqueta": "", "unidades07": unidades07}


def emparejar_f07(f06, unidades07, textos=None):
    """A qué pestaña (unidad) del estatus corresponde cada estadístico: lista de índices de `f06['por_unidad']` (o None).
    Primero por lo que dice el nombre («CEL UA» ↔ «… CEL UA»), luego por los GB totales (el estatus de una unidad suma lo mismo que su
    estadístico) y, si nada ayuda, por el orden. `textos`: lo que dice cada estadístico además de su etiqueta (el título del archivo)."""
    unidades = f06.get("por_unidad") or []
    if len(unidades) < 2:
        return [0 if i == 0 else None for i in range(len(unidades07))]            # un solo estatus: el primer estadístico es su pareja
    gb06 = [sum(d["gb"] for d in u["dias"]) for u in unidades]
    puntos = []
    for j, u7 in enumerate(unidades07):
        f = u7["f07"]
        texto = f"{f.get('etiqueta', '')} {(textos or {}).get(j, '')} {u7.get('nombre', '')}"
        gb07 = sum(f["camaras"].values()) + f["audio"]
        fila = []
        for i, u in enumerate(unidades):
            sc = rc.afinidad_de_unidad(u["pestana"], texto) * 10
            if gb07 > 0 and gb06[i] > 0:
                dif = abs(gb07 - gb06[i]) / max(gb07, gb06[i])
                sc += 5 if dif <= TOLERANCIA_COINCIDENCIA else 2 if dif <= 0.10 else 0
            fila.append(sc)
        puntos.append(fila)
    pares = [None] * len(unidades07)
    usadas = set()
    for sc, j, i in sorted(((puntos[j][i], j, i) for j in range(len(unidades07)) for i in range(len(unidades))), reverse=True):
        if sc > 0 and pares[j] is None and i not in usadas:
            pares[j], _ = i, usadas.add(i)
    for j in range(len(unidades07)):                                   # sin pistas: por orden, en las unidades que sobran
        if pares[j] is None:
            libre = next((i for i in range(len(unidades)) if i not in usadas), None)
            if libre is not None:
                pares[j] = libre
                usadas.add(libre)
    return pares


def letra_de_fuente(patrones):
    """Letra de una fuente de video: «A_» o «A_####_» → A; «D###», «D###_» o «D» → D (una letra y números = esa cámara). Si no, ''."""
    letra = rc.letra_de_camara(patrones)
    if letra:
        return letra
    if len(patrones) == 1:
        m = re.fullmatch(r"([A-Za-z])(#+_?|_?)", patrones[0])
        if m:
            return m.group(1).upper()
    return ""


def _claves_de_grupo(r, tipo, columnas07, f07=None):
    """Las columnas del estadístico (ML, MR…) a las que corresponden los BIN reales de un rollo del estatus. Si los nombres no dicen
    nada (p. ej. «BETACAM_TEST» que el estadístico anota en la columna H), se busca la columna que trae justo los mismos GB esos mismos días."""
    if tipo == "sonido" or not columnas07:
        return []
    claves = sorted({rc.clave_de_bin(b, columnas07) for b in r.get("bins", ())
                     if re.match(r"^[A-Za-z]+_?\d", str(b).strip())} & {str(k).upper() for k in columnas07})   # «BETACAM_TEST» no dice de qué cámara es
    if claves or not f07 or not r.get("por_dia"):
        return claves
    por_dia07 = {(d["fecha"] or dia_corto(d["dia"])): d["gb_por_camara"] for d in f07.get("con_datos", [])}
    candidatas = []
    for k in columnas07:
        ok = True
        for dia, gb in r["por_dia"].items():
            v = (por_dia07.get(dia) or {}).get(k, 0.0)
            if gb > 0 and abs(v - gb) > max(0.5, 0.02 * gb):
                ok = False
                break
        if ok:
            candidatas.append(str(k).upper())
    return candidatas if len(candidatas) == 1 else []


def _letras_de_camaras(cfg, camaras, f07):
    """Todas las cámaras (letras) que hay de verdad: las de Ajustes con material, las columnas del estadístico con datos y las que
    cualquiera de las dos hojas trae. Un equipo sin letra (Betacam) cuenta con su nombre. Devuelve (con_material, columnas_sin_material)."""
    con = set()
    for c in camaras:
        if c["tipo"] == "sonido" or c.get("sin_material") or (c["gb"] <= 0 and not c["tarjetas"]):
            continue
        g = next((x for x in cfg["grupos"] if (x.get("id") or x["nombre"]) == c.get("grupo_id", c.get("id", c["nombre"]))), None)
        letra = c["letra"] or (letra_de_fuente(g["patrones"]) if g else "")
        if letra and c.get("claves"):
            con.update(c["claves"])
        elif letra:
            c["letra"] = c["letra"] or letra
            con.add(letra)
        elif not c.get("solo_f07"):
            con.add(c["nombre"])                       # «Betacam»: es un equipo de grabación aunque no tenga letra
    for k in (f07 or {}).get("camaras", {}):
        con.add(k)
    vacias = [k for k in (f07 or {}).get("columnas", []) if k not in con]
    return sorted(con), vacias


# ---------------------------------------------------------------------------------------------
# Modelo único para la pantalla
# ---------------------------------------------------------------------------------------------
def _sonidos_multiples(por_grupo):
    """Rollos de sonido que traen más de una grabadora (modelo): esos se rotulan «Sonido · 788T» y «Sonido · 633»."""
    cuenta = {}
    for r in por_grupo.values():
        if rc.grupo_es_sonido(r["grupo"]):
            gid = r["grupo"].get("id") or r["grupo"]["nombre"]
            cuenta[gid] = cuenta.get(gid, 0) + 1
    return {gid for gid, n in cuenta.items() if n > 1}


def _entradas_f06(por_grupo, cfg, columnas07, f07, multi):
    """Una línea por rollo (y por grabadora, en el sonido) con lo que trae el estatus."""
    salida, vistos = [], {}
    for clave, r in por_grupo.items():
        g = r["grupo"]
        gid = g.get("id") or g["nombre"]
        tipo, letra, _otro = rc.tipo_de_patrones(g["patrones"])
        if rc.grupo_es_sonido(g):
            tipo = "sonido"
        nombre, color = g["nombre"], g.get("color") or ""
        if gid in multi and r.get("modelo"):
            if modelo_corto(r["modelo"]).upper() not in nombre.upper():           # sin repetir «SCORPIO · SCORPIO»
                nombre = f"{g['nombre']} · {modelo_corto(r['modelo'])}"
            if gid in vistos:
                color = ""                                   # cada grabadora con su propio color
            vistos[gid] = True
        salida.append({
            "id": clave, "grupo_id": gid, "claves": _claves_de_grupo(r, tipo, columnas07, f07),
            "nombre": nombre, "tipo": tipo, "letra": letra or "", "color": color,
            "modelo": r["modelo"] or g.get("modelo", ""), "rental": r["rental"] or g.get("rental", ""),
            "gb": r["gb"], "gb_principal": r.get("gb_principal", r["gb"]), "clips": r["clips"], "seg": r["seg"],
            "tarjetas": r["tarjetas"], "ultimo_bin": r["ultimo_bin"], "ultimo_rollo": r["ultimo_rollo"], "ultima_mag": r["ultima_mag"],
            "ultimo_dia": dia_corto(r["ultimo_dia"]), "ultima_fecha": r["ultima_fecha"], "dias": len(r["dias"]),
            "ultima_unidad": r.get("ultima_unidad", ""), "sin_material": False})
    return salida


def nombre_de_unidad(pestana, posicion):
    """«PP SECOND UNIT» → «Unidad 2»; «PP_MAIN_UNIT» → «Unidad 1». Si la pestaña no dice cuál es (CEL UA, CEL SP, CEL UB),
    la unidad se llama como la pestaña, para que se reconozca; si tampoco sirve, por orden (la principal es la 1)."""
    t = ec._n(pestana)
    if re.search(r"second|segund|2nd|\bu\s*2\b|unit\s*2|unidad\s*2|\b2\b", t):
        return "Unidad 2"
    if re.search(r"main|princip|first|primer|\bu\s*1\b|unit\s*1|unidad\s*1|\b1\b", t):
        return "Unidad 1"
    propio = " ".join(str(pestana).replace("_", " ").split())
    if len(propio) >= 2 and not rc._es_nombre_de_formato(propio):
        return propio
    return f"Unidad {posicion + 1}"


def _resumen_de_vista(cfg, camaras, serie):
    letras, vacias = _letras_de_camaras(cfg, camaras, None)
    gb = sum(c["gb"] for c in camaras)
    n = len(serie)
    return {"gb": gb, "tb": gb / GB_POR_TB,
            "clips": sum(c["clips"] for c in camaras if c["tipo"] != "sonido"),
            "clips_audio": sum(c["clips"] for c in camaras if c["tipo"] == "sonido"),
            "seg": sum(d["seg"] for d in serie), "seg_audio": sum(d.get("seg_audio", 0.0) for d in serie),
            "dias": n, "camaras": len(letras), "letras": letras, "letras_vacias": vacias,
            "tarjetas": sum(c["tarjetas"] for c in camaras), "promedio_gb": (gb / n) if n else 0.0,
            "mejor": max(serie, key=lambda d: d["gb"]) if serie else None,
            "ultimo": serie[-1] if serie else None, "primero": serie[0] if serie else None,
            "dias_previstos": None, "espacio_previsto_gb": None, "rollos": [c["nombre"] for c in camaras]}


def _serie_de_dias(dias):
    return [{"dia": dia_corto(d["dia"]), "fecha": d["fecha"], "gb": d["gb"], "seg": d["seg"], "clips": d["clips"],
             "seg_audio": d.get("seg_audio", 0.0), "clips_audio": d.get("clips_audio", 0),
             "tarjetas": d.get("tarjetas", 0), "detalle": d.get("detalle", [])}
            for d in dias if d["gb"] > 0 or d["clips"] or d.get("clips_audio")]


def _unidades_f06(f06, cfg, columnas07, f07, multi):
    """Cada unidad (pestaña) por separado: sus cámaras, sus días y sus totales. Vacío si el archivo trae una sola."""
    if len(f06.get("por_unidad", [])) < 2:
        return []
    salida = []
    for i, u in enumerate(f06["por_unidad"]):
        camaras = _entradas_f06(u["por_grupo"], cfg, columnas07, f07, multi)
        orden_id = {(g.get("id") or g["nombre"]): j for j, g in enumerate(cfg["grupos"])}
        camaras.sort(key=lambda c: orden_id.get(c["grupo_id"], 999))
        serie = _serie_de_dias(u["dias"])
        salida.append({"id": f"u{i + 1}", "nombre": nombre_de_unidad(u["pestana"], i), "pestana": u["pestana"],
                       "camaras": camaras, "serie": serie, "totales": _resumen_de_vista(cfg, camaras, serie)})
    nombres = [u["nombre"] for u in salida]
    for i, u in enumerate(salida):                       # si dos pestañas dieran el mismo nombre, se numeran por orden
        if nombres.count(u["nombre"]) > 1:
            u["nombre"] = f"Unidad {i + 1}"
    for u in salida:
        pct = u["totales"]["gb"]
        for c in u["camaras"]:
            c["pct"] = (c["gb"] / pct) if pct else 0.0
    return salida


def _separar_audio_en_camaras(camaras, por_rollo, resta, audio07, audio_clips07=0):
    """Audio que se descargó DENTRO de una tarjeta de cámara (HDT: Y001_1028BD_1 trae video + .wav). En el estatus la tarjeta suma todo;
    el estadístico lo separa (CAM Y sin el audio, AUDIO aparte). Si lo que le sobra a las cámaras del estatus frente al estadístico es
    justo lo que el estadístico tiene de AUDIO de más, se pasa ese peso de la cámara al audio. Devuelve {'gb','camaras'} o None."""
    a06 = sum(c["gb"] for c in camaras if c["tipo"] == "sonido")
    extra = round((audio07 or 0.0) - a06, 2)
    if extra <= 0.005:
        return None
    sobras = []
    for c in camaras:
        if c["tipo"] == "sonido" or c["id"] not in por_rollo:
            continue
        sobra = c.get("gb_principal", c["gb"]) - resta.get(c["id"], 0.0) - por_rollo[c["id"]]
        if sobra > 0.005:
            sobras.append((c, sobra))
    if not sobras or abs(sum(s for _c, s in sobras) - extra) > max(0.05, 0.01 * extra):
        return None
    clips = max(0, int(audio_clips07 or 0) - sum(c["clips"] for c in camaras if c["tipo"] == "sonido"))
    if len(sobras) != 1 or clips > sobras[0][0]["clips"]:
        clips = 0                                       # con varias cámaras no se sabe de cuál salen los clips: solo se separa el peso
    for c, s in sobras:
        c["gb"] -= s
        c["clips"] -= clips
        if "gb_principal" in c:
            c["gb_principal"] -= s
        c["audio_dentro_gb"] = s
    return {"gb": extra, "clips": clips, "camaras": [c["nombre"] for c, _s in sobras]}


def construir(cfg, f06=None, f07=None, nombre_proyecto=""):
    """Junta lo que haya (FO-06, FO-07 o ambas) en un modelo listo para dibujar."""
    avisos = []
    errores = []                                       # celdas del estatus con un error de escritura (con lo que probablemente quisieron escribir)
    camaras, serie, unidades = [], [], []
    columnas07 = list((f07 or {}).get("columnas", []))
    fuente = "FO-06" if f06 else "FO-07" if f07 else ""
    if f06:
        multi = _sonidos_multiples(f06["por_grupo"])
        camaras = _entradas_f06(f06["por_grupo"], cfg, columnas07, f07, multi)
        hechos = {c["grupo_id"] for c in camaras}
        for g in cfg["grupos"]:                       # todos los rollos de Ajustes aparecen, aunque aún no tengan material
            if (g.get("id") or g["nombre"]) not in hechos:
                tipo, letra, _otro = rc.tipo_de_patrones(g["patrones"])
                if rc.grupo_es_sonido(g):
                    tipo = "sonido"
                camaras.append({"id": g.get("id") or g["nombre"], "grupo_id": g.get("id") or g["nombre"], "claves": [],
                                "nombre": g["nombre"], "tipo": tipo, "letra": letra or "", "color": g.get("color") or "",
                                "modelo": g.get("modelo", ""), "rental": g.get("rental", ""), "gb": 0.0, "clips": 0, "seg": 0.0,
                                "tarjetas": 0, "ultimo_bin": "", "ultimo_rollo": None, "ultima_mag": None, "ultimo_dia": "",
                                "ultima_fecha": None, "dias": 0, "sin_material": True})
        orden_id = {(g.get("id") or g["nombre"]): i for i, g in enumerate(cfg["grupos"])}
        camaras.sort(key=lambda c: orden_id.get(c["grupo_id"], 999))
        unidades = _unidades_f06(f06, cfg, columnas07, f07, multi)
        serie = _serie_de_dias(f06["dias"])                                  # un día solo cuenta si tiene material
        avisos += rollos_repetidos(f06["por_grupo"])
        avisos += ultimos_en_conflicto(f06["por_grupo"])
        for k, c in enumerate(f06.get("celdas_texto") or [], start=1):
            sug = sugerir_celda(c["clave"], c["valor"])
            errores.append(dict(c, id=200000 + k, celda=ec.a1(c["fila"] - 1, c["col"]),
                                nuevo=sug[0] if sug else None, nuevo_txt=sug[1] if sug else "", motivo=sug[2] if sug else "",
                                corregible=bool(sug)))
        if f06.get("omitidas"):
            avisos.append(("info", "No usé " + "; ".join(f"«{n}» ({m})" for n, m in f06["omitidas"]) +
                                   ". Si alguna es una unidad de tu estatus, revisa que tenga el mismo formato que las demás."))
        if f06["sin_grupo"]:
            total = sum(v["gb"] for v in f06["sin_grupo"].values())
            bins = ", ".join(e for k, v in sorted(f06["sin_grupo"].items()) for e in (v.get("ej") or [k]))
            avisos.append(("aviso", f"No conté {texto_peso(total)} de tu hoja: el BIN «{bins}» no coincide con ningún rollo. "
                                    "Agrégalo en Ajustes → Rollos."))
    elif f07:
        for k, gb in f07["camaras"].items():
            camaras.append({"id": f"f07:{k}", "claves": [k], "nombre": f"Cámara {k}", "tipo": "camara", "letra": k, "color": "",
                            "modelo": "", "rental": "", "gb": gb, "clips": 0, "seg": 0.0, "tarjetas": 0, "ultimo_bin": "", "ultimo_rollo": None,
                            "ultima_mag": None, "ultimo_dia": "", "ultima_fecha": None, "dias": 0, "sin_material": False})
        if f07["audio"] > 0:
            camaras.append({"id": "f07:audio", "claves": [], "nombre": "Sonido", "tipo": "sonido", "letra": "", "color": "",
                            "modelo": "", "rental": "",
                            "gb": f07["audio"], "clips": 0, "seg": 0.0, "tarjetas": 0, "ultimo_bin": "",
                            "ultimo_rollo": None, "ultima_mag": None, "ultimo_dia": "", "ultima_fecha": None, "dias": 0,
                            "sin_material": False})
        for d in f07["con_datos"]:
            detalle = [{"cam": f"f07:{k}", "bin": "", "gb": v, "clips": 0, "seg": 0.0, "mag": None, "modelo": "", "unidad": "",
                        "audio": False} for k, v in d.get("gb_por_camara", {}).items() if v > 0]
            if d.get("audio"):
                detalle.append({"cam": "f07:audio", "bin": "", "gb": d["audio"], "clips": 0, "seg": 0.0, "mag": None, "modelo": "",
                                "unidad": "", "audio": True})
            serie.append({"dia": dia_corto(d["dia"]), "fecha": d["fecha"], "gb": d["gb"], "seg": d["seg"], "clips": d["clips"],
                          "detalle": detalle, "solo_f07": True})
        avisos.append(("info", "Conecta el estatus de tarjetas (FO-06) para ver también el rollo en el que va cada cámara."))
    total06_cubierto = None
    if f06 and f07 and unidades and f07.get("unidades07"):
        # Con varias unidades, cada estadístico se compara con SU pestaña del estatus (no con la principal) y las pestañas que no
        # tienen estadístico conectado no entran en la comparación.
        pares = emparejar_f07(f06, f07["unidades07"], f07.get("textos07"))
        cubiertas = sorted({i for i in pares if i is not None})
        for c in camaras:
            c["gb_principal"] = sum(x["gb"] for i in cubiertas for x in unidades[i]["camaras"] if x["id"] == c["id"])
        total06_cubierto = sum(unidades[i]["totales"]["gb"] for i in cubiertas)
        for u, i in zip(f07["unidades07"], pares):
            if i is not None:
                unidades[i]["estadistico"] = u.get("nombre", "")
                for clave in ("equipo", "formato", "semana"):                  # cada unidad con lo que dice SU estadístico
                    unidades[i][clave] = u["f07"].get(clave) or ({} if clave == "equipo" else [] if clave == "formato" else "")
                ex_u = u["f07"].get("extras", {})
                unidades[i]["dias_previstos"] = int(ex_u["dias_previstos"]) if "dias_previstos" in ex_u else None
                unidades[i]["espacio_previsto_gb"] = ex_u.get("espacio_previsto")
        sueltas = [unidades[i]["nombre"] for i in range(len(unidades)) if i not in cubiertas]
        if sueltas and len(f07["unidades07"]) < len(unidades):
            avisos.append(("info", "No comparé " + ", ".join(f"«{n}»" for n in sueltas) + ": esa unidad no tiene estadístico conectado "
                                   "(Hojas conectadas → Agregar otro estadístico)."))
    # Días del estatus que el estadístico todavía no tiene (el que se está registrando hoy): no entran en la comparación de totales,
    # si no, cada día a medias haría decir «tus dos hojas no coinciden». Solo con un estadístico (con varios, cada uno va por su unidad).
    resta, sin07 = {}, []
    if f06 and f07 and len(f07.get("unidades07") or []) <= 1 and len(unidades or []) <= 1 and f07.get("con_datos"):
        fechas07 = {d.get("fecha") for d in f07["con_datos"] if d.get("fecha")}
        for d in serie:
            if d.get("fecha") and d["fecha"] not in fechas07 and not d.get("solo_f07"):
                sin07.append(d["dia"])
                for x in d.get("detalle") or []:
                    resta[x["cam"]] = resta.get(x["cam"], 0.0) + x["gb"]
        if sin07:
            avisos.append(("info", f"No comparé {'el día' if len(sin07) == 1 else 'los días'} {', '.join(sin07)} con el estadístico: "
                                   "todavía no está ahí (¿se está registrando?)."))
    if f06 and f07:                                    # cruce rollo por rollo entre las dos hojas
        por_rollo, sin_rollo = {}, {}
        dueno = {}                                      # columna del estadístico → rollo de Ajustes, según los BIN reales del estatus
        comparten = {}                                  # rollo principal → otros rollos que anotan en la MISMA columna (Betacam en la H)
        for c in camaras:
            for k in c.get("claves", []):
                if k in dueno and dueno[k] != c["id"]:
                    comparten.setdefault(dueno[k], []).append(c)
                dueno.setdefault(k, c["id"])
        for k, v in f07["camaras"].items():
            idg = dueno.get(k)
            if idg is None:                              # sin BIN en el estatus: se prueba con nombres de ejemplo
                g = next((rc.grupo_de(m, cfg) for m in (f"{k}_0001", f"{k}001", f"{k}0001") if rc.grupo_de(m, cfg)), None)
                idg = (g.get("id") or g["nombre"]) if g else None
            if idg is not None:
                por_rollo[idg] = por_rollo.get(idg, 0.0) + v
            elif v > 0:
                sin_rollo[k] = v
        sonidos = [c for c in camaras if c["tipo"] == "sonido" and not c.get("sin_material")] or \
                  [c for c in camaras if c["tipo"] == "sonido"][:1]
        audio_en_camara = _separar_audio_en_camaras(camaras, por_rollo, resta, f07["audio"], f07.get("audio_clips", 0))
        if audio_en_camara:
            if sonidos:
                sonidos[0]["gb"] += audio_en_camara["gb"]
                sonidos[0]["clips"] += audio_en_camara["clips"]
                sonidos[0]["audio_en_tarjetas"] = audio_en_camara["gb"]
            else:
                camaras.append({"id": "audio_en_tarjetas", "grupo_id": "audio_en_tarjetas", "claves": [], "nombre": "Audio",
                                "tipo": "sonido", "letra": "", "color": "", "modelo": "", "rental": "", "gb": audio_en_camara["gb"],
                                "clips": audio_en_camara["clips"], "seg": 0.0, "tarjetas": 0, "ultimo_bin": "", "ultimo_rollo": None, "ultima_mag": None,
                                "ultimo_dia": "", "ultima_fecha": None, "dias": 0, "sin_material": False, "audio_en_tarjetas": audio_en_camara["gb"]})
            avisos.append(("info", f"{texto_peso(audio_en_camara['gb'])} de audio venía dentro de las tarjetas de "
                                   f"{', '.join(audio_en_camara['camaras'])} (se descargó junto). En el estatus sigue con la tarjeta; aquí lo "
                                   "muestro aparte como Audio, como en tu estadístico."))
        if sonidos and f07["audio"] > 0:
            por_rollo[sonidos[0]["id"]] = por_rollo.get(sonidos[0]["id"], 0.0) + f07["audio"]
            if len(sonidos) > 1:
                comparten.setdefault(sonidos[0]["id"], []).extend(sonidos[1:])        # las dos grabadoras juntas contra el «AUDIO» del estadístico
        diferentes = []
        for c in camaras:
            if c["id"] in por_rollo:
                otro = por_rollo[c["id"]]
                junto = [c] + comparten.get(c["id"], [])
                propio = sum(x.get("gb_principal", x["gb"]) - resta.get(x["id"], 0.0) for x in junto)   # solo la pestaña principal se compara
                if abs(otro - propio) > max(1.0, TOLERANCIA_COINCIDENCIA * max(otro, propio)):
                    diferentes.append(f"{' + '.join(x['nombre'] for x in junto)} (estatus {texto_peso(propio)} · estadístico {texto_peso(otro)})")
        for k, v in sorted(sin_rollo.items()):          # columnas del estadístico que ningún rollo de Ajustes reconoce
            camaras.append({"id": f"f07:{k}", "claves": [k], "nombre": f"Cámara {k}", "tipo": "camara", "letra": k, "color": "",
                            "modelo": "", "rental": "", "gb": v, "clips": 0, "seg": 0.0, "tarjetas": 0, "ultimo_bin": "", "ultimo_rollo": None,
                            "ultima_mag": None, "ultimo_dia": "", "ultima_fecha": None, "dias": 0, "sin_material": False,
                            "solo_f07": True})
            avisos.append(("aviso", f"«Cámara {k}» está en tu estadístico ({texto_peso(v)}) pero ningún rollo de Ajustes la reconoce: "
                                    "el resumen la suma desde el estadístico. Agrégala en Ajustes → Rollos."))
        if diferentes:
            avisos.append(("aviso", "No coinciden entre las dos hojas: " + "; ".join(diferentes) + "."))
    total_gb = sum(c["gb"] for c in camaras)
    for c in camaras:
        c["pct"] = (c["gb"] / total_gb) if total_gb else 0.0
    letras, vacias = _letras_de_camaras(cfg, camaras, f07)
    n_dias = len(serie)
    ex = (f07 or {}).get("extras", {})
    t = {
        "gb": total_gb, "tb": total_gb / GB_POR_TB,
        "clips": sum(c["clips"] for c in camaras if c["tipo"] != "sonido") or sum(d["clips"] for d in serie),
        "clips_audio": sum(c["clips"] for c in camaras if c["tipo"] == "sonido"),
        "seg": sum(d["seg"] for d in serie), "seg_audio": sum(d.get("seg_audio", 0.0) for d in serie), "dias": n_dias, "camaras": len(letras), "letras": letras, "letras_vacias": vacias,
        "rollos": [c["nombre"] for c in camaras], "tarjetas": sum(c["tarjetas"] for c in camaras),
        "promedio_gb": (total_gb / n_dias) if n_dias else 0.0,
        "mejor": max(serie, key=lambda d: d["gb"]) if serie else None,
        "ultimo": serie[-1] if serie else None, "primero": serie[0] if serie else None,
        "dias_previstos": int(ex["dias_previstos"]) if "dias_previstos" in ex else None,
        "espacio_previsto_gb": ex.get("espacio_previsto"),
    }
    if f06 and f07:
        gb07 = sum(f07["camaras"].values()) + f07["audio"]
        total06 = total06_cubierto if total06_cubierto is not None else (f06.get("gb_principal") or total_gb)   # solo las unidades que el estadístico trae
        total06 -= sum(resta.values())
        if total06 and gb07 and abs(gb07 - total06) / max(gb07, total06) > TOLERANCIA_COINCIDENCIA:
            avisos.append(("aviso", f"Tus dos hojas no coinciden: el estatus de tarjetas suma {texto_peso(total06)} y el "
                                    f"estadístico {texto_peso(gb07)}. Revisa que ambas estén al día."))
    return {"proyecto": nombre_proyecto, "fuente": fuente, "camaras": camaras, "serie": serie, "totales": t,
            "unidades": unidades,
            "equipo": (f07 or {}).get("equipo", {}), "formato": (f07 or {}).get("formato", []),
            "semana": (f07 or {}).get("semana", ""), "avisos": avisos, "errores_escritura": errores,
            # todos los días del estadístico (también los que faltan por rodar, en 0): el reporte los muestra como el «Resumen General»
            "dias07": [{"dia": str(d["dia"]), "fecha": d["fecha"], "gb": d["gb"], "seg": d["seg"], "semana": d.get("semana", ""),
                        "camaras": dict(d["gb_por_camara"]), "audio": d["audio"]} for d in (f07 or {}).get("dias", [])]}
