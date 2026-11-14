#!/usr/bin/env python3
"""
REGISTRO DIARIO - LÓGICA (sin ventanas y sin conexión a Google)
===============================================================
Aquí está "el cerebro": lee tu configuración (config_registro.json), reconoce
qué es cada nombre del PDF, arma el bloque del día con las reglas de siempre,
compara contra el PDF y prepara las instrucciones para escribir en Google Sheets.

Usa registro_diario.py TAL CUAL (solo para leer el PDF). No lo modifica.
"""
import copy
import json
import os
import functools
import re
import shutil
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

import registro_diario as rd

ASSETS = Path(__file__).resolve().parent      # archivos que vienen con el programa (logos, configuración inicial)


def _carpeta_de_datos():
    """Dónde se guardan tu configuración y tu sesión de Google.
    Como programa instalado (.app): en «Library/Application Support/Estadistico FilmFlow», para que no se pierdan
    al actualizar el programa. Como script suelto: en la misma carpeta de siempre."""
    import os
    forzada = os.environ.get("FILMFLOW_DATOS")
    if forzada:
        return Path(forzada).expanduser()
    if getattr(sys, "frozen", False) or ".app/Contents" in str(ASSETS):
        return Path.home() / "Library" / "Application Support" / "Estadistico FilmFlow"
    return ASSETS


CARPETA = _carpeta_de_datos()
if CARPETA != ASSETS:                              # primera vez: copiar la configuración y la llave de ejemplo
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        for _nombre in ("config_registro.json", "credenciales.json"):
            if (ASSETS / _nombre).exists() and not (CARPETA / _nombre).exists():
                shutil.copy2(ASSETS / _nombre, CARPETA / _nombre)
    except OSError:
        pass
RUTA_CONFIG = CARPETA / "config_registro.json"
PRIMERA_FILA = 7          # primera fila de datos de tu hoja
COLUMNAS = 10             # A..J
GB_POR_UNIDAD = rd.GB_POR_UNIDAD


class ErrorRegistro(Exception):
    """Un problema que se le explica a la persona en lenguaje simple."""


# =============================================================================
# 1. CONFIGURACIÓN
# =============================================================================
def validar_config(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get("grupos"), list):
        raise ErrorRegistro("La configuración está dañada (no encuentro la lista de grupos).")
    cfg.setdefault("hoja", {})
    cfg["hoja"].setdefault("enlace", "")
    cfg["hoja"].setdefault("pestana", "")
    ids = set()
    for g in cfg["grupos"]:
        for campo in ("id", "nombre", "patrones", "rental", "modelo"):
            if campo not in g:
                raise ErrorRegistro(f"A un grupo de la configuración le falta el dato «{campo}».")
        if g["id"] in ids:
            raise ErrorRegistro(f"El grupo «{g['id']}» está repetido en la configuración.")
        ids.add(g["id"])
        if isinstance(g["patrones"], str):
            g["patrones"] = [g["patrones"]]
        g["patrones"] = [p.strip() for p in g["patrones"] if str(p).strip()]
        if not g["patrones"]:
            raise ErrorRegistro(f"El grupo «{g['nombre']}» no tiene cómo reconocer sus nombres.")
        g.setdefault("ciclo_mag", None)
        if g["ciclo_mag"] in ("", 0):
            g["ciclo_mag"] = None
        g.setdefault("color", "")
        if g["color"] and not (isinstance(g["color"], str) and re.match(r"^#[0-9A-Fa-f]{6}$", g["color"])):
            raise ErrorRegistro(f"El color de «{g['nombre']}» no es válido (debe verse como #E24A38).")
        g.setdefault("avisar_si_falta", False)
    return cfg


def _config_vacia():
    return {"activo": "Mi proyecto",
            "proyectos": {"Mi proyecto": {"hoja": {"enlace": "", "pestana": ""}, "grupos": []}}}


def _migrar(data):
    """Acepta el formato anterior (una sola hoja y sus grupos) y lo convierte."""
    if isinstance(data, dict) and isinstance(data.get("proyectos"), dict) and data["proyectos"]:
        for nombre, p in list(data["proyectos"].items()):          # un proyecto a medias (sin hoja o sin rollos) se completa en vez de romper la app
            if not isinstance(p, dict):
                data["proyectos"][nombre] = p = {}
            if not isinstance(p.get("hoja"), dict):
                p["hoja"] = {"enlace": "", "pestana": ""}
            if not isinstance(p.get("grupos"), list):
                p["grupos"] = []
        if data.get("activo") not in data["proyectos"]:
            data["activo"] = next(iter(data["proyectos"]))
        return data
    if isinstance(data, dict) and "grupos" in data:
        return {"activo": "Mi proyecto",
                "proyectos": {"Mi proyecto": {"hoja": data.get("hoja", {}), "grupos": data["grupos"]}}}
    raise ErrorRegistro("La configuración está dañada (no encuentro los proyectos).")


def _leer_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def leer_archivo(ruta=RUTA_CONFIG):
    ruta = Path(ruta)
    try:
        data = _leer_json(ruta)
    except FileNotFoundError:
        return _config_vacia()
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        respaldo = ruta.with_name(ruta.stem + "_respaldo.json")
        try:                                           # el archivo se dañó: se vuelve solo a la última copia buena
            bueno = _migrar(_leer_json(respaldo))
        except Exception:
            raise ErrorRegistro(
                f"El archivo de configuración tiene un error ({e}) y la copia anterior tampoco se pudo leer. "
                f"Borra el archivo {ruta.name} (la app empieza de cero) o pide ayuda.")
        try:
            shutil.copy2(ruta, ruta.with_name(ruta.stem + "_danado.json"))     # el dañado se guarda aparte, por si hace falta
            shutil.copy2(respaldo, ruta)
        except OSError:
            pass
        return bueno
    return _migrar(data)


AL_ESCRIBIR = None          # la app lo rellena: se llama cada vez que cambia la configuración (para sincronizar con el otro aparato)


_CANDADO_ARCHIVO = threading.RLock()       # una sola escritura de la configuración a la vez (ventana y sincronización)


def escribir_archivo(data, ruta=RUTA_CONFIG, sin_aviso=False):
    ruta = Path(ruta)
    if ruta.exists():
        try:                                           # solo se hace copia si el archivo actual está sano (no se pisa una copia buena con una dañada)
            _leer_json(ruta)
            shutil.copy2(ruta, ruta.with_name(ruta.stem + "_respaldo.json"))
        except (OSError, ValueError):
            pass
    with _CANDADO_ARCHIVO:
        fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), prefix=ruta.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, ruta)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    if AL_ESCRIBIR is not None and not sin_aviso:
        try:
            AL_ESCRIBIR()
        except Exception:                              # sincronizar nunca debe impedir guardar
            pass


def cargar_config(ruta=RUTA_CONFIG):
    """La configuración del proyecto activo (hoja de Google + grupos)."""
    data = leer_archivo(ruta)
    cfg = copy.deepcopy(data["proyectos"][data["activo"]])
    cfg["_proyecto"] = data["activo"]
    return validar_config(cfg)


def guardar_config(cfg, ruta=RUTA_CONFIG):
    validar_config(cfg)
    data = leer_archivo(ruta)
    nombre = cfg.get("_proyecto") or data["activo"]
    previo = data["proyectos"].get(nombre, {})
    nuevo = {"hoja": cfg["hoja"], "grupos": cfg["grupos"]}
    estadistico = cfg["estadistico"] if "estadistico" in cfg else previo.get("estadistico")
    if estadistico:
        nuevo["estadistico"] = estadistico          # segundo Excel (FO-07): enlace y pestañas
    correo = cfg["correo"] if "correo" in cfg else previo.get("correo")
    if correo:
        nuevo["correo"] = correo                    # cómo se arma el correo de este proyecto (pestaña «Correo»)
    for k in ("equipo", "ficha", "origen"):         # encargados del proyecto y de dónde vino (sync_core: «Equipo del proyecto»)
        v = cfg[k] if k in cfg else previo.get(k)
        if v:
            nuevo[k] = v
    data["proyectos"][nombre] = nuevo
    escribir_archivo(data, ruta)


def listar_proyectos(ruta=RUTA_CONFIG):
    data = leer_archivo(ruta)
    return list(data["proyectos"]), data["activo"]


def cambiar_proyecto(nombre, ruta=RUTA_CONFIG):
    data = leer_archivo(ruta)
    if nombre not in data["proyectos"]:
        raise ErrorRegistro(f"No existe el proyecto «{nombre}».")
    data["activo"] = nombre
    escribir_archivo(data, ruta)


def crear_proyecto(nombre, copiar_de=None, ruta=RUTA_CONFIG):
    """Crea un proyecto nuevo y lo deja activo. Si copias, se llevan los grupos
    (cámaras, rentals, modelos, colores), pero NO la hoja de Google."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorRegistro("Ponle un nombre al proyecto.")
    data = leer_archivo(ruta)
    if nombre in data["proyectos"]:
        raise ErrorRegistro(f"Ya existe un proyecto llamado «{nombre}».")
    base = data["proyectos"].get(copiar_de) if copiar_de else None
    data["proyectos"][nombre] = {
        "hoja": {"enlace": "", "pestana": (base or {}).get("hoja", {}).get("pestana", "")},
        "grupos": copy.deepcopy(base["grupos"]) if base else []}
    data["activo"] = nombre
    escribir_archivo(data, ruta)


def renombrar_proyecto(viejo, nuevo, ruta=RUTA_CONFIG):
    nuevo = (nuevo or "").strip()
    if not nuevo:
        raise ErrorRegistro("Ponle un nombre al proyecto.")
    data = leer_archivo(ruta)
    if viejo not in data["proyectos"]:
        raise ErrorRegistro(f"No existe el proyecto «{viejo}».")
    if nuevo != viejo and nuevo in data["proyectos"]:
        raise ErrorRegistro(f"Ya existe un proyecto llamado «{nuevo}».")
    data["proyectos"] = {(nuevo if k == viejo else k): v for k, v in data["proyectos"].items()}
    if data["activo"] == viejo:
        data["activo"] = nuevo
    escribir_archivo(data, ruta)


def eliminar_proyecto(nombre, ruta=RUTA_CONFIG):
    data = leer_archivo(ruta)
    if len(data["proyectos"]) < 2:
        raise ErrorRegistro("Debe quedar al menos un proyecto.")
    data["proyectos"].pop(nombre, None)
    if data["activo"] == nombre:
        data["activo"] = next(iter(data["proyectos"]))
    escribir_archivo(data, ruta)


def nuevo_id(nombre, cfg):
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c))
    base = re.sub(r"[^A-Z0-9]+", "", sin_acentos.upper()) or "GRUPO"
    existentes = {g["id"] for g in cfg["grupos"]}
    candidato, n = base, 2
    while candidato in existentes:
        candidato, n = f"{base}{n}", n + 1
    return candidato


def agregar_grupo(cfg, nombre, patrones, rental, modelo, ciclo_mag, color, avisar_si_falta):
    g = {"id": nuevo_id(nombre, cfg), "nombre": nombre, "patrones": list(patrones),
         "rental": rental, "modelo": modelo, "ciclo_mag": ciclo_mag, "color": color,
         "avisar_si_falta": avisar_si_falta}
    cfg["grupos"].append(g)
    validar_config(cfg)
    return g


# =============================================================================
# 2. RECONOCER QUÉ ES CADA NOMBRE
#    Cómo se escriben los patrones:  #  = un número      *  = cualquier cosa
#    Todo lo demás se lee tal cual.  Se compara con el INICIO del nombre.
#    Ejemplos:  A_####_  reconoce A_0106_1EOH_hde      D###_  reconoce D036_x
#               ##Y##M   reconoce 26Y10M01
# =============================================================================
@functools.lru_cache(maxsize=512)
def patron_a_regex(patron):
    texto = ""
    for ch in patron:
        if ch == "#":
            texto += r"\d"
        elif ch == "*":
            texto += ".*"
        else:
            texto += re.escape(ch)
    return re.compile("^" + texto, re.IGNORECASE)


def grupo_de(nombre, cfg, audio=None, recientes=None, cam=""):
    """El grupo cuyo patrón (el más específico) coincide con el nombre, o None.
    `audio`: lo que se sabe de ese BIN. True = es audio (se prefiere un rollo de Sonido); False = no lo es (se prefiere un rollo
    que no sea de Sonido); None = no se sabe: se prefiere uno que no sea de Sonido (así una «D» de dron no cae en el sonido).
    Si ningún patrón coincide y NO es audio: el rollo de la cámara con la misma LETRA (la que dice el PDF en «Camera(s)» —`cam`— o
    la del nombre): «Cámara C» guardada como «C_» también reconoce «C001_1112YE», y una tarjeta con un nombre puesto a mano
    («DIA4_TARJETA_2») va a la cámara que el PDF dice."""
    candidatos = []
    for orden, g in enumerate(cfg["grupos"]):
        for p in g["patrones"]:
            if patron_a_regex(p).match(nombre):
                candidatos.append((-len(p), orden, g))
    if not candidatos and not audio:
        k = identificar_bin(nombre)                    # manda la letra del NOMBRE («I005» es de la I aunque el PDF diga cámara A:
        letra = (k["letra"] if k and k["tipo"] == "camara" else "") or (letra_de_cam(cam) if not (k and k["tipo"] != "camara") else "")
        if letra:                                      # así numera el iPhone sus clips); sin letra en el nombre, la del PDF
            for orden, g in enumerate(cfg["grupos"]):
                if not grupo_es_sonido(g) and letra_de_camara(g["patrones"]) == letra:
                    candidatos.append((0, orden, g))
    if not candidatos:
        return None
    de_sonido = [t for t in candidatos if grupo_es_sonido(t[2])]
    otros = [t for t in candidatos if not grupo_es_sonido(t[2])]
    preferidos = (de_sonido if audio else otros) or candidatos
    recientes = recientes or {}
    # empate (el mismo patrón en varios rollos, p. ej. dos grabadoras ##Y##M): gana el que la hoja usó más recientemente
    return min(preferidos, key=lambda t: (t[0], -recientes.get(t[2]["id"], -1), t[1]))[2]


def grupo_de_audio(nombre, cfg, modelo=None, recientes=None):
    """El rollo de Sonido para un BIN que se sabe que es audio: el de la misma grabadora (`modelo`, si hay varios sonidos),
    el que lo reconoce por su nombre, o el primero de sonido, o None."""
    mk = clave_modelo(modelo)
    if mk:
        misma = [x for x in cfg["grupos"] if grupo_es_sonido(x) and clave_modelo(x.get("modelo")) == mk]
        if misma:
            return next((x for x in misma if any(patron_a_regex(p).match(nombre) for p in x["patrones"])), misma[0])
    g = grupo_de(nombre, cfg, audio=True, recientes=recientes)
    if g is not None and grupo_es_sonido(g):
        return g
    sonidos = [x for x in cfg["grupos"] if grupo_es_sonido(x)]
    recientes = recientes or {}
    return max(sonidos, key=lambda x: recientes.get(x["id"], -1)) if sonidos else None


def patron_de_camara(letra):
    """Cámara con letra: 'M' -> 'M_' (reconoce los BIN que empiezan con M_)."""
    letra = (letra or "").strip().upper()
    if len(letra) != 1 or not letra.isalpha():
        raise ErrorRegistro("Escribe UNA sola letra (A, B, C, M…).")
    return f"{letra}_"


def patrones_de_camara(letra):
    """Una cámara con letra se reconoce con CUALQUIER forma de nombrar la tarjeta: «C_0001_1IH7» (ARRI ALEXA 35) y «C001_1112YE»
    (RED, Sony, Canon, ARRI clásica, Blackmagic…): la letra y un guion bajo, o la letra y un número."""
    base = patron_de_camara(letra)
    return [base, base[0] + "#"]


def normalizar_patrones(texto):
    """Lo que escribió la persona en «Empieza con» -> lista de patrones.
    Una sola letra (M) significa «cámara M»: los BIN que empiezan con M_.
    Cualquier otra cosa se toma tal cual (# = un número): ##Y##M, D###_, I###…"""
    salida = []
    for tok in str(texto).split(","):
        tok = tok.strip()
        if not tok:
            continue
        if len(tok) == 1 and tok.isalpha():
            tok = tok.upper() + "_"
        if tok not in salida:
            salida.append(tok)
    return salida


_PATRON_DE_LETRA = re.compile(r"[A-Za-z](_(#{1,4}_?)?|#{1,4}_?)")


def letra_de_camara(patrones):
    """Si el rollo es una cámara con letra (M_, A_####_, Y#, C### o varias de esas formas con la MISMA letra) devuelve la letra;
    si no, None. Los tipos fijos (drones D###_, celulares I###/J###) no son «cámara con letra»."""
    patrones = list(patrones or [])
    if not patrones or patrones in (PATRONES_DRONES, PATRONES_CELULARES):
        return None
    if all(_PATRON_DE_LETRA.fullmatch(str(x)) for x in patrones) and len({str(x)[0].upper() for x in patrones}) == 1:
        return str(patrones[0])[0].upper()
    return None


_INCRUSTADA = re.compile(r"^([A-Za-z]{2,})(_?)(\d{1,4})_([A-Za-z])(\d)")


def letra_incrustada(nombre):
    """«DJI_001_H10» → («H», «DJI_###_H#»): la cámara de bolsillo/acción que guarda la letra DENTRO del nombre (H = Action, J = otra).
    Devuelve (letra, patrón) o None. Un nombre de una sola letra al inicio (G011_4DP592) no entra aquí."""
    m = _INCRUSTADA.match(str(nombre or "").strip())
    if not m:
        return None
    pre, sep, dig, letra, _ = m.groups()
    return letra.upper(), f"{pre.upper()}{sep}{'#' * len(dig)}_{letra.upper()}#"


def parece_camara(nombre):
    """'E_0003_1XYZ_hde' -> 'E'; si no tiene forma de cámara, None."""
    m = re.match(r"^([A-Za-z])_\d", nombre)
    return m.group(1).upper() if m else None


# Tipos de rollo que la app reconoce sola (sin que nadie explique nada)
PATRONES_SONIDO = ["##Y##M"]            # 26Y10M01
PATRONES_DRONES = ["D###_"]             # D036_…
PATRONES_CELULARES = ["I###", "J###"]   # I001, J001
MAG_POR_TIPO = {"camara": 6, "sonido": 5, "drones": 5, "celulares": 1, "otro": None}
NOMBRE_POR_TIPO = {"sonido": "Sonido", "drones": "Drones", "celulares": "Celulares (props)"}


def patrones_de_tipo(tipo, letra="", otro=""):
    """Cómo se reconoce un rollo según su tipo. Cámara = solo la letra."""
    if tipo == "camara":
        return patrones_de_camara(letra)
    if tipo == "sonido":
        return list(PATRONES_SONIDO)
    if tipo == "drones":
        return list(PATRONES_DRONES)
    if tipo == "celulares":
        return list(PATRONES_CELULARES)
    patrones = normalizar_patrones(otro)
    if not patrones:
        raise ErrorRegistro("Escribe con qué empieza el nombre del BIN de este rollo.")
    return patrones


def tipo_de_patrones(patrones):
    """(tipo, letra, otro) de un rollo ya guardado, para mostrarlo al editarlo."""
    return _tipo_de_patrones(tuple(patrones))


@functools.lru_cache(maxsize=1024)
def _tipo_de_patrones(patrones):                      # con memoria: se llama miles de veces al leer una hoja larga
    for tipo, fijos in (("sonido", PATRONES_SONIDO), ("drones", PATRONES_DRONES), ("celulares", PATRONES_CELULARES)):
        if list(patrones) == fijos:
            return tipo, "", ""
    letra = letra_de_camara(patrones)
    if letra:
        return "camara", letra, ""
    return "otro", "", ", ".join(patrones)


# Tarjetas de sonido que se llaman por lo que son: Sound, SOUND_001, Audio, Audio 2, Sonido, SND_01, Snd…
ES_NOMBRE_DE_SONIDO = re.compile(r"(?i)^\s*(sound|audio|sonido|snd)(?![a-z])")

# -----------------------------------------------------------------------------------------------------------------------------
# CÓMO NOMBRA CADA MARCA SUS TARJETAS (rollo / reel / mag). Investigado el 13/11/2026 en los manuales de ARRI, RED, Sony, Canon,
# Blackmagic, Panasonic, Nikon, DJI, GoPro, Insta360, Sound Devices y Zoom. Cada entrada: (marca, tipo, expresión, qué grupo trae la
# letra de la cámara, qué grupo trae el número de rollo). Se prueban EN ORDEN: la primera que coincide gana, de lo más preciso a lo
# más general. El nombre que se compara ya viene sin lo que agregan Silverstack o el DIT al final («_hde», «_CINE», «_1», « 2»).
#   tipo: camara (cine, con letra) · dron · accion (GoPro, Insta360) · celular · foto (cámara de fotos que graba video) · sonido
# -----------------------------------------------------------------------------------------------------------------------------
_FAMILIAS = [(m, t, re.compile(x, re.IGNORECASE), gl, gr) for m, t, x, gl, gr in (
    # ---- sonido ----
    ("Sound Devices (carpeta del día)", "sonido", r"^\d{2}Y\d{2}M\d{2}", None, None),                   # 26Y11M12, 26Y11M12_AMB
    ("sonido (por su nombre)", "sonido", r"^(sound|audio|sonido|snd|wav|amb|ambiente|ambientes|wildtrack|wt|portatil|zoom|tascam|"
                                        r"cantar|nagra|zaxcom|scorpio|mixpre|sr|aud)(?![a-z])", None, None),
    ("sonido (por fecha)", "sonido", r"^\d{1,2}[-_ ][a-z]{3}[-_ ]\d{1,2}$", None, None),                # 10-OCT-28
    ("Zoom / Tascam (fecha y número)", "sonido", r"^\d{6}_\d{3,4}$", None, None),                      # 261112_001
    # ---- cine, con letra de cámara ----
    ("ARRI ALEXA 35 / 265", "camara", r"^([A-Z])_(\d{4})(?:_([A-Z0-9]{4}))?$", 1, 2),                    # A_0010_1IB7
    ("ARRI ALEXA (Mini, LF, AMIRA)", "camara", r"^([A-Z])(\d{3})R([A-Z0-9]{3,4})$", 1, 2),              # A001R1JK
    ("RED / DJI Ronin 4D / Nikon ZR", "camara", r"^([A-Z])(\d{3})_(\d{4})([A-Z0-9]{2})$", 1, 2),        # C001_1112YE (mes y día + 2 al azar)
    ("Blackmagic", "camara", r"^([A-Z])(\d{3})_(\d{8})$", 1, 2),                                       # A001_08151512
    ("Sony / Canon / Panasonic (cine)", "camara", r"^([A-Z])(\d{3})C(\d{3})?([A-Z0-9_]*)$", 1, 2),      # A001C001_230101AB, A168CUSW
    ("cámara de cine (letra, rollo y código)", "camara", r"^([A-Z])(\d{3})(?=[A-Z0-9]{0,3}[A-Z])([A-Z0-9]{4})$", 1, 2),   # A231APW8
    # ---- sin letra de cámara ----
    ("DJI (cámara con letra dentro)", "dron", r"^(?:dji|mavic|inspire|osmo|action|avata|dron|drone)_?\d{1,4}_([A-Z])(\d+)", 1, 2),   # DJI_001_H10
    ("DJI", "dron", r"^(dji|mavic|inspire|drone?|dron|avata|fpv|phantom|air ?\d)(?![a-z])", None, None),
    ("GoPro", "accion", r"^(gopro|gopr|hero(?![a-z])|g[hxsl]\d{6}|gp\d{6}|\d{3}gopro)", None, None),
    ("Insta360", "accion", r"^(insta|(pro_)?(vid|lrv|img)_\d{8}_\d{6}_\d{2}_\d{3})", None, None),
    ("iPhone", "celular", r"^(iphone|ipad|img_\d{4}|\d{3}apple)", None, None),
    ("celular", "celular", r"^(celular|movil|telefono|phone|android|samsung|galaxy|pixel|xiaomi|huawei|pxl_\d{8}|vid_\d{8}|"
                           r"\d{8}_\d{6}$)(?![a-z])", None, None),
    ("cámara de fotos (Nikon, Fuji, Canon, Sony, Lumix)", "foto", r"^(dsc[fn_]?\d{4}|_dsc\d{4}|mvi_\d{4}|p\d{7}|"
                                                                  r"\d{3}(nikon|canon|_fuji|_pana|msdcf)|ncz_|fotos?(?![a-z])|stills?(?![a-z]))", None, None),
    # ---- lo general: una letra (o letra y guion) y un número = la cámara de esa letra ----
    ("cámara con letra", "camara", r"^([A-Z])_(\d{1,5})(?!\d)", 1, 2),                                   # E_0003_x
    ("cámara con letra", "camara", r"^([A-Z])(\d{1,5})(?!\d)", 1, 2),                                    # Y001_1028BD, N004, M001L
)]
_COLA_DE_NOMBRE = re.compile(r"(?i)([_ -](hde|cine|ocn|raw|prores|proxy|r3d|mxf|copy|copia|bis|\d{1,2}))+$")


@functools.lru_cache(maxsize=4096)
def identificar_bin(nombre):
    """Qué es una tarjeta por la forma de su nombre: {marca, tipo, letra, rollo} o None si no se parece a nada conocido.
    «A_0010_1IB7_hde» → ARRI ALEXA 35, cámara A, rollo 10 · «C001_1112YE» → RED, cámara C, rollo 1 · «26Y11M12_AMB» → sonido."""
    t = str(nombre or "").strip()
    if not t:
        return None
    limpio = _COLA_DE_NOMBRE.sub("", t) or t
    for intento in ((t, limpio) if limpio != t else (t,)):
        for marca, tipo, rx, gl, gr in _FAMILIAS:
            m = rx.match(intento)
            if not m:
                continue
            if marca == "cámara con letra" and intento is t and limpio != t:
                break                                    # se mira primero el nombre limpio: puede ser de una marca precisa
            letra = m.group(gl).upper() if gl else ""
            try:
                rollo = int(m.group(gr)) if gr else None
            except (TypeError, ValueError):
                rollo = None
            return {"marca": marca, "tipo": tipo, "letra": letra, "rollo": rollo}
    return None


def tipo_de_grupo(g):
    """(tipo, letra, otro) de un rollo de Ajustes para mostrarlo o editarlo. Un rollo de SONIDO nunca es «cámara con letra» aunque se
    reconozca con «D#» (grabadora que nombra sus carpetas D001, D002…)."""
    tipo, letra, otro = tipo_de_patrones(g["patrones"])
    if tipo == "camara" and grupo_es_sonido(g):
        return "otro", "", ", ".join(g["patrones"])
    return tipo, letra, otro


def patrones_en_uso(cfg, menos=None):
    """Las formas de reconocer que ya usan los rollos (para no repetirlas al crear o editar uno; `menos` = posición del que se edita).
    Las de los rollos de sonido van marcadas: «Sonido» con «D#» no impide crear la «Cámara D»."""
    return [("sonido:" + p if grupo_es_sonido(g) else p) for j, g in enumerate(cfg["grupos"]) if j != menos for p in g["patrones"]]


def patrones_repetidos(patrones, usados, tipo="", nombre=""):
    """Los patrones del rollo que se está guardando que YA usa otro rollo. Un rollo de sonido solo choca con otro de sonido (y una
    cámara con otra cámara): «Sonido» con «D#» y «Cámara D» pueden convivir (el PDF dice cuál tarjeta es audio)."""
    es_sonido = tipo == "sonido" or es_nombre_de_sonido(nombre)
    ya = {clave_de_patron(u) for u in usados}
    return [x for x in patrones if (("sonido:" + str(x)) if es_sonido else clave_de_patron(x)) in ya]


def clave_de_patron(p):
    """Con qué se compara un patrón para saber si ya está usado: todas las formas de una cámara con letra son la misma («cam:C»)."""
    p = str(p)
    if p.startswith("sonido:"):
        return p
    letra = letra_de_camara([p])
    return "cam:" + letra if letra else p


# Colores de cámara en el set. No hay una norma escrita mundial, pero el uso del departamento de cámara (cinta de color en cuerpo,
# cajas, claqueta y tarjetas) es casi universal: A = rojo, B = azul; después lo más común es C = amarillo y D = verde. De la E en
# adelante cada producción elige: aquí siguen los colores que quedan de la paleta de la app. El sonido, café (como en las hojas).
COLOR_DE_CAMARA = {"A": "#E24A38", "B": "#70A6DD", "C": "#FFD60A", "D": "#34C759", "E": "#F28C28", "F": "#BF5AF2",
                   "G": "#FF6FB5", "H": "#5E5CE6"}
COLOR_DE_SONIDO = "#A2845E"


def color_sugerido(tipo, letra="", usados=()):
    """El color con que se propone un rollo nuevo: el de su letra según la costumbre del set (A rojo, B azul, C amarillo, D verde…),
    café para el sonido. '' si ese color ya lo usa otro rollo del proyecto o no hay costumbre (la app ofrece entonces el primero libre)."""
    color = COLOR_DE_SONIDO if tipo == "sonido" else COLOR_DE_CAMARA.get(str(letra or "").upper(), "") if tipo == "camara" else ""
    return color if color and color.upper() not in {str(u).upper() for u in usados if u} else ""


def letra_de_cam(cam):
    """La letra que el PDF pone en la columna «Camera(s)» del BIN: «A_» → A, «C» → C. Varias cámaras o nada → ''."""
    t = str(cam or "").strip().rstrip("_")
    return t.upper() if len(t) == 1 and t.isalpha() else ""


def letra_de_bin(nombre, cam=""):
    """La letra de la cámara de un BIN: la que trae el nombre de la tarjeta; si el nombre no dice nada (lo pusieron a mano al
    descargar), la que dice el PDF en «Camera(s)»."""
    k = identificar_bin(nombre)
    if k and k["tipo"] in ("camara", "dron") and k["letra"]:
        return k["letra"]
    return letra_de_cam(cam) if not k else ""


MBPS_SEGURO_SONIDO = 5.0      # menos que esto es sonido casi seguro (2 pistas 48 kHz/24 bit = 2,3 Mbps; el celular más liviano ≈ 8)
MBPS_SEGURO_IMAGEN = 60.0     # más que esto es imagen seguro (32 pistas de sonido = 37 Mbps; toda cámara de cine pasa de 100)


def mbps_de(gb, seg):
    """El peso por segundo de una tarjeta, en megabits por segundo (None si no hay duración)."""
    return (float(gb) * 8000.0 / float(seg)) if seg and gb else None


def adivinar_tipo(nombre_bin, cam=""):
    """Qué parece ser un BIN que no conocemos: (tipo, letra, otro). `cam`: lo que el PDF pone en «Camera(s)» para ese BIN."""
    letra = parece_camara(nombre_bin)
    if letra:
        return "camara", letra, ""
    k = identificar_bin(nombre_bin)
    if k and k["tipo"] == "camara" and k["letra"] and k["marca"] != "cámara con letra":
        return "camara", k["letra"], ""                                # C001_1112YE (RED), A001R1JK (ARRI), A001C001_… (Sony/Canon)
    if not k and letra_de_cam(cam):                    # nombre puesto a mano («TARJETA_2_DIA5»): el PDF dice de qué cámara es
        return "camara", letra_de_cam(cam), ""
    emb = letra_incrustada(nombre_bin)
    if emb:                                                           # DJI_001_H10: la letra de la cámara va dentro del nombre
        return "otro", "", emb[1]
    if any(patron_a_regex(p).match(nombre_bin) for p in PATRONES_SONIDO) or ES_NOMBRE_DE_SONIDO.match(str(nombre_bin)):
        return "sonido", "", ""
    if re.match(r"^PORTATIL", str(nombre_bin), re.IGNORECASE):     # grabadora de respaldo (LRDS4: PORTATIL, PORTATIL_03, modelo 633)
        return "sonido", "", "PORTATIL"
    if re.match(r"^K[A-Za-z]\d", nombre_bin):                      # GoPro KA001 → KA#
        return "otro", "", patron_corto(nombre_bin)
    if re.match(r"^[A-Za-z]\d", nombre_bin):          # Y001_1028BD, D001_…, N004, M001L: una letra y un número = la cámara de esa letra
        return "camara", str(nombre_bin)[0].upper(), ""
    if k and k["tipo"] == "sonido":                    # AMBIENTES_U2, ZOOM_01, SR001, 261112_001, 10-OCT-28: sonido con su propio comienzo
        return "otro", "", (patron_de_palabra(nombre_bin) if re.match(r"[A-Za-z]{2}", str(nombre_bin).strip()) else patron_corto(nombre_bin))
    if k and k["tipo"] in ("dron", "accion", "celular", "foto"):
        return "otro", "", patron_de_palabra(nombre_bin)
    return "otro", "", sugerir_patron(nombre_bin)


def patron_de_palabra(nombre):
    """«GOPRO_003» → GOPRO · «DJI_0045» → DJI_ · «IMG_0012» → IMG_ · «AMBIENTES U2» → AMBIENTES: la palabra con la que empieza
    (así reconoce todas las tarjetas de ese equipo, sin importar el número)."""
    m = re.match(r"^([A-Za-z]{2,}_?)", str(nombre).strip())
    return m.group(1).upper() if m else sugerir_patron(nombre)


NOMBRE_DE_TIPO = {"dron": "Dron", "accion": "Cámara de acción", "celular": "Celular", "foto": "Cámara de fotos", "sonido": "Sonido"}


def nombre_sugerido(nombre_bin, cam=""):
    """Cómo llamar el rollo nuevo: «Cámara C», «Dron», «GoPro», «Sonido»… ('' si no hay una buena idea)."""
    k = identificar_bin(nombre_bin)
    letra = letra_de_bin(nombre_bin, cam)
    if k and k["tipo"] == "sonido":
        return "Sonido"
    if letra and not (k and k["tipo"] in ("accion", "celular", "foto")):
        return f"Cámara {letra}"
    if k:
        return {"GoPro": "GoPro", "Insta360": "Insta360", "iPhone": "iPhone"}.get(k["marca"]) or NOMBRE_DE_TIPO.get(k["tipo"], "")
    return ""


def que_es_rollo(tipo, letra, nombre):
    """Cómo se le describe a la persona un BIN nuevo. «Y001_1028BD» (una letra y un número) es una cámara con esa letra, aunque su
    patrón sea «Y#» y no «Y_» (antes decía «algo que no reconozco» y había que adivinar qué era)."""
    k = identificar_bin(nombre)
    marca = f" ({k['marca']}" + (f", rollo {k['rollo']}" if k.get("rollo") else "") + ")" if k and k["marca"] != "cámara con letra" else ""
    if tipo == "camara":
        return f"una cámara nueva con la letra {letra}" + (marca if k and k["tipo"] == "camara" else "")
    if tipo == "otro" and re.match(r"^[A-Za-z]\d", str(nombre or "")):
        return f"una cámara nueva con la letra {str(nombre)[0].upper()}"
    if tipo == "otro" and k:
        return {"dron": "un dron", "accion": "una cámara de acción", "celular": "un celular", "foto": "una cámara de fotos",
                "sonido": "sonido"}.get(k["tipo"], "un equipo nuevo") + marca
    return {"sonido": "sonido", "drones": "drones", "celulares": "celulares"}.get(tipo, "algo que no reconozco")


def patron_corto(nombre):
    """D005 → D#  ·  A001CJJU_CINE → A#  ·  26Y10M01 → ##Y##M  (la forma más corta de reconocer esa familia de nombres)."""
    if re.fullmatch(r"\d{1,2}[-_][A-Za-z]{3}[-_]\d{1,2}", str(nombre).strip()):     # sonido por fecha «10-OCT-28»: sirve para todos los meses
        return "##-*"
    m = re.match(r"^(K[A-Za-z])\d", str(nombre)) or re.match(r"^([A-Za-z])\d", str(nombre))      # GoPro: KA001 → KA#
    return f"{m.group(1).upper()}#" if m else sugerir_patron(nombre)


def sugerir_patron(nombre):
    """Propone cómo reconocer un nombre nuevo: los números pasan a #, y se corta
    en el guion bajo que sigue al primer número.  E_0003_1XYZ_hde -> E_####_"""
    patron, vio_numero = "", False
    for ch in nombre:
        if ch.isdigit():
            patron += "#"
            vio_numero = True
        else:
            patron += ch
            if ch == "_" and vio_numero:
                break
    return patron


# =============================================================================
# 2b. LEER EL PDF DE SILVERSTACK
#     Usa el lector de texto de registro_diario.py (sin modificarlo), pero lee la tabla
#     «Bins» con un lector propio: entiende duraciones con decimales (1.5 sec), cámaras
#     como «M» y avisa de cualquier línea que no pudo leer, para que nada se pierda en silencio.
# =============================================================================
_DUR = r"(\d+(?::\d+){0,2}|\d+[.,]\d+)"
FILA_BIN = re.compile(            # el nombre puede traer espacios: «Y001_1028BD 1» (Silverstack agrega « 1» si el BIN ya existía)
    r"^\s*(\S+(?:\s+\S+)*?)\s+(?:([A-Za-z][A-Za-z0-9]*_?)\s+)?(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$")
# «Camera Sums»: Camera · Reel Count · Frames · Clips · Duration · Files · Size (solo video, nunca audio)
FILA_SUMA_CAM = re.compile(r"^\s*(\S+)\s+\d+\s+\d+\s+(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+\d+\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$")


def sumas_por_camara(texto):
    """{cámara: {clips, seg, gb}} de la tabla «Camera Sums» (solo video). Vacío si el reporte no la trae."""
    m = re.search(r"Camera\s+Sums(.*?)(?:Video\s+Formats|Audio\s+Tapes|Pomfort|$)", texto, re.S)
    salida = {}
    for linea in (m.group(1).splitlines() if m else []):
        f = FILA_SUMA_CAM.match(linea)
        if f and f.group(1).lower() != "total":
            salida[f.group(1)] = {"clips": int(f.group(2)), "seg": a_segundos(f.group(3), f.group(4)),
                                  "gb": round(float(f.group(5).replace(",", "")) * GB_POR_UNIDAD[f.group(6)], 2)}
    return salida
ENCABEZADO_BINS = re.compile(r"Clips\s+Duration\s+Files\s+Size|^\s*\(s\)|Bin\s*Name\s+Camera|^\s*(Page\s+)?\d+\s*/\s*\d+\s*$", re.I)


def a_segundos(token, unidad):
    """'12:56' min -> 776 · '1:15:21' h -> 4521 · '1.5' sec -> 1.5"""
    token = token.replace(",", ".")
    if ":" in token:
        p = [int(x) for x in token.split(":")]
        if unidad == "min":
            return p[0] * 60 + (p[1] if len(p) > 1 else 0)
        p += [0] * (3 - len(p))
        return p[0] * 3600 + p[1] * 60 + p[2]
    v = float(token) * {"sec": 1, "min": 60, "h": 3600}[unidad]
    return int(v) if v == int(v) else round(v, 2)


def hms(seg):
    seg = int(round(seg))
    return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


FOLDER_DIA = re.compile(r"(\d{8})_(?:DAY|D[IÍ]A)[_ ]?(\d{1,4})(?:_U(\d+))?", re.IGNORECASE)          # también «Day0001» (4 cifras, NM)          # 20261010_Day005, 20260930_DAY036, 20260805_DIA_09
# Reportes cuya carpeta no trae el día («Camera_Media»): la fecha y el día están en la fila «20260817  083  …» sobre los rótulos «Shooting Date  Shooting Day»
FECHA_DIA_TABLA_DMY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,4})\b.*\n\s*Shooting\s+Date\s+Shooting\s+Day", re.M)
# Solo la fecha («20261103  SAMIR …» sobre «Shooting Date  Director …»): reportes de sonido sin número de día
FECHA_SOLA = re.compile(r"^\s*(\d{4})-?(\d{2})-?(\d{2})\b.*\n\s*Shooting\s+Date\b", re.M)
FECHA_DIA_TABLA = re.compile(r"^\s*(\d{4})-?(\d{2})-?(\d{2})\s+(\d{1,3})\b.*\n\s*Shooting\s+Date\s+Shooting\s+Day", re.M)
# Sin pdftotext (Mac sin Homebrew) pdfplumber deja el guion de esas fechas como un símbolo privado («2026\ue08808\ue08817»)
GUION_PDF = str.maketrans({"\ue088": "-"})
FILA_CINTA = re.compile(r"^\s*(\S+)\s+(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$")


def cintas_de_audio(texto):
    """Los nombres de BIN que el reporte lista en «Audio Tapes» (lo que Silverstack considera audio). None si el reporte no trae esa sección."""
    m = re.search(r"Audio\s+Tapes\s*\n\s*Tape\s+Name[^\n]*\n(.*?)(?:Audio\s+Formats|Pomfort|$)", texto, re.S)
    if not m:
        return None
    return {f.group(1) for f in (FILA_CINTA.match(l) for l in m.group(1).splitlines()) if f}


MESES_EN = {m: i + 1 for i, m in enumerate("January February March April May June July August September October November December".split())}


def totales_de_audio(texto):
    """(clips, GB) que el reporte suma en «Audio Tapes», o None si no trae esa sección."""
    m = re.search(r"Audio\s+Tapes\s*\n\s*Tape\s+Name[^\n]*\n(.*?)(?:Audio\s+Formats|Pomfort|$)", texto, re.S)
    if not m:
        return None
    filas = [f for f in (FILA_CINTA.match(l) for l in m.group(1).splitlines()) if f]
    if not filas:
        return None
    return (sum(int(f.group(2)) for f in filas), sum(float(f.groups()[-2].replace(",", "")) * GB_POR_UNIDAD[f.groups()[-1]] for f in filas))


def fecha_de_descarga(texto):
    """Día en que se empezó a descargar («Offloads started between October 9, 2026 …»): el día real en que se hizo el reporte."""
    m = re.search(r"Offloads\s+started\s+between\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", texto)
    if not m or m.group(1).capitalize() not in MESES_EN:
        return None
    try:
        return datetime(int(m.group(3)), MESES_EN[m.group(1).capitalize()], int(m.group(2)))
    except ValueError:
        return None


def copias_de_seguridad(texto):
    """La sección «Backups (Verified)» del reporte de Silverstack: cuántos clips tienen 3 o más, 2, 1 o 0 copias verificadas.
    [{"copias": "3+"|"2"|"1"|"0", "clips", "duracion" (texto como en el PDF), "tamano" (texto)}]; vacía si el PDF no la trae."""
    m = re.search(r"Backups(.*?)(?:\nBins\b|\nVideo Reels|$)", texto or "", re.S)
    if not m:
        return []
    salida = []
    for nivel, clips, dur, _archivos, tam, unidad in re.findall(
            r"^\s*(3\+?|2|1|0)\s+(\d+)\s+(.+?)\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$", m.group(1), re.M):
        salida.append({"copias": "3+" if nivel.startswith("3") else nivel, "clips": int(clips), "duracion": dur.strip(),
                       "tamano": f"{tam} {unidad}"})
    return salida


def avisos_de_copias(reporte):
    """Avisos SOLO si hay clips con menos de 2 copias verificadas (0 o 1). Si todo tiene 2 o más, no dice nada.
    También trae los avisos de lectura del PDF (audio mezclado en un BIN de cámara)."""
    avisos = list(reporte.get("avisos_lectura") or [])
    for c in reporte.get("copias") or []:
        if c["clips"] <= 0 or c["copias"] not in ("0", "1"):
            continue
        cuantos = f"{c['clips']} clip{'s' if c['clips'] != 1 else ''} ({c['duracion']}, {c['tamano']})"
        if c["copias"] == "0":
            avisos.append(f"Copias de seguridad: según Silverstack, {cuantos} NO tiene{'n' if c['clips'] != 1 else ''} ninguna copia "
                          "verificada. Revisa en Silverstack cuáles son y cópialos y verifícalos antes de formatear las tarjetas.")
        else:
            avisos.append(f"Copias de seguridad: según Silverstack, {cuantos} tiene{'n' if c['clips'] != 1 else ''} UNA sola copia "
                          "verificada. Haz la segunda copia (y verifícala) antes de formatear las tarjetas.")
    return avisos


def totales_del_reporte(texto):
    """Los totales que trae «Clips Overview» (Source Video Clips y Audio Clips): {'video': {clips, seg, gb}, 'audio': {...}}.
    Sirven para el correo: son los números exactos del reporte (sumar BIN por BIN puede variar 0.01 GB por redondeo)."""
    salida = {}
    for clave, rotulo in (("video", r"Source\s+Video\s+Clips"), ("audio", r"Audio\s+Clips")):
        m = re.search(r"^\s*" + rotulo + r"\s+(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+\d+\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$", texto, re.M)
        if m:
            salida[clave] = {"clips": int(m.group(1)), "seg": a_segundos(m.group(2), m.group(3)),
                             "gb": round(float(m.group(4).replace(",", "")) * GB_POR_UNIDAD[m.group(5)], 2)}
    if "video" not in salida:                              # otro diseño del reporte: el total de video está en «Camera Sums → Total»
        cs = re.search(r"Camera\s+Sums(.*?)(?:Video\s+Formats|Audio\s+Tapes|$)", texto, re.S)
        if cs:
            t = re.search(r"^\s*Total\s+\d+\s+\d+\s+(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+\d+\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$", cs.group(1), re.M)
            if t and t.group(5) != "TB":                    # en TB solo trae 2 decimales (±10 GB): mejor sumar los BIN
                salida["video"] = {"clips": int(t.group(1)), "seg": a_segundos(t.group(2), t.group(3)),
                                   "gb": round(float(t.group(4).replace(",", "")) * GB_POR_UNIDAD[t.group(5)], 2)}
    return salida


def leer_reporte(ruta, texto=None):
    """Lee el PDF: día, fecha y los BIN (clips, duración en segundos, GB).
    También devuelve `sin_leer`: las líneas de la tabla de BIN que no pudo entender."""
    texto = (texto if texto is not None else rd.texto_del_pdf(ruta)).translate(GUION_PDF)
    m = FOLDER_DIA.search(texto) or FOLDER_DIA.search(Path(ruta).name)
    dia_de_carpeta = bool(m)                           # el día viene en la carpeta (20261009_DAY051): no se busca la fila por fecha
    if not m:
        t_ = FECHA_DIA_TABLA.search(texto)
        if t_ and int(t_.group(4)) > 0:
            try:
                datetime(int(t_.group(1)), int(t_.group(2)), int(t_.group(3)))
                m = re.match(r"(\d{8})_(\d+)()", f"{t_.group(1)}{t_.group(2)}{t_.group(3)}_{t_.group(4)}")
            except ValueError:
                m = None
    if not m:                                          # diseño nuevo: «2/11/26  001» sobre «Shooting Date  Shooting Day» (NM Sound_Media)
        t_ = FECHA_DIA_TABLA_DMY.search(texto)
        if t_ and int(t_.group(4)) > 0:
            try:
                a_ = int(t_.group(3))
                f_ = datetime(a_ + 2000 if a_ < 100 else a_, int(t_.group(2)), int(t_.group(1)))
                m = re.match(r"(\d{8})_(\d+)()", f"{f_:%Y%m%d}_{int(t_.group(4))}")
            except ValueError:
                m = None
    solo_fecha = False
    if not m:                                          # reporte solo de sonido (PP «Sound_Media»): trae la FECHA pero no el número de día
        t_ = FECHA_SOLA.search(texto)
        if t_:
            try:
                datetime(int(t_.group(1)), int(t_.group(2)), int(t_.group(3)))
                m = re.match(r"(\d{8})_(\d+)()", f"{t_.group(1)}{t_.group(2)}{t_.group(3)}_0")
                solo_fecha = True
            except ValueError:
                m = None
    if not m:
        raise ErrorRegistro("No encontré el día de rodaje (algo como 20260930_DAY036) ni la fecha de rodaje en el PDF.")
    fecha = datetime.strptime(m.group(1), "%Y%m%d")
    sd = re.search(r"Shooting\s+Date:\s*(\d{4})-(\d{2})-(\d{2})", texto)
    if sd:                                              # la fecha de rodaje manda sobre la del nombre de la carpeta
        try:
            fecha = datetime(int(sd.group(1)), int(sd.group(2)), int(sd.group(3)))
        except ValueError:
            pass
    dia = None if solo_fecha else f"D{int(m.group(2)):03d}"          # None: el día se busca por la FECHA en tus hojas (dia_por_fecha)
    fecha_dudosa = False
    sdia = re.search(r"Shooting\s+Day:\s*(\d{1,3})", texto)
    desc = fecha_de_descarga(texto)
    if sd and sdia and int(sdia.group(1)) == 0 and desc:     # «Shooting Day: 000» = nadie llenó la ficha: su «Shooting Date» es la de una plantilla vieja
        fecha, fecha_dudosa = desc, True
    elif not sd and desc and abs((fecha - desc).days) > 45:    # la fecha de la carpeta está mal escrita (20260109 en vez de 20261009)
        fecha, fecha_dudosa = desc, True
    num_unidad = int(m.group(3)) if m.group(3) else 1              # 20261009_DAY007_U2 = segunda unidad
    dia_rodaje = None
    tabla = re.search(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s{2,}(\d{1,3})\s{2,}.*\n\s*Shooting\s+Date\s+Shooting\s+Day", texto, re.M)
    if tabla:                                                      # formato nuevo del reporte: «10/10/26   06 …» y debajo los rótulos
        dia_rodaje = int(tabla.group(4))
        if not sd:
            a_ = int(tabla.group(3))
            try:
                fecha = datetime(a_ + 2000 if a_ < 100 else a_, int(tabla.group(2)), int(tabla.group(1)))
            except ValueError:
                pass
    sd2 = re.search(r"Shooting\s+Day:\s*(\d{1,3})", texto)
    if dia_rodaje is None and sd2 and int(sd2.group(1)) > 0:     # 000 = sin llenar
        dia_rodaje = int(sd2.group(1))
    ini = re.search(r"Bin\s*Name\s+Camera", texto)
    if not ini:
        raise ErrorRegistro("No encontré la tabla «Bins» en el PDF. ¿Cambió el formato del reporte?")
    resto = texto[ini.end():]
    fin = re.search(r"Video\s+Reels|Camera\s+Sums|Audio\s+Tapes", resto)
    seccion = resto[: fin.start()] if fin else resto
    bins, sin_leer = [], []
    for linea in seccion.splitlines():
        if not linea.strip() or ENCABEZADO_BINS.search(linea):
            continue
        f = FILA_BIN.match(linea)
        if not f:
            sin_leer.append(linea.strip())
            continue
        nombre, cam, clips, dur, unidad, _files, tam, u_tam = f.groups()
        nombre = re.sub(r"\s+(\d+)$", r"_\1", nombre.strip())     # «Y001_1028BD 1» → «Y001_1028BD_1» (repetición de la tarjeta Y001)
        bins.append({"nombre": nombre, "clips": int(clips), "seg": a_segundos(dur, unidad), "cam": cam or "",
                     "gb": round(float(tam.replace(",", "")) * GB_POR_UNIDAD[u_tam], 2)})
    cintas = cintas_de_audio(texto)
    tot = totales_de_audio(texto)
    for b in bins:                         # True = audio · False = video · None = el reporte no lo dice
        b["audio"] = None if cintas is None else b["nombre"] in cintas
        if b["audio"] is False and not b["cam"] and tot and b["clips"] == tot[0] and abs(b["gb"] - tot[1]) <= 0.05:
            b["audio"] = True              # el BIN de audio se llama de otra forma (10-OCT-09) pero trae justo los clips y GB de «Audio Tapes»
    _audio_por_cintas(bins, cintas_con_datos(texto), tot)
    avisos_lectura = _separar_audio_de_camara(bins, sumas_por_camara(texto))
    if not bins:
        raise ErrorRegistro("No encontré filas en la tabla «Bins». ¿Cambió el formato del reporte?")
    reporte = {"dia": dia, "fecha": fecha, "bins": bins, "sin_leer": sin_leer, "unidad": num_unidad, "dia_rodaje": dia_rodaje,
               "fecha_dudosa": fecha_dudosa, "totales": totales_del_reporte(texto),
               "carpeta_con_unidad": bool(m.group(3)), "copias": copias_de_seguridad(texto), "avisos_lectura": avisos_lectura,
               "dia_de_carpeta": dia_de_carpeta,
               "solo_fecha": solo_fecha, "confirmaciones": []}
    try:
        confirmar_reporte(reporte, texto)              # cruza «Bins», «Video Reels», «Camera Sums», «Video Formats» y «Audio Tapes»
    except Exception as e:                             # confirmar nunca impide leer
        reporte["confirmaciones"] = [("info", f"No pude cruzar las partes del PDF para confirmar las cámaras ({type(e).__name__}).")]
        for b_ in bins:
            b_.setdefault("verif", {"tipo": "", "letra": "", "rollo": None, "marca": "", "pruebas": [], "dudas": []})
    return reporte


def dia_por_fecha(reporte, valores06=None, datos07=None):
    """Reporte que trae la FECHA pero no el número de día (PP «Sound_Media», solo sonido): el día se busca en tus hojas por esa fecha
    (primero el estatus de tarjetas, luego el estadístico) y se pone en reporte['dia']. Devuelve el aviso para mostrar, o None si el
    reporte ya traía el día. Si no hay un único día con esa fecha, explica qué hacer (ErrorRegistro)."""
    if reporte.get("dia"):
        return None
    import estadistico_core as ec_                   # (import aquí: estadistico_core importa este módulo)
    objetivo = reporte["fecha"].date()
    nums, donde = set(), ""
    if valores06 is not None:
        try:
            fmt = formato_de(valores06)
            for b in bloques_de_hoja(valores06, fmt):
                if not (b["material"] and b["clave"]):
                    continue
                v = _celda(list(valores06[b["filas"][0] - fmt["primera"]]) + [""] * fmt["ncol"], fmt, "fecha_col") if "fecha_col" in fmt["col"] else ""
                if ec_.fecha_de_celda(v) == objetivo:
                    nums.add(int(re.sub(r"\D", "", b["clave"]) or 0))
            donde = "el estatus de tarjetas"
        except ErrorRegistro:
            pass
    if not nums and datos07 is not None:
        try:
            nums = {d["num"] for d in ec_.encontrar_tabla(datos07)["dias"] if d.get("fecha") == objetivo}
            donde = "el estadístico"
        except ErrorRegistro:
            pass
    if len(nums) == 1:
        n = nums.pop()
        reporte["dia"] = f"D{n:03d}"
        return (f"Este reporte (solo sonido) no dice qué día de rodaje es, solo la fecha {objetivo:%d/%m/%Y}: según {donde}, "
                f"ese día es el {reporte['dia']}.")
    if len(nums) > 1:
        raise ErrorRegistro(f"Este reporte no dice qué día de rodaje es, solo la fecha {objetivo:%d/%m/%Y}, y en tus hojas hay varios días "
                            f"con esa fecha ({', '.join(f'D{x:03d}' for x in sorted(nums))}). Registra primero el reporte del día "
                            "(el que trae las cámaras): este sonido normalmente ya viene incluido en él.")
    raise ErrorRegistro(f"Este reporte no dice qué día de rodaje es, solo la fecha {objetivo:%d/%m/%Y}, y en tus hojas todavía no hay "
                        "un día con esa fecha. Registra primero el reporte del día (el que trae las cámaras): este sonido normalmente "
                        "ya viene incluido en él.")


def cintas_con_datos(texto):
    """Las filas de «Audio Tapes» con sus números: [(nombre, clips, segundos, GB)]. La cinta no siempre se llama como el BIN
    (BIN «26Y11M12_AMB», cinta «261112»), pero trae los mismos clips, duración y peso."""
    m = re.search(r"Audio\s+Tapes\s*\n\s*Tape\s+Name[^\n]*\n(.*?)(?:Audio\s+Formats|Pomfort|$)", texto, re.S)
    salida = []
    for f in (FILA_CINTA.match(l) for l in (m.group(1).splitlines() if m else [])):
        if f:
            nombre, clips, dur, unidad, _files, tam, u = f.groups()
            salida.append((nombre, int(clips), a_segundos(dur, unidad), float(tam.replace(",", "")) * GB_POR_UNIDAD[u]))
    return salida


def _audio_por_cintas(bins, cintas, tot):
    """Marca como audio los BIN que el reporte no listó por su nombre en «Audio Tapes» pero que SON esas cintas:
    1) mismos clips, duración y peso que una cinta;  2) los BIN sin cámara que, juntos, pesan lo que suma «Audio Tapes»."""
    libres = list(cintas)
    for b in bins:
        if b.get("audio") is True:
            libres = [c for c in libres if c[0] != b["nombre"]]
    for b in bins:
        if b.get("audio") is True or b.get("cam"):
            continue
        igual = next((c for c in libres if c[1] == b["clips"] and abs(c[2] - b["seg"]) <= 2 and abs(c[3] - b["gb"]) <= max(0.02, c[3] * 0.01)), None)
        if igual:
            b["audio"] = True
            libres.remove(igual)
    if tot:                                            # solo si de verdad FALTA audio por ubicar (si no, una tarjeta liviana sin cámara
        sin_cam = [b for b in bins if not b.get("cam") and b.get("audio") is not True]      # —un clip de celular— caía en el margen)
        ya = sum(b["gb"] for b in bins if b.get("audio") is True)
        ya_clips = sum(b["clips"] for b in bins if b.get("audio") is True)
        margen = max(0.05, tot[1] * 0.01)
        peso = sum(b["gb"] for b in sin_cam)
        if sin_cam and any(b.get("cam") for b in bins) and tot[1] - ya > margen and peso > margen and abs(ya + peso - tot[1]) <= margen \
                and ya_clips + sum(b["clips"] for b in sin_cam) == tot[0]:
            for b in sin_cam:
                b["audio"] = True


# -----------------------------------------------------------------------------------------------------------------------------
# CONFIRMAR CADA TARJETA CON VARIAS PARTES DEL PDF. El reporte dice lo mismo en varios lugares: la tabla «Bins» (nombre con que se
# descargó + cámara), «Video Reels» (el rollo como lo nombró la cámara), «Camera Sums» (lo que suma cada cámara), «Video Formats»
# (el códec: ARRIRAW = ARRI, R3D = RED, X-OCN = Sony…) y «Audio Tapes». Aquí se cruzan: cada dato queda con sus pruebas, y lo que
# no cuadra sale como duda (nunca detiene la lectura). Lo que se ESCRIBE en la hoja es siempre el nombre con que se descargó.
# -----------------------------------------------------------------------------------------------------------------------------
_FILA_ROLLO = re.compile(r"^\s*(.*?)\s*(\d+)\s+" + _DUR + r"\s*(h|min|sec)\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$")
_CODECS = (("ARRI", r"arri"), ("RED", r"\br3d\b|redcode|\bred\b"), ("Sony", r"sony|x-?ocn|xocn|xavc"), ("Canon", r"canon|xf-?avc|\bcrm\b"),
           ("Blackmagic", r"blackmagic|\bbraw\b"), ("Panasonic", r"panasonic|v-?raw|avc-?intra"), ("DJI / CinemaDNG", r"cinemadng|\bdng\b"),
           ("ProRes", r"prores"), ("H.264 / H.265", r"h\.?26[45]|hevc|avc"))


def _gb_y_margen(numero, unidad):
    """(GB, margen por el redondeo con que el PDF lo escribe): «1.77 TB» = 1770 GB ± 5."""
    dec = len(numero.split(".")[1]) if "." in numero else 0
    return float(numero.replace(",", "")) * GB_POR_UNIDAD[unidad], 0.5 * 10 ** (-dec) * GB_POR_UNIDAD[unidad] + 0.011


def rollos_de_video(texto, camaras=()):
    """Las filas de «Video Reels»: [{nombre, cams, clips, seg, gb}]. El nombre puede venir vacío y las cámaras ser varias («A, B»)."""
    m = re.search(r"Video\s+Reels\s*\n\s*Reel\s+Name[^\n]*\n(.*?)(?:Camera\s+Sums|Video\s+Formats|Audio\s+Tapes|$)", texto, re.S)
    conocidas = {str(c).upper() for c in camaras if c}
    salida = []
    for linea in (m.group(1).splitlines() if m else []):
        if ENCABEZADO_BINS.search(linea) or not linea.strip():
            continue
        f = _FILA_ROLLO.match(linea)
        if not f:
            continue
        cabeza, clips, dur, unidad, _files, tam, u = f.groups()
        partes = [x for x in re.split(r"[\s,]+", cabeza.strip()) if x]
        cams = []
        while partes and partes[-1].upper() in conocidas and (len(partes) > 1 or not cams):
            cams.insert(0, partes.pop())
            if not partes:
                break
        if not conocidas and len(partes) > 1 and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,2}_?", partes[-1]):
            cams.insert(0, partes.pop())
        salida.append({"nombre": " ".join(partes), "cams": cams, "clips": int(clips), "seg": a_segundos(dur, unidad),
                       "gb": float(tam.replace(",", "")) * GB_POR_UNIDAD[u]})
    return salida


def formatos_de_video(texto):
    """Las filas de «Video Formats» con la marca que delata su códec: [{marca, codec, clips, gb, margen}]."""
    m = re.search(r"Video\s+Formats(.*?)(?:Audio\s+Tapes|Audio\s+Formats|$)", texto, re.S)
    lineas = [l.strip() for l in (m.group(1).splitlines() if m else []) if l.strip()]
    datos = re.compile(r"^(.*?)\b([A-Za-z0-9]{2,4})\s+\S+\s+[\d.]+\s+(\d+)\s+" + _DUR + r"\s*(?:h|min|sec)\s+\d+\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$")
    es_ruido = lambda l: bool(re.match(r"(?i)^(codec|project|fps|page\b|pomfort|shooting day report)", l))
    marca_de = lambda t: next((n for n, rx in _CODECS if re.search(rx, t, re.I)), "")
    filas = [(k, datos.match(l)) for k, l in enumerate(lineas)]
    con = [k for k, f in filas if f]
    salida = []
    for n, i in enumerate(con):
        f = filas[i][1]
        antes = [l for l in lineas[(con[n - 1] + 1 if n else 0):i] if not es_ruido(l)]
        despues = [l for l in lineas[i + 1:(con[n + 1] if n + 1 < len(con) else len(lineas))] if not es_ruido(l)]
        # el nombre del códec viene partido en renglones: primero lo que está en SU renglón, luego lo de arriba (el más cercano
        # primero) y al final lo de abajo; así no se le pega la marca del códec vecino
        propio = (f.group(1).strip() + " " + f.group(2)).strip()
        marca = marca_de(propio) or next((m for m in (marca_de(l) for l in reversed(antes)) if m), "") \
            or next((m for m in (marca_de(l) for l in despues[:1]) if m), "")
        codec = " ".join(antes[-1:] + [propio] + despues[:1]).strip()
        gb, margen = _gb_y_margen(f.group(5), f.group(6))
        salida.append({"marca": marca, "codec": " ".join(codec.split()), "clips": int(f.group(3)), "gb": gb, "margen": margen})
    return salida


def _marca_corta(marca):
    """De «ARRI ALEXA 35 / 265» → {ARRI}; «Sony / Canon / Panasonic (cine)» → {Sony, Canon, Panasonic}; «RED / DJI…» → {RED, DJI / CinemaDNG}."""
    t = str(marca or "")
    return {n for n, clave in (("ARRI", "ARRI"), ("RED", "RED"), ("Sony", "Sony"), ("Canon", "Canon"), ("Panasonic", "Panasonic"),
                               ("Blackmagic", "Blackmagic"), ("DJI / CinemaDNG", "DJI")) if clave in t}


def confirmar_reporte(reporte, texto):
    """Cruza las partes del PDF y deja en cada BIN `verif` = {tipo, letra, rollo, marca, pruebas: [...], dudas: [...]} y, si el nombre
    no dice de qué cámara es (lo pusieron a mano al descargar), `letra` = la que confirman «Camera(s)» y «Video Reels».
    Devuelve las líneas para «Comprobaciones»: [(estado, mensaje)]. Nunca lanza errores: si una parte del PDF no se entiende, se salta."""
    bins = reporte["bins"]
    # los signos que el PDF trae como símbolos privados (dos puntos, paréntesis, cifras) y los que no se saben leer (la coma de «A, B»)
    texto = "".join(" " if 0xE000 <= ord(ch) <= 0xF8FF else ch for ch in texto.translate(str.maketrans(dict(rd.PUA))))
    sumas = sumas_por_camara(texto)
    rollos = rollos_de_video(texto, list(sumas) + [b.get("cam") for b in bins])
    formatos = formatos_de_video(texto)
    cintas = cintas_con_datos(texto)
    libres = list(rollos)
    for b in bins:
        k = identificar_bin(b["nombre"]) or {}
        v = b["verif"] = {"tipo": "", "letra": "", "rollo": k.get("rollo"), "marca": k.get("marca", ""), "pruebas": [], "dudas": []}
        mbps = mbps_de(b["gb"], b["seg"])
        if b.get("audio"):
            v["tipo"] = "sonido"
            if any(c[0] == b["nombre"] for c in cintas):
                v["pruebas"].append("«Audio Tapes»")
            elif any(c[1] == b["clips"] and abs(c[2] - b["seg"]) <= 2 for c in cintas):
                v["pruebas"].append("«Audio Tapes»")
            elif cintas:
                v["pruebas"].append("«Audio Tapes»")
            if k.get("tipo") == "sonido":
                v["pruebas"].append("nombre de sonido")
            if not b.get("cam"):
                v["pruebas"].append("sin cámara en «Bins»")
            if mbps is not None and mbps > MBPS_SEGURO_IMAGEN:
                v["dudas"].append(f"«{b['nombre']}» figura como audio pero pesa como imagen ({mbps:.0f} Mbps): revísalo.")
            elif mbps is not None:
                v["pruebas"].append("peso de sonido")
            continue
        # ---- imagen ----
        letra_nombre = k.get("letra", "") if k.get("tipo") in ("camara", "dron") else ""
        letra_pdf = letra_de_cam(b.get("cam"))
        if k.get("tipo") and k["tipo"] != "sonido":
            v["tipo"] = k["tipo"]
            v["pruebas"].append("nombre de la tarjeta")
        mio = None
        for r in libres:                                   # su rollo en «Video Reels»: mismos clips, duración y peso
            if r["clips"] == b["clips"] - (b.get("audio_mezclado") or {}).get("clips", 0) and abs(r["seg"] - b["seg"]) <= 2 + (b.get("audio_mezclado") or {}).get("seg", 0) \
                    and abs(r["gb"] - b["gb"]) <= max(0.02, b["gb"] * 0.002) + (b.get("audio_mezclado") or {}).get("gb", 0) \
                    and (not r["cams"] or not b.get("cam") or b["cam"].upper() in {c.upper() for c in r["cams"]}):
                mio = r
                break
        letra_rollo = ""
        if mio:
            libres.remove(mio)
            kr = identificar_bin(mio["nombre"]) or {}
            letra_rollo = kr.get("letra", "") if kr.get("tipo") == "camara" and kr.get("marca") != "cámara con letra" else ""
            if len(mio["cams"]) == 1 and not letra_rollo:
                letra_rollo = letra_de_cam(mio["cams"][0])
            v["rollo_pdf"] = mio["nombre"]
            v["pruebas"].append("«Video Reels»")
            if v["rollo"] is None and kr.get("rollo") is not None:
                v["rollo"] = kr["rollo"]
            elif v["rollo"] is None and re.fullmatch(r"\d{1,4}", mio["nombre"] or ""):
                v["rollo"] = int(mio["nombre"])
            if not v["marca"] or v["marca"] == "cámara con letra":
                v["marca"] = kr.get("marca", "") if kr.get("marca") != "cámara con letra" else v["marca"]
        if b.get("cam"):
            v["tipo"] = v["tipo"] or "camara"
        votos = [x for x in (letra_nombre, letra_pdf, letra_rollo) if x]
        v["letra"] = letra_nombre or (max(set(votos), key=votos.count) if votos else "")
        if letra_pdf and letra_pdf == v["letra"]:
            v["pruebas"].append("cámara de «Bins»")
        if v["letra"] and not letra_nombre:
            b["letra"] = v["letra"]                        # nombre puesto a mano: la cámara la dicen «Bins» y «Video Reels»
        distintas = sorted({x for x in votos if x != v["letra"]})
        if distintas and letra_nombre:
            v["dudas"].append(f"«{b['nombre']}»: por su nombre es de la cámara {letra_nombre}, pero el PDF la anota en la cámara "
                              f"{' / '.join(distintas)}. La dejé en la {letra_nombre} (manda el nombre con que se descargó); revísalo.")
        if mbps is not None and mbps < MBPS_SEGURO_SONIDO and not b.get("audio_mezclado"):
            v["dudas"].append(f"«{b['nombre']}» figura como imagen pero pesa como sonido ({mbps:.1f} Mbps): revísalo.")
        elif mbps is not None and mbps > MBPS_SEGURO_IMAGEN:
            v["pruebas"].append("peso de imagen")
    # ---- cada cámara contra «Camera Sums» y contra el códec de «Video Formats» ----
    lineas = []
    de_cam = {}
    for b in bins:
        if not b.get("audio") and b.get("cam"):
            de_cam.setdefault(b["cam"], []).append(b)
    suma_ok = {}
    for cam, s_ in sumas.items():
        suyos = de_cam.get(cam) or []
        if not suyos:
            continue
        clips = sum(b["clips"] - (b.get("audio_mezclado") or {}).get("clips", 0) for b in suyos)
        gb = sum(b["gb"] - (b.get("audio_mezclado") or {}).get("gb", 0.0) for b in suyos)
        suma_ok[cam] = clips == s_["clips"] and abs(gb - s_["gb"]) <= max(0.02 * len(suyos) + 0.02, s_["gb"] * 0.006)
        if suma_ok[cam]:
            for b in suyos:
                b["verif"]["pruebas"].append("«Camera Sums»")
    por_marca = {}
    for f in formatos:
        if f["marca"]:
            por_marca.setdefault(f["marca"], [0.0, 0.0])
            por_marca[f["marca"]][0] += f["gb"]
            por_marca[f["marca"]][1] += f["margen"]
    for marca, (gb_m, margen) in por_marca.items():
        if marca in ("ProRes", "H.264 / H.265"):
            continue
        cams = [c for c, bs in de_cam.items() if any(marca in _marca_corta(b["verif"]["marca"]) for b in bs)]
        total = sum(sumas[c]["gb"] if c in sumas else sum(b["gb"] for b in de_cam[c]) for c in cams)
        if cams and abs(total - gb_m) <= margen + 0.006 * gb_m + 0.05:
            for c in cams:
                for b in de_cam[c]:
                    b["verif"]["pruebas"].append("códec de «Video Formats»")
                    b["verif"]["marca_ok"] = marca
        elif not cams:                                    # el nombre no decía la marca: una sola cámara pesa justo lo de ese códec
            solas = [c for c in de_cam if abs((sumas[c]["gb"] if c in sumas else sum(b["gb"] for b in de_cam[c])) - gb_m) <= margen + 0.006 * gb_m + 0.05]
            if len(solas) == 1:
                for b in de_cam[solas[0]]:
                    b["verif"]["pruebas"].append("códec de «Video Formats»")
                    b["verif"]["marca_ok"] = marca
    # ---- líneas para la pantalla: una por cámara, una para el sonido, y las dudas ----
    grupos = {}
    for b in bins:
        v = b["verif"]
        clave = "Sonido" if v["tipo"] == "sonido" else (f"Cámara {v['letra']}" if v["letra"] else b["nombre"])
        grupos.setdefault(clave, []).append(b)
    for clave, bs in grupos.items():
        en_todas = [x for x in dict.fromkeys(x for b in bs for x in b["verif"]["pruebas"]) if all(x in b["verif"]["pruebas"] for b in bs)]
        n = len(en_todas)
        marca = next((b["verif"].get("marca_ok") or "" for b in bs if b["verif"].get("marca_ok")), "")
        quien = clave + (f" ({marca})" if marca and clave.startswith("Cámara") else "")
        if n >= 2:
            lineas.append(("ok", f"{quien}: confirmada con {n} datos del PDF ({', '.join(en_todas)})."))
        elif n == 1:
            lineas.append(("info", f"{quien}: un solo dato del PDF la confirma ({en_todas[0]})."))
        else:
            lineas.append(("aviso", f"{quien}: el PDF no trae con qué confirmarla (ni cámara, ni rollo, ni cinta). Revisa que quede en el rollo correcto."))
    for b in bins:
        for d in b["verif"]["dudas"]:
            lineas.append(("info" if "manda el nombre" in d else "aviso", d))
    reporte["confirmaciones"] = lineas
    return lineas


def _separar_audio_de_camara(bins, sumas):
    """Un BIN de cámara que trae también los .wav del sonido (HDT DAY902: «Y001_1028BD 1» = 64 clips de video + 36 de audio).
    «Camera Sums» solo cuenta video: si la cámara tiene UN solo BIN y ese BIN trae más clips que su suma, el BIN se deja COMPLETO
    (así se descargó y así va al estatus de tarjetas) y se anota `audio_mezclado` = la parte que no es video: el estadístico y el
    Resumen la cuentan como AUDIO y la cámara solo con su video. Devuelve los avisos."""
    avisos = []
    for cam, s in sumas.items():
        suyos = [b for b in bins if b["cam"] and b["cam"].rstrip("_").upper() == cam.rstrip("_").upper() and b.get("audio") is not True]
        if len(suyos) != 1 or suyos[0]["clips"] <= s["clips"]:
            continue
        b = suyos[0]
        extra = {"clips": b["clips"] - s["clips"], "seg": max(0, b["seg"] - s["seg"]), "gb": round(max(0.0, b["gb"] - s["gb"]), 2)}
        b["audio_mezclado"] = extra
        avisos.append(f"La tarjeta «{b['nombre']}» trae {s['clips']} clips de video de la cámara {cam.rstrip('_')} ({texto_gb(s['gb'])}) y "
                      f"{extra['clips']} de audio ({texto_gb(extra['gb'])}) en la misma descarga. En el estatus de tarjetas queda completa, "
                      f"como se descargó ({b['clips']} clips, {texto_gb(b['gb'])}); en el estadístico y en el Resumen se separan: "
                      f"CAM {cam.rstrip('_')} {texto_gb(s['gb'])} y AUDIO {texto_gb(extra['gb'])}.")
    return avisos


def texto_gb(gb):
    """0.55 → «550 MB» · 389.76 → «389.76 GB»."""
    return f"{gb * 1000:.0f} MB" if 0 < gb < 1 else f"{gb:.2f} GB"


_leer_reporte_crudo = leer_reporte


def leer_reporte(ruta, texto=None):
    """Lee el PDF de Silverstack. Si un dato viene dañado (un número como «6..51») avisa con claridad en vez de romperse."""
    try:
        return _leer_reporte_crudo(ruta, texto)
    except ValueError as e:
        raise ErrorRegistro(f"El PDF trae un dato que no pude leer ({e}). Abre el PDF y revisa que esté completo; "
                            "si es el original de Silverstack, avísame cuál es y lo reviso.")


def revisar_unidad(reporte, pestana):
    """Un reporte de la unidad 2 (…_U2) no debe ir a la pestaña de la unidad 1. Devuelve un mensaje de error si la pestaña elegida no
    parece de esa unidad, o None si todo cuadra (o si es la unidad 1)."""
    n = reporte.get("unidad", 1)
    if n <= 1:
        return None
    t = _sin_acentos(pestana)
    pistas = {2: ("SECOND", "SEGUNDA", "2ND", "2DA"), 3: ("THIRD", "TERCERA", "3RD", "3RA")}.get(n, ())
    if any(p in t for p in pistas) or re.search(rf"(?<![A-Z0-9])(U|UNIT|UNIDAD)\s*0?{n}(?![0-9])", t):
        return None
    return (f"Este reporte es de la unidad {n} (…_U{n}), pero la pestaña elegida («{pestana}») no parece de esa unidad. "
            "No escribí nada para no mezclar las unidades. Cambia la pestaña en Ajustes del proyecto → Hojas conectadas "
            f"(o crea un proyecto aparte para la unidad {n}).")


# =============================================================================
# 3. LEER EL HISTORIAL DE TU HOJA
# =============================================================================
def dia_normal(texto):
    """La etiqueta de un día escrita como la escriba tu hoja → «D###». D051 → D051 · 20261009_DAY051 → D051 · DAY_51 → D051 · 51 → D051 ·
    DAY51 LMA → D051 (con el lugar o la unidad al final).
    Si no parece un día, None."""
    if isinstance(texto, (int, float)) and not isinstance(texto, bool):
        return f"D{int(texto):03d}" if texto == int(texto) and 0 < texto < 1000 else None      # hojas que numeran el día (1, 2, 3…)
    t = str(texto).strip() if isinstance(texto, str) else ""
    m = (re.fullmatch(r"D(\d{3})", t, re.I) or re.fullmatch(r"(?:\d{8}_)?(?:DAY|DIA|DÍA)[_\s-]*0*(\d{1,3})(?:[_\s-]+[A-Z0-9]{1,8})*", t, re.I)
         or re.fullmatch(r"0*(\d{1,3})", t))
    return f"D{int(m.group(1)):03d}" if m and int(m.group(1)) > 0 else None


def leer_historial(valores, cfg, primera_fila=PRIMERA_FILA):
    """`valores`: las filas de datos de la pestaña (de `registro_google.leer_hoja`, con su formato aprendido; con fórmulas como texto).
    Devuelve qué días ya existen, el último # Mag y la última fila de cada rollo, en qué orden pone la hoja los rollos, los días
    (`bloques`) y cómo escribe esta hoja cada día (`estilo`)."""
    fmt = formato_de(valores)
    if not isinstance(valores, FilasHoja) and primera_fila != PRIMERA_FILA:
        fmt = dict(fmt, primera=primera_fila)
    bloques = bloques_de_hoja(valores, fmt)
    h = {"dias": {b["clave"] for b in bloques if b["material"] and b["clave"]}, "ultimo_mag": {}, "ultima_fila": {},
         "totales": [b["total"] for b in bloques if b["total"]], "fmt": fmt, "bloques": bloques,
         "ultima_fila_con_datos": max([b["total"] or b["filas"][-1] for b in bloques] or [fmt["primera"] - 1])}
    secuencias = []
    for b in bloques:
        if not b["material"]:
            continue
        actual = []
        for r in b["filas"]:
            fila = list(valores[r - fmt["primera"]])
            nombre = _celda(fila, fmt, "cam")
            if not (isinstance(nombre, str) and nombre.strip()):
                continue
            modelo_f = _celda(fila, fmt, "modelo")
            if es_modelo_de_audio(modelo_f) or (clave_modelo(modelo_f) and any(grupo_es_sonido(x) and clave_modelo(x.get("modelo")) == clave_modelo(modelo_f) for x in cfg["grupos"])):
                grupo = grupo_de_audio(nombre.strip(), cfg, modelo_f)          # la grabadora de ESA fila (688 ≠ 744)
            else:
                grupo = grupo_de(nombre.strip(), cfg)
            if grupo:
                if grupo["id"] not in actual:
                    actual.append(grupo["id"])
                h["ultima_fila"][grupo["id"]] = r
                mag = _celda(fila, fmt, "mag")
                if isinstance(mag, (int, float)) and not isinstance(mag, bool):
                    h["ultimo_mag"][grupo["id"]] = int(mag)
        if actual:
            secuencias.append(actual)
    posiciones = {}
    for seq in secuencias:
        if len(seq) > 1:
            for k, gid in enumerate(seq):
                posiciones.setdefault(gid, []).append(k / len(seq))
    h["orden"] = {gid: sum(p) / len(p) for gid, p in posiciones.items()}
    h["estilo"] = estilo_de_hoja(valores, fmt, bloques, cfg)
    # filas vacías justo debajo de los títulos (para escribir el PRIMER día de una hoja nueva sin insertar filas)
    libres = 0
    claves_ = [k for k in ("dia", "cam", "clips", "duracion", "gb") if k in fmt["col"]]
    for fila in list(valores) + [[]] * 200:
        if libres >= 200 or not all(_vacio(_celda(list(fila) + [""] * fmt["ncol"], fmt, k)) for k in claves_):
            break
        libres += 1
    h["libres_arriba"] = libres
    return h


def _numero_y_base(nombre):
    """'H004' → (4, 'H004'); 'N004_1' → (4, 'N004'); 'DJI_001_H15' → (15, 'DJI_001_H15'); sin número (sonido) → (None, nombre)."""
    t = str(nombre or "").strip()
    m = re.match(r"^[A-Za-z]_?(\d+)", t) or re.match(r"^[A-Za-z]{2,}_?\d{1,4}_[A-Za-z](\d+)", t)
    return (int(m.group(1)) if m else None), re.sub(r"[_\-]\d{1,2}$", "", t).upper()


def avisar_rollos_repetidos(valores, filas, cfg, primera_fila=PRIMERA_FILA):
    """Avisos si un rollo de las filas por escribir tiene el MISMO consecutivo que otro rollo distinto de la misma cámara que ya está
    en la hoja (H004 y H004B), o si el reporte mismo trae dos así. Es un error de nombre: cada rollo tiene un número único.
    (El mismo rollo continuando otro día no es repetido; N004_1 cuenta como N004.)"""
    fmt = getattr(valores, "fmt", None) or FORMATO_DSMD
    existentes = {}
    for fila in valores:
        fila = list(fila)
        nombre = _celda(fila, fmt, "cam")
        if not (isinstance(nombre, str) and nombre.strip()):
            continue
        grupo = grupo_de(nombre.strip(), cfg, audio=True if es_modelo_de_audio(_celda(fila, fmt, "modelo")) else None)
        n, base = _numero_y_base(nombre)
        if grupo and n is not None and not grupo_es_sonido(grupo):
            existentes.setdefault((grupo["id"], n), {})[base] = nombre.strip()
    avisos, vistos = [], {}
    nombres_g = {g["id"]: g["nombre"] for g in cfg["grupos"]}
    for f in filas:
        n, base = _numero_y_base(f["nombre"])
        if n is None or f.get("audio"):
            continue
        clave = (f["grupo"], n)
        otros = {b: nom for b, nom in existentes.get(clave, {}).items() if b != base}
        otros.update({b: nom for b, nom in vistos.get(clave, {}).items() if b != base})
        vistos.setdefault(clave, {})[base] = f["nombre"]
        if otros:
            avisos.append(f"Rollo repetido en {nombres_g.get(f['grupo'], '')}: «{f['nombre']}» tiene el mismo consecutivo ({n}) que "
                          f"«{', '.join(sorted(otros.values()))}». Cada rollo debe tener un número único; revisa cuál está mal escrito antes de guardar.")
    return avisos


# =============================================================================
# 3. EL FORMATO DE TU HOJA (se aprende de lo que ya está escrito)
#    Cada estatus de tarjetas se parece, pero no es igual: la fila de títulos cambia (fila 3, fila 7…), hay columnas que no existen
#    (sin RENTAL o sin # Mag), el día se escribe «D049», «20261016_DAY049» o «49», en la primera fila del día o en todas, la fecha
#    como fecha, «2026/10/16» o 20261016, y el total del día suma todo o solo el video, con o sin un texto «TOTAL…».
#    Aquí se aprende todo eso del último día ya escrito, para escribir el nuevo IGUAL.
# =============================================================================
class FilasHoja(list):
    """Las filas de datos de la pestaña (desde la fila siguiente a los títulos). `fmt` = {primera, col, ncol} (o None si no hay títulos)."""
    fmt = None


FORMATO_DSMD = {"primera": PRIMERA_FILA, "col": {"dia": 0, "fecha_col": 1, "rental": 2, "cam": 3, "modelo": 4, "mag": 5,
                                                  "clips": 6, "duracion": 7, "gb": 8}, "ncol": 10}
COLUMNAS_DE_VALOR = ("clips", "duracion", "gb")


def columnas_de_tabla(titulos, col):
    """Completa las columnas con las de números: # of Clips, Duración y Total GB (en español o inglés)."""
    col = dict(col)
    for j, x in enumerate(titulos):
        t = _sin_acentos(x) if isinstance(x, str) else ""
        if "CLIPS" in t and "clips" not in col:
            col["clips"] = j
        elif (t.startswith("DURACION") or t.startswith("DURATION")) and "duracion" not in col:
            col["duracion"] = j
        elif ("GB" in t.split() or t.endswith("GB") or t in ("SIZE", "TAMANO", "PESO")) and "gb" not in col:
            col["gb"] = j
        elif t in ("SEMANA", "WEEK") and "semana" not in col:
            col["semana"] = j
    return col


def tabla_de_hoja(filas):
    """`filas`: la pestaña completa desde la fila 1 (con fórmulas). Devuelve FilasHoja con las filas de datos y su formato."""
    hallado = encontrar_encabezado(filas)
    if not hallado:
        r = FilasHoja(filas[PRIMERA_FILA - 1:])
        r.fmt = None
        return r
    i0, col = hallado
    col = columnas_de_tabla(filas[i0], col)
    titulos = [str(x).strip() for x in filas[i0]]
    while titulos and not titulos[-1]:
        titulos.pop()
    r = FilasHoja(filas[i0 + 1:])
    r.fmt = {"primera": i0 + 2, "col": col, "ncol": max(len(titulos), max(col.values()) + 1)}
    return r


def formato_de(valores):
    fmt = getattr(valores, "fmt", None)
    if fmt is None and isinstance(valores, FilasHoja):
        raise ErrorRegistro("No encontré los títulos de la tabla del estatus de tarjetas (DIA RODAJE, CAM, # of Clips, Total GB…). "
                            "¿Es la pestaña correcta?")
    fmt = fmt or FORMATO_DSMD
    falta = [n for k, n in (("cam", "CAM"), ("clips", "# of Clips"), ("duracion", "Duración"), ("gb", "Total GB")) if k not in fmt["col"]]
    if falta:
        raise ErrorRegistro("Tu estatus de tarjetas no tiene la(s) columna(s) " + ", ".join(f"«{x}»" for x in falta) +
                            ". No escribí nada para no dañar la hoja.")
    return fmt


def _celda(fila, fmt, clave):
    c = fmt["col"].get(clave)
    return fila[c] if c is not None and c < len(fila) else ""


def celda_en(valores, r, clave):
    """El valor de la columna `clave` («mag», «gb»…) en la fila `r` de la hoja (numerada desde 1)."""
    fmt = getattr(valores, "fmt", None) or FORMATO_DSMD
    i = r - fmt["primera"]
    return _celda(list(valores[i]), fmt, clave) if 0 <= i < len(valores) else None


def _vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _es_fila_total(fila, fmt):
    """Fila de total del día: sin nombre de tarjeta y con números (o con un texto «TOTAL…»)."""
    if not _vacio(_celda(fila, fmt, "cam")):
        return False
    if any(isinstance(v, str) and "TOTAL" in _sin_acentos(v) for v in fila):
        return True
    return any(not _vacio(_celda(fila, fmt, k)) for k in COLUMNAS_DE_VALOR)


def _clave_dia(etiqueta):
    return dia_normal(etiqueta)


def _fila_es_audio(fila, fmt, cfg):
    nombre, modelo = _celda(fila, fmt, "cam"), _celda(fila, fmt, "modelo")
    if es_modelo_de_audio(modelo) or es_nombre_de_sonido(str(nombre or "")):
        return True
    if cfg and isinstance(nombre, str) and nombre.strip():
        g = grupo_de(nombre.strip(), cfg)
        return bool(g and grupo_es_sonido(g))
    return False


def bloques_de_hoja(valores, fmt):
    """Los días de la hoja, en orden: [{clave (D###), etiqueta, filas: [r…], total: r|None, material: bool}].
    Un día «preparado de antemano» (con etiqueta, rental o equipo pero sin tarjetas ni números) tiene material=False."""
    bloques, actual = [], None
    for i, fila in enumerate(valores):
        r = fmt["primera"] + i
        fila = list(fila)
        if _es_fila_total(fila, fmt):
            if actual is not None and actual["total"] is None:
                actual["total"] = r
            continue
        et = _celda(fila, fmt, "dia")
        cam = _celda(fila, fmt, "cam")
        tiene_et = not _vacio(et) and _clave_dia(et) is not None
        de_datos = not _vacio(cam) or (tiene_et and not (_vacio(_celda(fila, fmt, "rental")) and _vacio(_celda(fila, fmt, "modelo"))))
        if not de_datos:
            continue                                        # vacía, o solo la columna Semana, o un número suelto
        if actual is None or actual["total"] is not None or (tiene_et and _clave_dia(et) != actual["clave"]):
            actual = {"clave": _clave_dia(et) if tiene_et else None, "etiqueta": et if tiene_et else "", "filas": [], "total": None,
                      "material": False}
            bloques.append(actual)
        if actual["clave"] is None and tiene_et:
            actual["clave"], actual["etiqueta"] = _clave_dia(et), et
        actual["filas"].append(r)
        numeros = [_celda(fila, fmt, k) for k in COLUMNAS_DE_VALOR]
        if not _vacio(cam) and any(isinstance(v, (int, float)) and not isinstance(v, bool) and v or isinstance(v, str) and v.strip()
                                   for v in numeros):
            actual["material"] = True
    return bloques


_REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")


def _letra(c):
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _filas_de_formula(formula, columna):
    """Qué filas de la columna suma una fórmula («=SUM(G5:G10)», «=SUM(G5:G9,G11)», «=G5+G6»). None si no es una suma simple."""
    f = formula.upper().replace(" ", "")
    resto = re.sub(r"SUBTOTAL\(9,|SUMA\(|SUM\(|[()]", "", f.lstrip("="))
    if not re.fullmatch(r"[A-Z$0-9:,+]*", resto):
        return None
    filas = set()
    letra = _letra(columna)
    for c1, r1, _c2, r2 in _REF.findall(resto):
        if c1 != letra:
            continue
        r1 = int(r1)
        r2 = int(r2) if r2 else r1
        filas.update(range(min(r1, r2), max(r1, r2) + 1))
    return filas


def _numero_de(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _clase_de_cobertura(cubiertas, filas, audio):
    filas = set(filas)
    video = filas - set(audio)
    tocadas = cubiertas & filas
    if tocadas == filas or (cubiertas >= filas):
        return "todas"
    if video and tocadas == video:
        return "sin_audio"
    if audio and tocadas == set(audio) & filas:
        return "solo_audio"
    return "todas"


def _convencion_fecha(muestras):
    """Cómo escribe ESTA hoja la fecha del día: ('serial'|'yyyymmdd'|'ddmmyyyy'|'texto8'|'texto', detalle)."""
    # Hoja con fechas MEZCLADAS: unas como texto «27/10/2026» y otras como fecha de Google (CODT). Pasa en hojas con formato de
    # EE. UU.: la gente escribe día/mes y Google solo convierte a fecha las que pueden ser mes/día (≤ 12). La app escribe como la
    # gente (texto día/mes con ceros) y Google la guarda exactamente igual que las demás.
    textos = [str(v).strip() for v in muestras if isinstance(v, str) and re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", str(v).strip())]
    seriales = [v for v in muestras if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000]
    if textos and seriales:
        orden = "dmy"
        for x in textos:
            a_, b_ = (int(t) for t in re.split(r"[/.-]", x)[:2])
            if b_ > 12 >= a_:
                orden = "mdy"
                break
            if a_ > 12:
                break
        partes = [p for x in textos for p in re.split(r"[/.-]", x)[:2]]
        chicos = [p for p in partes if int(p) < 10]
        ceros = any(p.startswith("0") for p in chicos) if chicos else True
        sep = re.search(r"[/.-]", textos[-1]).group(0)
        return "texto", {"sep": sep, "orden": orden, "ceros": ceros, "anio2": len(re.split(r"[/.-]", textos[-1])[2]) == 2}
    for v in muestras:
        if isinstance(v, bool) or _vacio(v):
            continue
        if isinstance(v, (int, float)):
            n = int(v)

            def fecha_ok(a, m_, d):
                try:
                    datetime(a, m_, d)
                    return 1900 <= a <= 2100
                except ValueError:
                    return False
            ymd = 19000101 <= n <= 21001231 and fecha_ok(n // 10000, n // 100 % 100, n % 100)
            dmy = 1010000 <= n <= 31129999 and len(str(n)) in (7, 8) and fecha_ok(n % 10000, n // 10000 % 100, n // 1000000)
            if ymd and not dmy:
                return "yyyymmdd", None
            if dmy:
                return "ddmmyyyy", None
            return "serial", None
        t = str(v).strip()
        if re.fullmatch(r"\d{8}", t):
            return "texto8", None
        m = re.fullmatch(r"(\d{1,4})([/.-])(\d{1,2})\2(\d{2,4})", t)
        if m:
            textos = [str(x).strip() for x in muestras if isinstance(x, str)]
            if len(m.group(1)) == 4:
                orden = "ymd"
            else:
                orden = "dmy"
                for x in textos:
                    mm = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", x)
                    if mm and int(mm.group(1)) > 12:
                        orden = "dmy"
                        break
                    if mm and int(mm.group(2)) > 12:
                        orden = "mdy"
                        break
            ceros = any(re.fullmatch(r"0\d[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}[/.-]0\d[/.-]\d{2,4}|\d{4}[/.-]0\d[/.-]\d{1,2}", x) for x in textos)
            return "texto", {"sep": m.group(2), "orden": orden, "ceros": ceros or orden == "ymd", "anio2": len(m.group(4)) == 2}
    return "serial", None


def valor_de_fecha_hoja(fecha, convencion):
    tipo, det = convencion
    if tipo == "yyyymmdd":
        return int(f"{fecha.year}{fecha.month:02d}{fecha.day:02d}")
    if tipo == "ddmmyyyy":
        return int(f"{fecha.day:02d}{fecha.month:02d}{fecha.year}")
    if tipo == "texto8":
        return f"{fecha.year}{fecha.month:02d}{fecha.day:02d}"
    if tipo == "texto":
        d = f"{fecha.day:02d}" if det["ceros"] else str(fecha.day)
        m = f"{fecha.month:02d}" if det["ceros"] else str(fecha.month)
        y = str(fecha.year)[2:] if det["anio2"] else str(fecha.year)
        partes = {"ymd": (str(fecha.year), m, d), "dmy": (d, m, y), "mdy": (m, d, y)}[det["orden"]]
        return det["sep"].join(partes)
    return (fecha - datetime(1899, 12, 30)).days


def etiqueta_de_dia(plantilla, reporte):
    """La etiqueta del día nuevo escrita como las de tu hoja: «D048» → «D049», «20261015_DAY048» → «20261016_DAY049»,
    «48» → 49 (número), «DAY_048_U2» → «DAY_049_U2». Si no se entiende la de la hoja, «D049»."""
    n = int(reporte["dia"][1:])
    if isinstance(plantilla, (int, float)) and not isinstance(plantilla, bool):
        return n
    t = str(plantilla or "").strip()
    if not t:
        return reporte["dia"]
    if re.fullmatch(r"\d+", t):
        return str(n).zfill(len(t))
    fecha = reporte["fecha"]

    def poner_fecha(m):
        try:
            datetime.strptime(m.group(0), "%Y%m%d")
            return f"{fecha:%Y%m%d}"
        except ValueError:
            return m.group(0)
    nuevo = re.sub(r"(?<!\d)\d{8}(?!\d)", poner_fecha, t)
    m = re.search(r"(?i)(?<![A-Z])(DAY|D[IÍ]A|D)([_\s-]*)(\d+)", nuevo)
    if not m:
        return reporte["dia"]
    nuevo = nuevo[:m.start(3)] + str(n).zfill(len(m.group(3))) + nuevo[m.end(3):]
    return nuevo if dia_normal(nuevo) == reporte["dia"] else reporte["dia"]


def estilo_de_fabrica():
    """Hoja nueva SIN ningún día (HDT el primer día): no hay de dónde aprender, así que se escribe como las hojas FilmFlow (DSMD):
    la etiqueta del día como la trae el PDF (D901), la fecha solo en la primera fila (dd/mm/aaaa), y una fila de TOTAL con fórmulas
    que suman clips, duración y GB. Desde el segundo día la app aprende de lo que quedó escrito (o de lo que la persona cambie)."""
    return {"etiqueta": None, "et_todas": False, "fecha_todas": False, "fecha": ("serial", None), "bloque_ref": None,
            "total": {"fila_ref": None, "textos": {},
                      "columnas": {k: {"modo": "formula", "suma": "todas"} for k in COLUMNAS_DE_VALOR}},
            "de_fabrica": True}


def estilo_de_hoja(valores, fmt, bloques, cfg=None):
    """Cómo escribe esta hoja cada día, aprendido del último día con material (y con fila de total, si hay)."""
    con_material = [b for b in bloques if b["material"]]
    if not con_material:
        return estilo_de_fabrica()
    recientes = con_material[-4:]                       # lo que hacen los últimos días manda (hay hojas que cambian a mitad de rodaje)
    usa_total = sum(1 for b in recientes if b["total"]) * 2 >= len(recientes)
    ref = next((b for b in reversed(recientes) if b["total"]), recientes[-1]) if usa_total else recientes[-1]

    def fila(r):
        return list(valores[r - fmt["primera"]]) + [""] * fmt["ncol"]
    filas = ref["filas"]
    et_todas = any(not _vacio(_celda(fila(r), fmt, "dia")) for r in filas[1:])
    fecha_todas = "fecha_col" in fmt["col"] and any(not _vacio(_celda(fila(r), fmt, "fecha_col")) for r in filas[1:])
    muestras = [_celda(fila(r), fmt, "fecha_col") for b in con_material[-10:] for r in b["filas"][:1]] if "fecha_col" in fmt["col"] else []
    estilo = {"etiqueta": _celda(fila(filas[0]), fmt, "dia"), "et_todas": et_todas, "fecha_todas": fecha_todas,
              "fecha": _convencion_fecha(muestras), "bloque_ref": ref, "total": None}
    if usa_total and ref["total"]:
        ft = fila(ref["total"])
        cols_valor = {fmt["col"][k] for k in COLUMNAS_DE_VALOR}
        textos = {c: v for c, v in enumerate(ft[:fmt["ncol"]]) if isinstance(v, str) and v.strip() and not v.startswith("=")
                  and c not in cols_valor and c != fmt["col"].get("semana")}

        def como_suma(b, k):
            """Qué suma (y cómo) la columna `k` en la fila de total del día `b`."""
            filas_b = b["filas"]
            audio = {r for r in filas_b if _fila_es_audio(fila(r), fmt, cfg)}
            c = fmt["col"][k]
            v = fila(b["total"])[c]
            if isinstance(v, str) and v.startswith("="):
                cubiertas = _filas_de_formula(v, c)
                return {"modo": "formula", "suma": _clase_de_cobertura(cubiertas, filas_b, audio) if cubiertas else "todas"}
            if _numero_de(v) is not None:
                por_fila = {r: _numero_de(_celda(fila(r), fmt, k)) or 0.0 for r in filas_b}
                video = [r for r in filas_b if r not in audio]
                sumas = {"todas": sum(por_fila.values()), "sin_audio": sum(por_fila[r] for r in video),
                         "solo_audio": sum(por_fila[r] for r in audio)}
                return {"modo": "valor", "suma": min(sumas, key=lambda s: abs(sumas[s] - _numero_de(v)))}
            if _vacio(v):
                return {"modo": "nada", "suma": "todas"}
            return {"modo": "formula", "suma": "todas"}                     # #REF! u otro error: se escribe la suma de todo
        # Lo que hace la MAYORÍA de los días recientes (en el último puede haber un error a mano); si empatan, el más reciente.
        con_total_ = [b for b in recientes if b["total"]]
        columnas = {}
        for k in COLUMNAS_DE_VALOR:
            votos = [como_suma(b, k) for b in con_total_]
            cuenta = {}
            for v_ in votos:
                cuenta[(v_["modo"], v_["suma"])] = cuenta.get((v_["modo"], v_["suma"]), 0) + 1
            mejor = max(cuenta.values())
            elegido = next(v_ for v_ in reversed(votos) if cuenta[(v_["modo"], v_["suma"])] == mejor)
            columnas[k] = elegido
        estilo["total"] = {"fila_ref": ref["total"], "textos": textos, "columnas": columnas}
    return estilo


def _formula_suma(columna, filas_):
    if not filas_:
        return 0
    filas_ = sorted(filas_)
    partes, ini, fin = [], filas_[0], filas_[0]
    for r in filas_[1:] + [None]:
        if r is not None and r == fin + 1:
            fin = r
            continue
        letra = _letra(columna)
        partes.append(f"{letra}{ini}" if ini == fin else f"{letra}{ini}:{letra}{fin}")
        if r is not None:
            ini = fin = r
    return "=SUM(" + ",".join(partes) + ")"


# =============================================================================
# 3b. DESCUBRIR LOS ROLLOS QUE YA EXISTEN EN UNA HOJA
#     Lee las filas de una pestaña y deduce cuáles rollos (cámaras, sonido…) hay,
#     con su rental, modelo, ciclo de # Mag y en qué orden aparecen.
# =============================================================================
COLUMNAS_POR_DEFECTO = {"dia": 0, "rental": 2, "cam": 3, "modelo": 4, "mag": 5}


def _sin_acentos(t):
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(ch for ch in t if not unicodedata.combining(ch)).strip().upper()


def columnas_de_encabezado(fila):
    """Qué columna es cada cosa, leyendo los títulos de una fila: {'cam': 3, 'rental': 2, …}.
    Entiende los títulos en español y en inglés (DIA/DAY, FECHA/DATE, DURACION/DURATION, MODELO/CAM ID…)."""
    mapa = {}
    for i, celda in enumerate(fila):
        if not isinstance(celda, str):
            continue
        t = _sin_acentos(celda)
        t = re.sub(r"\s+", " ", t)
        if t in ("CAM", "CAMARA", "CAMARAS", "BIN", "CAMERA", "CAMERAS", "CARD", "CARDS", "TARJETA", "TARJETAS") and "cam" not in mapa:
            mapa["cam"] = i
        elif "RENTAL" in t and "rental" not in mapa:
            mapa["rental"] = i
        elif ("MODELO" in t or t in ("CAM ID", "CAMERA ID", "CAMERA MODEL", "MODEL", "EQUIPO", "EQUIPMENT")) and "modelo" not in mapa:
            mapa["modelo"] = i
        elif re.search(r"(^|[^A-Z])MAGS?([^A-Z]|$)", t) and "mag" not in mapa:
            mapa["mag"] = i
        elif (t.startswith("DIA") or t in ("DAY", "SHOOTING DAY", "SHOOT DAY", "JORNADA")) and "dia" not in mapa:
            mapa["dia"] = i
        elif (t.startswith("FECHA") or t in ("DATE", "SHOOTING DATE")) and "fecha_col" not in mapa:
            mapa["fecha_col"] = i
    return mapa


def encontrar_encabezado(filas, limite=40):
    """Busca la fila de títulos de la tabla (la que tiene «CAM» junto a «RENTAL», «MODELO» o «# Mag»).
    Devuelve (índice_de_esa_fila, columnas) o None."""
    for i, fila in enumerate(filas[:limite]):
        mapa = columnas_de_encabezado(fila)
        if "cam" in mapa and len(mapa) >= 3:
            return i, mapa
        if "cam" in mapa and len(mapa) == 2:            # hoja mínima: DIA RODAJE · CAM · # of Clips · Duración · Total GB (sin fecha, rental ni modelo)
            try:
                completo = columnas_de_tabla(fila, dict(mapa))
            except ErrorRegistro:
                continue
            if "gb" in completo and ("clips" in completo or "duracion" in completo):
                return i, mapa
    return None


_PALABRAS_DE_FORMATO = {
    "CARDS", "CARD", "STATUS", "ESTATUS", "TARJETAS", "TARJETA", "FORMATO", "ESTADISTICO", "ESTADISTICA", "ESTADISTICOS", "RESUMEN", "GENERAL",
    "DATOS", "DATA", "DIT", "SHOOTING", "DAY", "DIA", "REPORT", "REPORTE", "MEDIA", "DOWNLOAD", "DESCARGA", "DESCARGAS", "LOG", "SHEET", "HOJA",
    "FF", "GS", "FO", "STATS", "STATISTICS", "MANAGER", "MANAGEMENT", "UNIT", "UNIDAD", "MAIN", "SECOND", "SEGUNDA", "PRINCIPAL", "DE", "DEL",
    "LA", "EL", "Y", "SEMANA", "WEEK", "DAILIES", "OCF", "COPIA", "COPY", "NUEVO", "NUEVA", "PLANTILLA", "TEMPLATE", "UNTITLED", "SIN", "TITULO",
    "SHEET1", "HOJA1", "BACKUP", "ARCHIVO", "ARCHIVOS"}


def _palabras(texto):
    return re.findall(r"[A-Z0-9]+", _sin_acentos(str(texto)).upper())


def _es_nombre_de_formato(texto):
    """«CARDS STATUS», «ESTATUS TARJETAS», «UNIT 2», «RESUMEN GENERAL»: dicen qué es la hoja, no cómo se llama el proyecto."""
    palabras = _palabras(texto)
    if not palabras:
        return True
    return all(p in _PALABRAS_DE_FORMATO or re.fullmatch(r"(U|UNIT|UNIDAD|D|DAY|DIA)?\d{1,3}", p) for p in palabras)


def _palabras_propias(texto):
    return {p for p in _palabras(texto) if len(p) >= 3 and p not in _PALABRAS_DE_FORMATO and not p.isdigit()}


def titulo_de_proyecto(filas_superiores, pistas=()):
    """El nombre del proyecto escrito arriba de la tabla, sin importar en qué celda esté (p. ej. «DESMADRE U1»
    o «PRIMERA PLANA - HIJO DE TIGRE - NETFLIX»). Se descarta lo que es el nombre del formato («CARDS STATUS»,
    «ESTATUS DE TARJETAS»), una etiqueta (Código, Versión, Fecha…) o un valor suelto. Si quedan varios candidatos
    gana el que comparte palabras con las `pistas` (el nombre de la pestaña, el del archivo) y, si no, el más cercano a los títulos.
    Sin nada arriba, sirve de nombre la pestaña si no es genérica."""
    etiquetas = ("ESTATUS", "FF-GS", "TARJETAS", "FORMATO", "CODIGO", "VERSION", "FECHA", "PAGINA", "REVISION",
                 "DIA RODAJE", "RENTAL", "TOTAL", "ELABORO", "APROBO")
    propias = set()
    for p in pistas:
        propias |= _palabras_propias(p)
    candidatos = []
    for fila in reversed(list(filas_superiores)):
        for celda in fila:
            if isinstance(celda, str) and len(celda.strip()) >= 3 and not celda.startswith("="):
                t = _sin_acentos(celda)
                if any(e in t for e in etiquetas) or re.fullmatch(r"[\d\W_]+", t) or _es_nombre_de_formato(celda):
                    continue
                texto = " ".join(celda.split())
                if texto not in candidatos:
                    candidatos.append(texto)
    if candidatos:
        def puntos(i):
            texto = candidatos[i]
            return (10 if _palabras_propias(texto) & propias else 0) + (1 if len(_palabras(texto)) >= 2 else 0) - 0.5 * i
        return candidatos[max(range(len(candidatos)), key=puntos)]
    for p in pistas[:1]:                                  # la pestaña: «LA CASAMENTERA» sí es un nombre; «PP_MAIN_UNIT» o «Hoja 1» no
        nombre = " ".join(str(p).replace("_", " ").split())
        if nombre and not _es_nombre_de_formato(nombre) and len(_palabras_propias(nombre)) >= 1 and len(nombre) >= 4:
            return nombre
    return ""


def _nombre_amigable(patrones, modelo):
    """Un nombre legible para un rollo raro, sin # ni guiones: 'AMBIENTES_U#' -> 'Ambientes';
    'H###' (una sola letra) -> 'Cámara H'."""
    palabra = re.match(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", patrones[0])
    palabra = palabra.group(0) if palabra else ""
    if len(palabra) >= 3:
        return palabra.capitalize()
    if len(palabra) == 1:                      # H001, K001_E00N16 -> es una cámara con esa letra
        return f"Cámara {palabra.upper()}"
    if modelo:
        return " ".join(w if len(w) <= 3 and w.isupper() else w.capitalize() for w in modelo.split())
    return "Rollo nuevo"


_SONIDO_NOMBRE = re.compile(r"^\s*(audio|sonido|sound)(\W|\d|_|$)", re.IGNORECASE)


def es_nombre_de_sonido(nombre):
    """«Audio», «AUDIO_01», «Sonido»: así se llama el audio en algunas hojas (en vez de 26Y10M01)."""
    return bool(_SONIDO_NOMBRE.match(str(nombre or "")))


_MODELO_AUDIO = re.compile(r"\b(zoom|sound\s*devices?|tascam|mix\s*pre|audio|sonido|recorder|grabadora|sound)\b", re.IGNORECASE)


def es_modelo_de_audio(modelo):
    """«ZOOM F8M PRO», «Sound Devices 833»: el equipo de la fila dice que es una grabadora de audio."""
    return bool(_MODELO_AUDIO.search(str(modelo or "")))


def clave_modelo(modelo):
    """«SOUND DEVICE 788T» y «Sound Devices 788T» son la misma grabadora: 788t."""
    t = re.sub(r"sound\s*devices?", "", str(modelo or "").lower())
    return re.sub(r"[^a-z0-9]+", "", t)


def modelo_corto(modelo):
    """«SOUND DEVICES 633» → «633» (para rotular el sonido por grabadora)."""
    t = re.sub(r"(?i)sound\s*devices?\s*", "", str(modelo or "")).strip()
    return t or str(modelo or "").strip()


def grupo_por_modelo(modelo, cfg):
    """El rollo (que no sea de sonido) cuyo equipo coincide con el de la fila, si es uno solo; si no, None.
    Sirve para un BIN con un nombre raro: se mira la columna del equipo («ALEXA 35») para saber a qué cámara pertenece."""
    m = re.sub(r"\s+", " ", str(modelo or "")).strip().upper()
    if not m:
        return None
    hallados = [g for g in cfg["grupos"] if not grupo_es_sonido(g)
                and re.sub(r"\s+", " ", str(g.get("modelo") or "")).strip().upper() == m]
    return hallados[0] if len(hallados) == 1 else None


def grupo_provisional(nombre, modelo=""):
    """Una tarjeta de una cámara con letra que NO está en los rollos de Ajustes (la agregó otra persona del equipo, o se escribió a
    mano en la hoja): se cuenta igual, como «Cámara B», en vez de mezclarla con otra cámara o dejarla por fuera. None si el nombre
    no dice de qué cámara es."""
    k = identificar_bin(nombre)
    if not k or k["tipo"] != "camara" or not k["letra"]:
        return None
    letra = k["letra"]
    return {"id": f"auto-cam-{letra}", "nombre": f"Cámara {letra}", "patrones": patrones_de_camara(letra), "rental": "",
            "modelo": str(modelo or "").strip(), "ciclo_mag": None, "color": "", "avisar_si_falta": False, "provisional": True}


def grupo_de_sonido(cfg):
    """El rollo de sonido de la configuración; si no hay ninguno, uno provisional («Sonido») para no perder el audio."""
    g = next((x for x in cfg["grupos"] if grupo_es_sonido(x)), None)
    return g or {"id": "sonido-auto", "nombre": "Sonido", "patrones": [], "rental": "", "modelo": "", "ciclo_mag": None,
                 "color": "", "avisar_si_falta": False}


def grupo_es_sonido(g):
    """El rollo es de sonido si lo dice su tipo (##Y##M) o si se reconoce por un nombre como «Audio»."""
    return _es_sonido(g.get("id"), tuple(g["patrones"]), g.get("nombre", ""))


@functools.lru_cache(maxsize=2048)
def _es_sonido(gid, patrones, nombre):                # con memoria: depende solo de estos tres datos
    return bool(gid == "sonido-auto" or _tipo_de_patrones(patrones)[0] == "sonido"
                or any(es_nombre_de_sonido(p) for p in patrones) or es_nombre_de_sonido(nombre))


def clave_de_bin(nombre, claves=None, completo=False):
    """La «cámara» de un BIN tal como la nombra el estadístico.
    A_0124_1EOH → A · D005_E00N15 → D · M001L → ML (cámara M, lado L) · A001C001 → A · BETACAM_TEST → BETACAM (cámara propia).
    Con `claves` (las columnas del estadístico: {'ML','MR','MC'}) se elige la que existe de verdad; si ninguna existe devuelve la
    más completa. Sin `claves`: la primera letra (o, con `completo`, la letra y el sufijo: ML)."""
    t = str(nombre or "").strip()
    emb = letra_incrustada(t)
    if emb:                                         # DJI_001_H10 es de la cámara H, no de una «cámara DJI»
        return emb[0]
    m = re.match(r"^([A-Za-z]+)_?(\d+)(?:([A-Za-z]{1,2})(?![A-Za-z0-9]))?", t)
    if not m:
        # Sin número: «BETACAM_TEST» es una cámara propia llamada BETACAM (no la cámara B); una sola letra se queda como está.
        palabra = re.match(r"[A-Za-z]+", t)
        return palabra.group().upper() if palabra and len(palabra.group()) >= 3 else t[:1].upper()
    pre, suf = m.group(1).upper(), (m.group(3) or "").upper()
    if len(pre) >= 3:                               # BETACAM_001, GOPRO_002: la palabra es la cámara (nunca su primera letra)
        candidatas = [pre + suf, pre] if suf else [pre]
        if claves:
            existentes = {str(k).upper() for k in claves}
            return next((c for c in candidatas if c in existentes), candidatas[0])
        return candidatas[0]
    candidatas = []
    for c in (pre + suf, pre[:1] + suf, pre, pre[:1]):
        if c and c not in candidatas:
            candidatas.append(c)
    if claves:
        existentes = {str(k).upper() for k in claves}
        for c in candidatas:
            if c in existentes:
                return c
        return candidatas[0]
    return pre[:1] + suf if completo else pre[:1]


def _ciclo_reciente(mags):
    """Cuántas tarjetas tiene el ciclo de # Mag, mirando cómo se reinició en las últimas vueltas (…5, 6, 1, 2…): el valor MÁS repetido
    entre los últimos reinicios. Un «7» suelto entre muchos ciclos de 6 (una tarjeta extra un día) no cambia el ciclo.
    Si empatan, el más reciente. Sin reinicios todavía, el valor más alto visto."""
    from collections import Counter
    topes = [a for a, b in zip(mags, mags[1:]) if b < a]          # el último número antes de volver a empezar
    if not topes:
        return max(mags)
    ultimos = Counter(topes[-6:])
    mejor = max(ultimos.values())
    return next(t for t in reversed(topes) if ultimos[t] == mejor)   # empate: el más reciente


def inferir_rollos(valores, primera_fila=PRIMERA_FILA, columnas=None):
    """`valores`: filas de datos de la pestaña (la primera es la fila `primera_fila`); `columnas` dice en qué
    columna está cada dato (se averigua leyendo los títulos; si falta, se usa el orden del formato). Devuelve una lista (en el orden en que
    aparecen en la hoja) de diccionarios: tipo, letra, otro, patrones, nombre, rental, modelo,
    ciclo_mag, avisar_si_falta, fila (primera fila donde aparece), ejemplo, filas."""
    from collections import Counter
    c = {**COLUMNAS_POR_DEFECTO, **(columnas or {})}
    if columnas:                                   # hoja con títulos pero sin RENTAL o # Mag (SSSHP4): esa columna no existe, no se lee otra en su lugar
        for k, falta in enumerate(("rental", "mag", "modelo", "dia")):
            if falta not in columnas:
                c[falta] = 90 + k
    hallados, dia_actual, dias_total = {}, None, set()
    # Nombres como A001CJJU_CINE: letra + número + un código que cambia en cada tarjeta. Ese código no distingue cámaras
    # (si no, cada tarjeta sería una «cámara» distinta). Solo se conserva cuando son pocos y cortos (M001L, M001R, M001C).
    colas = {}
    for fila in valores:
        v = fila[c["cam"]] if len(fila) > c["cam"] else ""
        m = re.match(r"^([A-Za-z])(\d+)([A-Za-z].*)$", v.strip()) if isinstance(v, str) else None
        if m:
            colas.setdefault(m.group(1).upper(), set()).add(m.group(3))
    colapsar = {l for l, t in colas.items() if len(t) > 4 or any(len(x) > 2 for x in t)}
    for i, fila in enumerate(valores):
        fila = list(fila) + [""] * (max(COLUMNAS, max(c.values()) + 1) - len(fila))
        a = fila[c["dia"]]
        nombre = fila[c["cam"]]
        if not isinstance(nombre, str) or not nombre.strip():
            continue                       # filas de total o vacías
        if a not in ("", None):
            dia_actual = str(a).strip()    # «D038», «20260803_DAY001», 3…
            dias_total.add(dia_actual)
        nombre = nombre.strip()
        tipo, letra, otro = adivinar_tipo(nombre)
        inicial = re.match(r"^([A-Za-z])_?\d", nombre)
        audio_modelo = es_modelo_de_audio(fila[c["modelo"]]) and not es_nombre_de_sonido(nombre)
        emb = letra_incrustada(nombre) if tipo != "sonido" and not es_nombre_de_sonido(nombre) else None
        try:
            if emb:
                tipo, letra, otro, inicial = "otro", "", emb[1], True       # DJI_001_H10: es de la cámara H
                patrones = (emb[1],)
            elif es_nombre_de_sonido(nombre):
                # «Audio» (u otro nombre así): es sonido, y se reconoce por ese nombre
                tipo, letra, otro, inicial = "sonido", "", "", None
                patrones = (re.split(r"[\d_]", nombre.strip(), maxsplit=1)[0] or nombre.strip(),)
            elif inicial and tipo != "sonido" and re.match(r"^[A-Za-z]\d+[A-Za-z]", nombre) and nombre[0].upper() in colapsar:
                tipo, letra, otro = "otro", "", nombre[0].upper() + "#"
                patrones = (otro,)
            elif inicial and tipo != "sonido":
                # todo lo que empieza con una letra y un número es una cámara con esa letra (A, B, D, I, J, M…)
                if tipo == "camara":
                    patrones = tuple(patrones_de_tipo(tipo, letra, otro))
                else:
                    tipo, letra, otro = "otro", "", sugerir_patron(nombre).rstrip("_")
                    patrones = (otro,)
            else:
                patrones = tuple(patrones_de_tipo(tipo, letra, otro))
        except ErrorRegistro:
            continue
        if audio_modelo and tipo != "sonido":
            # una grabadora (ZOOM…) que comparte letra con otra cosa (el dron D001): es un rollo de Sonido aparte,
            # aunque se reconozca con el mismo comienzo; al leer, el equipo de la fila decide a cuál va cada tarjeta
            tipo, letra, otro, inicial = "sonido", "", "", None
        mk = clave_modelo(fila[c["modelo"]]) if tipo == "sonido" else ""          # cada grabadora (788T, 633…) es su propio rollo de Sonido
        h = hallados.get((patrones, tipo == "sonido", mk))
        if h is None:
            h = hallados[(patrones, tipo == "sonido", mk)] = {"tipo": tipo, "letra": letra, "otro": otro, "patrones": list(patrones),
                                      "fila": primera_fila + i, "ejemplo": nombre, "filas": 0,
                                      "_rental": Counter(), "_modelo": Counter(), "_mags": [], "_dias": set(),
                                      "_letra": clave_de_bin(nombre, completo=True) if inicial and tipo != "sonido" else "",
                                      "_audio": 0}
        h["filas"] += 1
        if es_modelo_de_audio(fila[c["modelo"]]):
            h["_audio"] += 1
        for clave, col in (("_rental", c["rental"]), ("_modelo", c["modelo"])):
            v = fila[col]
            if clave == "_modelo" and isinstance(v, (int, float)) and not isinstance(v, bool) and v == int(v) and v > 0:
                v = str(int(v))                                # un modelo que es solo un número (la grabadora «688»)
            if isinstance(v, str) and v.strip():
                h[clave][v.strip()] += 1
        m = fila[c["mag"]]
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            h["_mags"].append(int(m))
        if dia_actual:
            h["_dias"].add(dia_actual)
    # filas de sonido sin el equipo escrito: se unen a la grabadora que más material tiene (con los mismos patrones, si la hay)
    sonidos = [(k, h) for k, h in hallados.items() if k[1]]
    con_equipo = [(k, h) for k, h in sonidos if k[2]]
    if con_equipo:
        for k, h in sonidos:
            if k[2]:
                continue
            mismos = [x for x in con_equipo if x[0][0] == k[0]] or con_equipo
            destino = max(mismos, key=lambda x: x[1]["filas"])[1]
            destino["filas"] += h["filas"]
            destino["fila"] = min(destino["fila"], h["fila"])
            destino["_audio"] += h["_audio"]
            destino["_mags"] += h["_mags"]
            destino["_dias"] |= h["_dias"]
            for q in ("_rental",):
                destino[q] += h[q]
            del hallados[k]
    varias_grabadoras = len({k[2] for k in hallados if k[1] and k[2]}) > 1
    salida = []
    for h in hallados.values():
        por_defecto = MAG_POR_TIPO.get(h["tipo"])
        if h["_mags"]:
            ciclo = _ciclo_reciente(h["_mags"])
            if por_defecto and ciclo < por_defecto and h["filas"] < por_defecto:
                ciclo = por_defecto          # todavía no se vio el ciclo completo
        else:
            ciclo = None
        modelo = h["_modelo"].most_common(1)[0][0] if h["_modelo"] else ""
        if h["_letra"]:
            nombre = f"Cámara {h['_letra']}"
        elif h["tipo"] == "sonido" and varias_grabadoras and modelo:
            nombre = f"Sonido · {modelo_corto(modelo)}"                # con varias grabadoras, cada una lleva su nombre
        else:
            nombre = NOMBRE_POR_TIPO.get(h["tipo"]) or _nombre_amigable(h["patrones"], modelo)
        h.update(nombre=nombre,
                 rental=h["_rental"].most_common(1)[0][0] if h["_rental"] else "",
                 modelo=modelo,
                 ciclo_mag=ciclo,
                 avisar_si_falta=bool(dias_total) and len(h["_dias"]) >= 0.5 * len(dias_total))
        for k in ("_rental", "_modelo", "_mags", "_dias", "_letra"):
            del h[k]
        salida.append(h)
    return _unir_iguales(salida)


def _unir_iguales(rollos):
    """Si varios hallazgos tienen el MISMO nombre (Cámara D: «D#» y «D###»), son la misma cámara: se unen sus formas de reconocerla.
    Un rollo cuyas tarjetas son todas de una grabadora de audio (ZOOM…) se llama Sonido."""
    unidos = {}
    for r in rollos:
        clave = r["nombre"]
        u = unidos.get(clave)
        if u is None:
            unidos[clave] = u = {**r, "patrones": list(r["patrones"]), "_audio": r.get("_audio", 0), "_mejor": r["filas"]}
            continue
        for p in r["patrones"]:
            if p not in u["patrones"]:
                u["patrones"].append(p)
        u["filas"] += r["filas"]
        u["_audio"] += r.get("_audio", 0)
        u["fila"] = min(u["fila"], r["fila"])
        u["avisar_si_falta"] = u["avisar_si_falta"] or r["avisar_si_falta"]
        if r["ciclo_mag"] and (not u["ciclo_mag"] or r["ciclo_mag"] > u["ciclo_mag"]):
            u["ciclo_mag"] = r["ciclo_mag"]
        if r["filas"] > u["_mejor"]:
            u["_mejor"] = r["filas"]
            for k in ("rental", "modelo"):
                if r[k]:
                    u[k] = r[k]
    salida = []
    for u in unidos.values():
        if u["tipo"] != "sonido" and u["filas"] and u["_audio"] == u["filas"]:
            u.update(tipo="sonido", nombre=NOMBRE_POR_TIPO["sonido"])
        u.pop("_audio", None)
        u.pop("_mejor", None)
        salida.append(u)
    return salida


def combinar_hallazgos(listas):
    """`listas`: [(pestaña, [rollos de inferir_rollos])] con la pestaña principal primero.
    Une los que se repiten entre pestañas y anota en cuáles están (`pestanas`)."""
    unidos = {}
    for pestana, rollos in listas:
        for r in rollos:
            clave = tuple(r["patrones"]) + ((r["nombre"], clave_modelo(r["modelo"])) if r["tipo"] == "sonido" else ())      # dos grabadoras con el mismo patrón son dos rollos
            if clave not in unidos:
                unidos[clave] = {**r, "pestanas": [pestana], "pestana_fila": pestana}
            else:
                unidos[clave]["pestanas"].append(pestana)
    # el mismo rollo visto con formas distintas en cada unidad (Cámara H: «H###» en una y «DJI_###_H#» en otra) es UNO solo
    por_nombre = {}
    for r in unidos.values():
        k = r["nombre"] if r["tipo"] != "sonido" else (r["nombre"], clave_modelo(r["modelo"]), tuple(r["patrones"]))
        u = por_nombre.get(k)
        if u is None:
            por_nombre[k] = r
            continue
        for p in r["patrones"]:
            if p not in u["patrones"]:
                u["patrones"].append(p)
        for p in r["pestanas"]:
            if p not in u["pestanas"]:
                u["pestanas"].append(p)
        u["filas"] += r["filas"]
        for q in ("rental", "modelo"):
            if not u[q] and r[q]:
                u[q] = r[q]
        if r["ciclo_mag"] and (not u["ciclo_mag"] or r["ciclo_mag"] > u["ciclo_mag"]):
            u["ciclo_mag"] = r["ciclo_mag"]
    salida = list(por_nombre.values())
    sonidos = [r for r in salida if r["tipo"] == "sonido"]
    if len({clave_modelo(r["modelo"]) for r in sonidos if clave_modelo(r["modelo"])}) > 1:      # varias grabadoras (cada pestaña pudo ver solo una)
        for r in sonidos:
            if clave_modelo(r["modelo"]):
                r["nombre"] = f"Sonido · {modelo_corto(r['modelo'])}"
    # el sonido va siempre al final (orden estable para el resto)
    salida.sort(key=lambda r: r["tipo"] == "sonido" or "SOUND" in r["modelo"].upper())
    # «LOMA» y «LOMA RENTAL» son el mismo rental: se deja la forma que la hoja MÁS usa (antes: la más larga, y la app terminaba
    # escribiendo «LOMA Film Rental» en 12 filas que la hoja llevaba como «LOMA»)
    uso = {}
    for r in salida:
        if r["rental"]:
            uso[r["rental"]] = uso.get(r["rental"], 0) + (r.get("filas") or 1)
    for r in salida:
        if not r["rental"]:
            continue
        mismas = [n for n in uso if n.upper() == r["rental"].upper() or n.upper().startswith(r["rental"].upper() + " ")
                  or r["rental"].upper().startswith(n.upper() + " ")]
        r["rental"] = max(mismas, key=lambda n: (uso[n], len(n)))
    return salida


def _sonido_de_la_misma_grabadora(r, cfg):
    """El rollo de Sonido de la configuración que es de la misma grabadora que el hallazgo (o None)."""
    mk = clave_modelo(r.get("modelo"))
    if not mk:
        return None
    return next((g for g in cfg["grupos"] if grupo_es_sonido(g) and clave_modelo(g.get("modelo")) == mk), None)


def hallado_ya_esta(r, cfg):
    """¿Algún rollo de la configuración ya reconoce a este hallazgo? (Un Sonido no cuenta como «ya está» por el hecho de que otro rollo, p. ej. un dron, empiece igual.)
    Con varias grabadoras, un Sonido solo «ya está» si es la misma grabadora y su rollo reconoce todos sus nombres."""
    if r["tipo"] == "sonido":
        g = _sonido_de_la_misma_grabadora(r, cfg)
        if g is not None:
            return all(any(patron_a_regex(q).match(str(r["ejemplo"])) for q in g["patrones"]) or p in g["patrones"] for p in r["patrones"]) \
                or any(p in g["patrones"] for p in r["patrones"])
        # un rollo de Sonido sin grabadora escrita (de antes) que ya reconoce ese nombre: se da por bueno
        return any(grupo_es_sonido(x) and not clave_modelo(x.get("modelo")) and any(patron_a_regex(q).match(str(r["ejemplo"])) for q in x["patrones"])
                   for x in cfg["grupos"])
    ya = grupo_de(r["ejemplo"], cfg, audio=None)
    return bool(ya and not grupo_es_sonido(ya))


def agregar_hallados(cfg, elegidos):
    """Agrega a la configuración los rollos elegidos (en su orden), saltando los que ya se reconocen.
    Si el Sonido hallado es de una grabadora que ya tiene su rollo, solo se le suman las formas de reconocerlo.
    Devuelve los nombres agregados."""
    agregados = []
    for r in elegidos:
        if hallado_ya_esta(r, cfg):
            continue
        if r["tipo"] == "sonido":
            g = _sonido_de_la_misma_grabadora(r, cfg)
            if g is not None:
                for p in r["patrones"]:
                    if p not in g["patrones"]:
                        g["patrones"].append(p)
                validar_config(cfg)
                agregados.append(g["nombre"])
                continue
        nombre = r["nombre"]
        if any(x["nombre"] == nombre for x in cfg["grupos"]):               # no puede haber dos rollos con el mismo nombre
            nombre = f"{nombre} · {modelo_corto(r['modelo'])}" if r.get("modelo") else f"{nombre} (2)"
        agregar_grupo(cfg, nombre, r["patrones"], r["rental"], r["modelo"], r["ciclo_mag"],
                      r.get("color", ""), r["avisar_si_falta"])
        agregados.append(nombre)
    return agregados


# =============================================================================
# 4. ARMAR LAS FILAS DEL DÍA
# =============================================================================
def clasificar(reporte, cfg, recientes=None):
    """`recientes`: {id de rollo: última fila de la hoja donde se usó} (de leer_historial): desempata rollos con el mismo patrón."""
    por_grupo, sin = {}, []
    for b in reporte["bins"]:
        g = (grupo_de_audio(b["nombre"], cfg, recientes=recientes) if b.get("audio")
             else grupo_de(b["nombre"], cfg, audio=b.get("audio"), recientes=recientes, cam=b.get("letra") or b.get("cam") or ""))
        if g is None and b.get("audio"):
            g = grupo_de(b["nombre"], cfg, recientes=recientes)
        if g is None and ES_NOMBRE_DE_SONIDO.match(b["nombre"]):          # «Audio», «Sonido», «SND_01»: van al rollo de Sonido
            g = grupo_de_audio(b["nombre"], cfg, recientes=recientes)
            if g is not None and b.get("audio") is None:
                b["audio"] = True
        (por_grupo.setdefault(g["id"], []) if g else sin).append(b)
    return por_grupo, sin


def datos_de_camara_en_hoja(valores, letra):
    """Si la cámara de esa letra YA tiene filas en el estatus (la agregó otra persona del equipo, o desde otro aparato): su rental y
    su equipo más usados, para no volver a escribirlos. ('', '') si no hay."""
    from collections import Counter
    if not valores or not letra:
        return "", ""
    fmt = getattr(valores, "fmt", None) or FORMATO_DSMD
    rental, modelo = Counter(), Counter()
    for fila in valores:
        try:
            nombre = _celda(list(fila), fmt, "cam")
            if not isinstance(nombre, str) or letra_de_bin(nombre.strip()) != letra:
                continue
            k = identificar_bin(nombre.strip())
            if k and k["tipo"] == "sonido":
                continue
            for cuenta, clave in ((rental, "rental"), (modelo, "modelo")):
                v = _celda(list(fila), fmt, clave) if fmt["col"].get(clave) is not None else ""
                if isinstance(v, str) and v.strip():
                    cuenta[v.strip()] += 1
        except Exception:
            continue
    return (rental.most_common(1)[0][0] if rental else ""), (modelo.most_common(1)[0][0] if modelo else "")


def rollo_nuevo_sugerido(cfg, reporte, valores=None):
    """El primer BIN del PDF que ningún rollo reconoce, con todo lo que se puede adelantar para el formulario «rollo nuevo» (lo mismo
    en el Mac y en el celular), o None si todo se reconoce. Devuelve {nombre_bin, cam, es_audio, base, que, ejemplos, pos_camara}."""
    _, sin = clasificar(reporte, cfg)
    if not sin:
        return None
    b0 = sorted(sin, key=lambda b: b["nombre"])[0]
    nombre, cam, es_audio = b0["nombre"], b0.get("letra") or b0.get("cam") or "", bool(b0.get("audio"))
    tipo, letra, otro = adivinar_tipo(nombre, cam)
    if es_audio and tipo != "sonido":
        k = identificar_bin(nombre)
        otro = patron_de_palabra(nombre) if (k and k["tipo"] == "sonido" and re.match(r"[A-Za-z]{2}", nombre)) else patron_corto(nombre)
        tipo, letra = "otro", ""
    igual = adivinar_tipo(nombre, cam)
    parecidos = sorted(b["nombre"] for b in sin if adivinar_tipo(b["nombre"], b.get("letra") or b.get("cam") or "") == igual and bool(b.get("audio")) == es_audio)
    que = que_es_rollo(tipo, letra, nombre)
    verif = b0.get("verif") or {}
    if tipo == "camara" and verif.get("marca_ok"):     # la marca que confirma el códec del PDF manda sobre la que sugiere el nombre
        que = f"una cámara nueva con la letra {letra} ({verif['marca_ok']} según el códec del PDF" + \
              (f", rollo {verif['rollo']}" if verif.get("rollo") else "") + ")"
    if tipo == "camara" and len([x for x in verif.get("pruebas") or [] if x != "peso de imagen"]) >= 2:
        que += ". Lo confirman: " + ", ".join(x for x in verif["pruebas"] if x != "peso de imagen")
    base = {"tipo": tipo, "letra": letra, "otro": otro}
    if es_audio and tipo == "otro":
        que = "AUDIO (el reporte lo lista como grabación de audio). Llámalo «Sonido» para que cuente como audio"
        base["nombre"], base["nombre_fijo"] = "Sonido", True
    elif tipo == "otro" and nombre_sugerido(nombre, cam):
        base["nombre"] = nombre_sugerido(nombre, cam)
    if tipo == "camara":
        rental, modelo = datos_de_camara_en_hoja(valores, letra)
        if rental:
            base["rental"] = rental
        if modelo:
            base["modelo"] = modelo
    color = color_sugerido("sonido" if (tipo == "sonido" or es_audio) else tipo, letra, [g.get("color") for g in cfg["grupos"]])
    if color:
        base["color"] = color                          # A rojo, B azul, C amarillo, D verde… (se puede cambiar en el formulario)
    idx_cam = [i for i, g in enumerate(cfg["grupos"]) if not grupo_es_sonido(g)]
    return {"nombre_bin": nombre, "cam": cam, "es_audio": es_audio, "base": base, "que": que,
            "ejemplos": ", ".join(parecidos[:3]) + ("…" if len(parecidos) > 3 else ""),
            "pos_camara": (idx_cam[-1] + 1) if idx_cam else 0}


def rollo_nuevo_sirve(prueba, g, sugerido):
    """¿El rollo recién llenado reconoce de verdad el BIN que lo motivó?"""
    return grupo_de(sugerido["nombre_bin"], prueba, audio=True if sugerido["es_audio"] else None, cam=sugerido.get("cam") or "") is g \
        or (sugerido["es_audio"] and grupo_de_audio(sugerido["nombre_bin"], prueba) is g)


def siguiente_mag(ultimo, ciclo):
    if not ciclo:
        return None
    return 1 if ultimo is None or ultimo >= ciclo else ultimo + 1          # (7 con ciclo 6 → 1, antes daba 2)


def _es_ambiguo(nombre, cfg):
    """El nombre lo reconocen a la vez un rollo de Sonido y otro que no lo es (grabadora y dron con la misma letra)."""
    tipos = {grupo_es_sonido(g) for g in cfg["grupos"] if any(patron_a_regex(p).match(nombre) for p in g["patrones"])}
    return len(tipos) == 2


def armar_filas(reporte, cfg, hist):
    por_grupo, sin = clasificar(reporte, cfg, hist.get("ultima_fila"))
    if sin:
        raise ErrorRegistro("Hay nombres que no reconozco: " + ", ".join(b["nombre"] for b in sin))
    mags = dict(hist["ultimo_mag"])
    filas, avisos = [], []
    orden = hist.get("orden") or {}
    # como ordena tu hoja cada día. Un rollo que la hoja todavía no tiene (cámara nueva) va pegado al rollo que tiene ANTES en tus
    # Ajustes (antes se calculaba un lugar aparte y la cámara C nueva caía después del sonido).
    lugar, previo = {}, None
    for i, g in enumerate(cfg["grupos"]):
        if g["id"] in orden:
            previo = orden[g["id"]]
            lugar[g["id"]] = (previo, 0)
        elif previo is not None:
            lugar[g["id"]] = (previo, i + 1)
    primero = min((v[0] for v in lugar.values()), default=0.0)
    for i, g in enumerate(cfg["grupos"]):
        lugar.setdefault(g["id"], (primero - 1, i))            # los de antes del primero conocido: al comienzo, en su orden
    grupos = sorted(enumerate(cfg["grupos"]), key=lambda p: (lugar[p[1]["id"]], p[0]))
    for _, g in (grupos if orden else enumerate(cfg["grupos"])):
        for b in sorted(por_grupo.get(g["id"], []), key=lambda x: x["nombre"]):
            mag = siguiente_mag(mags.get(g["id"]), g["ciclo_mag"])
            if mag is not None:
                mags[g["id"]] = mag
            filas.append({"grupo": g["id"], "rental": g["rental"], "nombre": b["nombre"], "cam": b.get("cam") or "",
                          "modelo": g["modelo"], "mag": mag, "clips": b["clips"],
                          "seg": b["seg"], "gb": b["gb"], "audio": bool(b.get("audio")) or grupo_es_sonido(g)})
            m_nombre = re.fullmatch(r"(?i)c[áa]mara\s+([A-Z])", str(g.get("nombre") or "").strip())
            letra_ok = (b.get("verif") or {}).get("letra")
            letra_g = letra_de_camara(g["patrones"]) or (m_nombre.group(1).upper() if m_nombre else None)
            if letra_ok and letra_g and letra_ok != letra_g and not filas[-1]["audio"]:
                avisos.append(f"«{b['nombre']}» quedó en «{g['nombre']}», pero el PDF dice que es de la cámara {letra_ok}. Revisa en "
                              f"Ajustes → Rollos con qué empieza «{g['nombre']}».")
            if b.get("audio_mezclado") and not filas[-1]["audio"]:
                filas[-1]["audio_mezclado"] = dict(b["audio_mezclado"])     # la tarjeta va completa; el estadístico separa el audio
            if b.get("audio") is None and _es_ambiguo(b["nombre"], cfg):
                avisos.append(f"«{b['nombre']}» podría ser audio o video (un rollo de Sonido y otro que no lo es empiezan igual) y "
                              f"este reporte no trae la lista «Audio Tapes» para saberlo: lo puse en «{g['nombre']}». Revísalo.")
            if b.get("audio") and not grupo_es_sonido(g):
                avisos.append(f"«{b['nombre']}» es AUDIO según el reporte, pero no tienes un rollo de Sonido que lo reconozca: lo puse en "
                              f"«{g['nombre']}» (rental y equipo de esa fila). Crea en Ajustes → Rollos un rollo «Sonido» que empiece con "
                              f"{patron_corto(b['nombre'])} para que quede bien. En el estadístico sí cuenta como audio.")
        if g["avisar_si_falta"] and g["id"] not in por_grupo:
            avisos.append(f"El reporte NO trae «{g['nombre']}». El día quedó sin esas filas "
                          "y los totales no las incluyen.")
    if not filas:
        raise ErrorRegistro("No encontré ninguna fila para agregar en el PDF.")
    return filas, avisos


def texto_tabla(reporte, filas, inicio, total):
    lineas = [f"{reporte['dia']}  ·  {reporte['fecha']:%d/%m/%Y}", ""]
    lineas.append(f"{'Fila':<5}{'RENTAL':<15}{'CAM':<18}{'MAG':<5}{'CLIPS':<7}{'DURACIÓN':<10}{'GB':>9}")
    for i, f in enumerate(filas):
        lineas.append(f"{inicio + i:<5}{f['rental']:<15}{f['nombre']:<18}{str(f['mag'] or ''):<5}"
                      f"{f['clips']:<7}{hms(f['seg']):<10}{f['gb']:>9.2f}")
    lineas.append(f"{total:<5}{'TOTAL':<38}{sum(f['clips'] for f in filas):<7}"
                  f"{hms(sum(f['seg'] for f in filas)):<10}{sum(f['gb'] for f in filas):>9.2f}")
    return "\n".join(lineas)


# =============================================================================
# 5. COMPARAR CONTRA EL PDF
# =============================================================================
def _gb(num, unidad):
    return float(num.replace(",", "")) * GB_POR_UNIDAD[unidad]


def validar_contra_pdf(texto, filas):
    """Devuelve una lista de (estado, mensaje): estado = 'ok', 'aviso' o 'info'."""
    res = []
    clips = sum(f["clips"] for f in filas)
    gb = sum(f["gb"] for f in filas)

    m = re.search(r"(\d+)\s+(\d+)\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*\n\s*Total\b", texto)
    if m:
        clips_pdf, gb_pdf = int(m.group(1)), _gb(m.group(4), m.group(5))
        decimales = len(m.group(4).split(".")[1]) if "." in m.group(4) else 0
        tolerancia = 0.5 * 10 ** (-decimales) * GB_POR_UNIDAD[m.group(5)] + 0.01
        res.append(("ok" if clips == clips_pdf else "aviso",
                    f"Clips totales: hoja {clips} · PDF {clips_pdf}"))
        res.append(("ok" if abs(gb - gb_pdf) <= tolerancia else "aviso",
                    f"GB totales: hoja {gb:,.2f} · PDF {m.group(4)} {m.group(5)}"))
    else:
        # otros diseños: la fila «Total  47  40:34 min  81  583.21 GB» de «Clips Overview», o el total de video de «Camera Sums»
        t1 = re.search(r"^\s*Total\s+(\d+)\s+" + _DUR + r"\s*(?:h|min|sec)\s+\d+\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$", texto, re.M)
        tv = totales_del_reporte(texto).get("video")
        tol = 0.02
        if t1:
            clips_pdf, gb_pdf, txt = int(t1.group(1)), _gb(t1.group(3), t1.group(4)), f"{t1.group(3)} {t1.group(4)}"
            c_h, g_h = clips, gb
            dec = len(t1.group(3).split(".")[1]) if "." in t1.group(3) else 0
            tol = max(0.5 * 10 ** (-dec) * GB_POR_UNIDAD[t1.group(4)] + 0.01, 0.02 + 0.005 * len(filas))   # (redondeo de cada tarjeta)
        elif tv:
            clips_pdf, gb_pdf, txt = tv["clips"], tv["gb"], f"{tv['gb']:,.2f} GB (solo video)"
            c_h = sum(f["clips"] - (f.get("audio_mezclado") or {}).get("clips", 0) for f in filas if not f.get("audio"))
            g_h = sum(f["gb"] - (f.get("audio_mezclado") or {}).get("gb", 0.0) for f in filas if not f.get("audio"))
        else:
            clips_pdf = None
        if clips_pdf is None:
            res.append(("info", "No pude leer el total del PDF para compararlo."))
        else:
            res.append(("ok" if c_h == clips_pdf else "aviso", f"Clips totales: hoja {c_h} · PDF {clips_pdf}"))
            res.append(("ok" if abs(g_h - gb_pdf) <= tol else "aviso", f"GB totales: hoja {g_h:,.2f} · PDF {txt}"))

    suma = re.search(r"Camera\s+Sums(.*?)(?:Video\s+Formats|$)", texto, re.S)
    if suma:
        patron = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*_?)\s+(\d+)\s+\d+\s+(\d+)\s+" + _DUR +
                            r"\s*(h|min|sec)\s+\d+\s+[\d.,]+\s*(?:KB|MB|GB|TB)\s*$", re.M)
        for letra, _reels, c, dur, unidad in patron.findall(suma.group(1)):
            if letra.lower() == "total":
                continue
            nombre_cam = letra.rstrip("_")
            con_cam = [f for f in filas if f.get("cam")]
            propias = ([f for f in con_cam if f["cam"].upper() == letra.upper()] +          # «A_» ≠ «A» (DAY047: I005 es la cámara A, A_0… es la A_)
                       [f for f in filas if not f.get("cam") and f["nombre"].upper().startswith(letra.upper())
                        and not f.get("audio")])
            if not propias:
                res.append(("aviso", f"El PDF trae la cámara {nombre_cam} pero no está en la tabla."))
                continue
            seg_pdf = a_segundos(dur, unidad)
            mez = lambda f, k: (f.get("audio_mezclado") or {}).get(k, 0)        # el audio que venía en la tarjeta no es de la cámara
            seg = sum(f["seg"] - mez(f, "seg") for f in propias)
            clips_cam = sum(f["clips"] - mez(f, "clips") for f in propias)
            ok_clips = clips_cam == int(c)
            ok_dur = abs(seg - seg_pdf) <= max(2, len(propias))
            res.append(("ok" if ok_clips and ok_dur else "aviso",
                        f"Cámara {nombre_cam}: hoja {clips_cam} clips, "
                        f"{hms(seg)} · PDF {c} clips, {hms(seg_pdf)}" + (" (sin el audio de la tarjeta)" if any(mez(f, "clips") for f in propias) else "")))

    cintas = re.search(r"Audio\s+Tapes(.*?)Audio\s+Formats", texto, re.S)
    if cintas:
        patron = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\d+(?::\d+){0,2}|\d+[.,]\d+)\s*(?:h|min|sec)\s+\d+\s+[\d.,]+\s*(?:KB|MB|GB|TB)\s*$", re.M)
        for nombre, c in [(a, b) for a, b, *_ in patron.findall(cintas.group(1))]:
            fila = [f for f in filas if f["nombre"] == nombre]
            dentro = [f for f in filas if (f.get("audio_mezclado") or {}).get("clips") == int(c)]
            if not fila and dentro:                # cinta sin nombre en el PDF: es el audio que venía dentro de una tarjeta de cámara
                res.append(("ok", f"Audio: {c} clips dentro de la tarjeta {dentro[0]['nombre']} · PDF {c}"))
                continue
            otra = [f for f in filas if f.get("audio") and f["clips"] == int(c)]
            if not fila and len(otra) == 1:        # la cinta se llama distinto que el BIN («AUDIO» / BIN «10-OCT-28»): mismos clips
                res.append(("ok", f"Audio {otra[0]['nombre']}: hoja {otra[0]['clips']} clips · PDF {c}"))
                continue
            nombre_v = "".join(ch for ch in nombre if not 0xE000 <= ord(ch) <= 0xF8FF) or "(sin nombre)"
            res.append(("ok" if fila and fila[0]["clips"] == int(c) else "aviso",
                        f"Cinta {nombre_v}: hoja {fila[0]['clips'] if fila else 'no está'} clips · PDF {c}"))
    return res


# =============================================================================
# 6. INSTRUCCIONES PARA GOOGLE SHEETS
# =============================================================================
def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _corridas(valores, primera_fila):
    """Agrupa filas seguidas con el mismo valor: [(fila_ini, fila_fin, valor), …]."""
    salida = []
    for i, v in enumerate(valores):
        r = primera_fila + i
        if salida and salida[-1][2] == v and salida[-1][1] == r - 1:
            salida[-1][1] = r
        else:
            salida.append([r, r, v])
    return [tuple(x) for x in salida]


def _texto(s):
    return {"userEnteredValue": {"stringValue": s}}


def _numero(x):
    return {"userEnteredValue": {"numberValue": x}}


def _valor(v):
    """Una celda con un número, un texto o una fórmula."""
    if isinstance(v, str):
        return {"userEnteredValue": {"formulaValue": v}} if v.startswith("=") else _texto(v)
    if v is None:
        return {}
    return _numero(v)


def construir_solicitudes(sheet_id, reporte, filas, hist, cfg, filas_en_hoja, merges=None):
    """Arma las instrucciones (batchUpdate) que escriben el día IGUAL que los días anteriores de ESA hoja: en las columnas que tiene,
    con la etiqueta y la fecha como las escribe, su fila de total (texto y fórmulas que suman lo mismo que antes) y su formato.
    Si el día ya estaba preparado de antemano (filas con la etiqueta pero sin tarjetas), se llena ahí; si no, se inserta debajo del
    último día con material (sin pisar nada de lo que hay más abajo). `merges`: celdas combinadas de la pestaña (de info_completa).
    Devuelve (instrucciones, inicio, final, total) con filas numeradas desde 1; `total` es None si la hoja no usa filas de total.
    Lo que se espera leer después queda en hist["escritura"] (para `comparar_escritura`)."""
    fmt, estilo, bloques = hist["fmt"], hist["estilo"], hist["bloques"]
    col = fmt["col"]
    ncol = fmt["ncol"]
    ref = estilo["bloque_ref"]
    con_total = estilo["total"] is not None
    n = len(filas)

    def rango(r1, r2, c1, c2):                # filas desde 1 (inclusivas); columnas desde 0
        return {"sheetId": sheet_id, "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2}

    sol = []
    preparado = next((b for b in bloques if not b["material"] and b["clave"] == reporte["dia"]), None)
    if preparado and ref is None and con_total != bool(preparado["total"]):
        con_total = bool(preparado["total"])          # hoja sin ningún día escrito con días preparados sin fila de total: se respeta eso
    if preparado and (con_total == bool(preparado["total"])):
        # ---- el día ya estaba preparado: se usan sus filas (y se agregan o quitan las que sobren o falten) ----
        inicio, previas = preparado["filas"][0], len(preparado["filas"])
        sol.append({"unmergeCells": {"range": rango(inicio, (preparado["total"] or preparado["filas"][-1]), 0, ncol)}})
        if n > previas:
            sol.append({"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": inicio - 1 + previas,
                                                      "endIndex": inicio - 1 + n}, "inheritFromBefore": True}})
        elif n < previas:
            sol.append({"deleteDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": inicio - 1 + n,
                                                      "endIndex": inicio - 1 + previas}}})
        modo = "preparado"
    elif ref is None:
        # ---- hoja SIN ningún día: el primero va justo debajo de los títulos. Si esas filas están vacías se escribe ahí mismo;
        #      si hay algo, se insertan filas nuevas (sin heredar el formato de los títulos) para no pisar nada ----
        inicio = fmt["primera"]
        if hist.get("libres_arriba", 0) < n + (1 if con_total else 0):
            sol.append({"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": inicio - 1,
                                                      "endIndex": inicio - 1 + n + (1 if con_total else 0)}, "inheritFromBefore": False}})
            modo = "nuevo"
        else:
            modo = "primero"
    else:
        # ---- día nuevo: se insertan filas debajo del último día con material ----
        ultimo = [b for b in bloques if b["material"]][-1]
        ancla = ultimo["total"] or ultimo["filas"][-1]
        inicio = ancla + 1
        sol.append({"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": ancla,
                                                  "endIndex": ancla + n + (1 if con_total else 0)}, "inheritFromBefore": True}})
        modo = "nuevo"
    final = inicio + n - 1
    total = final + 1 if con_total else None
    desplazamiento = (n + (1 if con_total else 0)) if modo == "nuevo" else 0

    def antes(r):                              # dónde queda, después de insertar, una fila que estaba antes en la hoja
        return r + desplazamiento if modo == "nuevo" and r >= inicio else r

    # a) formato: cada fila copia el de la última fila de su rollo (o la del último día); la etiqueta y la fecha, del día anterior
    if ref is None:                            # primer día de una hoja vacía: formato de números propio (no hay día del que copiar)
        ultima_r = total or final
        for clave, patron, tipo in (("duracion", "[h]:mm:ss", "TIME"), ("gb", "#,##0.00", "NUMBER"), ("clips", "0", "NUMBER")):
            c = col.get(clave)
            if c is not None:
                sol.append({"repeatCell": {"range": rango(inicio, ultima_r, c, c + 1),
                                           "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}},
                                           "fields": "userEnteredFormat.numberFormat"}})
        if col.get("fecha_col") is not None:
            c = col["fecha_col"]
            sol.append({"repeatCell": {"range": rango(inicio, final, c, c + 1),
                                       "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}},
                                       "fields": "userEnteredFormat.numberFormat"}})
        if con_total:
            sol.append({"repeatCell": {"range": rango(total, total, 0, ncol),
                                       "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                       "fields": "userEnteredFormat.textFormat.bold"}})
    else:
        fuentes = [antes(hist["ultima_fila"].get(f["grupo"], ref["filas"][-1])) for f in filas]
        for r1, r2, src in _corridas(fuentes, inicio):
            sol.append({"copyPaste": {"source": rango(src, src, 0, ncol), "destination": rango(r1, r2, 0, ncol),
                                      "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
        for clave in ("dia", "fecha_col"):
            c = col.get(clave)
            if c is not None:
                sol.append({"copyPaste": {"source": rango(antes(ref["filas"][0]), antes(ref["filas"][0]), c, c + 1),
                                          "destination": rango(inicio, inicio, c, c + 1), "pasteType": "PASTE_FORMAT",
                                          "pasteOrientation": "NORMAL"}})
    if con_total and estilo["total"]["fila_ref"]:
        sol.append({"copyPaste": {"source": rango(antes(estilo["total"]["fila_ref"]), antes(estilo["total"]["fila_ref"]), 0, ncol),
                                  "destination": rango(total, total, 0, ncol), "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
    # b) color de cada rollo en CAM, Modelo y # Mag (si el rollo tiene color elegido)
    colores = {g["id"]: g["color"] for g in cfg["grupos"]}
    for r1, r2, color in _corridas([colores.get(f["grupo"], "") for f in filas], inicio):
        if color:
            rgb = _rgb(color)
            for clave in ("cam", "modelo", "mag"):
                c = col.get(clave)
                if c is not None:
                    sol.append({"repeatCell": {"range": rango(r1, r2, c, c + 1),
                                               "cell": {"userEnteredFormat": {"backgroundColor": rgb, "backgroundColorStyle": {"rgbColor": rgb}}},
                                               "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.backgroundColorStyle"}})
    # c) los valores, en las columnas que tiene la hoja
    etiqueta = etiqueta_de_dia(estilo["etiqueta"], reporte)
    fecha = valor_de_fecha_hoja(reporte["fecha"], estilo["fecha"])
    ultima_col = max(col[k] for k in ("dia", "fecha_col", "rental", "cam", "modelo", "mag", "clips", "duracion", "gb") if k in col)
    esperado = []
    filas_valores = []
    for i, f in enumerate(filas):
        celdas = {}
        if "dia" in col:
            celdas[col["dia"]] = etiqueta if (i == 0 or estilo["et_todas"]) else None
        if "fecha_col" in col:
            celdas[col["fecha_col"]] = fecha if (i == 0 or estilo["fecha_todas"]) else None
        for clave, v in (("rental", f["rental"]), ("cam", f["nombre"]), ("modelo", f["modelo"]), ("mag", f["mag"]),
                         ("clips", f["clips"]), ("duracion", f["seg"] / 86400), ("gb", f["gb"])):
            if clave in col:
                celdas[col[clave]] = v
        esperado.append(celdas)
        filas_valores.append({"values": [_valor(celdas.get(c)) for c in range(ultima_col + 1)]})
    sol.append({"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": inicio - 1, "columnIndex": 0},
                                "rows": filas_valores, "fields": "userEnteredValue"}})
    # d) la fila de total: el mismo texto y una suma de las mismas filas que suma la hoja (todas, solo video o solo sonido)
    esperado_total = {}
    if con_total:
        audio = [inicio + i for i, f in enumerate(filas)
                 if f.get("audio") or es_nombre_de_sonido(f["nombre"]) or es_modelo_de_audio(f["modelo"])]
        todas = list(range(inicio, final + 1))
        conjuntos = {"todas": todas, "sin_audio": [r for r in todas if r not in audio], "solo_audio": audio}
        for c, texto in estilo["total"]["textos"].items():
            esperado_total[c] = texto
        for clave, conf in estilo["total"]["columnas"].items():
            c = col[clave]
            usadas = conjuntos[conf["suma"]]
            if conf["modo"] == "formula":
                esperado_total[c] = _formula_suma(c, usadas)
            elif conf["modo"] == "valor":
                por_fila = {inicio + i: (f["clips"] if clave == "clips" else f["seg"] / 86400 if clave == "duracion" else f["gb"])
                            for i, f in enumerate(filas)}
                esperado_total[c] = sum(por_fila[r] for r in usadas)
        ult = max(esperado_total) if esperado_total else 0
        sol.append({"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": total - 1, "columnIndex": 0},
                                    "rows": [{"values": [_valor(esperado_total.get(c, "")) if c in esperado_total else {}
                                                         for c in range(ult + 1)]}], "fields": "userEnteredValue"}})
    # e) celdas combinadas: las mismas que tiene el día anterior (o, si no se sabe, la etiqueta y la fecha cuando van solo arriba)
    nuevas = []
    if merges is not None and ref is not None:
        # las columnas que se combinan de arriba abajo (DIA RODAJE, FECHA…) se aprenden del último día con VARIAS filas
        # (si el último día tuvo una sola tarjeta, como HDT D903, no hay nada combinado de dónde aprender)
        # Además, DIA RODAJE y FECHA se combinan SIEMPRE que la hoja las escribe una sola vez por día (todas las hojas lo hacen así:
        # DSMD, PP, CODT, CONT, Microhistorias…). Antes se copiaba lo del día anterior, y un día que quedó sin combinar (HDT D001,
        # escrito con una versión vieja) hacía que todos los siguientes quedaran igual: una celda con «D004» y nueve vacías debajo.
        cols_v = set()
        for varios in [b for b in reversed([b for b in bloques if b["material"]]) if len(b["filas"]) > 1][:1]:
            r0, r1_ = varios["filas"][0], varios["filas"][-1]
            for m in merges:
                a, b, c1, c2 = m.get("startRowIndex", 0) + 1, m.get("endRowIndex", 0), m.get("startColumnIndex", 0), m.get("endColumnIndex", 0)
                if a == r0 and b == r1_ and c2 - c1 == 1:
                    cols_v.add(c1)
        if not estilo["et_todas"]:
            cols_v |= {col[k] for k, todas_ in (("dia", False), ("fecha_col", estilo["fecha_todas"])) if k in col and not todas_}
        if n > 1:
            nuevas += [rango(inicio, final, c, c + 1) for c in sorted(cols_v)]
        if con_total and estilo["total"]["fila_ref"]:
            for m in merges:
                a, b, c1, c2 = m.get("startRowIndex", 0) + 1, m.get("endRowIndex", 0), m.get("startColumnIndex", 0), m.get("endColumnIndex", 0)
                if a == b == estilo["total"]["fila_ref"]:
                    nuevas.append(rango(total, total, c1, c2))
    else:
        for clave, todas_ in (("dia", estilo["et_todas"]), ("fecha_col", estilo["fecha_todas"])):
            if clave in col and not todas_ and n > 1:
                nuevas.append(rango(inicio, final, col[clave], col[clave] + 1))
    for rg_ in nuevas:
        sol.append({"mergeCells": {"range": rg_, "mergeType": "MERGE_ALL"}})
    hist["escritura"] = {"inicio": inicio, "final": final, "total": total, "filas": esperado, "total_celdas": esperado_total,
                         "modo": modo}
    return sol, inicio, final, total


# =============================================================================
# 5b. UN DÍA QUE YA ESTÁ EN LA HOJA: ¿es igual al reporte o distinto?
# =============================================================================
def comparar_dia(valores, reporte, filas, primera_fila=PRIMERA_FILA):
    """Compara el bloque del día que YA está en la hoja con lo que dice el reporte (filas armadas con `armar_filas`).
    `valores`: filas de datos de la hoja (con su formato). Las filas se emparejan por el nombre del BIN.
    Devuelve {'existe', 'igual', 'inicio', 'final', 'total', 'diferencias': [texto], 'celdas': [(fila, columna, valor)],
    'reemplazable'}; `celdas` son las celdas que se corregirían (solo se corrigen números: clips, duración, GB y fecha);
    si faltan o sobran BIN no es reemplazable (habría que mover filas, y eso lo debe decidir una persona)."""
    import estadistico_core as ec
    fmt = getattr(valores, "fmt", None) or dict(FORMATO_DSMD, primera=primera_fila)
    col = fmt["col"]
    bloque_ = next((b for b in bloques_de_hoja(valores, fmt) if b["material"] and b["clave"] == reporte["dia"]), None)
    res = {"existe": bloque_ is not None, "igual": False, "inicio": None, "final": None, "total": None,
           "diferencias": [], "celdas": [], "reemplazable": False, "celdas_todas": [], "reescribible": False, "filas_hoja": {}}
    if bloque_ is None:
        return res
    res.update(inicio=bloque_["filas"][0], final=bloque_["filas"][-1], total=bloque_["total"])

    def fila_de(r):
        return list(valores[r - fmt["primera"]]) + [""] * fmt["ncol"]
    bloque = [(r, fila_de(r)) for r in bloque_["filas"]]
    en_hoja, repetidos = {}, False
    for r, fila in bloque:
        nombre = str(_celda(fila, fmt, "cam") or "").strip()
        if nombre:
            repetidos = repetidos or nombre in en_hoja
            en_hoja[nombre] = (r, fila)
    esperados = {}
    for f in filas:
        repetidos = repetidos or f["nombre"] in esperados
        esperados[f["nombre"]] = f
    estructura_ok = not repetidos
    res["filas_hoja"] = {n: v[0] for n, v in en_hoja.items()}         # BIN -> fila de la hoja (para mostrar lo que HAY escrito)
    if repetidos:
        res["diferencias"].append("Hay BIN con el mismo nombre repetido; no puedo emparejar las filas con seguridad.")
    for nombre in esperados:
        if nombre not in en_hoja:
            res["diferencias"].append(f"El reporte trae «{nombre}» y la hoja no lo tiene en ese día.")
            estructura_ok = False
    # reporte de SOLO sonido (PP «Sound_Media»): las cámaras del día no vienen en él, así que no se cuentan como «sobran»
    solo_sonido = bool(filas) and all(f.get("audio") for f in filas)
    res["solo_sonido"] = solo_sonido
    for nombre in en_hoja:
        if nombre not in esperados and not solo_sonido:
            res["diferencias"].append(f"La hoja tiene «{nombre}» en ese día y el reporte no.")
            estructura_ok = False

    def distinto_num(real, esperado, tol):
        return not (isinstance(real, (int, float)) and not isinstance(real, bool) and abs(real - esperado) <= tol)

    def texto(v, tipo):
        if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
            return "vacío" if v in ("", None) else str(v)
        if tipo == "hora":
            return hms(round(v * 86400))
        return f"{v:,.2f}" if tipo == "gb" else f"{v:,.0f}"

    if bloque and "fecha_col" in col:
        r0, fila0 = bloque[0]
        actual = fila0[col["fecha_col"]]
        conv = _convencion_fecha([actual])
        nueva = valor_de_fecha_hoja(reporte["fecha"], conv)
        res["celdas_todas"].append((r0, col["fecha_col"], nueva))
        if ec.fecha_de_celda(actual) != reporte["fecha"].date():
            f_ = ec.fecha_de_celda(actual)
            res["diferencias"].append(f"Fecha: hoja {f_.strftime('%d/%m/%Y') if f_ else 'vacía'} → reporte "
                                      f"{reporte['fecha']:%d/%m/%Y} (fila {r0})")
            res["celdas"].append((r0, col["fecha_col"], nueva))
    for nombre, f in esperados.items():
        if nombre not in en_hoja:
            continue
        r, fila = en_hoja[nombre]
        for clave, concepto, esperado, tol, tipo in (("clips", "clips", f["clips"], 0, "n"), ("duracion", "duración", f["seg"] / 86400, 0.6 / 86400, "hora"),
                                                     ("gb", "GB", f["gb"], 0.005, "gb")):
            c = col[clave]
            res["celdas_todas"].append((r, c, esperado))
            if distinto_num(fila[c], esperado, tol):
                res["diferencias"].append(f"{nombre} · {concepto}: hoja {texto(fila[c], tipo)} → reporte "
                                          f"{texto(esperado, tipo)} (fila {r})")
                res["celdas"].append((r, c, esperado))
    res["igual"] = not res["diferencias"]
    res["reemplazable"] = bool(res["diferencias"]) and estructura_ok and bool(res["celdas"])
    res["reescribible"] = res["igual"] and estructura_ok and bool(res["celdas_todas"])      # ya está igual y aun así quieres volver a escribirlo
    return res


def solicitudes_reemplazo(sheet_id, celdas):
    """Instrucciones de Google para corregir SOLO esas celdas (fila desde 1, columna desde 0, valor: número o texto)."""
    return [{"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": r - 1, "columnIndex": c},
                             "rows": [{"values": [_valor(v)]}], "fields": "userEnteredValue"}}
            for r, c, v in celdas]


# =============================================================================
# 7. COMPROBAR LO ESCRITO (leyendo la hoja de vuelta)
# =============================================================================
def comparar_escritura(valores, formulas_total, filas, reporte, inicio, total, esperado=None):
    """`valores`: filas inicio..total (o hasta el final del día) leídas con valores reales; `formulas_total`: la fila de total con
    fórmulas. `esperado`: lo que se escribió (hist["escritura"] de `construir_solicitudes`). Devuelve [(estado, mensaje)]."""
    import estadistico_core as ec
    res, malas = [], []
    esperado = esperado or {"filas": [], "total_celdas": {}}
    for i, celdas in enumerate(esperado["filas"]):
        fila = list(valores[i]) if i < len(valores) else []
        for c, e in celdas.items():
            real = fila[c] if c < len(fila) else ""
            if e is None:
                bien = real in ("", None)
            elif isinstance(e, (int, float)) and not isinstance(e, bool):
                bien = isinstance(real, (int, float)) and not isinstance(real, bool) and abs(real - e) < 1e-6
                if not bien and isinstance(real, str):                       # una fecha escrita como texto que Google convirtió
                    bien = ec.fecha_de_celda(real) is not None and ec.fecha_de_celda(real) == ec.fecha_de_celda(e)
            else:
                bien = str(real).strip() == str(e).strip() or (ec.fecha_de_celda(e) is not None and ec.fecha_de_celda(real) == ec.fecha_de_celda(e))
            if not bien:
                malas.append(f"fila {inicio + i}, columna {_letra(c)}: esperaba {e!r}, la hoja tiene {real!r}")
    res.append(("ok" if not malas else "aviso",
                "Las filas del día quedaron escritas igual que la tabla" if not malas else "Hay diferencias: " + "; ".join(malas[:5])))
    if total and esperado["total_celdas"]:
        fila_t = list(formulas_total[0]) if formulas_total else []
        formulas = {c: e for c, e in esperado["total_celdas"].items() if isinstance(e, str) and e.startswith("=")}
        reales = {c: (fila_t[c] if c < len(fila_t) else "") for c in formulas}
        ok_f = all(str(reales[c]).replace(" ", "") == formulas[c] for c in formulas)
        res.append(("ok" if ok_f else "aviso",
                    f"Fórmulas del total: {', '.join(str(reales[c]) for c in sorted(reales))}" if ok_f else
                    f"Las fórmulas del total no son las esperadas: {[reales[c] for c in sorted(reales)]}"))
        fila_v = list(valores[len(esperado["filas"])]) if len(valores) > len(esperado["filas"]) else []
        n = len(esperado["filas"])
        malas_t = []
        for c, e in esperado["total_celdas"].items():
            if isinstance(e, str) and not e.startswith("="):
                continue
            if isinstance(e, str):                                           # fórmula: se suma lo que dice cubrir
                usadas = _filas_de_formula(e, c) or set()
                e = sum(x for r in usadas if 0 <= r - inicio < min(n, len(valores)) and c < len(valores[r - inicio])
                        and isinstance(x := valores[r - inicio][c], (int, float)) and not isinstance(x, bool))
            real = fila_v[c] if c < len(fila_v) else ""
            if not (isinstance(real, (int, float)) and abs(real - e) < 1e-6):
                malas_t.append(f"columna {_letra(c)}: {real!r} (esperaba {e:,.2f})")
        res.append(("ok" if not malas_t else "aviso", "Google calculó el total del día igual que la tabla" if not malas_t else
                    "El total que calculó Google no coincide: " + "; ".join(malas_t)))
    return res


# ---------------------------------------------------------------------------------------------
# Varios estadísticos (FO-07) en un mismo proyecto: uno por unidad
# ---------------------------------------------------------------------------------------------
# Muchos proyectos con varias unidades llevan UN estatus de tarjetas con una pestaña por unidad y UN estadístico por unidad (cada uno con su
# «Datos Generales» y su «Resumen General»). La config guarda el primero en cfg["estadistico"] (así todo lo anterior sigue funcionando)
# y los demás en cfg["estadistico"]["otros"]. Cada uno es {enlace, titulo, datos, resumen, etiqueta}.
_NO_DICEN_UNIDAD = {"FF", "GS", "FO", "FORMATO", "ESTADISTICO", "ESTATUS", "TARJETAS", "RESUMEN", "GENERAL", "GENERALES", "DATOS",
                    "FILMFLOW", "COPIA", "DE", "DEL", "LA", "EL", "Y", "HOJA", "PROYECTO", "NOMBRE", "SHEET"}


def _palabras_de_unidad(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).upper()
    return {p for p in re.split(r"[^A-Z0-9]+", t) if p and p not in _NO_DICEN_UNIDAD and not re.fullmatch(r"0*\d{1,3}", p) or p in ("U1", "U2", "U3")}


def afinidad_de_unidad(nombre_pestana, texto_estadistico):
    """Cuántas palabras en común hay entre el nombre de una pestaña del estatus («CEL UA») y lo que dice un estadístico
    («FF-GS-FO-07 FORMATO ESTADISTICO CEL UA»). Mientras más palabras distintivas comparten, más seguro que son de la misma unidad."""
    return len(_palabras_de_unidad(nombre_pestana) & _palabras_de_unidad(texto_estadistico))


def texto_de_estadistico(est):
    return f"{est.get('etiqueta', '')} {est.get('titulo', '')}"


def estadisticos(cfg):
    """Los estadísticos conectados, el principal primero. Vacío si no hay ninguno."""
    est = (cfg or {}).get("estadistico") or {}
    if not est.get("enlace"):
        return []
    principal = {k: v for k, v in est.items() if k != "otros"}
    return [principal] + [dict(o) for o in est.get("otros", []) if isinstance(o, dict) and o.get("enlace")]


def estadistico_para_pestana(cfg, pestana):
    """El estadístico que corresponde a una pestaña del estatus: el que comparte más palabras con su nombre; si ninguno, el principal."""
    todos = estadisticos(cfg)
    if not todos:
        return {}
    if len(todos) == 1 or not pestana:
        return todos[0]
    puntos = [afinidad_de_unidad(pestana, texto_de_estadistico(e)) for e in todos]
    mejor = max(puntos)
    return todos[puntos.index(mejor)] if mejor > 0 else todos[0]


def guardar_estadistico(cfg, entrada, indice=0):
    """Guarda un estadístico. `indice` 0 = el principal; N = el que ocupa ese lugar; None = uno nuevo (si el enlace ya estaba, se reemplaza)."""
    todos = estadisticos(cfg)
    entrada = {k: entrada[k] for k in ("enlace", "titulo", "datos", "resumen", "etiqueta") if k in entrada}
    if indice is None:
        mismo = next((i for i, e in enumerate(todos) if e.get("enlace") == entrada["enlace"] and e.get("datos") == entrada.get("datos")), None)
        if mismo is None:
            todos.append(entrada)
        else:
            todos[mismo] = entrada
    elif indice < len(todos):
        todos[indice] = entrada
    else:
        todos.append(entrada)
    cfg["estadistico"] = dict(todos[0], otros=todos[1:]) if todos else {}
    return cfg


def quitar_estadistico(cfg, indice=0):
    """Quita uno; si era el principal, el siguiente pasa a ser el principal."""
    todos = estadisticos(cfg)
    if 0 <= indice < len(todos):
        todos.pop(indice)
    cfg["estadistico"] = dict(todos[0], otros=todos[1:]) if todos else {}
    return cfg


# ---- Varios archivos de estatus de tarjetas (FO-06): el principal es donde se registra; los demás solo se leen ----
def estatus(cfg):
    """Los archivos de estatus conectados, el principal primero (cada uno: enlace, titulo, pestana). Vacío si no hay ninguno."""
    h = (cfg or {}).get("hoja") or {}
    if not h.get("enlace"):
        return []
    principal = {"enlace": h["enlace"], "titulo": h.get("titulo", ""), "pestana": h.get("pestana", "")}
    return [principal] + [dict(o) for o in h.get("otros", []) if isinstance(o, dict) and o.get("enlace")]


def _poner_estatus(cfg, todos):
    otros = todos[1:]
    if todos:
        cfg["hoja"] = {"enlace": todos[0]["enlace"], "pestana": todos[0].get("pestana", ""), "titulo": todos[0].get("titulo", "")}
        if otros:
            cfg["hoja"]["otros"] = otros
    else:
        cfg["hoja"] = {"enlace": "", "pestana": ""}
    return cfg


def guardar_estatus(cfg, entrada, indice=0):
    """Guarda un archivo de estatus. `indice` 0 = el principal; N = el que ocupa ese lugar; None = uno nuevo (si el enlace ya estaba, se reemplaza)."""
    todos = estatus(cfg)
    entrada = {k: entrada.get(k, "") for k in ("enlace", "titulo", "pestana")}
    if indice is None:
        mismo = next((i for i, e in enumerate(todos) if e.get("enlace") == entrada["enlace"]), None)
        if mismo is None:
            todos.append(entrada)
        else:
            todos[mismo] = entrada
    elif indice < len(todos):
        todos[indice] = entrada
    else:
        todos.append(entrada)
    return _poner_estatus(cfg, todos)


def quitar_estatus(cfg, indice=0):
    """Quita uno; si era el principal, el siguiente pasa a ser el principal."""
    todos = estatus(cfg)
    if 0 <= indice < len(todos):
        todos.pop(indice)
    return _poner_estatus(cfg, todos)


def hacer_principal_estatus(cfg, indice):
    """Pasa un archivo de estatus a ser el principal (donde se registra)."""
    todos = estatus(cfg)
    if 0 < indice < len(todos):
        todos.insert(0, todos.pop(indice))
    return _poner_estatus(cfg, todos)
