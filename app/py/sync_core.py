#!/usr/bin/env python3
"""
SINCRONIZACIÓN ENTRE LA APP DEL MAC Y LA DEL TELÉFONO
=====================================================
Tus proyectos (hojas conectadas, rollos, correo…) se guardan en UNA hoja de Google
llamada «FILMFLOW_CONFIG (no borrar)» dentro de TU Drive. Las dos apps entran con tu
misma cuenta de Google, encuentran esa hoja solas (por su nombre) y se ponen de acuerdo:

  · lo que cambias en una app aparece en la otra la próxima vez que se sincroniza;
  · si cambias el MISMO proyecto en las dos, gana el cambio más reciente (por proyecto);
  · si borras un proyecto en una app, se borra también en la otra;
  · la opción «Apariencia», la sesión de Google y el proyecto abierto NO se comparten (son de cada aparato).

Este archivo no depende de Tk ni de librerías de Google: recibe una función `http(metodo, url, cuerpo)`
que devuelve (código, texto). Así es el MISMO código en el Mac y en el teléfono.
"""
import copy
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import registro_core as rc

TITULO = "FILMFLOW_CONFIG (no borrar)"
PESTANA = "Config"
PERMISO_DRIVE = "https://www.googleapis.com/auth/drive.metadata.readonly"
DRIVE = "https://www.googleapis.com/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
TROZO = 30000                      # una celda de Google admite 50 000 caracteres; se guarda en trozos
FILAS_TROZOS = 40                  # filas reservadas para los trozos (1,2 millones de caracteres: de sobra)
VIGENCIA_BORRADOS = 90 * 86400     # un proyecto borrado se «recuerda» 90 días para avisar a la otra app
PROYECTO_INICIAL = "Mi proyecto"


class ErrorSync(rc.ErrorRegistro):
    """Un problema de sincronización, explicado en lenguaje simple. `.codigo` = código HTTP (0 = sin internet)."""

    def __init__(self, texto, codigo=None, falta_permiso=False, falta_api=False):
        super().__init__(texto)
        self.codigo, self.falta_permiso, self.falta_api = codigo, falta_permiso, falta_api


def _traducir(codigo, texto, que="sincronizar"):
    t = (texto or "").lower()
    if codigo == 0:
        return ErrorSync("No pude hablar con Google (¿sin internet?). Se vuelve a intentar solo.", 0)
    if codigo == 401:
        return ErrorSync("La sesión de Google venció. Conéctala de nuevo y se sincroniza.", 401)
    if codigo == 403 and ("accessnotconfigured" in t or "has not been used" in t or "is disabled" in t or "api has not" in t):
        return ErrorSync("Falta activar «Google Drive API» en tu proyecto de Google Cloud (es un clic). "
                         "Mira el paso a paso en la sección «Sincronizar» de Ajustes.", 403, falta_api=True)
    if codigo == 403 and ("insufficient" in t or "scope" in t or "permission" in t):
        return ErrorSync("Tu sesión de Google no tiene el permiso para encontrar la hoja de sincronización. "
                         "Vuelve a conectar la cuenta y acepta el permiso nuevo.", 403, falta_permiso=True)
    if codigo == 404:
        return ErrorSync("La hoja de sincronización ya no existe (¿la borraste?). Se crea una nueva.", 404)
    if codigo == 429:
        return ErrorSync("Google recibió demasiadas peticiones seguidas. Espera un minuto.", 429)
    if isinstance(codigo, int) and codigo >= 500:
        return ErrorSync("Google tuvo un problema por su lado. Se vuelve a intentar solo.", codigo)
    return ErrorSync(f"No pude {que}: Google respondió con un error ({codigo}).", codigo)


def _llamar(http, metodo, url, cuerpo=None, que="sincronizar"):
    codigo, texto = http(metodo, url, cuerpo)
    if codigo == 0 or codigo >= 400:
        raise _traducir(codigo, texto, que)
    return json.loads(texto) if texto else {}


# ---------------------------------------------------------------------------------------- la hoja en Google
def id_de_enlace(enlace):
    m = re.search(r"/d/([A-Za-z0-9_-]+)", enlace or "") or re.fullmatch(r"\s*([A-Za-z0-9_-]{25,})\s*", enlace or "")
    if not m:
        raise ErrorSync("Ese enlace no parece de una hoja de Google.")
    return m.group(1)


def buscar_id(http):
    """El id de la hoja de sincronización de esta cuenta (la tuya, o una que te compartieron). None si no hay."""
    q = f"name = '{TITULO}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    url = DRIVE + "?" + urlencode({"q": q, "fields": "files(id,name,ownedByMe,modifiedTime)", "orderBy": "modifiedTime desc",
                                   "pageSize": 20, "spaces": "drive", "supportsAllDrives": "true",
                                   "includeItemsFromAllDrives": "true"}, quote_via=quote)
    r = _llamar(http, "GET", url, que="buscar la hoja de sincronización")
    archivos = r.get("files") or []
    propios = [a for a in archivos if a.get("ownedByMe")]
    return (propios or archivos or [{}])[0].get("id")


def crear_hoja(http):
    r = _llamar(http, "POST", SHEETS, {"properties": {"title": TITULO},
                                       "sheets": [{"properties": {"title": PESTANA}}, {"properties": {"title": "Proyectos"}}]},
                que="crear la hoja de sincronización")
    return r["spreadsheetId"]


def leer_remoto(http, sid):
    rango = quote(f"{PESTANA}!A4:A{3 + FILAS_TROZOS}", safe="")
    r = _llamar(http, "GET", f"{SHEETS}/{sid}/values/{rango}?valueRenderOption=UNFORMATTED_VALUE", que="leer la hoja de sincronización")
    texto = "".join(str(f[0]) for f in (r.get("values") or []) if f)
    if not texto.strip():
        return {"v": 1, "proyectos": {}, "borrados": {}}
    try:
        doc = json.loads(texto)
        if not isinstance(doc, dict):
            raise ValueError
    except ValueError:
        raise ErrorSync("La hoja de sincronización está dañada (alguien la editó). Bórrala en Drive y se crea una nueva.")
    doc.setdefault("proyectos", {})
    doc.setdefault("borrados", {})
    return doc


def _resumen_proyectos(doc):
    filas = [["Proyecto", "Estatus de tarjetas (FO-06)", "Pestaña", "Estadístico (FO-07)", "Rollos", "Última modificación"]]
    for nombre, e in doc["proyectos"].items():
        p = e.get("p") or {}
        est = [x for x in ([p.get("estadistico")] if p.get("estadistico") else []) + list(((p.get("estadistico") or {}).get("otros")) or []) if x]
        filas.append([nombre, ", ".join(x for x in [(p.get("hoja") or {}).get("enlace", "")] + [o.get("enlace", "") for o in ((p.get("hoja") or {}).get("otros") or []) if isinstance(o, dict)] if x), (p.get("hoja") or {}).get("pestana", ""),
                      ", ".join(x.get("enlace", "") for x in est if isinstance(x, dict)), len(p.get("grupos") or []),
                      time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("mod", 0)))])
    return filas


def escribir_remoto(http, sid, doc, quien):
    texto = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    trozos = [texto[i:i + TROZO] for i in range(0, len(texto), TROZO)] or [""]
    if len(trozos) > FILAS_TROZOS:
        raise ErrorSync("Tus proyectos son demasiado grandes para sincronizarse.")
    filas = [["NO BORRES NI EDITES ESTA HOJA: la usa «Estadístico FilmFlow» para sincronizar tus proyectos entre el Mac y el teléfono."],
             [f"Actualizado {time.strftime('%Y-%m-%d %H:%M')} por {quien}"], ["v1"]]
    filas += [[t] for t in trozos] + [[""]] * (FILAS_TROZOS - len(trozos))      # los trozos viejos que sobren se vacían
    resumen = _resumen_proyectos(doc)
    cuerpo = {"valueInputOption": "RAW", "data": [
        {"range": f"{PESTANA}!A1:A{len(filas)}", "values": filas},
        {"range": f"Proyectos!A1:F{max(len(resumen), 30)}", "values": resumen + [[""] * 6] * max(0, 30 - len(resumen))}]}
    _llamar(http, "POST", f"{SHEETS}/{sid}/values:batchUpdate", cuerpo, que="guardar en la hoja de sincronización")


# ---------------------------------------------------------------------------------------- estado de este aparato
def _ruta_estado(carpeta):
    return Path(carpeta) / "sync.json"


def leer_estado(carpeta=None):
    try:
        return json.loads(_ruta_estado(carpeta or rc.CARPETA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_estado(est, carpeta):
    ruta = _ruta_estado(carpeta)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def olvidar(carpeta=None):
    """Deja este aparato como si nunca se hubiera sincronizado (no toca los proyectos)."""
    try:
        _ruta_estado(carpeta or rc.CARPETA).unlink()
    except OSError:
        pass


def _huella(p):
    limpio = {k: v for k, v in p.items() if not str(k).startswith("_")}
    return hashlib.sha1(json.dumps(limpio, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _vacio(p):
    return not ((p.get("hoja") or {}).get("enlace") or p.get("grupos") or p.get("estadistico") or p.get("correo"))


def enlace_hoja(carpeta=None):
    sid = leer_estado(carpeta).get("id")
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else ""


def describir(carpeta=None):
    e = leer_estado(carpeta)
    return {"activa": bool(e.get("id")), "ultima": e.get("ultima"), "correo": e.get("correo"), "enlace": enlace_hoja(carpeta),
            "error": e.get("error", "")}


# ---------------------------------------------------------------------------------------- el trabajo
def sincronizar(http, correo, dispositivo="", crear=True, carpeta=None, ahora=None, gana_local_al_inicio=False, sid_manual=None):
    """Pone de acuerdo este aparato con Google. Devuelve un resumen:
    {'estado': 'ok'|'sin_config', 'sid', 'creada', 'bajados': [...], 'subidos': [...], 'borrados': [...], 'proyectos': n}
    `gana_local_al_inicio`: la PRIMERA vez que este aparato se sincroniza, si un proyecto existe en los dos lados con el mismo
    nombre, gana el de este aparato (el Mac: es el principal) o el de Google (el teléfono)."""
    carpeta = Path(carpeta or rc.CARPETA)
    ruta = carpeta / "config_registro.json"
    ahora = int(ahora or time.time())
    est = leer_estado(carpeta)
    if est.get("correo") and correo and est["correo"].lower() != correo.lower():
        est = {}                                              # otra cuenta de Google: se empieza de cero
    sid = sid_manual or est.get("id") or buscar_id(http)
    creada = False
    if not sid:
        if not crear:
            return {"estado": "sin_config", "bajados": [], "subidos": [], "borrados": [], "proyectos": 0}
        sid, creada = crear_hoja(http), True
    try:
        remoto = leer_remoto(http, sid)
    except ErrorSync as e:
        if e.codigo != 404 or sid_manual:
            raise
        sid, creada, est = crear_hoja(http), True, {}          # la hoja desapareció: se crea otra
        remoto = {"v": 1, "proyectos": {}, "borrados": {}}
    primera_vez = est.get("id") != sid

    local = rc.leer_archivo(ruta)
    prev = {} if primera_vez else dict(est.get("proyectos") or {})
    borr = {} if primera_vez else dict(est.get("borrados") or {})

    loc = {}                                                   # nombre -> (proyecto, mod, hash)
    for nombre, p in local["proyectos"].items():
        if nombre == PROYECTO_INICIAL and _vacio(p):
            continue                                           # el proyecto vacío de fábrica nunca se sincroniza
        h = _huella(p)
        mod = prev[nombre]["mod"] if nombre in prev and prev[nombre]["h"] == h else ahora
        loc[nombre] = (p, mod, h)
        if borr.get(nombre, 0) < mod:
            borr.pop(nombre, None)
    for nombre in prev:
        if nombre not in local["proyectos"] and nombre not in borr:
            borr[nombre] = ahora                               # lo borraste en este aparato

    rem = {n: e for n, e in remoto["proyectos"].items() if isinstance(e, dict) and isinstance(e.get("p"), dict)}
    tumbas = dict(remoto.get("borrados") or {})
    for n, t in borr.items():
        tumbas[n] = max(tumbas.get(n, 0), t)

    final, bajados, subidos, borrados = {}, [], [], []
    nombres = list(loc) + [n for n in rem if n not in loc]
    for n in nombres:
        l, r = loc.get(n), rem.get(n)
        if l and r:
            if primera_vez and l[2] != _huella(r["p"]):
                ganador = "local" if gana_local_al_inicio else "remoto"
            else:
                ganador = "local" if l[1] >= int(r.get("mod", 0)) else "remoto"
        else:
            ganador = "local" if l else "remoto"
        p, mod = (l[0], l[1]) if ganador == "local" else (r["p"], int(r.get("mod", 0)))
        if primera_vez and ganador == "local" and l and r and l[2] != _huella(r["p"]):
            mod = max(mod, int(r.get("mod", 0)) + 1)           # gana el de aquí: que también «parezca» el más nuevo
        if tumbas.get(n, 0) >= mod and not (primera_vez and l):
            if l:
                borrados.append(n)
            continue
        final[n] = {"p": copy.deepcopy(p), "mod": mod}
        if ganador == "remoto" and (not l or l[2] != _huella(p)):
            bajados.append(n)
        elif ganador == "local" and (not r or _huella(r["p"]) != l[2]):
            subidos.append(n)

    if not final:                                              # nunca se deja la app sin proyectos
        final = {n: {"p": copy.deepcopy(v[0]), "mod": v[1]} for n, v in loc.items()}

    # --- lo de aquí
    nuevo_local = copy.deepcopy(local)
    previos = [n for n in local["proyectos"] if n in final]
    orden = previos + [n for n in final if n not in previos]
    if final:
        nuevo_local["proyectos"] = {n: final[n]["p"] for n in orden}
    elif not nuevo_local["proyectos"]:
        nuevo_local = rc._config_vacia()
    if nuevo_local.get("activo") not in nuevo_local["proyectos"]:
        nuevo_local["activo"] = next(iter(nuevo_local["proyectos"]))
    if json.dumps(nuevo_local, sort_keys=True) != json.dumps(local, sort_keys=True):
        if bajados or borrados:
            copia = carpeta / "config_antes_de_sincronizar.json"
            try:
                copia.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")   # por si hace falta volver atrás
            except OSError:
                pass
        rc.escribir_archivo(nuevo_local, ruta, sin_aviso=True)

    # --- lo de Google
    vivas = set(final)
    doc = {"v": 1, "proyectos": {n: {"mod": e["mod"], "p": e["p"]} for n, e in final.items()},
           "borrados": {n: t for n, t in tumbas.items() if n not in vivas and ahora - t < VIGENCIA_BORRADOS}}
    if creada or json.dumps(doc, sort_keys=True) != json.dumps({"v": remoto.get("v", 1), "proyectos": remoto["proyectos"],
                                                                "borrados": remoto.get("borrados") or {}}, sort_keys=True):
        escribir_remoto(http, sid, doc, f"{correo or 'tu cuenta'} ({dispositivo or 'aparato'})")

    _guardar_estado({"id": sid, "correo": correo, "ultima": ahora, "error": "",
                     "proyectos": {n: {"h": _huella(e["p"]), "mod": e["mod"]} for n, e in final.items()},
                     "borrados": doc["borrados"]}, carpeta)
    return {"estado": "ok", "sid": sid, "creada": creada, "bajados": bajados, "subidos": subidos, "borrados": borrados,
            "proyectos": len(final)}


def anotar_error(texto, carpeta=None):
    """Guarda (sin perder lo demás) el último problema, para mostrarlo en Ajustes."""
    carpeta = Path(carpeta or rc.CARPETA)
    e = leer_estado(carpeta)
    if e.get("error", "") == texto:                # nada cambió: no se reescribe (en el teléfono cada escritura va a IndexedDB)
        return
    e["error"] = texto
    try:
        _guardar_estado(e, carpeta)
    except OSError:
        pass
