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
PERMISO_DRIVE = "https://www.googleapis.com/auth/drive.file"      # «solo los archivos que usas con esta app» (permiso normal: no
                                                                  # necesita auditoría de Google; antes era drive.metadata.readonly)
URL_APP = "https://filmflowestadistico.github.io/app/"
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


# ---------------------------------------------------------------------------------------- equipo del proyecto
# Quien tiene acceso a las hojas (la cuenta de la empresa) agrega a los encargados del proyecto (nombre, correo, editar o solo ver).
# La app les COMPARTE todas las hojas conectadas (estatus y estadísticos) y les deja una «ficha del proyecto»: una hoja
# «FILMFLOW_PROYECTO · <nombre> (no borrar)» con la configuración (hojas, pestañas, rollos, correo), compartida como lectura.
# Cuando la persona entra con SU correo, la sincronización encuentra la ficha (compartida con ella) y el proyecto le aparece solo.
# Compartir archivos pide a Google un permiso más amplio (PERMISO_COMPARTIR): se pide solo al usar esto, solo a quien comparte.
PERMISO_COMPARTIR = "https://www.googleapis.com/auth/drive"
PREFIJO_FICHA = "FILMFLOW_PROYECTO · "
_NO_SE_COMPARTE = ("equipo", "ficha", "origen")          # lo que NO va en la ficha (es de quien comparte)


class FaltaPermisoCompartir(ErrorSync):
    """La sesión no tiene el permiso de Google para compartir archivos: hay que volver a conectar con ese permiso."""


def enlace_invitacion(fid):
    """El enlace que se le manda a cada persona del equipo: al abrirlo, la app se une al proyecto (lee su ficha)."""
    return f"{URL_APP}?unirse={fid}"


def id_de_invitacion(texto):
    """El id de la ficha en un enlace de invitación (…?unirse=ID) o en un enlace de la hoja (/d/ID/). None si no hay."""
    m = re.search(r"unirse=([A-Za-z0-9_-]{20,})", texto or "") or re.search(r"/d/([A-Za-z0-9_-]{20,})", texto or "") \
        or re.fullmatch(r"\s*([A-Za-z0-9_-]{25,})\s*", texto or "")
    return m.group(1) if m else None


def unirse(fid, carpeta=None):
    """Anota la ficha de un proyecto al que te invitaron; la próxima sincronización lo trae."""
    carpeta = Path(carpeta or rc.CARPETA)
    est = leer_estado(carpeta)
    unidas = [x for x in (est.get("fichas_unidas") or []) if x != fid] + [fid]
    est["fichas_unidas"] = unidas
    _guardar_estado(est, carpeta)


def titulo_ficha(nombre):
    return f"{PREFIJO_FICHA}{nombre} (no borrar)"


def correo_valido(correo):
    return bool(re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}", (correo or "").strip()))


def hojas_del_proyecto(p):
    """[(id, nombre para mostrar)] de TODAS las hojas conectadas: estatus (principal y otros) y estadísticos."""
    salida, vistos = [], set()

    def una(enlace, que):
        try:
            sid = id_de_enlace(enlace)
        except ErrorSync:
            return
        if sid not in vistos:
            vistos.add(sid)
            salida.append((sid, que))
    h = p.get("hoja") or {}
    if h.get("enlace"):
        una(h["enlace"], h.get("titulo") or "Estatus de tarjetas")
    for o in h.get("otros") or []:
        if isinstance(o, dict) and o.get("enlace"):
            una(o["enlace"], o.get("titulo") or "Otro estatus de tarjetas")
    e = p.get("estadistico") or {}
    for x in ([e] if e.get("enlace") else []) + [o for o in (e.get("otros") or []) if isinstance(o, dict)]:
        if x.get("enlace"):
            una(x["enlace"], x.get("titulo") or "Estadístico")
    return salida


def _error_drive(codigo, texto, que):
    t = (texto or "").lower()
    if codigo == 403 and ("insufficient authentication scopes" in t or "access_token_scope_insufficient" in t
                          or ("insufficientpermissions" in t and "file" not in t)):
        return FaltaPermisoCompartir(
            "Para dar acceso a otras personas, Google pide un permiso más: «Ver, editar, crear y borrar tus archivos de Google Drive». "
            "Se pide una sola vez y solo a la cuenta que comparte.", 403, falta_permiso=True)
    if codigo in (403, 404) and ("insufficientfilepermissions" in t or "does not have sufficient permissions" in t
                                 or "file not found" in t or "notfound" in t):
        return ErrorSync(f"esta cuenta no puede compartir {que}: no es dueña ni editora de esa hoja (o no la ve)", codigo)
    if "shareoutnotpermitted" in t or "no se puede compartir fuera" in t or "cannot be shared outside" in t:
        dominio = re.search(r"fuera de (?:www\.)?([\w.-]+)|outside (?:of )?(?:www\.)?([\w.-]+)", texto or "")
        dom = next((g for g in (dominio.groups() if dominio else ()) if g), "tu empresa").rstrip(".\"")
        e = ErrorSync(f"Google Workspace de {dom} no deja compartir {que} con correos de fuera de {dom} (la marcó como contenido sensible). "
                      f"Solo el administrador de Google Workspace puede permitirlo; mientras tanto se puede dar acceso a un correo @{dom}.", codigo)
        e.bloqueo = dom
        return e
    if codigo == 400 and ("invalidsharingrequest" in t or "notify" in t):
        return ErrorSync("ese correo no tiene cuenta de Google: Google solo deja compartir avisándole por correo", codigo)
    return _traducir(codigo, texto, f"compartir {que}")


def _dar_permiso(http, sid, correo, rol, que, avisar=False, mensaje=""):
    q = {"sendNotificationEmail": "true" if (avisar or mensaje) else "false", "supportsAllDrives": "true", "fields": "id"}
    if mensaje:
        q["emailMessage"] = mensaje
    url = f"{DRIVE}/{sid}/permissions?" + urlencode(q)
    codigo, texto = http("POST", url, {"type": "user", "role": rol, "emailAddress": correo})
    if codigo == 400 and not avisar and "notif" in (texto or "").lower():     # correo sin cuenta de Google: solo se puede avisando
        return _dar_permiso(http, sid, correo, rol, que, avisar=True)
    if codigo == 0 or codigo >= 400:
        raise _error_drive(codigo, texto, que)


def _quitar_permiso(http, sid, correo, que):
    url = f"{DRIVE}/{sid}/permissions?" + urlencode({"fields": "permissions(id,emailAddress,role)", "supportsAllDrives": "true",
                                                     "pageSize": 100})
    codigo, texto = http("GET", url, None)
    if codigo == 0 or codigo >= 400:
        raise _error_drive(codigo, texto, que)
    for perm in (json.loads(texto or "{}").get("permissions") or []):
        if (perm.get("emailAddress") or "").lower() == correo.lower() and perm.get("role") != "owner":
            c2, t2 = http("DELETE", f"{DRIVE}/{sid}/permissions/{perm['id']}?supportsAllDrives=true", None)
            if c2 == 0 or (c2 >= 400 and c2 != 404):
                raise _error_drive(c2, t2, que)


def _ficha_doc(nombre, p, de, ahora):
    return {"v": 1, "nombre": nombre, "de": de, "mod": int(ahora),
            "p": {k: copy.deepcopy(v) for k, v in p.items() if k not in _NO_SE_COMPARTE and not str(k).startswith("_")}}


def escribir_ficha(http, nombre, p, de="", ahora=None):
    """Crea (si no existe) y llena la ficha del proyecto. Devuelve su id (queda en p["ficha"])."""
    fid = p.get("ficha")
    doc = _ficha_doc(nombre, p, de, ahora or time.time())
    if not fid:
        fid = _llamar(http, "POST", SHEETS, {"properties": {"title": titulo_ficha(nombre)}, "sheets": [{"properties": {"title": PESTANA}}]},
                      que="crear la ficha del proyecto")["spreadsheetId"]
    texto = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    trozos = [texto[i:i + TROZO] for i in range(0, len(texto), TROZO)] or [""]
    filas = [["NO BORRES NI EDITES ESTA HOJA: la usa «Estadístico FilmFlow» para darle el proyecto a su equipo."],
             [f"Proyecto «{nombre}» · compartido por {de or 'su encargado'} · {time.strftime('%Y-%m-%d %H:%M')}"], ["v1"]]
    filas += [[t] for t in trozos] + [[""]] * max(0, FILAS_TROZOS - len(trozos))
    try:
        _llamar(http, "POST", f"{SHEETS}/{fid}/values:batchUpdate",
                {"valueInputOption": "RAW", "data": [{"range": f"{PESTANA}!A1:A{len(filas)}", "values": filas}]}, que="guardar la ficha del proyecto")
    except ErrorSync as e:
        if e.codigo != 404 or not p.get("ficha"):
            raise
        p.pop("ficha", None)                                   # la borraron en Drive: se crea otra
        return escribir_ficha(http, nombre, p, de, ahora)
    p["ficha"] = fid
    return fid


def leer_ficha(http, fid):
    rango = quote(f"{PESTANA}!A4:A{3 + FILAS_TROZOS}", safe="")
    r = _llamar(http, "GET", f"{SHEETS}/{fid}/values/{rango}?valueRenderOption=UNFORMATTED_VALUE", que="leer la ficha del proyecto")
    texto = "".join(str(f[0]) for f in (r.get("values") or []) if f)
    try:
        doc = json.loads(texto)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("p"), dict) and doc.get("nombre") else None


def fichas_compartidas(http):
    """{id: {'t': modifiedTime, 'de': correo del dueño}} de las fichas que OTRAS personas te compartieron. None si no se pudo mirar."""
    q = f"name contains '{PREFIJO_FICHA.strip()}' and sharedWithMe = true and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    url = DRIVE + "?" + urlencode({"q": q, "fields": "files(id,name,modifiedTime,owners(emailAddress))", "pageSize": 100,
                                   "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}, quote_via=quote)
    try:
        codigo, texto = http("GET", url, None)
        archivos = json.loads(texto or "{}").get("files") or [] if 0 < codigo < 400 else None
    except Exception:                                          # mirar las fichas nunca debe impedir sincronizar
        return None
    if archivos is None:
        return None
    salida = {}
    for f in archivos:
        if str(f.get("name", "")).startswith(PREFIJO_FICHA):
            salida[f["id"]] = {"t": f.get("modifiedTime", ""), "de": ((f.get("owners") or [{}])[0]).get("emailAddress", "")}
    return salida


def dar_acceso(http, nombre, p, personas, de="", ahora=None):
    """Comparte las hojas del proyecto y su ficha con `personas` (correos de p["equipo"]). Cambia `p` (estado de cada persona y
    p["ficha"]): la app lo guarda después. Devuelve [(estado, texto)] para mostrar. Lanza FaltaPermisoCompartir si falta el permiso."""
    ahora = int(ahora or time.time())
    hojas = hojas_del_proyecto(p)
    if not hojas:
        raise ErrorSync("Este proyecto todavía no tiene hojas conectadas: conéctalas primero.")
    equipo = {x["correo"].lower(): x for x in p.get("equipo") or []}
    elegidos = [equipo[c.lower()] for c in personas if c.lower() in equipo]
    fid = escribir_ficha(http, nombre, p, de, ahora)
    salida = []
    for x in elegidos:
        rol = "writer" if x.get("puede", "editar") == "editar" else "reader"
        fallos, bloqueadas, dom = [], [], ""
        for sid, que in hojas:
            try:
                _dar_permiso(http, sid, x["correo"], rol, f"«{que}»")
            except FaltaPermisoCompartir:
                raise
            except ErrorSync as e:
                if getattr(e, "bloqueo", None):                # regla de Google Workspace: un solo aviso para todas esas hojas
                    bloqueadas.append(f"«{que}»")
                    dom = e.bloqueo
                else:
                    fallos.append(str(e))
        sin_hojas = len(fallos) + len(bloqueadas)                 # cuántas hojas NO se compartieron
        if bloqueadas:
            fallos.insert(0, f"Google Workspace de {dom} no deja compartir {' ni '.join(bloqueadas)} con correos de fuera de {dom} "
                             f"({'la marcó' if len(bloqueadas) == 1 else 'las marcó'} como contenido sensible). Solo el administrador de "
                             f"Google Workspace puede permitirlo; mientras tanto se puede dar acceso a un correo @{dom}.")
        if sin_hojas < len(hojas):                             # la ficha solo si tiene acceso al menos a una hoja (si no, vería
            try:                                               # un proyecto al que no puede entrar)
                _dar_permiso(http, fid, x["correo"], "reader", "la ficha del proyecto",
                             mensaje=f"Te agregaron al proyecto «{nombre}» en Estadístico FilmFlow. Abre este enlace en el celular o en el "
                                     f"computador para tenerlo en la app (entra con este mismo correo): {enlace_invitacion(fid)}")
            except FaltaPermisoCompartir:
                raise
            except ErrorSync as e:
                fallos.append(str(e))
        else:
            try:
                _quitar_permiso(http, fid, x["correo"], "la ficha del proyecto")
            except ErrorSync:
                pass
        fallos = list(dict.fromkeys(fallos))                   # (el mismo aviso para varias hojas: una sola vez)
        x["compartido"] = ahora
        x["estado"] = " ".join(fallos) if fallos else "ok"
        x["hojas"] = len(hojas)
        n_ok = len(hojas) - sin_hojas
        salida.append(("aviso", f"{x['nombre'] or x['correo']}: {n_ok} de {len(hojas)} hojas compartidas. " + " ".join(fallos)) if fallos else
                      ("ok", f"{x['nombre'] or x['correo']} ya tiene acceso ({'puede editar' if rol == 'writer' else 'solo ver'}) a "
                             f"{len(hojas)} {'hoja' if len(hojas) == 1 else 'hojas'}. Le llegó un correo de Google con el enlace para tener el "
                             f"proyecto en la app (también se lo puedes mandar tú): {enlace_invitacion(fid)}"))
    return salida


def quitar_acceso(http, p, correo):
    """Le quita a `correo` el acceso a las hojas del proyecto y a su ficha, y lo saca de p["equipo"]. Devuelve [(estado, texto)]."""
    fallos = []
    for sid, que in hojas_del_proyecto(p) + ([(p["ficha"], "la ficha del proyecto")] if p.get("ficha") else []):
        try:
            _quitar_permiso(http, sid, correo, f"«{que}»")
        except FaltaPermisoCompartir:
            raise
        except ErrorSync as e:
            fallos.append(str(e))
    p["equipo"] = [x for x in p.get("equipo") or [] if x["correo"].lower() != correo.lower()]
    return [("aviso", f"Quité a {correo} del equipo, pero revisa: " + "; ".join(fallos))] if fallos else \
        [("ok", f"{correo} ya no tiene acceso a las hojas de este proyecto.")]


RELEER_FICHAS = 600        # una ficha que Drive no lista se vuelve a leer cada 10 minutos como mucho (antes: en cada sincronización)


def _proyectos_compartidos(http, est, conocidas=(), forzar=False, ahora=None):
    """Los proyectos que te compartieron: las fichas que Drive deja ver (si tu sesión tiene ese permiso) más las CONOCIDAS (enlaces
    de invitación que abriste y las fichas de los proyectos que ya tienes de alguien). Devuelve (proyectos, caché, perdidas):
    proyectos = {nombre: (p, mod, id_ficha, de)}; perdidas = fichas que Google confirma que ya no puedes ver (te quitaron)."""
    vistas = fichas_compartidas(http) or {}
    viejas = est.get("fichas") or {}
    nuevas, salida, perdidas = {}, {}, set()
    for fid in list(vistas) + [f for f in conocidas if f not in vistas]:
        info = vistas.get(fid) or {"t": "", "de": ""}
        guardada = viejas.get(fid)
        reciente = guardada and guardada.get("doc") and not forzar and (ahora or time.time()) - guardada.get("leida", 0) < RELEER_FICHAS
        if (info["t"] and guardada and guardada.get("t") == info["t"] and guardada.get("doc")) or (not info["t"] and reciente):
            doc = guardada["doc"]
            leida = guardada.get("leida", 0)
        else:
            leida = int(ahora or time.time())
            try:
                doc = leer_ficha(http, fid)
            except ErrorSync as e:
                if e.codigo in (403, 404):                      # ya no tienes acceso (o la borraron)
                    perdidas.add(fid)
                    continue
                doc = (guardada or {}).get("doc")               # sin internet u otro problema: lo último que se leyó
                leida = (guardada or {}).get("leida", 0)
        if not doc:
            continue
        nuevas[fid] = {"t": info["t"], "doc": doc, "leida": leida}
        de = doc.get("de") or info["de"]
        p = dict(copy.deepcopy(doc["p"]), origen={"ficha": fid, "de": de})
        salida[doc["nombre"]] = (p, int(doc.get("mod", 0)), fid, de)
    return salida, nuevas, perdidas


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


def avisos_de_sync(r):
    """Los avisos para la persona después de sincronizar (los mismos en el Mac y en el celular)."""
    out = []
    if r.get("cuenta_anterior"):
        out.append(f"Cambiaste de cuenta: los proyectos de {r['cuenta_anterior']} quedaron guardados aparte en este equipo "
                   "(vuelven si entras otra vez con esa cuenta). Ahora ves solo los de esta cuenta.")
    if r.get("sin_acceso"):
        n = len(r["sin_acceso"])
        out.append(f"Quité de esta cuenta {'el proyecto' if n == 1 else f'{n} proyectos'} {', '.join(r['sin_acceso'])}: "
                   "esta cuenta no tiene permiso para abrir ninguna de sus hojas.")
    return out


def _ruta_cuenta(carpeta, correo):
    return Path(carpeta) / "cuentas" / (re.sub(r"[^a-z0-9._@-]", "_", correo.lower()) + ".json")


def _guardar_cuenta(carpeta, correo, config, est):
    """Guarda aparte los proyectos y el estado de sincronización de una cuenta (al cambiar de cuenta en este aparato)."""
    ruta = _ruta_cuenta(carpeta, correo)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(ruta.name + ".tmp")
        tmp.write_text(json.dumps({"config": config, "estado": est}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ruta)
    except OSError:
        pass


def _cargar_cuenta(carpeta, correo):
    """(config, estado) guardados de esa cuenta en este aparato, o (None, None)."""
    try:
        d = json.loads(_ruta_cuenta(carpeta, correo).read_text(encoding="utf-8"))
        return d.get("config"), d.get("estado")
    except (OSError, ValueError):
        return None, None


# ---------------------------------------------------------------------------------------- el trabajo
def sincronizar(http, correo, dispositivo="", crear=True, carpeta=None, ahora=None, gana_local_al_inicio=False, sid_manual=None,
                forzar_fichas=False):
    """Pone de acuerdo este aparato con Google. Devuelve un resumen:
    {'estado': 'ok'|'sin_config', 'sid', 'creada', 'bajados': [...], 'subidos': [...], 'borrados': [...], 'proyectos': n}
    `gana_local_al_inicio`: la PRIMERA vez que este aparato se sincroniza, si un proyecto existe en los dos lados con el mismo
    nombre, gana el de este aparato (el Mac: es el principal) o el de Google (el teléfono)."""
    carpeta = Path(carpeta or rc.CARPETA)
    ruta = carpeta / "config_registro.json"
    ahora = int(ahora or time.time())
    est = leer_estado(carpeta)
    cuenta_cambiada = None
    if est.get("correo") and correo and est["correo"].lower() != correo.lower():
        # otra cuenta de Google en este aparato: los proyectos de la anterior se guardan aparte (no se le suben a la cuenta nueva,
        # como pasó el 12/11/2026) y la cuenta nueva sigue con los suyos (si ya había entrado antes aquí) o empieza vacía
        cuenta_cambiada = est["correo"]
        _guardar_cuenta(carpeta, est["correo"], rc.leer_archivo(ruta), est)
        conf_nueva, est_nuevo = _cargar_cuenta(carpeta, correo)
        rc.escribir_archivo(conf_nueva or rc._config_vacia(), ruta, sin_aviso=True)
        est = est_nuevo or {}
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
    # proyectos que el encargado te compartió (fichas «FILMFLOW_PROYECTO · …»): aparecen solos y se actualizan con la ficha;
    # uno tuyo con el mismo nombre nunca se pisa. Si te quitaron el acceso (la ficha ya no está), el proyecto se quita.
    conocidas = set(est.get("fichas_unidas") or []) | {(e_[0].get("origen") or {}).get("ficha") for e_ in loc.values()} \
        | {(e_["p"].get("origen") or {}).get("ficha") for e_ in rem.values()}
    compartidos, fichas, perdidas_f = _proyectos_compartidos(http, est, sorted(x for x in conocidas if x), forzar=forzar_fichas, ahora=ahora)
    for n, (p_c, mod_c, fid, _de) in compartidos.items():
        r_ = rem.get(n)
        de_ficha = r_ is not None and ((r_["p"].get("origen") or {}).get("ficha") == fid)
        l_ = loc.get(n)
        if l_ is not None and (l_[0].get("origen") or {}).get("ficha") != fid:
            continue                                           # ya tienes un proyecto tuyo con ese nombre
        if r_ is None or (de_ficha and mod_c > int(r_.get("mod", 0))):
            rem[n] = {"p": p_c, "mod": mod_c}
    perdidos = set()
    for n, (p_l, _m, _h) in list(loc.items()):
        if (p_l.get("origen") or {}).get("ficha") in perdidas_f:
            borr[n] = ahora                                    # te quitaron el acceso a ese proyecto
            perdidos.add(n)
    for n, r_ in list(rem.items()):
        if (r_["p"].get("origen") or {}).get("ficha") in perdidas_f:
            rem.pop(n)
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

    # proyectos en los que esta cuenta no puede abrir NINGUNA de sus hojas (p. ej. se colaron de otra cuenta): se quitan y se avisa.
    # Cada proyecto se revisa una vez por cuenta (y otra vez si cambian sus hojas); un error de red no quita nada.
    sin_acceso, revisados = [], dict(est.get("revisados") or {})
    for n, e in list(final.items()):
        if e["p"].get("origen") or n == PROYECTO_INICIAL:
            continue
        ids = [x for x, _q in hojas_del_proyecto(e["p"])]
        firma = ",".join(sorted(ids))
        if not ids or revisados.get(n) == firma:
            continue
        codigos = []
        for x in ids:
            try:
                codigos.append(http("GET", f"{SHEETS}/{x}?fields=spreadsheetId", None)[0])
            except Exception:
                codigos.append(0)
        if all(c == 403 for c in codigos):                     # 403 = Google dice «sin permiso» (una hoja borrada da 404: no se quita)
            sin_acceso.append(n)
            final.pop(n)
            tumbas[n] = max(tumbas.get(n, 0), ahora)
            perdidos.add(n)
            for lista in (bajados, subidos):
                if n in lista:
                    lista.remove(n)
            if n in loc:
                borrados.append(n)
        elif any(200 <= c < 300 for c in codigos):
            revisados[n] = firma

    if not final:                                              # nunca se deja la app sin proyectos (salvo los que te quitaron)
        final = {n: {"p": copy.deepcopy(v[0]), "mod": v[1]} for n, v in loc.items() if n not in perdidos}

    # --- lo de aquí
    nuevo_local = copy.deepcopy(local)
    previos = [n for n in local["proyectos"] if n in final]
    orden = previos + [n for n in final if n not in previos]
    if final:
        nuevo_local["proyectos"] = {n: final[n]["p"] for n in orden}
    elif not nuevo_local["proyectos"] or perdidos:
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

    # --- las fichas de los proyectos que TÚ compartes: si el proyecto cambió (rollos, hojas…), su equipo recibe el cambio
    propias = dict(est.get("fichas_propias") or {})
    for n, e in final.items():
        if e["p"].get("ficha") and not e["p"].get("origen"):
            h = _huella({k: v for k, v in e["p"].items() if k not in _NO_SE_COMPARTE})
            if propias.get(n) != h:
                try:
                    escribir_ficha(http, n, dict(e["p"]), correo, e["mod"])
                    propias[n] = h
                except ErrorSync:
                    pass                                       # se intenta en la próxima sincronización

    _guardar_estado({"id": sid, "correo": correo, "ultima": ahora, "error": "",
                     "proyectos": {n: {"h": _huella(e["p"]), "mod": e["mod"]} for n, e in final.items()},
                     "borrados": doc["borrados"], "fichas": fichas,
                     "fichas_unidas": [f for f in (est.get("fichas_unidas") or []) if f not in perdidas_f],
                     "fichas_propias": {n: h for n, h in propias.items() if n in final},
                     "revisados": {n: f for n, f in revisados.items() if n in final}}, carpeta)
    return {"estado": "ok", "sid": sid, "creada": creada, "bajados": bajados, "subidos": subidos, "borrados": borrados,
            "proyectos": len(final), "sin_acceso": sin_acceso, "cuenta_anterior": cuenta_cambiada}


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
