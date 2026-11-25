"""Correo de data management: arma el texto del correo del día a partir del reporte PDF y la configuración del proyecto.

Sin pantalla (Tk): se puede probar sola. La pestaña «Correo» de la app solo muestra y copia lo que sale de aquí.
Todo lo que cambia entre proyectos (cómo se escribe el día, el asunto, si se detalla por cámara, GB o TB…) está en `opciones`
y se guarda por proyecto; lo demás sale del reporte.
"""
import html
import re

import registro_core as rc

# ---- cómo se escribe el día y el asunto: cada estilo se muestra con un ejemplo en la pantalla ----
FRASE_VERIFICACION = "LA DESCARGA DE TODO EL MATERIAL SE GENERÓ CON ÉXITO A LOS DISCOS DESTINADOS POR MEDIO DE VERIFICACIÓN XXHASH128."


# ---------------------------------------------------------------- nombres de rollo
_ROLLO = re.compile(r"^([A-Za-z]+)_?(\d+)(.*)$")


def nombre_de_rollo(bin_):
    """El nombre corto con el que se nombra un rollo en el correo.
    A_0115_1EOH_hde -> A0115 · A011CJXD_CINE -> A011 · M020L -> M020L (una letra suelta al final se conserva) · M_001_110_01_01 -> M001."""
    m = _ROLLO.match(bin_.strip())
    if not m:
        return bin_.strip()
    letras, numero, cola = m.groups()
    if re.fullmatch(r"[A-Za-z]", cola):
        return f"{letras.upper()}{numero}{cola.upper()}"
    return f"{letras.upper()}{numero}"


def _orden_natural(texto):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", texto)]


def rango_de_rollos(rollos):
    """['A129','A130'] -> 'A129 AL A130' · ['A011'] -> 'A011'."""
    unicos = sorted(set(rollos), key=_orden_natural)
    if not unicos:
        return ""
    return unicos[0] if len(unicos) == 1 else f"{unicos[0]} AL {unicos[-1]}"


def etiqueta_de_camara(grupo, rollos):
    """CAM A, CAM L… Si los rollos son tipo M020L / M021L, la etiqueta es la letra final (L); si no, la letra de la cámara."""
    finales = {m.group(3) for m in (re.fullmatch(r"([A-Z]+)(\d+)([A-Z])", r) for r in rollos) if m}
    if len(finales) == 1 and all(re.fullmatch(r"[A-Z]+\d+[A-Z]", r) for r in rollos):
        return "CAM " + finales.pop()
    letra = rc.letra_de_camara(grupo["patrones"])
    if letra:
        return "CAM " + letra
    for r in rollos:
        m = re.match(r"[A-Z]+", r)
        if m:
            return "CAM " + m.group(0)
    nombre = re.sub(r"^c[áa]mara\s+", "", grupo["nombre"], flags=re.I).strip()
    return "CAM " + nombre.upper()


# ---------------------------------------------------------------- datos del día
def _suma(bins):
    return {"clips": sum(b["clips"] for b in bins), "seg": sum(b["seg"] for b in bins), "gb": round(sum(b["gb"] for b in bins), 2)}


def datos_del_correo(reporte, cfg):
    """Todo lo que el correo necesita saber del día, ya ordenado. No escribe nada en ningún lado."""
    if not reporte.get("dia"):
        raise rc.ErrorRegistro(f"Este reporte (solo sonido) no dice qué día de rodaje es, solo la fecha {reporte['fecha']:%d/%m/%Y}. "
                               "Para el correo usa el reporte del día (el que trae las cámaras): ese sonido ya viene incluido en él.")
    por_grupo, sin = rc.clasificar(reporte, cfg)
    sonido_ids = {g["id"] for g in cfg["grupos"] if rc.grupo_es_sonido(g)}
    audio = [b for b in reporte["bins"] if b.get("audio") or any(b in por_grupo.get(i, []) for i in sonido_ids)]
    ids_audio = {id(b) for b in audio}
    camaras = []
    for g in cfg["grupos"]:
        bins = [b for b in por_grupo.get(g["id"], []) if id(b) not in ids_audio]
        if not bins or g["id"] in sonido_ids:
            continue
        rollos = [nombre_de_rollo(b["nombre"]) for b in bins]
        camaras.append({"grupo": g["nombre"], "rollos": sorted(set(rollos), key=_orden_natural), "rango": rango_de_rollos(rollos),
                        "modelo": (g.get("modelo") or "").strip(), "etiqueta": etiqueta_de_camara(g, rollos), **_suma(bins)})
    video_bins = [b for b in reporte["bins"] if id(b) not in ids_audio]
    totales = reporte.get("totales") or {}
    return {
        "dia": int(reporte["dia"][1:]), "fecha": reporte["fecha"], "unidad": reporte.get("unidad") or 1, "carpeta_con_unidad": reporte.get("carpeta_con_unidad", False),
        "camaras": camaras, "sin_reconocer": [b["nombre"] for b in sin if id(b) not in ids_audio],
        "video": totales.get("video") or _suma(video_bins), "audio": totales.get("audio") or _suma(audio),
        "sonido": sorted({b["nombre"] for b in audio}, key=_orden_natural),
        "hay_audio": bool(audio),
    }


# ---------------------------------------------------------------- estilos por proyecto (aprendidos de los correos enviados)
# Cada proyecto escribe su correo con pequeñas diferencias. Estos son los de los proyectos ya enviados; un proyecto nuevo usa el «general».
#   dia: cómo se escribe el día en el cuerpo · asunto_dia: DAY### o DAY_### · report: REPORTE / REPORT · unidad_asunto: dónde va _U#
#   (None = no se pone, "fin" = al final, "inicio" = tras el prefijo; "siempre" = también en la unidad 1) · saludo/cierre/nota_antes/hora_con_cero/rotulo_sonido
ESTILO_GENERAL = {"clave": "", "prefijo": None, "dia": "{Y}{m}{d}_DAY{n}", "asunto_dia": "DAY{n}", "report": "REPORTE",
                  "unidad_asunto": "fin", "unidad_siempre": False, "unidad_solo_u2": False, "saludo": "Hola a todos,", "entrada": "rollos:", "hora_con_cero": True,
                  "rotulo_sonido": "Rollos de Sonido", "sep_sonido": ": ", "cierre": "", "nota_antes": True, "firma": "Saludos."}
ESTILOS = [
    ("PRIMERA PLANA", {"clave": "PP", "prefijo": "PP", "unidad_solo_u2": True, "dia": "DAY{n}_{Y}_{m}_{d}", "rotulo_sonido": "Rollos de Sonido", "sep_sonido": " "}),
    ("CASAMENTERA", {"clave": "LC", "prefijo": "LC", "dia": "DAY{n}", "report": "REPORT", "hora_con_cero": False, "sep_sonido": " : "}),
    ("DESMADRE", {"clave": "DSMD", "prefijo": "DSMD", "asunto_dia": "DAY_{n}", "unidad_asunto": "inicio", "unidad_siempre": True,
                  "entrada": ":", "rotulo_sonido": "Rollo de sonido", "cierre": "Muchas gracias, buena noche para todos.", "nota_antes": False}),
    ("REINA DEL SUR", {"clave": "LRDS4", "prefijo": "LRDS4", "dia": "{Y}{m}{d}_Day{n}", "asunto_dia": "DAY_{n}", "unidad_asunto": "inicio",
                       "unidad_siempre": True, "u1_cuerpo": "MU", "saludo_otras": "Buenas noches."}),
    ("MICROHISTORIAS", {"clave": "MH", "prefijo": "MICROHISTORIAS_MGF", "dia": "{Y}{m}{d}_DAY_{n}", "asunto_dia": "DAY_{n}", "saludo": "Hola a todos.",
                        "entrada": ":", "rotulo_sonido": "Rollo de Sonido", "cierre": "Muchas gracias, buena noche para todos.", "unidad_asunto": None}),
]


def estilo_de(proyecto, prefijo_guardado=""):
    """El estilo de correo de este proyecto: por su nombre (o por el prefijo que la persona ya usa); si no se conoce, el general."""
    clave = re.sub(r"[^A-Z0-9]+", " ", (proyecto or "").upper())
    pref = (prefijo_guardado or "").upper()
    for palabra, est in ESTILOS:
        if palabra in clave or (pref and pref == est["prefijo"]):
            return {**ESTILO_GENERAL, **est}
    return dict(ESTILO_GENERAL)


# ---------------------------------------------------------------- opciones (las decide la app; nadie las configura)
def _parece_fecha(nombre):
    return bool(re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{1,2}", nombre))


def opciones_automaticas(proyecto, datos, guardado=None):
    """Cómo se arma el correo, decidido solo a partir del PDF y del proyecto:
    - día en el cuerpo: la fecha real + DAY### (+ _U# si la carpeta de Silverstack lo traía);
    - si las cámaras de un mismo equipo se distinguen por la letra final (M020L / M020R), se detalla por cámara y se suma el total;
    - el rollo de sonido se nombra por fecha (26Y10M13) cuando el BIN de audio se llama como una fecha (10-OCT-09), si no, como dice el PDF;
    - el prefijo del asunto es el que la persona ya usó para este proyecto (se aprende al corregir el asunto) o, si no, el nombre del proyecto."""
    guardado = guardado or {}
    est = estilo_de(proyecto, guardado.get("prefijo"))
    prefijo = guardado.get("prefijo") or est["prefijo"] or re.sub(r"[^A-Za-z0-9]+", "_", (proyecto or "").strip()).strip("_").upper()
    por_letra = len(datos["camaras"]) >= 2 and all(re.fullmatch(r"[A-Z]+\d+[A-Z]", r) for c in datos["camaras"] for r in c["rollos"])
    return {"prefijo": prefijo, "proyecto": (proyecto or "").strip(), "con_unidad": (datos["unidad"] > 1) if est["unidad_solo_u2"] else (bool(datos.get("carpeta_con_unidad")) or est["unidad_siempre"]),
            "por_camara": por_letra, "total_final": por_letra, "estilo": est,
            "sonido_por_fecha": bool(datos["sonido"]) and all(_parece_fecha(n) for n in datos["sonido"]),
            "unidad_video": "auto", "hora_con_cero": est["hora_con_cero"], "rotulo_sonido": est["rotulo_sonido"], "firma": est["firma"]}


def prefijo_de_asunto(asunto_):
    """Lo que la persona dejó antes de «_REPORTE_DATA_MANAGEMENT» (o «_REPORT_…»): así se recuerda el prefijo de cada proyecto."""
    m = re.match(r"^(.*?)_?REPORTE?_DATA_MANAGEMENT", asunto_.strip(), re.I)
    return re.sub(r"_U\d+$", "", m.group(1).strip("_ "), flags=re.I) if m else ""   # «DSMD_U1» -> «DSMD»: la unidad la pone la app


# ---------------------------------------------------------------- formatos
def texto_de_dia(datos, con_unidad=False, estilo=None):
    est = estilo or ESTILO_GENERAL
    f, n, u = datos["fecha"], datos["dia"], datos["unidad"]
    t = est["dia"].format(Y=f"{f:%Y}", m=f"{f:%m}", d=f"{f:%d}", n=f"{n:03d}")
    if not con_unidad:
        return t
    return t + ("_" + est["u1_cuerpo"] if u == 1 and est.get("u1_cuerpo") else f"_U{u}")


def asunto(opciones, datos):
    est = opciones.get("estilo") or ESTILO_GENERAL
    f, n, u = datos["fecha"], datos["dia"], datos["unidad"]
    pref = (opciones["prefijo"] or "").strip("_ ")
    unidad = f"U{u}" if est["unidad_asunto"] and (u > 1 or est["unidad_siempre"] or (datos.get("carpeta_con_unidad") and not est["unidad_solo_u2"])) else ""
    partes = [pref]
    if unidad and est["unidad_asunto"] == "inicio":
        partes.append(unidad)
    partes += [est["report"], "DATA", "MANAGEMENT", est["asunto_dia"].format(n=f"{n:03d}"), f"{f:%Y%m%d}"]
    if unidad and est["unidad_asunto"] == "fin":
        partes.append(unidad)
    return "_".join(x for x in partes if x)


def hora(seg, con_cero=True):
    seg = int(round(seg))
    h, m, s = seg // 3600, seg % 3600 // 60, seg % 60
    return f"{h:02d}:{m:02d}:{s:02d} h" if con_cero else f"{h}:{m:02d}:{s:02d} h"


def peso(gb, unidad="auto"):
    if unidad == "TB" or (unidad == "auto" and gb >= 1000):
        return f"{gb / 1000:.2f} TB"
    return f"{gb:,.2f} GB".replace(",", "")


def nombre_del_sonido(datos, opciones):
    if opciones["sonido_por_fecha"]:
        f = datos["fecha"]
        return f"{f:%y}Y{f:%m}M{f:%d}"
    return ", ".join(datos["sonido"])


# ---------------------------------------------------------------- el correo
def armar(datos, opciones, nota=""):
    """{'asunto', 'lineas'}: cada línea es una lista de (texto, negrita). Las líneas vacías son [] ."""
    o = opciones
    est = o.get("estilo") or ESTILO_GENERAL
    L = []

    def linea(*partes):
        L.append([(t, b) for t, b in partes])

    def vacia(n=1):
        for _ in range(n):
            L.append([])

    linea((est.get("saludo_otras") if datos["unidad"] > 1 and est.get("saludo_otras") else est["saludo"], False))
    vacia()
    dia = texto_de_dia(datos, o["con_unidad"], est)
    linea(("Adjunto los reportes de data management correspondientes al ", False), (dia, True),
          (" del proyecto ", False), (o["proyecto"], True), ((" " if est["entrada"].startswith("r") else "") + est["entrada"], False))
    vacia()
    for c in datos["camaras"]:
        etiqueta = c["etiqueta"]
        modelo = f" ({c['modelo'].upper()})" if c["modelo"] else ""
        linea((f"{etiqueta}: {c['rango']}{modelo}", True))
    if datos["camaras"]:
        vacia()
    if o["por_camara"]:
        for c in datos["camaras"]:
            linea((c["etiqueta"], True))
            linea(("Video clips: ", False), (str(c["clips"]), True))
            linea(("TRT: ", False), (hora(c["seg"], o["hora_con_cero"]), True))
            linea(("Video Storage: ", False), (peso(c["gb"], o["unidad_video"]), True))
            vacia()
        v = datos["video"]
        linea(("Total Video clips: ", False), (str(v["clips"]), True))
        linea(("Total Video Storage: ", False), (peso(v["gb"], o["unidad_video"]), True))
    else:
        v = datos["video"]
        linea(("Video clips: ", False), (str(v["clips"]), True))
        linea(("TRT: ", False), (hora(v["seg"], o["hora_con_cero"]), True))
        linea(("Total Video Storage: ", False), (peso(v["gb"], o["unidad_video"]), True))
    if datos["hay_audio"]:
        vacia()
        linea((o["rotulo_sonido"] + est["sep_sonido"], False), (nombre_del_sonido(datos, o), True))
        vacia()
        a = datos["audio"]
        linea(("Audio clips: ", False), (str(a["clips"]), True))
        linea(("TAR: ", False), (hora(a["seg"], o["hora_con_cero"]), True))
        linea(("Total Audio Storage: ", False), (peso(a["gb"], "GB"), True))
    if o["total_final"]:
        vacia()
        linea(("Total Storage: ", True), (peso(datos["video"]["gb"] + datos["audio"]["gb"], o["unidad_video"]), True))
    notas = [t.strip() for t in (nota or "").splitlines() if t.strip()]

    def poner_nota():
        vacia()
        for n_, t in enumerate(notas):
            linea(("NOTA: " if n_ == 0 else "", True), (t, False))

    if notas and est["nota_antes"]:                    # la nota del día (no se guarda: es de este correo)
        poner_nota()
    vacia()
    linea((FRASE_VERIFICACION, True))
    if est["cierre"]:
        vacia()
        linea((est["cierre"], False))
    if o["firma"].strip():
        vacia()
        linea((o["firma"].strip(), False))
    if notas and not est["nota_antes"]:
        poner_nota()
    return {"asunto": asunto(o, datos), "lineas": L}


def a_texto(lineas):
    return "\n".join("".join(t for t, _b in l) for l in lineas)


def a_html(lineas):
    """El correo con las negritas, para pegarlo tal cual en Gmail. Cada línea es un <div>; las vacías, un salto."""
    filas = []
    for l in lineas:
        if not l:
            filas.append('<div style="font-size:7px;line-height:9px"><br></div>')       # línea vacía más baja: el correo queda compacto
            continue
        filas.append('<div style="margin:0;line-height:1.3">' + "".join(f"<b>{html.escape(t)}</b>" if b else html.escape(t) for t, b in l if t) + "</div>")
    return "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.3\">" + "".join(filas) + "</div>"


# =============================================================================
# ENVIAR el correo desde la app (Gmail): quién puede, a quién (por proyecto), adjuntos y firma
# =============================================================================
# Por ahora solo la cuenta de la empresa puede enviar desde la app; las demás (invitados, otros correos) copian asunto y texto.
AUTORIZADOS_ENVIO = ("datacol@filmflowtv.com",)
PERMISO_ENVIAR = "https://www.googleapis.com/auth/gmail.send"      # solo ENVIAR (la app no puede leer tu correo)
URL_ENVIAR = "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send?uploadType=media"
LIMITE_ADJUNTOS = 25 * 1000 * 1000          # lo que Gmail deja adjuntar (25 MB)
_CORREO_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def puede_enviar(correo):
    """¿Esta cuenta puede enviar el correo desde la app?"""
    return (correo or "").strip().lower() in AUTORIZADOS_ENVIO


def separar_correos(texto):
    """Lo que la persona pegó (uno por línea, o separados por coma/punto y coma; también «Nombre <correo>» como los copia Gmail)
    → (lista de correos válidos sin repetir, lista de lo que no parece un correo)."""
    validos, malos, vistos = [], [], set()
    for trozo in re.split(r"[,;\n]+", texto or ""):
        t = trozo.strip().strip('"').strip()
        if not t:
            continue
        m = re.search(r"<([^<>]+)>\s*$", t)
        nombre = t[:m.start()].strip().strip('"').strip() if m else ""
        correo = (m.group(1) if m else t).strip().strip('"')
        if not _CORREO_RE.match(correo):
            malos.append(t)
            continue
        if correo.lower() in vistos:
            continue
        vistos.add(correo.lower())
        if nombre and nombre.lower() != correo.lower():
            nombre = f'"{nombre}"' if re.search(r'[,;<>"@()\[\]:\\]', nombre) else nombre
            validos.append(f"{nombre} <{correo}>")
        else:
            validos.append(correo)
    return validos, malos


def sin_repetir(cc, para):
    """CC sin los correos que ya van en «Para» (Gmail los mandaría dos veces)."""
    ya = {solo_correo(x).lower() for x in para or []}
    return [x for x in cc or [] if solo_correo(x).lower() not in ya]


def solo_correo(direccion):
    m = re.search(r"<([^<>]+)>", direccion or "")
    return (m.group(1) if m else direccion or "").strip()


def limpiar_firma(h):
    """La firma tal como viene de Gmail (HTML pegado), sin nada que pueda ejecutar código. Las imágenes siguen siendo las de Gmail."""
    h = h or ""
    h = re.sub(r"(?is)<(script|style|iframe|object|embed|form|meta|link)\b.*?(</\1\s*>|$)", "", h)
    h = re.sub(r"(?is)<(script|iframe|object|embed|meta|link)\b[^>]*>", "", h)
    h = re.sub(r"""(?i)\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", "", h)
    h = re.sub(r"""(?i)(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2""", r'\1="#"', h)
    h = re.sub(r'\s+(data-aii|data-os)="[^"]*"', "", h)
    return h.strip()


def texto_de_firma(h):
    """La firma en texto simple (para la parte de texto del correo)."""
    t = re.sub(r"(?i)<br\s*/?>|</div>|</p>", "\n", h or "")
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\u200b", "")
    return "\n".join(x.strip() for x in t.splitlines() if x.strip())


def html_para_enviar(html_cuerpo, firma_html=None):
    """El cuerpo como lo arma la app (el mismo de «Copiar») + la firma elegida (igual que Gmail: «-- » y la firma)."""
    firma = (f'<br><div dir="ltr" class="gmail_signature">-- <br>{limpiar_firma(firma_html)}</div>' if firma_html else "")
    return f"<!doctype html><html><body>{html_cuerpo}{firma}</body></html>"


def armar_mime(de, para, cc, asunto_, texto, html_cuerpo, adjuntos=(), firma_html=None, cco=()):
    """El correo completo (texto + HTML + adjuntos) listo para Gmail. `adjuntos`: [(nombre, tipo_mime, bytes)]."""
    from email.message import EmailMessage
    from email import policy
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = de
    msg["To"] = ", ".join(para)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if cco:                                        # copia oculta: Gmail se lo entrega y quita este renglón antes de que llegue
        msg["Bcc"] = ", ".join(cco)
    msg["Subject"] = asunto_
    tf = texto_de_firma(firma_html) if firma_html else ""
    msg.set_content((texto or "") + (f"\n\n-- \n{tf}\n" if tf else ""))
    msg.add_alternative(html_para_enviar(html_cuerpo, firma_html), subtype="html")
    for nombre, tipo, datos in adjuntos:
        principal, _, secundario = (tipo or "application/octet-stream").partition("/")
        msg.add_attachment(datos, maintype=principal or "application", subtype=secundario or "octet-stream", filename=nombre)
    return msg.as_string()


def cortes_de_adjuntos(mime):
    """Dónde empieza cada adjunto dentro del correo armado (para mostrar cuál se está enviando)."""
    return [m.start() for m in re.finditer(r"(?im)^Content-Disposition: attachment", mime)]
