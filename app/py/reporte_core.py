"""
REPORTE DEL PERIODO (lógica pura, sin pantalla ni Google: se puede probar sola)
===============================================================================
Con el modelo del Resumen (resumen_core.construir) arma un reporte para ENVIAR de un día, una semana o las fechas que se elijan:
  - `armar(modelo, desde, hasta, …)` → los números del periodo (por cámara, por día, tarjeta por tarjeta, avance del proyecto).
  - `a_html(datos, modo, logos)` → una página completa (claro u oscuro) con gráficas en SVG, lista para abrir, imprimir o guardar en PDF.
  - Calendario: `rodados`, `semana_de`, `tocar`, `mes` (lo usan la ventana del Mac y la del teléfono para elegir las fechas).
El diseño imita los reportes de Silverstack: títulos con verde de marca, cajas redondeadas con el dato arriba y el rótulo en verde abajo.
Unidades: GB decimales, 1 TB = 1.000 GB (como todo el programa).
"""
import calendar
import html
import re
from datetime import date, datetime, timedelta

import resumen_core as rsm

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_SEMANA = ["lu", "ma", "mi", "ju", "vi", "sá", "do"]
TIPOS = (("dia", "Día"), ("semana", "Semana"), ("dias", "Varios días"))
PALETA = ["#E24A38", "#F28C28", "#FFD60A", "#34C759", "#70A6DD", "#5E5CE6", "#BF5AF2", "#FF6FB5", "#A2845E", "#CCCCCC"]
VERDE = "#00B85A"


# ---------------------------------------------------------------------------------------------
# Elegir los días (lo mismo en el Mac y en el teléfono). Lo elegido es siempre un CONJUNTO de fechas: un día, una semana
# o los días sueltos que se quieran (13, 15 y 17), aunque no sean seguidos.
# ---------------------------------------------------------------------------------------------
def vista_de(modelo, unidad_id=None):
    """La unidad elegida en el Resumen (o None = todo el proyecto)."""
    return next((u for u in modelo.get("unidades") or [] if u["id"] == unidad_id), None)


def rodados(modelo, unidad_id=None):
    """Las fechas con material, de la más vieja a la más nueva."""
    v = vista_de(modelo, unidad_id)
    return sorted({d["fecha"] for d in (v or modelo)["serie"] if d.get("fecha")})


def semana_de(f):
    """Lunes y domingo de la semana de `f`."""
    lunes = f - timedelta(days=f.weekday())
    return lunes, lunes + timedelta(days=6)


def rango(desde, hasta):
    """Todas las fechas de `desde` a `hasta` (ambas incluidas)."""
    return {desde + timedelta(days=k) for k in range((hasta - desde).days + 1)}


def semanas_del_proyecto(modelo, unidad_id=None):
    """Las semanas DEL PROYECTO (no las del calendario), en orden: las que marca la columna SEMANA del estadístico («1 PILOTO», 1, 2…);
    sin estadístico (o sin esa columna), cada semana de calendario con material es la siguiente: Semana 1, Semana 2…
    Cada una: {id, nombre («Semana 3» / «Piloto»), corto («S3»), fechas (las rodadas, en orden), desde, hasta, dias, gb, primero, ultimo}."""
    v = vista_de(modelo, unidad_id)
    serie = [d for d in (v or modelo)["serie"] if d.get("fecha")]
    fechas = sorted({d["fecha"] for d in serie})
    if not fechas:
        return []
    gb_de, dia_de = {}, {}
    for d in serie:
        gb_de[d["fecha"]] = gb_de.get(d["fecha"], 0.0) + (d.get("gb") or 0.0)
        dia_de.setdefault(d["fecha"], d["dia"])
    marca_de = {}
    for d in modelo.get("dias07") or []:
        if d.get("fecha") and str(d.get("semana") or "").strip():
            marca_de.setdefault(d["fecha"], str(d["semana"]).strip())
    salida, por_id = [], {}
    if any(f in marca_de for f in fechas):
        primera, marca = min(f for f in fechas if f in marca_de), None
        for f in fechas:
            marca = marca_de.get(f) or (marca if f > primera else None)
            clave = marca or "antes"
            if clave not in por_id:
                nombre = nombre_semana(marca) if marca else "Antes de la Semana 1"
                por_id[clave] = {"id": clave, "nombre": nombre, "fechas": []}
                salida.append(por_id[clave])
            por_id[clave]["fechas"].append(f)
    else:
        for f in fechas:
            clave = semana_de(f)[0].isoformat()
            if clave not in por_id:
                por_id[clave] = {"id": clave, "nombre": f"Semana {len(salida) + 1}", "fechas": []}
                salida.append(por_id[clave])
            por_id[clave]["fechas"].append(f)
    for w in salida:
        fs = w["fechas"]
        num = re.search(r"\d+", w["nombre"])
        w.update(desde=fs[0], hasta=fs[-1], dias=len(fs), gb=sum(gb_de.get(f, 0.0) for f in fs), primero=dia_de.get(fs[0], ""),
                 ultimo=dia_de.get(fs[-1], ""), corto=("S" + num[0]) if w["nombre"].startswith("Semana") and num else
                 "Antes" if w["id"] == "antes" else w["nombre"][:10])
    return salida


def semanas_elegidas(semanas, elegidos):
    """Los id de las semanas del proyecto que están COMPLETAS en lo elegido."""
    sel = set(elegidos)
    return [w["id"] for w in semanas if w["fechas"] and set(w["fechas"]) <= sel]


def tocar_semana(semanas, elegidos, wid, sumar=False):
    """Tocar una semana de la rueda: sola (lo normal) o, con `sumar`, se agrega a las elegidas o se quita si ya estaba."""
    w = next((x for x in semanas if x["id"] == wid), None)
    if not w:
        return set(elegidos)
    fs = set(w["fechas"])
    if not sumar:
        return fs
    sel = set(elegidos)
    return (sel - fs) if fs <= sel else (sel | fs)


def desde_hasta(semanas, elegidos):
    """Para la rueda «Desde / Hasta»: (id de la primera, id de la última) semana del proyecto que están completas en lo elegido.
    Si no hay ninguna completa, la última semana del proyecto en las dos."""
    ids = semanas_elegidas(semanas, elegidos)
    if ids:
        return ids[0], ids[-1]
    return (semanas[-1]["id"], semanas[-1]["id"]) if semanas else (None, None)


def elegir_desde_hasta(semanas, elegidos, columna, wid):
    """Girar una de las dos ruedas: `columna` = "desde" o "hasta", `wid` = la semana que quedó en el centro. Si «desde» pasa a
    «hasta» (o al revés) la otra rueda la sigue. Devuelve las fechas rodadas de todas las semanas de ese tramo."""
    orden = [w["id"] for w in semanas]
    if wid not in orden:
        return set(elegidos)
    d, h = desde_hasta(semanas, elegidos)
    i_d, i_h, i = orden.index(d), orden.index(h), orden.index(wid)
    if columna == "desde":
        i_d, i_h = i, max(i, i_h)
    else:
        i_h, i_d = i, min(i, i_d)
    return {f for w in semanas[i_d:i_h + 1] for f in w["fechas"]}


def semana_de_fecha(semanas, f):
    """La semana del proyecto que tiene la fecha `f` (o la última antes de ella)."""
    previa = None
    for w in semanas:
        if w["desde"] <= f <= w["hasta"] or f in w["fechas"]:
            return w
        if w["desde"] <= f:
            previa = w
    return previa or (semanas[0] if semanas else None)


def inicial(modelo, unidad_id=None):
    """Lo que se propone al abrir: la última semana del proyecto (vacío si no hay fechas)."""
    semanas = semanas_del_proyecto(modelo, unidad_id)
    return set(semanas[-1]["fechas"]) if semanas else set()


def tocar(tipo, elegidos, f):
    """Lo elegido después de tocar el día `f`. Día: solo ese día. Semana: su semana (lunes a domingo).
    Varios días: el día se agrega o se quita (se pueden elegir los días que se quiera, seguidos o sueltos)."""
    if tipo == "dia":
        return {f}
    if tipo == "semana":
        return rango(*semana_de(f))
    return set(elegidos) ^ {f}


def ajustar(tipo, elegidos, fechas, semanas=None):
    """Al cambiar de Día/Semana/Varios días, lo elegido se acomoda sin perder el lugar. Con `semanas` (las del proyecto), «Semana»
    elige la semana del proyecto de lo que estaba elegido (si no, la de calendario, lunes a domingo)."""
    ref = max(elegidos) if elegidos else (fechas[-1] if fechas else date.today())
    con_material = sorted(f for f in elegidos if f in set(fechas))
    if tipo == "dia":
        return {con_material[-1] if con_material else ref}
    if tipo == "semana":
        if semanas:
            ya = semanas_elegidas(semanas, elegidos)
            if ya and set(elegidos) <= set().union(*(set(w["fechas"]) for w in semanas if w["id"] in ya)):
                return set(elegidos)                   # ya eran semanas completas: se quedan
            w = semana_de_fecha(semanas, con_material[-1] if con_material else ref)
            if w:
                return set(w["fechas"])
        return rango(*semana_de(ref))
    return set(con_material) or {ref}                 # de una semana quedan sus días con material, para quitar o agregar


def atajos(modelo, unidad_id=None):
    """Botones rápidos: [(texto, tipo, fechas)]."""
    fechas = rodados(modelo, unidad_id)
    if not fechas:
        return []
    u = fechas[-1]
    semanas = semanas_del_proyecto(modelo, unidad_id)
    salida = [("Último día", "dia", {u})]
    if semanas:
        salida.append((f"Última semana ({semanas[-1]['corto']})", "semana", set(semanas[-1]["fechas"])))
    if len(semanas) > 1:
        salida.append((f"Semana anterior ({semanas[-2]['corto']})", "semana", set(semanas[-2]["fechas"])))
    salida.append(("Todo el proyecto", "dias", set(fechas)))
    return salida


def mes(anio, mes_, fechas, elegidos):
    """La cuadrícula de un mes para dibujar el calendario: semanas de 7 casillas (None fuera del mes). Cada casilla:
    {fecha, rodado, elegido, inicio, fin, hoy}; inicio/fin marcan los bordes de cada tramo de días seguidos (un día suelto es ambos)."""
    rod, sel = set(fechas), set(elegidos)
    hoy = date.today()
    semanas = []
    for sem in calendar.Calendar(firstweekday=0).monthdatescalendar(anio, mes_):
        fila = []
        for f in sem:
            if f.month != mes_:
                fila.append(None)
                continue
            dentro = f in sel
            fila.append({"fecha": f, "rodado": f in rod, "elegido": dentro, "hoy": f == hoy,
                         "inicio": dentro and (f - timedelta(days=1)) not in sel, "fin": dentro and (f + timedelta(days=1)) not in sel})
        semanas.append(fila)
    return semanas


def mover_mes(anio, mes_, paso):
    m = mes_ - 1 + paso
    return anio + m // 12, m % 12 + 1


def titulo_mes(anio, mes_):
    return f"{MESES[mes_ - 1].capitalize()} {anio}"


def texto_fecha(f, anio=True):
    if not f:
        return "—"
    return f"{f.day} {MESES[f.month - 1][:3]}" + (f" {f.year}" if anio else "")


def texto_periodo(desde, hasta):
    """«13 oct 2026», «13 – 19 oct 2026», «28 sep – 4 oct 2026», «28 dic 2026 – 3 ene 2027»."""
    if not desde:
        return "Sin fechas"
    if desde == hasta:
        return texto_fecha(desde)
    if desde.year != hasta.year:
        return f"{texto_fecha(desde)} – {texto_fecha(hasta)}"
    if desde.month == hasta.month:
        return f"{desde.day} – {texto_fecha(hasta)}"
    return f"{texto_fecha(desde, False)} – {texto_fecha(hasta)}"


def texto_periodo_corto(desde, hasta):
    """Para las tarjetas de la rueda: «7 – 12 sep», «31 ago – 5 sep» (sin el año; con año solo si cruza de año)."""
    if desde.year != hasta.year:
        return texto_periodo(desde, hasta)
    if desde == hasta:
        return texto_fecha(desde, False)
    if desde.month == hasta.month:
        return f"{desde.day} – {texto_fecha(hasta, False)}"
    return f"{texto_fecha(desde, False)} – {texto_fecha(hasta, False)}"


def texto_del_al(desde, hasta):
    """«del 13 al 16 oct 2026», «del 28 sep al 4 oct 2026», «del 28 dic 2026 al 3 ene 2027»."""
    if desde.year != hasta.year:
        return f"del {texto_fecha(desde)} al {texto_fecha(hasta)}"
    if desde.month != hasta.month:
        return f"del {texto_fecha(desde, False)} al {texto_fecha(hasta)}"
    return f"del {desde.day} al {texto_fecha(hasta)}"


def titulo_de(datos, todas_las_fechas):
    """El nombre del reporte según lo elegido: «de todo el proyecto», «Semana 9», «D049» o «del 13 al 16 oct 2026»."""
    con_material = [d["fecha"] for d in datos["dias"]]
    if not con_material:
        return texto_del_al(datos["desde"], datos["hasta"]) if datos["desde"] != datos["hasta"] else texto_fecha(datos["desde"])
    sem = datos.get("semanas_rep") or []
    if sem and (datos.get("modo") == "semana" or len(con_material) > 1) and \
            not (datos.get("modo") != "semana" and len(todas_las_fechas) > 1 and set(con_material) == set(todas_las_fechas)):
        return texto_semanas(sem)                       # «Semana 3», «Semanas 3 y 4», «Semanas 1, 3 y 5»
    if len(todas_las_fechas) > 1 and set(con_material) == set(todas_las_fechas):
        return "de todo el proyecto"
    if len(con_material) == 1:
        return datos["dias"][0]["dia"]
    if datos["tipo"] == "semanal" and len(datos["semanas"]) == 1:
        return nombre_semana(datos["semanas"][0])
    if datos["tipo"] == "semanal":
        return "semanal " + texto_del_al(datos["desde"], datos["hasta"])
    return texto_del_al(min(con_material), max(con_material))


def seguidos(elegidos):
    return bool(elegidos) and (max(elegidos) - min(elegidos)).days + 1 == len(elegidos)


def texto_seleccion(elegidos):
    """«13 – 19 oct 2026» si son seguidos; «13, 15 y 17 oct 2026» si son pocos sueltos; si son muchos, cuántos y entre qué fechas."""
    if not elegidos:
        return "Sin días elegidos"
    sel = sorted(elegidos)
    if seguidos(sel):
        return texto_periodo(sel[0], sel[-1])
    if len(sel) <= 4:
        partes = [str(f.day) if k + 1 < len(sel) and sel[k + 1].month == f.month else texto_fecha(f, False) for k, f in enumerate(sel)]
        texto = ", ".join(partes[:-1]) + " y " + partes[-1]
        return f"{texto} {sel[-1].year}"
    return f"{len(sel)} días · {texto_periodo(sel[0], sel[-1])}"


def tipo_de(desde, hasta):
    """«diario», «semanal» o «del periodo» (para el título del reporte)."""
    if desde == hasta:
        return "diario"
    if desde.weekday() == 0 and hasta - desde == timedelta(days=6):
        return "semanal"
    return "del periodo"


# ---------------------------------------------------------------------------------------------
# Los números del periodo
# ---------------------------------------------------------------------------------------------

def _rango_de_rollos(bins, tipo):
    """«A120 – A124» con los BIN de una cámara en el periodo (en el orden en que se grabaron)."""
    if not bins:
        return ""
    if tipo != "camara":
        return bins[0] if len(bins) == 1 else f"{bins[0]} – {bins[-1]}"
    cortos = ["_".join(b.split("_")[:2]) if "_" in b else b for b in bins]
    return cortos[0] if len(cortos) == 1 else f"{cortos[0]} – {cortos[-1]}"


GRUPOS_TIPO = (("camara", "Cámaras"), ("sonido", "Sonido"), ("otros", "Drones y otros"))


def _grupo_tipo(tipo):
    return tipo if tipo in ("camara", "sonido") else "otros"


def colores_de_camaras(camaras, paleta=None):
    """El color de cada cámara (en el mismo orden): SIEMPRE el suyo (el de la hoja al importar, o el que elegiste en Ajustes), aunque
    otra cámara tenga el mismo. Solo una cámara sin color toma uno de la paleta que no esté usado. Lo usan el reporte y el Resumen de
    las dos apps, así los colores son los mismos en todas partes."""
    paleta = paleta or PALETA
    propios = [(c.get("color") or "") if re.fullmatch(r"#[0-9A-Fa-f]{6}", c.get("color") or "") else "" for c in camaras]
    usados = {h.upper() for h in propios if h}
    out = []
    for i, h in enumerate(propios):
        if not h:
            h = next((p for p in paleta if p.upper() not in usados), paleta[i % len(paleta)])
            usados.add(h.upper())
        out.append(h)
    return out


def armar(modelo, elegidos, unidad_id=None, paleta=None, ahora=None, modo=None):
    """Todo lo que lleva el reporte de los días `elegidos` (conjunto de fechas, seguidas o sueltas).
    `unidad_id`: la unidad elegida en el Resumen (None = todas)."""
    paleta = paleta or PALETA
    sel = set(elegidos)
    desde, hasta = (min(sel), max(sel)) if sel else (date.today(), date.today())
    vista = vista_de(modelo, unidad_id)
    serie = (vista or modelo)["serie"]
    todas = modelo["camaras"]
    colores = dict(zip((c["id"] for c in todas), colores_de_camaras(todas, paleta)))
    info = {c["id"]: c for c in todas}
    dias = [d for d in serie if d.get("fecha") in sel]
    sin_fecha = sum(1 for d in serie if not d.get("fecha"))

    # ---- por cámara (sumando tarjeta por tarjeta) ----
    por_cam = {}
    for d in dias:
        for x in d.get("detalle") or []:
            c = info.get(x["cam"]) or {"id": x["cam"], "nombre": x["cam"], "tipo": "sonido" if x.get("audio") else "camara",
                                       "modelo": "", "rental": "", "letra": ""}
            r = por_cam.setdefault(x["cam"], {"id": x["cam"], "nombre": c["nombre"], "tipo": c["tipo"], "letra": c.get("letra", ""),
                                              "modelo": x.get("modelo") or c.get("modelo", ""), "rental": c.get("rental", ""),
                                              "color": colores.get(x["cam"]) or paleta[len(por_cam) % len(paleta)],
                                              "gb": 0.0, "clips": 0, "seg": 0.0, "tarjetas": 0, "bins": [], "dias": [], "mags": [],
                                              "por_dia": {}})
            r["gb"] += x["gb"]
            r["clips"] += x["clips"]
            r["seg"] += x["seg"]
            if x.get("bin"):
                r["tarjetas"] += 1
                r["bins"].append(x["bin"])
            if x.get("mag") is not None and x["mag"] not in r["mags"]:
                r["mags"].append(x["mag"])
            if d["dia"] not in r["dias"]:
                r["dias"].append(d["dia"])
            r["por_dia"][d["fecha"]] = r["por_dia"].get(d["fecha"], 0.0) + x["gb"]
    orden = {c["id"]: i for i, c in enumerate(todas)}
    camaras = sorted(por_cam.values(), key=lambda r: orden.get(r["id"], 999))
    gb = sum(d["gb"] for d in dias)
    for r in camaras:
        r["pct"] = r["gb"] / gb if gb else 0.0
        r["rollos"] = _rango_de_rollos(r["bins"], r["tipo"])

    # ---- por tipo (como «Clips Overview» de Silverstack) ----
    tipos = []
    for clave, nombre in GRUPOS_TIPO:
        cs = [r for r in camaras if _grupo_tipo(r["tipo"]) == clave]
        if cs:
            tipos.append({"clave": clave, "nombre": nombre, "equipos": len(cs), "gb": sum(r["gb"] for r in cs),
                          "clips": sum(r["clips"] for r in cs), "seg": sum(r["seg"] for r in cs), "tarjetas": sum(r["tarjetas"] for r in cs)})

    # ---- totales del periodo ----
    n = len(dias)
    clips_v = sum(d.get("clips", 0) for d in dias)
    clips_a = sum(d.get("clips_audio", 0) for d in dias)
    seg_v = sum(d.get("seg", 0.0) for d in dias)
    seg_a = sum(d.get("seg_audio", 0.0) for d in dias)
    tot = {"gb": gb, "tb": gb / rsm.GB_POR_TB, "dias": n, "clips": clips_v, "clips_audio": clips_a, "seg": seg_v, "seg_audio": seg_a,
           "tarjetas": sum(d.get("tarjetas", 0) for d in dias) or sum(r["tarjetas"] for r in camaras),
           "promedio_gb": gb / n if n else 0.0, "mejor": max(dias, key=lambda d: d["gb"]) if dias else None,
           "menor": min(dias, key=lambda d: d["gb"]) if dias else None,
           "camaras": len([r for r in camaras if r["tipo"] == "camara"]), "equipos": len(camaras)}

    # ---- semanas del proyecto que están completas en lo elegido (para el título «Semana 3») ----
    semanas_proy = semanas_del_proyecto(modelo, unidad_id)
    ids = semanas_elegidas(semanas_proy, sel)
    cubiertas = [w for w in semanas_proy if w["id"] in ids]
    con_mat = {d["fecha"] for d in dias}
    exacto = bool(cubiertas) and set().union(*(set(w["fechas"]) for w in cubiertas)) == con_mat
    semanas_rep = [w["nombre"] for w in cubiertas] if exacto else []

    # ---- con qué se compara: la semana anterior del proyecto, la de calendario, o los mismos días de rodaje justo antes ----
    tipo = tipo_de(desde, hasta) if seguidos(sel) else "de días elegidos"
    if exacto and len(cubiertas) == 1 and semanas_proy.index(cubiertas[0]) > 0:
        tipo = "semanal"
        w_ant = semanas_proy[semanas_proy.index(cubiertas[0]) - 1]
        previos = [d for d in serie if d.get("fecha") in set(w_ant["fechas"])]
        texto_ant = w_ant["nombre"]
    elif tipo == "semanal":
        previos = [d for d in serie if d.get("fecha") and desde - timedelta(days=7) <= d["fecha"] < desde]
        texto_ant = "semana anterior"
    else:
        antes = [d for d in serie if d.get("fecha") and d["fecha"] < desde]
        previos = antes[-n:] if n else []
        texto_ant = "día de rodaje anterior" if n == 1 else f"{n} días de rodaje anteriores"
    anterior = {"gb": sum(d["gb"] for d in previos), "dias": len(previos), "texto": texto_ant,
                "promedio_gb": sum(d["gb"] for d in previos) / len(previos)} if previos else None

    # ---- lo previsto (del estadístico) ----
    t_m = (vista or modelo)["totales"]
    previstos = (vista.get("dias_previstos") if vista else None) or t_m.get("dias_previstos")
    espacio = (vista.get("espacio_previsto_gb") if vista else None) or t_m.get("espacio_previsto_gb")

    # ---- día por día, con sus tarjetas ----
    lista_dias = []
    for d in dias:
        tarjetas = []
        for x in d.get("detalle") or []:
            c = por_cam.get(x["cam"], {})
            tarjetas.append({"bin": x.get("bin") or c.get("nombre", ""), "camara": c.get("nombre", ""), "color": c.get("color", "#999999"),
                             "modelo": x.get("modelo") or c.get("modelo", ""), "mag": x.get("mag"), "clips": x["clips"], "seg": x["seg"],
                             "gb": x["gb"], "audio": x.get("audio", False), "unidad": x.get("unidad", "")})
        por_cam_dia = {}
        for x in d.get("detalle") or []:
            por_cam_dia[x["cam"]] = por_cam_dia.get(x["cam"], 0.0) + x["gb"]
        lista_dias.append({"dia": d["dia"], "fecha": d["fecha"], "gb": d["gb"], "clips": d.get("clips", 0), "seg": d.get("seg", 0.0),
                           "clips_audio": d.get("clips_audio", 0), "seg_audio": d.get("seg_audio", 0.0),
                           "tarjetas": d.get("tarjetas", 0) or len([t for t in tarjetas if t["bin"]]), "lista": tarjetas,
                           "por_camara": por_cam_dia, "solo_f07": d.get("solo_f07", False)})

    general = _general(modelo, vista, serie, todas, colores, hasta, previstos, espacio)
    semanas = []
    for d in general["filas"]:
        if d["semana"] and d["fecha"] in sel and d["gb"] > 0 and d["semana"] not in semanas:
            semanas.append(d["semana"])
    # los días elegidos agrupados por semana (la del estadístico; sin estadístico, la semana de calendario)
    sem_de = {d["fecha"]: d["semana"] for d in general["filas"] if d["fecha"] and d["semana"]}
    por_semana = []
    for d in lista_dias:
        nombre = nombre_semana(sem_de.get(d["fecha"])) or f"Semana del {texto_fecha(semana_de(d['fecha'])[0], False)}"
        if not por_semana or por_semana[-1]["nombre"] != nombre:
            por_semana.append({"nombre": nombre, "dias": 0, "gb": 0.0, "seg": 0.0, "clips": 0, "primero": d["dia"], "ultimo": d["dia"]})
        w = por_semana[-1]
        w["dias"] += 1
        w["gb"] += d["gb"]
        w["seg"] += d["seg"]
        w["clips"] += d["clips"]
        w["ultimo"] = d["dia"]
    # el almacenamiento de ESTOS días por columna del estadístico (CAM A, CAM B… AUDIO), como el «Resumen General»
    alm = {}
    for d in general["filas"]:
        if d["fecha"] in sel and d["rodado"]:
            for k, v in (d.get("por_columna") or {}).items():
                alm[k] = alm.get(k, 0.0) + v
    color07 = {c["nombre"]: c["color"] for c in general["camaras"]}
    total_alm = sum(v for v in alm.values() if v > 0)            # (el % sobre el total del estadístico: antes se dividía por el del estatus)
    almacenamiento = [{"nombre": k, "gb": v, "color": color07.get(k, "#9A9AA0"), "pct": v / total_alm if total_alm else 0.0}
                      for k, v in alm.items() if v > 0]
    if not almacenamiento:                         # sin estadístico: por rollo, desde el estatus de tarjetas
        almacenamiento = [{"nombre": c["nombre"], "gb": c["gb"], "color": c["color"], "pct": c["pct"]} for c in camaras if c["gb"] > 0]

    avisos = []
    if not dias:
        avisos.append("No hay material registrado en los días elegidos.")
    if sin_fecha:
        avisos.append(f"{sin_fecha} {'día' if sin_fecha == 1 else 'días'} de tu hoja no tienen fecha y no entran en ningún reporte por fechas.")
    if any(d.get("solo_f07") for d in dias):
        avisos.append("Este reporte sale del estadístico (FO-07): no trae el detalle tarjeta por tarjeta. "
                      "Conecta el estatus de tarjetas (FO-06) para verlo.")
    if vista is None and modelo.get("unidades") and len(modelo["unidades"]) > 1:
        unidad_txt = "Todas las unidades"
    else:
        unidad_txt = vista["nombre"] if vista else ""
    datos = {"proyecto": modelo.get("proyecto") or "", "desde": desde, "hasta": hasta, "elegidos": sel, "tipo": tipo,
            "periodo": texto_seleccion(sel), "almacenamiento": almacenamiento, "unidad": unidad_txt, "dias": lista_dias, "camaras": camaras, "tipos": tipos,
            "totales": tot, "anterior": anterior, "general": general, "semanas": semanas, "por_semana": por_semana, "equipo": (vista or {}).get("equipo") or modelo.get("equipo") or {},
            "formato": (vista or {}).get("formato") or modelo.get("formato") or [], "fuente": modelo.get("fuente", ""),
            "generado": ahora or datetime.now(), "avisos": avisos, "semanas_rep": semanas_rep, "modo": modo,
            "proyecto_bonito": proyecto_bonito(modelo.get("proyecto") or "")}
    datos["titulo"] = titulo_de(datos, sorted({d["fecha"] for d in serie if d.get("fecha")}))
    datos["titulo_grande"] = titulo_grande(datos["titulo"])
    datos["unidad_id"] = vista["id"] if vista else None
    datos["por_unidad"] = por_unidad(modelo, sel, colores) if vista is None else []
    if datos["por_unidad"]:                            # cada unidad tiene su equipo: arriba solo lo que comparten, lo demás en su fila
        equipos = [u.get("equipo") or {} for u in modelo["unidades"]]
        comun = {k: v for k, v in equipos[0].items() if all(e.get(k) == v for e in equipos[1:])}
        if any(equipos):
            datos["equipo"] = comun
            for x, e in zip(datos["por_unidad"], equipos):
                x["equipo"] = {k: v for k, v in e.items() if k not in comun}
    return datos


def por_unidad(modelo, elegidos, colores=None):
    """Con varias unidades y el reporte de «Todo»: lo de cada unidad en los días elegidos
    [{'nombre','gb','tb','dias','pct','camaras':[(nombre, gb, color)]}]. Con una sola unidad, []."""
    unidades = modelo.get("unidades") or []
    if len(unidades) < 2:
        return []
    nombres = {c["id"]: c["nombre"] for c in modelo.get("camaras") or []}
    colores = colores or {}
    out = []
    for u in unidades:
        dias = [d for d in u.get("serie") or [] if d.get("fecha") in elegidos and d["gb"] > 0]
        cams = {}
        for d in dias:
            for x in d.get("detalle") or []:
                cams[x["cam"]] = cams.get(x["cam"], 0.0) + x["gb"]
        gb = sum(d["gb"] for d in dias)
        out.append({"id": u["id"], "nombre": u["nombre"], "gb": gb, "tb": gb / rsm.GB_POR_TB, "dias": len(dias),
                    "camaras": [(nombres.get(k, k), v, colores.get(k, "#9A9AA0")) for k, v in cams.items() if v > 0]})
    total = sum(x["gb"] for x in out)
    for x in out:
        x["pct"] = x["gb"] / total if total else 0.0
    return out


def _general(modelo, vista, serie, todas, colores, hasta, previstos, espacio):
    """El «Resumen General» del proyecto hasta `hasta` (lo mismo que trae el PDF del estadístico que se envía cada semana):
    almacenamiento por cámara, espacio OCF, días previstos/rodados, promedio, semana y TODOS los días (también los que faltan por rodar).
    Sale del estadístico (FO-07) si está conectado; si no, del estatus de tarjetas."""
    varias = len(modelo.get("unidades") or []) > 1
    d07 = modelo.get("dias07") or []
    if d07 and (vista is None or not varias):
        filas = [dict(d, rodado=bool(d["gb"] > 0 and d["fecha"] and d["fecha"] <= hasta),
                      por_columna=dict({f"CAM {k}": v for k, v in d["camaras"].items()}, AUDIO=d["audio"])) for d in d07]
        cams = {}
        for d in filas:
            if d["rodado"]:
                for k, v in d["camaras"].items():
                    cams[f"CAM {k}"] = cams.get(f"CAM {k}", 0.0) + v
                cams["AUDIO"] = cams.get("AUDIO", 0.0) + d["audio"]
        por_letra = {}
        for c in todas:
            for k in c.get("claves") or []:
                por_letra.setdefault(f"CAM {k}", colores.get(c["id"]))
        sonido = next((colores.get(c["id"]) for c in todas if c["tipo"] == "sonido"), None)
        camaras = [{"nombre": k, "gb": v, "color": por_letra.get(k) or (sonido if k == "AUDIO" else None) or "#9A9AA0"}
                   for k, v in cams.items() if v > 0]
        fuente = "FO-07"
    else:
        filas = [{"dia": d["dia"], "fecha": d["fecha"], "gb": d["gb"], "seg": d.get("seg", 0.0), "semana": "",
                  "rodado": bool(d.get("fecha") and d["fecha"] <= hasta)} for d in serie]
        cams = {}
        for d in serie:
            if d.get("fecha") and d["fecha"] <= hasta:
                for x in d.get("detalle") or []:
                    cams[x["cam"]] = cams.get(x["cam"], 0.0) + x["gb"]
        nombres = {c["id"]: c["nombre"] for c in todas}
        orden = {c["id"]: i for i, c in enumerate(todas)}
        camaras = [{"nombre": nombres.get(k, k), "gb": v, "color": colores.get(k, "#9A9AA0")}
                   for k, v in sorted(cams.items(), key=lambda kv: orden.get(kv[0], 999))]
        fuente = "FO-06"
    rodadas = [d for d in filas if d["rodado"]]
    gb = sum(d["gb"] for d in rodadas)
    n = len(rodadas)
    semana = next((d["semana"] for d in reversed(rodadas) if d["semana"]), "")
    return {"filas": filas, "camaras": camaras, "gb": gb, "dias": n, "promedio_gb": gb / n if n else 0.0, "semana": semana,
            "dias_previstos": previstos or (len(filas) if fuente == "FO-07" and len(filas) > n else None),
            "espacio_previsto_gb": espacio, "fuente": fuente}


def nombre_archivo(datos, ext="pdf"):
    """«Reporte_DESMADRE_2026-10-13_a_2026-10-19.pdf» (sin caracteres raros, para mandarlo por correo o WhatsApp)."""
    proy = re.sub(r"[^A-Za-z0-9]+", "_", _sin_tildes(datos["proyecto"] or "FilmFlow")).strip("_") or "FilmFlow"
    d, h = datos["desde"], datos["hasta"]
    rango = d.isoformat() if d == h else f"{d.isoformat()}_a_{h.isoformat()}"
    if not seguidos(datos["elegidos"]):
        rango = f"{len(datos['elegidos'])}_dias_{d.isoformat()}_a_{h.isoformat()}"
    titulo = datos.get("titulo") or ""
    if titulo == "de todo el proyecto" or titulo.startswith(("Semana", "Piloto")):          # el nombre dice lo mismo que el título
        rango = re.sub(r"[^A-Za-z0-9]+", "_", _sin_tildes(titulo.replace("de todo", "todo"))).strip("_") + f"_{h.isoformat()}"
    uni = datos.get("unidad") or ""
    if uni:                                                # si no, los de cada unidad con las mismas fechas se pisarían
        uni = "_" + (re.sub(r"[^A-Za-z0-9]+", "_", _sin_tildes(uni)).strip("_") if uni != "Todas las unidades" else "Todas_las_unidades")
    return f"Reporte_{proy}{uni}_{rango}.{ext}"


def _sin_tildes(t):
    return str(t).translate(str.maketrans("áéíóúÁÉÍÓÚñÑüÜ", "aeiouAEIOUnNuU"))


# ---------------------------------------------------------------------------------------------
# La página (HTML + SVG, sin nada externo: se puede mandar sola)
# ---------------------------------------------------------------------------------------------
def _e(t):
    return html.escape(str(t if t is not None else ""), quote=True)


def _dur(seg):
    """«12:04:31 h», «46:54 min», «38 s» (como Silverstack)."""
    seg = int(round(seg or 0))
    if seg >= 3600:
        return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d} h"
    if seg >= 60:
        return f"{seg // 60}:{seg % 60:02d} min"
    return f"{seg} s"


def _num(n):
    return f"{int(n):,}".replace(",", ".")


def _peso(gb):
    return rsm.texto_peso(gb)


def _pct(x):
    return f"{x * 100:.1f} %".replace(".", ",")


def _escala(maximo):
    """Un tope «redondo» para el eje (1, 2, 2.5, 5 × 10ⁿ) y su paso."""
    if maximo <= 0:
        return 1.0, 0.25
    import math
    p = 10 ** math.floor(math.log10(maximo))
    for m, paso in ((1, .2), (2, .5), (2.5, .5), (5, 1), (10, 2)):
        if m * p >= maximo * 1.04:                  # un poco de aire arriba para el número de la columna más alta
            return m * p, paso * p
    return 10 * p, 2 * p


def _svg_linea(filas, sel, ancho=700, alto=220):
    """GB de cada día de todo el proyecto (como la gráfica del «Resumen General»); el periodo del reporte va resaltado y los días que
    faltan por rodar quedan vacíos al final."""
    if len(filas) < 2:
        return ""
    izq, abajo, arriba = 48, 30, 24
    h, w = alto - abajo - arriba, ancho - izq - 10
    rod = [(i, d) for i, d in enumerate(filas) if d["rodado"]]
    if not rod:
        return ""
    tope, paso = _escala(max(d["gb"] for _i, d in rod))
    n = len(filas)

    def X(i):
        return izq + w * i / (n - 1)

    def Y(v):
        return arriba + h - h * v / tope
    out = []
    k = 0.0
    while k <= tope + 1e-9:
        out.append(f'<line x1="{izq}" x2="{ancho - 10}" y1="{Y(k):.1f}" y2="{Y(k):.1f}" class="rejilla"/>'
                   f'<text x="{izq - 8}" y="{Y(k) + 4:.1f}" text-anchor="end" class="eje">{k:,.0f}</text>')
        k += paso
    out.append(f'<text x="{izq - 8}" y="{arriba - 12}" text-anchor="end" class="eje">GB</text>')
    dentro = [i for i, d in rod if d["fecha"] in sel]
    paso_x = w / (n - 1)
    for i in dentro:                                  # cada día elegido con su franja (pueden ser días sueltos)
        out.append(f'<rect x="{X(i) - paso_x / 2:.1f}" y="{arriba}" width="{paso_x:.1f}" height="{h}" class="zona"/>')
    puntos = " ".join(f"{X(i):.1f},{Y(d['gb']):.1f}" for i, d in rod)
    out.append(f'<polyline points="{puntos}" class="linea"/>')
    for i, d in rod:
        clase = "punto" if i in dentro else "punto tenue"
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(d["gb"]):.1f}" r="{3 if i in dentro else 1.8}" class="{clase}">'
                   f'<title>{_e(d["dia"])}: {d["gb"]:,.2f} GB</title></circle>')
    cada = max(1, round(n / 12))
    for i, d in enumerate(filas):
        if (i % cada == 0 and (i == n - 1 or n - 1 - i > cada / 2)) or i == n - 1:      # el último rótulo no se pisa con el anterior
            out.append(f'<text x="{X(i):.1f}" y="{arriba + h + 16}" text-anchor="middle" class="eje{"" if d["rodado"] else " tenue"}">'
                       f'{_e(_dia_corto(d["dia"]))}</text>')
    return f'<svg class="graf" viewBox="0 0 {ancho} {alto}" role="img" aria-label="Almacenamiento por día">{"".join(out)}</svg>'


def _dia_corto(t):
    """«DIA 01 Piloto» → «D01P», «DIA 45» → «D45», «D045» igual."""
    m = re.search(r"(\d+)", str(t))
    if not m:
        return str(t)[:6]
    return f"D{m.group(1)}" + ("P" if "pilot" in str(t).lower() else "")


def _tabla_dias(filas, sel):
    """Todos los días del proyecto en dos columnas (DÍA · TOTAL GB · DURACIÓN), como el «Resumen General»."""
    def fila(d):
        en = d["rodado"] and d["fecha"] in sel
        clase = "en-periodo" if en else "" if d["rodado"] else "por-rodar"
        gb = f'{d["gb"]:,.2f}' if d["rodado"] else "—"
        dur = rsm.hms(d["seg"]) if d["rodado"] else "—"
        return f'<tr class="{clase}"><td>{_e(d["dia"])}</td><td class="n">{gb}</td><td class="n">{dur}</td></tr>'
    mitad = (len(filas) + 1) // 2
    cab = '<thead><tr><th>Día</th><th class="n">Total (GB)</th><th class="n">Duración</th></tr></thead>'
    partes = [filas[:mitad], filas[mitad:]]
    tablas = "".join(f'<table class="limpia dias">{cab}<tbody>{"".join(fila(d) for d in p)}</tbody></table>' for p in partes if p)
    return (f'<div class="dos" style="align-items:start">{tablas}</div>'
            '<p class="nota-graf">Verde: días de este reporte. Gris: días que faltan por rodar.</p>')


CSS = """
:root{--fondo:#F2F3F5;--papel:#FFFFFF;--texto:#1D1D1F;--texto2:#6E6E73;--borde:#DADADF;--suave:#F6F6F8;--verde:#00B85A;--verde-t:#009A4E;
--pista:#E9E9ED;--fondo-impresion:#FFFFFF;--rejilla:#ECECF0;--zona:rgba(0,184,90,.12);--aviso:#8F5600;--aviso-f:#FFF3D6;color-scheme:light}
:root[data-tema=oscuro]{--fondo:#000000;--papel:#1C1C1E;--texto:#F5F5F7;--texto2:#A1A1A8;--borde:#3A3A3E;--suave:#242427;--verde:#00B85A;
--verde-t:#30D17A;--pista:#2C2C2F;--fondo-impresion:#121212;--rejilla:#2C2C2F;--zona:rgba(0,184,90,.18);--aviso:#FFC24D;--aviso-f:#3A2C0F;color-scheme:dark}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
html{background:var(--fondo)}
body{margin:0;background:var(--fondo);color:var(--texto);font:13px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Helvetica Neue",Arial,sans-serif}
.hoja{max-width:820px;margin:24px auto;background:var(--papel);border-radius:18px;padding:40px 44px 28px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:22px}
h1{font-size:28px;line-height:1.15;margin:18px 0 0;font-weight:700;letter-spacing:-.3px}
h1 em{font-style:normal;color:var(--verde)}
.logo{width:150px;height:auto}
.logo.oscuro{display:none}
:root[data-tema=oscuro] .logo.claro{display:none}
:root[data-tema=oscuro] .logo.oscuro{display:block}
h2{font-size:16px;margin:28px 0 10px;font-weight:700}
h2 small{font-weight:500;color:var(--texto2);font-size:12px;margin-left:6px}
h4{margin:0 0 12px;font-size:12px;color:var(--texto2);font-weight:600;text-align:center}
.marco{border:1px solid var(--borde);border-radius:10px;padding:14px 16px}
.info{display:grid;grid-template-columns:repeat(4,1fr);gap:12px 16px}
.dato b{display:block;font-size:13px;font-weight:700;word-break:break-word}
.dato span{display:block;color:var(--verde-t);font-size:12px}
.dato i{display:block;font-style:normal;color:var(--texto2);font-size:11px}
.cajas{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.caja{border:1px solid var(--borde);border-radius:10px;padding:14px 12px 4px;text-align:center}
.caja .dato{margin-bottom:12px}
.total{display:grid;grid-template-columns:1.1fr repeat(4,1fr);align-items:center;gap:10px;margin-top:12px;text-align:center}
.total>b{font-size:14px}
.graf{width:100%;height:auto;display:block}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:12px}
.leyenda span{display:inline-flex;align-items:center;gap:6px}
.leyenda i{width:10px;height:10px;border-radius:50%;display:inline-block}
.leyenda em{font-style:normal;color:var(--texto2)}
.reparto{display:flex;gap:24px;align-items:center}
.reparto>div{flex:1;min-width:0}
.dona-n{font-size:20px;font-weight:700;fill:var(--texto)}
.dona-s{font-size:11px;fill:var(--texto2)}
.eje{font-size:10px;fill:var(--texto2)}
.eje.tenue{opacity:.75}
.valor{font-size:10px;font-weight:600;fill:var(--texto)}
.rejilla{stroke:var(--rejilla);stroke-width:1}
.promedio{stroke:var(--texto2);stroke-width:1;stroke-dasharray:4 4}
.promedio-t{font-size:10px;fill:var(--texto2)}
.zona{fill:var(--zona)}
.area{fill:var(--zona)}
.linea{fill:none;stroke:var(--verde);stroke-width:2.2;stroke-linejoin:round}
.punto{fill:var(--verde);stroke:var(--papel);stroke-width:1.5}
table{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--borde);border-radius:10px;overflow:hidden;font-size:12px}
th{background:var(--suave);font-weight:600;padding:9px 10px;text-align:center;border-bottom:1px solid var(--borde)}
td{padding:8px 10px;border-bottom:1px solid var(--borde);font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right}
td+td,th+th{border-left:1px solid var(--borde)}
tfoot td{background:var(--suave);font-weight:700}
.cam{display:inline-flex;align-items:center;gap:7px;font-weight:600}
.cam i{width:9px;height:9px;border-radius:50%;flex:none}
.sub{color:var(--texto2);font-weight:400}
.avance{margin:6px 0 14px}
.avance-t{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px}
.avance-t span{color:var(--texto2)}
.pista{height:10px;background:var(--pista);border-radius:5px;overflow:hidden}
.pista>div{height:100%;background:var(--verde);border-radius:5px}
.cifras{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.cifra{border:1px solid var(--borde);border-radius:10px;padding:12px 14px}
.cifra span{display:block;color:var(--texto2);font-size:11px;text-transform:uppercase;letter-spacing:.4px}
.cifra b{display:block;font-size:22px;letter-spacing:-.3px;margin-top:2px}
.cifra i{display:block;font-style:normal;color:var(--texto2);font-size:11px}
.cifra .sube{color:var(--verde-t)}
.dia-t{display:flex;justify-content:space-between;align-items:baseline;margin:18px 0 8px}
.dia-t b{font-size:14px}
.dia-t span{color:var(--texto2);font-size:12px}
.aviso{background:var(--aviso-f);color:var(--aviso);border-radius:10px;padding:10px 14px;margin:10px 0;font-size:12px}
.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:12px 16px}
.nota-graf{margin:6px 2px 0;font-size:11px;color:var(--texto2)}
.kv5{display:grid;grid-template-columns:repeat(5,1fr);gap:12px 14px}
h3{font-size:13px;margin:18px 0 8px;font-weight:700}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:12px}
table.dias td{padding:4px 10px;font-size:11px}
tr.en-periodo td{background:var(--zona);font-weight:600}
tr.por-rodar td{color:var(--texto2);opacity:.6}
.punto.tenue{stroke-width:0;opacity:.8}
.tj h2 small{font-weight:500;color:var(--texto2);font-size:12px;margin-left:6px}
h2.seccion{font-size:17px;margin:22px 0 10px}
.tipos{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:18px}
.tipo h3{margin:0 0 6px;font-size:13px;color:var(--verde-t)}
.tipo dl{display:grid;grid-template-columns:auto auto;gap:4px 12px;margin:0;font-size:12.5px}
.tipo dt{color:var(--texto2)}.tipo dd{margin:0;text-align:right;font-weight:700}
.g-angosta{display:none}
td.n{white-space:nowrap}
.hoja.plano{background:transparent;box-shadow:none;padding:36px 40px 24px}
.cab{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:20px}
.cab h1{margin:0;font-size:30px}
.periodo{font-size:20px;font-weight:600;margin-top:6px}
.meta{color:var(--texto2);font-size:12.5px;margin-top:6px}
.equipo{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px 18px;padding:12px 0;margin-bottom:18px;
border-top:1px solid var(--borde);border-bottom:1px solid var(--borde)}
.equipo span{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--verde-t)}
.equipo b{display:block;font-size:12px;font-weight:600;line-height:1.3;margin-top:2px}
.u-chip{display:inline-block;background:var(--verde);color:#04130A;font-weight:700;font-size:11px;letter-spacing:.3px;text-transform:none;
border-radius:999px;padding:3px 10px;margin-left:10px;vertical-align:1px}
.portada{position:relative;padding:4px 0 22px;margin-bottom:22px;border-bottom:1px solid var(--borde)}
.portada::after{content:"";position:absolute;left:0;bottom:-2px;width:64px;height:3px;border-radius:3px;background:var(--verde)}
.p-kicker{font-size:11px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;color:var(--verde-t)}
.p-proyecto{font-size:34px;line-height:1.08;font-weight:800;letter-spacing:-.6px;margin:8px 0 4px}
.p-titulo{margin:0;font-size:26px;line-height:1.2;font-weight:700;letter-spacing:-.3px;color:var(--verde-t)}
.portada .periodo{font-size:15px;font-weight:600;margin-top:6px;color:var(--texto)}
.portada .meta{margin-top:4px}
.pu{padding:10px 0;border-bottom:1px solid var(--borde)}.pu:last-child{border-bottom:0}
.pu-cab{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:14px}.pu-cab span{color:var(--texto2);font-size:12.5px}
.pu-eq{font-size:11.5px;color:var(--texto2);margin-top:3px}.pu-eq b{color:var(--texto);font-weight:600}
.pu-pista{height:10px;border-radius:999px;background:var(--pista);margin:7px 0 6px;overflow:hidden}
.pu-barra{height:100%;border-radius:999px;background:var(--verde)}
.pu-cams{font-size:11.5px;color:var(--texto2);line-height:1.6}.pu-cams i{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 4px 0 6px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--suave);border-radius:14px;padding:14px 16px}
.kpi span{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--texto2);white-space:nowrap}
.kpi b{display:block;font-size:24px;letter-spacing:-.4px;margin:4px 0 2px;white-space:nowrap}
.kpi i{display:block;font-style:normal;font-size:11px;color:var(--texto2);line-height:1.35}
.kpi i.sube{color:var(--verde-t)}
.tj{background:var(--suave);border-radius:16px;padding:16px 18px 14px;margin-bottom:14px}
.tj h2{margin:0 0 12px;font-size:15px}
.b-nombre{font-size:12.5px;font-weight:600;fill:var(--texto)}
.b-pista{fill:var(--pista)}
.b-valor{font-size:12.5px;font-weight:700;fill:var(--texto)}
.b-pct{font-weight:500;fill:var(--texto2)}
.pie-tj{display:flex;justify-content:space-between;border-top:1px solid var(--borde);margin-top:8px;padding-top:10px;font-size:12.5px}
.pie-tj span{color:var(--texto2)}
.col{fill:var(--verde);opacity:.62}
.col.mejor{opacity:1}
.tj .valor{paint-order:stroke;stroke:var(--suave);stroke-width:4px;stroke-linejoin:round}
.eje.fuerte{fill:var(--texto);font-weight:600}
.promedio-t.fuerte{fill:var(--texto);font-weight:700}
table.limpia{border:0;border-radius:0;margin-top:0;background:transparent}
table.limpia th{background:transparent;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--texto2);
border-bottom:1px solid var(--borde);padding:6px 8px}
table.limpia td{padding:7px 8px;border-bottom:1px solid var(--borde)}
table.limpia td+td,table.limpia th+th{border-left:0}
table.limpia th.n{text-align:right}
table.limpia tfoot td{background:transparent;border-bottom:0;font-weight:700}
table.limpia tfoot{display:table-row-group}
.avance2{display:flex;align-items:center;gap:28px}
.anillos{display:flex;gap:14px}
.a-pista{stroke:var(--pista)}.a-valor{stroke:var(--verde)}
.a-n{font-size:20px;font-weight:700;fill:var(--texto)}.a-s{font-size:11px;fill:var(--texto2)}
.avance2 dl{display:grid;grid-template-columns:auto auto;gap:6px 18px;margin:0;font-size:12.5px;flex:1}
.avance2 dt{color:var(--texto2)}.avance2 dd{margin:0;font-weight:700;text-align:right}
.formato{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:4px 0 6px}
.f-t{font-size:12px;font-weight:700;margin-right:4px}
.chip{background:var(--suave);border-radius:999px;padding:5px 11px;font-size:11.5px;font-weight:600}
.chip i{font-style:normal;font-weight:500;color:var(--texto2)}
footer{break-before:avoid;page-break-before:avoid;display:flex;flex-wrap:wrap;gap:4px 16px;justify-content:space-between;color:var(--texto2);font-size:11px;margin-top:14px;padding-top:10px;border-top:1px solid var(--borde)}
.barra{position:sticky;top:0;z-index:5;display:none;justify-content:center;gap:8px;padding:10px;background:var(--fondo)}
.barra button{font:600 13px -apple-system,BlinkMacSystemFont,sans-serif;border:1px solid var(--borde);background:var(--papel);color:var(--texto);
border-radius:999px;padding:7px 16px;cursor:pointer}
.con-botones .barra{display:flex}
.barra button.verde{background:var(--verde);border-color:var(--verde);color:#04130A}
.bloque{break-inside:avoid;page-break-inside:avoid}
@media screen and (max-width:640px){.hoja{margin:0;border-radius:0;padding:24px 16px}.info,.kv{grid-template-columns:repeat(2,1fr)}
.cifras{grid-template-columns:repeat(2,1fr)}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.g-ancha{display:none}.g-angosta{display:block}.tj{padding:14px 12px}.equipo{grid-template-columns:repeat(2,minmax(0,1fr))}
.avance2{flex-direction:column;align-items:stretch}.anillos{justify-content:center}.hoja.plano{padding:22px 16px}.cab h1{font-size:26px}.dos{grid-template-columns:1fr}.total{grid-template-columns:repeat(2,1fr)}.reparto{flex-direction:column}
header{flex-direction:column-reverse}.cab{flex-direction:row;align-items:flex-start;gap:12px}.cab .logo{width:84px;flex:none}
.cab h1{font-size:24px}.periodo{font-size:17px}.p-proyecto{font-size:27px}.p-titulo{font-size:20px}.portada .periodo{font-size:14px}.tj h2 small,h2 small{display:block;margin:3px 0 0}.kv5{grid-template-columns:repeat(2,1fr)}.logo{width:120px}table{font-size:11px}td,th{padding:7px 6px}.ocultar-movil{display:none}}
@page{size:A4;margin:11mm 0}
@media print{html,body{background:var(--fondo-impresion)}.hoja{margin:0;max-width:none;box-shadow:none;border-radius:0;padding:12mm 13mm}
.hoja.plano{padding:0 13mm}.barra{display:none}
h2,h3{break-after:avoid}tr{break-inside:avoid}}
"""

JS = """
function tema(t){document.documentElement.dataset.tema=t;document.querySelectorAll('[data-t]').forEach(b=>b.classList.toggle('verde',b.dataset.t===t));}
// Los botones de arriba solo aparecen si pueden funcionar: abierto en un navegador (no dentro de la app, ni en la vista previa de
// Archivos/Mail/WhatsApp, donde no corre JavaScript y no servirían).
function botones(){try{if(window.top===window.self)document.documentElement.classList.add('con-botones');}catch(e){}}
"""


def texto_dias(datos):
    """«D046 – D049», «D046, D048 y D050» o «D038 … D049 (9 días)»."""
    et = [d["dia"] for d in datos["dias"]]
    if not et:
        return "—"
    if len(et) == 1:
        return et[0]
    if seguidos(datos["elegidos"]):
        return f"{et[0]} – {et[-1]}"
    if len(et) <= 5:
        return ", ".join(et[:-1]) + " y " + et[-1]
    return f"{et[0]} … {et[-1]} ({len(et)} días)"


def _svg_barras_camaras(alm, ancho=700):
    """Una barra por cámara (de mayor a menor), con su nombre a la izquierda y su total y porcentaje a la derecha."""
    filas = sorted((c for c in alm if c["gb"] > 0), key=lambda c: -c["gb"])
    if not filas:
        return ""
    alto_f, izq, der = 34, (92 if ancho > 500 else 62), (190 if ancho > 500 else 112)
    w = ancho - izq - der
    maximo = filas[0]["gb"]
    out = []
    for i, c in enumerate(filas):
        y = i * alto_f
        largo = max(3.0, w * c["gb"] / maximo)
        out.append(f'<text x="0" y="{y + 21}" class="b-nombre">{_e(c["nombre"])}</text>'
                   f'<rect x="{izq}" y="{y + 8}" width="{w}" height="18" rx="9" class="b-pista"/>'
                   f'<rect x="{izq}" y="{y + 8}" width="{largo:.1f}" height="18" rx="9" fill="{c["color"]}"/>'
                   f'<text x="{ancho}" y="{y + 21}" text-anchor="end" class="b-valor">{_e(_peso(c["gb"]))}'
                   f'<tspan class="b-pct" dx="8">{_e(_pct(c["pct"]))}</tspan></text>')
    return (f'<svg class="graf" viewBox="0 0 {ancho} {alto_f * len(filas)}" role="img" aria-label="Almacenamiento por cámara">'
            f'{"".join(out)}</svg>')


def _svg_columnas_simple(puntos, promedio, unidad="TB", ancho=700, alto=230, valores=True):
    """Columnas de un solo color (una por día o por semana), con su valor encima, la más alta resaltada y la línea del promedio
    rotulada fuera de las columnas. `puntos`: [(rótulo, gb, sub)]."""
    if not puntos:
        return ""
    izq, der, abajo, arriba = 40, 74, 38 if any(p[2] for p in puntos) else 26, 22
    h, w = alto - abajo - arriba, ancho - izq - der
    tope, paso = _escala(max(p[1] for p in puntos) / rsm.GB_POR_TB)
    n = len(puntos)
    hueco = w / n
    ancho_col = max(3.0, min(54.0, hueco * 0.64))
    mejor = max(range(n), key=lambda i: puntos[i][1])
    out = []
    k = 0.0
    while k <= tope + 1e-9:
        y = arriba + h - h * k / tope
        out.append(f'<line x1="{izq}" x2="{izq + w}" y1="{y:.1f}" y2="{y:.1f}" class="rejilla"/>'
                   f'<text x="{izq - 8}" y="{y + 4:.1f}" text-anchor="end" class="eje">{k:g}</text>')
        k += paso
    out.append(f'<text x="{izq - 8}" y="{arriba - 9}" text-anchor="end" class="eje">{unidad}</text>')
    if promedio and n > 1:                                          # la línea va debajo de las columnas y de sus cifras
        y = arriba + h - h * (promedio / rsm.GB_POR_TB) / tope
        out.append(f'<line x1="{izq}" x2="{izq + w + 6}" y1="{y:.1f}" y2="{y:.1f}" class="promedio"/>'
                   f'<text x="{izq + w + 10}" y="{y - 2:.1f}" class="promedio-t">promedio</text>'
                   f'<text x="{izq + w + 10}" y="{y + 11:.1f}" class="promedio-t fuerte">{promedio / rsm.GB_POR_TB:.2f} {unidad}</text>')
    cada = max(1, round(n / max(4, int(w / 48))))                  # los rótulos de abajo nunca se pisan, también en el teléfono
    for i, (rot, gb, sub) in enumerate(puntos):
        x = izq + hueco * i + (hueco - ancho_col) / 2
        hh = h * (gb / rsm.GB_POR_TB) / tope
        rad = min(6.0, ancho_col / 2)
        clase = "col mejor" if i == mejor and n > 1 else "col"
        out.append(f'<path d="M{x:.1f},{arriba + h:.1f} v{-max(hh - rad, 0):.1f} q0,{-rad:.1f} {rad:.1f},{-rad:.1f} h{ancho_col - 2 * rad:.1f} '
                   f'q{rad:.1f},0 {rad:.1f},{rad:.1f} v{max(hh - rad, 0):.1f} z" class="{clase}"><title>{_e(rot)}: {_e(_peso(gb))}</title></path>')
        if valores and (n <= max(5, int(w / 38)) or i == mejor):
            out.append(f'<text x="{x + ancho_col / 2:.1f}" y="{arriba + h - hh - 6:.1f}" text-anchor="middle" class="valor">'
                       f'{gb / rsm.GB_POR_TB:.2f}</text>')
        if i % cada == 0 and (n - 1 - i >= cada or i == n - 1) or i == n - 1:
            out.append(f'<text x="{x + ancho_col / 2:.1f}" y="{arriba + h + 16}" text-anchor="middle" class="eje fuerte">{_e(rot)}</text>')
            if sub and n <= max(4, int(w / 60)):
                out.append(f'<text x="{x + ancho_col / 2:.1f}" y="{arriba + h + 30}" text-anchor="middle" class="eje">{_e(sub)}</text>')
    return f'<svg class="graf" viewBox="0 0 {ancho} {alto}" role="img" aria-label="Columnas">{"".join(out)}</svg>'


def _svg_anillo(fr, centro, sub, lado=128):
    """Un anillo de avance (0 a 1) con el porcentaje en el centro."""
    import math
    r, g = lado / 2 - 10, 12
    c = 2 * math.pi * r
    fr = max(0.0, min(1.0, fr))
    return (f'<svg viewBox="0 0 {lado} {lado}" width="{lado}" height="{lado}" class="anillo" role="img" aria-label="{_e(sub)}">'
            f'<circle cx="{lado / 2}" cy="{lado / 2}" r="{r}" class="a-pista" stroke-width="{g}" fill="none"/>'
            f'<circle cx="{lado / 2}" cy="{lado / 2}" r="{r}" class="a-valor" stroke-width="{g}" fill="none" stroke-linecap="round" '
            f'stroke-dasharray="{c * fr:.1f} {c:.1f}" transform="rotate(-90 {lado / 2} {lado / 2})"/>'
            f'<text x="{lado / 2}" y="{lado / 2 + 2}" text-anchor="middle" class="a-n">{_e(centro)}</text>'
            f'<text x="{lado / 2}" y="{lado / 2 + 20}" text-anchor="middle" class="a-s">{_e(sub)}</text></svg>')


def _dos(f, *a, **k):
    """La gráfica en dos tamaños: la ancha para el computador y el PDF, la angosta para leerla bien en el teléfono."""
    angosta = dict(k, ancho=360) if f is _svg_barras_camaras else dict(k, ancho=360, alto=int(k.get("alto", 230) * 0.95))
    return f'<div class="g-ancha">{f(*a, **k)}</div><div class="g-angosta">{f(*a, **angosta)}</div>'


def _pagina_resumen(datos, logo, completo=False):
    """El reporte: lo del «Resumen General» del estadístico, solo de los días elegidos, con gráficas fáciles de leer.
    Sin cajas dentro de cajas: la página es plana y cada bloque es una sola tarjeta. `completo` (Detallado) agrega, con el mismo diseño,
    el material por tipo, cada cámara con sus rollos, todos los datos de cada día, todos los días del proyecto y cada tarjeta."""
    t, g, ant = datos["totales"], datos["general"], datos["anterior"]
    out = []
    meta = [datos["proyecto"] or "", texto_dias(datos) if t["dias"] else "", texto_semanas(datos["semanas"]),
            "generado " + datos["generado"].strftime("%d/%m/%Y %H:%M")]
    meta = [texto_dias(datos) if t["dias"] else "", "generado " + datos["generado"].strftime("%d/%m/%Y %H:%M")]
    chip_u = f'<span class="u-chip">{_e(datos["unidad"])}</span>' if datos.get("unidad") else ""
    tg = datos.get("titulo_grande") or titulo_grande(datos["titulo"])
    periodo = texto_periodo(datos["desde"], datos["hasta"]) if datos.get("semanas_rep") else datos["periodo"]   # semanas: de qué fecha a qué fecha
    periodo = periodo if periodo not in tg else ""
    out.append(f'<header class="cab portada"><div class="p-izq"><div class="p-kicker">Reporte de data management{chip_u}</div>'
               f'<div class="p-proyecto">{_e(datos.get("proyecto_bonito") or datos["proyecto"] or "Proyecto")}</div>'
               f'<h1 class="p-titulo">{_e(tg)}</h1>'
               + (f'<div class="periodo">{_e(periodo)}</div>' if periodo else "") +
               f'<div class="meta">{" · ".join(_e(x) for x in meta if x)}</div></div>{logo}</header>')
    for a in datos["avisos"]:
        out.append(f'<div class="aviso">{_e(a)}</div>')
    if datos["equipo"]:
        out.append('<div class="equipo">' + "".join(f'<div><span>{_e(k)}</span><b>{_e(v)}</b></div>' for k, v in datos["equipo"].items())
                   + "</div>")
    # ---- cifras ----
    cambio = ""
    if ant and ant["gb"] and t["dias"]:
        dif = (t["gb"] - ant["gb"]) / ant["gb"]
        cambio = f'<i class="{"sube" if dif >= 0 else "baja"}">{"▲" if dif >= 0 else "▼"} {abs(dif) * 100:.0f} % vs. {_e(ant["texto"])}</i>'
    cifras = [("Espacio OCF", f'{t["tb"]:,.2f} TB', cambio or f'<i>{t["gb"]:,.2f} GB</i>'),
              ("Días rodados", str(t["dias"]), f'<i>{_e(texto_semanas(datos["semanas"]) or datos["periodo"])}</i>'),
              ("Promedio por día", f'{t["promedio_gb"] / rsm.GB_POR_TB:,.2f} TB', f'<i>{t["promedio_gb"]:,.0f} GB</i>'),
              ("Duración", _dur(t["seg"]).replace(" h", "") + " h" if t["seg"] else "—",
               f'<i>{_num(t["clips"])} clips de video</i>' if t["clips"] else "")]
    out.append('<div class="kpis bloque">' + "".join(f'<div class="kpi"><span>{_e(a)}</span><b>{_e(b)}</b>{c}</div>'
                                                     for a, b, c in cifras) + "</div>")
    # ---- con varias unidades y «Todo»: cuánto puso cada una ----
    pu = [u for u in datos.get("por_unidad") or []]
    if pu and t["gb"]:
        filas = "".join(
            f'<div class="pu"><div class="pu-cab"><b>{_e(u["nombre"])}</b><span>{u["tb"]:,.2f} TB · {u["pct"] * 100:.1f} % · '
            f'{u["dias"]} {"día" if u["dias"] == 1 else "días"}</span></div>'
            + (f'<div class="pu-eq">' + " · ".join(f"{_e(k)}: <b>{_e(v)}</b>" for k, v in u["equipo"].items()) + "</div>"
               if u.get("equipo") else "") +
            f'<div class="pu-pista"><div class="pu-barra" style="width:{u["pct"] * 100:.1f}%"></div></div>'
            f'<div class="pu-cams">' + (" · ".join(f'<i style="background:{_e(c)}"></i>{_e(n)} {g / rsm.GB_POR_TB:,.2f} TB'
                                                     for n, g, c in u["camaras"]) or "sin material en estos días") + '</div></div>'
            for u in pu)
        out.append('<section class="tj bloque"><h2>Por unidad</h2>' + filas + "</section>")
    # ---- almacenamiento por cámara ----
    if datos["almacenamiento"] and t["gb"]:
        out.append('<section class="tj bloque"><h2>Almacenamiento por cámara</h2>' + _dos(_svg_barras_camaras, datos["almacenamiento"])
                   + f'<div class="pie-tj"><span>Espacio utilizado OCF</span><b>{t["gb"]:,.2f} GB</b></div></section>')
    if completo:
        out += _detalle_camaras(datos)
    # ---- días o semanas ----
    dias, semanas = datos["dias"], datos["por_semana"]
    muchos = len(dias) > 14 and len(semanas) > 1
    if muchos:
        prom_sem = t["gb"] / len(semanas)
        out.append('<section class="tj bloque"><h2>TB por semana</h2>'
                   + _dos(_svg_columnas_simple, [(w["nombre"].replace("Semana ", "S"), w["gb"], f'{w["dias"]} días') for w in semanas], prom_sem)
                   + "</section>")
        filas = "".join(f'<tr><td><b>{_e(w["nombre"])}</b><span class="sub ocultar-movil"> · {_e(w["primero"])}{" – " + _e(w["ultimo"]) if w["ultimo"] != w["primero"] else ""}</span></td>'
                        f'<td class="n">{w["dias"]}</td><td class="n">{_e(_peso(w["gb"]))}</td>'
                        f'<td class="n ocultar-movil">{_e(_peso(w["gb"] / w["dias"]))}</td><td class="n">{_e(rsm.hms(w["seg"]))}</td></tr>' for w in semanas)
        out.append('<section class="tj bloque"><h2>Resumen por semana</h2><table class="limpia"><thead><tr><th>Semana</th><th class="n">Días</th>'
                   '<th class="n">Total</th><th class="n ocultar-movil">Promedio/día</th><th class="n">Duración</th></tr></thead>'
                   f'<tbody>{filas}</tbody><tfoot><tr><td>Total</td><td class="n">{t["dias"]}</td><td class="n">{_e(_peso(t["gb"]))}</td>'
                   f'<td class="n ocultar-movil">{_e(_peso(t["promedio_gb"]))}</td><td class="n">{_e(rsm.hms(t["seg"]))}</td></tr></tfoot></table></section>')
        out.append('<section class="tj bloque"><h2>TB por día</h2>'
                   + _dos(_svg_columnas_simple, [(d["dia"], d["gb"], "") for d in dias], t["promedio_gb"], alto=190, valores=False)
                   + "</section>")
    elif dias:
        grafica = _dos(_svg_columnas_simple, [(d["dia"], d["gb"], texto_fecha(d["fecha"], False)) for d in dias], t["promedio_gb"]) \
            if len(dias) > 1 else ""
        filas = "".join(f'<tr><td><b>{_e(d["dia"])}</b></td><td class="n">{_e(_peso(d["gb"]))}</td>'
                        f'<td class="n">{_e(rsm.hms(d["seg"]))}</td><td class="n">{_num(d["clips"]) if d["clips"] else "—"}</td></tr>'
                        for d in dias)
        tabla = ('<table class="limpia"><thead><tr><th>Día</th><th class="n">Total</th><th class="n">Duración</th><th class="n">Clips</th></tr>'
                 f'</thead><tbody>{filas}</tbody>'
                 + (f'<tfoot><tr><td>Total</td><td class="n">{_e(_peso(t["gb"]))}</td><td class="n">{_e(rsm.hms(t["seg"]))}</td>'
                    f'<td class="n">{_num(t["clips"])}</td></tr></tfoot>' if len(dias) > 1 else "") + "</table>")
        if grafica:
            out.append('<section class="tj bloque"><h2>TB por día</h2>' + grafica + "</section>")
        if not completo:                              # en el detallado va la tabla con todos los datos de cada día
            out.append('<section class="tj bloque"><h2>' + ("Día por día" if len(dias) > 1 else "El día") + "</h2>" + tabla + "</section>")
    if completo and dias:
        out += _detalle_dias(datos)
    # ---- avance del proyecto ----
    if g["gb"]:
        anillos = ""
        if g["dias_previstos"]:
            anillos += _svg_anillo(g["dias"] / g["dias_previstos"], f'{g["dias"]}/{g["dias_previstos"]}', "días")
        if g["espacio_previsto_gb"]:
            anillos += _svg_anillo(g["gb"] / g["espacio_previsto_gb"], f'{g["gb"] / g["espacio_previsto_gb"] * 100:.0f} %', "espacio")
        lista = [("Total días de rodaje", str(g["dias_previstos"]) if g["dias_previstos"] else "—"), ("Días rodados", str(g["dias"])),
                 ("Promedio por día", _peso(g["promedio_gb"])), ("Espacio utilizado OCF", f'{g["gb"]:,.2f} GB'),
                 ("Espacio aprox. total", f'{g["espacio_previsto_gb"]:,.2f} GB' if g["espacio_previsto_gb"] else "—")]
        sem = f' · {_e(nombre_semana(g["semana"]))}' if g["semana"] else ""
        out.append(f'<section class="tj bloque"><h2>Avance del proyecto <small>hasta el {_e(texto_fecha(datos["hasta"]))}{sem}</small></h2>'
                   f'<div class="avance2"><div class="anillos">{anillos}</div><dl>'
                   + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in lista) + "</dl></div></section>")
        if completo and len(g["filas"]) > 1:
            out.append('<section class="tj bloque"><h2>Todo el proyecto, día por día <small>GB de cada día; en verde, los días de este reporte</small></h2>'
                       + _svg_linea(g["filas"], datos["elegidos"]) + "</section>")
            out.append('<section class="tj"><h2>Almacenamiento y tiempo rodado <small>todos los días del proyecto</small></h2>'
                       + _tabla_dias(g["filas"], datos["elegidos"]) + "</section>")
    # ---- formato ----
    if datos["formato"]:
        out.append('<div class="formato bloque"><span class="f-t">Formato de grabación</span>'
                   + "".join(f'<span class="chip"><i>{_e(k)}</i> {_e(v)}</span>' for k, v in datos["formato"]) + "</div>")
    if completo:
        out += _detalle_tarjetas(datos)
    return out


def _detalle_camaras(datos):
    """Detallado: el material por tipo (cámaras, sonido, drones…) y cada cámara con sus rollos."""
    out = []
    if datos["tipos"]:
        cajas = ""
        for g in datos["tipos"]:
            filas = [("Tamaño", _peso(g["gb"])), ("Clips", _num(g["clips"]) if g["clips"] else "—"),
                     ("Tarjetas", _num(g["tarjetas"]) if g["tarjetas"] else "—"), ("Duración", _dur(g["seg"]) if g["seg"] else "—"),
                     ("Cámaras" if g["clave"] == "camara" else "Equipos", str(g["equipos"]))]
            cajas += (f'<div class="tipo"><h3>{_e(g["nombre"])}</h3><dl>'
                      + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in filas) + "</dl></div>")
        out.append(f'<section class="tj bloque"><h2>Material por tipo</h2><div class="tipos">{cajas}</div></section>')
    cams = [c for c in datos["camaras"] if c["gb"] > 0]
    if cams:
        filas = "".join(f'<tr><td><span class="cam"><i style="background:{c["color"]}"></i>{_e(c["nombre"])}</span>'
                        f'{f"<br><span class=sub>{_e(c["modelo"])}</span>" if c["modelo"] else ""}</td>'
                        f'<td class="ocultar-movil">{_e(c["rollos"]) or "—"}</td><td class="n">{_num(c["tarjetas"]) if c["tarjetas"] else "—"}</td>'
                        f'<td class="n">{_num(c["clips"]) if c["clips"] else "—"}</td><td class="n ocultar-movil">{_e(_dur(c["seg"])) if c["seg"] else "—"}</td>'
                        f'<td class="n">{_e(_peso(c["gb"]))}</td></tr>' for c in cams)
        t = datos["totales"]
        out.append('<section class="tj bloque"><h2>Cámaras y rollos</h2><table class="limpia"><thead><tr><th>Cámara</th>'
                   '<th class="ocultar-movil">Rollos</th><th class="n">Tarjetas</th><th class="n">Clips</th><th class="n ocultar-movil">Duración</th>'
                   f'<th class="n">Tamaño</th></tr></thead><tbody>{filas}</tbody><tfoot><tr><td>Total</td><td class="ocultar-movil"></td>'
                   f'<td class="n">{_num(sum(c["tarjetas"] for c in cams))}</td><td class="n">{_num(sum(c["clips"] for c in cams))}</td>'
                   f'<td class="n ocultar-movil">{_e(_dur(sum(c["seg"] for c in cams)))}</td><td class="n">{_e(_peso(t["gb"]))}</td></tr></tfoot>'
                   "</table></section>")
    return out


def _detalle_dias(datos):
    """Detallado: cada día elegido con todos sus datos."""
    t = datos["totales"]
    filas = "".join(f'<tr><td><b>{_e(d["dia"])}</b> <span class="sub">{_e(texto_fecha(d["fecha"], False))}</span></td>'
                    f'<td class="n">{_num(d["tarjetas"]) if d["tarjetas"] else "—"}</td><td class="n">{_num(d["clips"]) if d["clips"] else "—"}</td>'
                    f'<td class="n ocultar-movil">{_num(d["clips_audio"]) if d["clips_audio"] else "—"}</td>'
                    f'<td class="n">{_e(rsm.hms(d["seg"]))}</td><td class="n">{_e(_peso(d["gb"]))}</td></tr>' for d in datos["dias"])
    return ['<section class="tj"><h2>Día por día</h2><table class="limpia"><thead><tr><th>Día</th><th class="n">Tarjetas</th>'
            '<th class="n">Clips video</th><th class="n ocultar-movil">Clips audio</th><th class="n">Duración</th><th class="n">Tamaño</th></tr></thead>'
            f'<tbody>{filas}</tbody><tfoot><tr><td>Total</td><td class="n">{_num(t["tarjetas"])}</td><td class="n">{_num(t["clips"])}</td>'
            f'<td class="n ocultar-movil">{_num(t["clips_audio"])}</td><td class="n">{_e(rsm.hms(t["seg"]))}</td>'
            f'<td class="n">{_e(_peso(t["gb"]))}</td></tr></tfoot></table></section>']


def _detalle_tarjetas(datos):
    """Detallado: cada tarjeta (BIN) de cada día elegido."""
    if not any(any(x["bin"] for x in d["lista"]) for d in datos["dias"]):
        return []
    out = ['<h2 class="seccion">Detalle de tarjetas</h2>']
    for d in datos["dias"]:
        filas = "".join(f'<tr><td><span class="cam"><i style="background:{x["color"]}"></i>{_e(x["bin"])}</span></td>'
                        f'<td class="ocultar-movil">{_e(x["camara"])}</td><td class="ocultar-movil">{_e(x["modelo"]) or "—"}</td>'
                        f'<td class="n ocultar-movil">{x["mag"] if x["mag"] is not None else "—"}</td>'
                        f'<td class="n">{_num(x["clips"]) if x["clips"] else "—"}</td>'
                        f'<td class="n">{_e(_dur(x["seg"])) if x["seg"] else "—"}</td><td class="n">{_e(_peso(x["gb"]))}</td></tr>' for x in d["lista"])
        out.append(f'<section class="tj bloque"><h2>{_e(d["dia"])} <small>{_e(texto_fecha(d["fecha"]))} · {_num(len(d["lista"]))} tarjetas · '
                   f'{_e(_peso(d["gb"]))}</small></h2><table class="limpia"><thead><tr><th>Tarjeta (BIN)</th><th class="ocultar-movil">Cámara</th>'
                   '<th class="ocultar-movil">Modelo</th><th class="n ocultar-movil"># Mag</th><th class="n">Clips</th><th class="n">Duración</th>'
                   f'<th class="n">Tamaño</th></tr></thead><tbody>{filas}</tbody></table></section>')
    return out


def nombre_semana(marca):
    """Lo que dice la columna SEMANA del estadístico, para leer: «1 PILOTO» → «Piloto», «8» → «Semana 8»."""
    t = str(marca or "").strip()
    if not t:
        return ""
    if "pilot" in t.lower():
        return "Piloto"
    return f"Semana {t}" if re.fullmatch(r"\d+", t) else t


def texto_semanas(semanas):
    """«Semana 8», «Semanas 7 y 8», «Piloto a Semana 9»."""
    n = [nombre_semana(x) for x in semanas]
    if not n:
        return ""
    if len(n) == 1:
        return n[0]
    a, b = n[0], n[-1]
    nums = [x[7:] for x in n if x.startswith("Semana ")]
    if len(nums) == len(n) and all(x.isdigit() for x in nums):
        k = [int(x) for x in nums]
        if len(k) == 2:
            return f"Semanas {k[0]} y {k[1]}"
        if k == list(range(k[0], k[0] + len(k))):
            return f"Semanas {k[0]} a {k[-1]}"
        return "Semanas " + ", ".join(map(str, k[:-1])) + f" y {k[-1]}"
    if len(n) == 2:
        return f"{a} y {b}"
    return f"{a} a {b}"


_MINUSCULAS = {"de", "del", "la", "el", "los", "las", "y", "en", "a", "con", "por", "para", "un", "una", "e", "o"}


def proyecto_bonito(nombre):
    """El nombre del proyecto para la portada: «PRIMERA PLANA - HIJO DE TIGRE» → «Primera Plana · Hijo de Tigre»; las siglas cortas
    (HDT, AAZ, CODT) y los nombres escritos a gusto (con minúsculas) se dejan como están."""
    partes = [x.strip() for x in re.split(r"\s+[-–—|]\s+|_", str(nombre or "")) if x.strip()]

    def una(t):
        if t != t.upper() or len(t.replace(" ", "")) <= 5:
            return t
        palabras = t.lower().split()
        return " ".join(w if (k and w in _MINUSCULAS) else (w[:1].upper() + w[1:]) for k, w in enumerate(palabras))
    return " · ".join(una(x) for x in partes)


def titulo_grande(titulo):
    """El título para leer en grande: «de todo el proyecto» → «Todo el proyecto», «del 13 al 16 oct 2026» → «Del 13 al 16 oct 2026»."""
    t = re.sub(r"^de todo", "todo", str(titulo or "").strip())
    return t[:1].upper() + t[1:]


def a_html(datos, modo="claro", logos=None, barra=True, completo=False):
    """La página del reporte. `modo`: «claro» u «oscuro» (se puede cambiar después con los botones de arriba, que no salen al imprimir).
    `logos`: {"claro": src, "oscuro": src} (data: URI o ruta); sin logos, se pone el nombre FilmFlow en texto.
    `barra`: los botones de arriba (Claro/Oscuro/Imprimir); se quitan para hacer el PDF.
    `completo`: False = el resumen corto (como el «Resumen General» del estadístico, solo con los días elegidos);
    True = además el detalle (por cámara, por día, tarjeta por tarjeta y todos los días del proyecto)."""
    out = []
    if barra:
        out.append('<div class="barra"><button data-t="claro" onclick="tema(\'claro\')">Claro</button>'
                   '<button data-t="oscuro" onclick="tema(\'oscuro\')">Oscuro</button>'
                   '<button onclick="window.print()">Imprimir o guardar PDF</button></div>')
    if logos and not barra:                       # sin botones no se cambia de claro a oscuro: basta el logo de ese modo
        k = "oscuro" if modo == "oscuro" else "claro"
        logos = {k: logos.get(k)} if logos.get(k) else logos
    if logos:
        logo = "".join(f'<img class="logo {k}" src="{_e(v)}" alt="FilmFlow">' for k, v in logos.items() if v)
    else:
        logo = '<b style="font-size:20px;letter-spacing:3px;color:var(--verde)">FILMFLOW</b>'
    out.append('<div class="hoja plano">')
    out += _pagina_resumen(datos, logo, completo)
    fuente = {"FO-06": "estatus de tarjetas (FO-06)", "FO-07": "estadístico (FO-07)"}.get(datos["fuente"], "tus hojas")
    out.append(f'<footer><span>Estadístico FilmFlow · datos de tu {_e(fuente)} · 1 TB = 1.000 GB</span>'
               f'<span>{_e(datos.get("proyecto_bonito") or datos["proyecto"])}</span></footer></div>')
    nombre = f'Reporte {datos["titulo"]} · {datos["proyecto"]}'
    return (f'<!doctype html><html lang="es" data-tema="{"oscuro" if modo == "oscuro" else "claro"}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(nombre)}</title>'
            f'<style>{CSS}</style><script>{JS}</script></head><body onload="tema(document.documentElement.dataset.tema);botones()">'
            f'{"".join(out)}</body></html>')
