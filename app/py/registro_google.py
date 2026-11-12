#!/usr/bin/env python3
"""
REGISTRO DIARIO - CONEXIÓN CON GOOGLE SHEETS
============================================
Aquí está todo lo que habla con Google: iniciar sesión (una sola vez), leer tu
hoja, escribir el bloque del día y leerlo de vuelta para comprobarlo.

Necesita en la misma carpeta el archivo  credenciales.json  (la "llave" que se
crea una sola vez en Google). La primera vez se abre el navegador para pedir
permiso; después queda guardado en  token.json.
"""
import json
import os
import re
import shutil
import sys
import time
import threading
from pathlib import Path
from types import SimpleNamespace

from registro_core import CARPETA, PRIMERA_FILA, ErrorRegistro

PERMISO_DRIVE = "https://www.googleapis.com/auth/drive.file"    # solo los archivos que crea la app (encontrar la hoja de sincronización)
PERMISO_DRIVE_VIEJO = "https://www.googleapis.com/auth/drive.metadata.readonly"   # el de antes (las sesiones viejas lo traen)
PERMISOS = ["https://www.googleapis.com/auth/spreadsheets", PERMISO_DRIVE, "openid",
            "https://www.googleapis.com/auth/userinfo.email"]
CORREO = "https://www.googleapis.com/auth/userinfo.email"
PERMISO_COMPARTIR = "https://www.googleapis.com/auth/drive"   # solo para «Equipo del proyecto» (dar acceso a las hojas); se pide al usarlo
FALTA_LLAVE = ("Falta la «llave» de Google (el archivo credenciales.json). "
               "Pulsa «Conectar con Google» y elige el archivo cuando te lo pida.")
NO_CONECTADO = ("Todavía no has conectado tu cuenta de Google (o la sesión venció). "
                "Pulsa «Conectar con Google» y vuelve a intentar.")


def id_de_enlace(enlace):
    m = re.search(r"/d/([A-Za-z0-9_-]+)", enlace or "")
    if not m:
        raise ErrorRegistro("El enlace de la hoja no parece de Google Sheets. "
                            "Ve a «Ajustes del proyecto», pulsa «Cambiar…» y pega el enlace completo (el de la barra de direcciones).")
    return m.group(1)


def _nombre_pestana(pestana):
    return "'" + pestana.replace("'", "''") + "'"


def _traducir(error):
    """Convierte un error de Google en una frase simple."""
    codigo = getattr(getattr(error, "resp", None), "status", None)
    if codigo == 404:
        return "Google no encuentra esa hoja. Revisa el enlace en «Ajustes del proyecto» (botón «Cambiar…»)."
    if codigo == 403:
        return ("Google dice que esta cuenta no tiene permiso para editar esa hoja. "
                "Entra con la cuenta que es dueña de la hoja, o pide que te den acceso de editor.")
    if codigo == 400 and "not supported for this document" in str(error):
        return ("Ese archivo es un Excel guardado en Drive, no una hoja de Google. "
                "Ábrelo y usa Archivo > Guardar como hoja de cálculo de Google.")
    if codigo is None and isinstance(error, (OSError, EOFError)):       # SSL, internet caído, tiempo agotado…
        return "No pude hablar con Google (la conexión falló o tardó demasiado). Revisa tu internet y vuelve a intentar."
    if codigo == 429:
        return "Google recibió demasiadas peticiones seguidas. Espera un minuto y vuelve a intentar."
    if codigo == 401:
        return "La sesión de Google venció. Pulsa «Conectar con Google» y vuelve a intentar."
    if isinstance(codigo, int) and codigo >= 500:
        return "Google tuvo un problema por su lado (no es tu hoja). Espera un momento y vuelve a intentar."
    return f"Google respondió con un error ({codigo}): {error}"


def _google():
    """Las piezas de Google, o un aviso claro si no están instaladas."""
    try:
        from google.auth.exceptions import RefreshError, TransportError
        from google.auth.transport.requests import AuthorizedSession, Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ErrorRegistro(
            "Falta instalar las piezas de Google en el Python que abre este programa.\n"
            "Abre la Terminal, copia y pega EXACTAMENTE esta línea y presiona Enter:\n\n"
            f'"{sys.executable}" -m pip install google-api-python-client google-auth-oauthlib\n\n'
            "Cuando termine, cierra este programa y ábrelo de nuevo.")
    return SimpleNamespace(RefreshError=RefreshError, TransportError=TransportError,
                           AuthorizedSession=AuthorizedSession, Request=Request, Credentials=Credentials,
                           InstalledAppFlow=InstalledAppFlow, build=build)


def tiene_llave(carpeta=CARPETA):
    return (carpeta / "credenciales.json").exists()


def instalar_llave(origen, carpeta=CARPETA):
    """Copia el archivo de llave que descargó la persona, comprobando que sí lo es."""
    try:
        datos = json.loads(Path(origen).read_text(encoding="utf-8"))
    except Exception:
        raise ErrorRegistro("Ese archivo no se puede leer. Debe ser el JSON que descargaste de Google Cloud.")
    if "installed" not in datos:
        raise ErrorRegistro("Ese archivo no es una llave de «App de escritorio». "
                            "En Google Cloud crea el cliente OAuth con tipo «App de escritorio» y descárgalo de nuevo.")
    shutil.copy2(origen, carpeta / "credenciales.json")


def _cargar_credenciales(carpeta, g):
    """(credenciales, motivo): motivo = None si todo bien, 'sin_sesion', 'vencida' o 'sin_internet'."""
    token = carpeta / "token.json"
    if not token.exists():
        return None, "sin_sesion"
    try:
        creds = g.Credentials.from_authorized_user_file(str(token))   # con los permisos que ya se dieron
    except Exception:
        return None, "vencida"
    if creds.valid:
        return creds, None
    if creds.expired and creds.refresh_token:
        try:
            with _CANDADO_TOKEN:                       # dos hilos no deben renovar y escribir el token a la vez
                creds.refresh(g.Request())
                tmp = token.with_name(token.name + ".tmp")
                tmp.write_text(creds.to_json())
                os.replace(tmp, token)                 # escritura atómica: nunca queda un token a medias
            return creds, None
        except g.TransportError:
            return None, "sin_internet"
        except Exception:
            return None, "vencida"
    return None, "vencida"


_CANDADO_TOKEN = threading.Lock()
_CACHE = {"mtime": None, "servicio": None, "correo": None, "gen": 0}
_LOCAL = threading.local()         # cada hilo tiene su propia conexión (así dos lecturas pueden ir de verdad a la vez)
_TITULOS = {}                      # nombre real de cada hoja: (nombre, hora); se vuelve a preguntar cada 10 minutos


def _mtime(carpeta):
    try:
        return (carpeta / "token.json").stat().st_mtime
    except OSError:
        return None


def estado_cuenta(carpeta=CARPETA):
    """Dice si hay una cuenta de Google conectada, sin abrir el navegador.
    {'conectado': True/False/None (None = no pude comprobar), 'correo': ..., 'motivo': texto}"""
    try:
        g = _google()
    except ErrorRegistro:
        return {"conectado": False, "correo": None, "motivo": "Faltan las piezas de Google por instalar."}
    creds, motivo = _cargar_credenciales(carpeta, g)
    if not creds:
        texto = {"sin_sesion": "Todavía no has iniciado sesión.",
                 "vencida": "La sesión venció; conéctala de nuevo.",
                 "sin_internet": "No pude comprobarlo (¿sin internet?)."}[motivo]
        return {"conectado": None if motivo == "sin_internet" else False, "correo": None, "motivo": texto}
    correo = _CACHE["correo"] if _CACHE["mtime"] == _mtime(carpeta) else None
    if correo is None and CORREO in (creds.scopes or []):
        try:
            correo = g.AuthorizedSession(creds).get("https://www.googleapis.com/oauth2/v3/userinfo",
                                                   timeout=10).json().get("email")
            _CACHE.update(mtime=_mtime(carpeta), correo=correo)
        except Exception:
            pass
    return {"conectado": True, "correo": correo, "motivo": ""}


def conectar_cuenta(carpeta=CARPETA, extra=()):
    """Abre el navegador para que la persona elija su cuenta de Google y dé permiso. `extra`: permisos de más (p. ej. compartir)."""
    g = _google()
    llave = carpeta / "credenciales.json"
    if not llave.exists():
        raise ErrorRegistro(FALTA_LLAVE)
    try:
        flujo = g.InstalledAppFlow.from_client_secrets_file(str(llave), PERMISOS + [x for x in extra if x not in PERMISOS])
        argumentos = dict(port=0, prompt="select_account",
                          success_message="Listo, ya puedes volver a la aplicación.")
        try:
            creds = flujo.run_local_server(timeout_seconds=240, **argumentos)   # no se queda esperando para siempre
        except TypeError:
            creds = flujo.run_local_server(**argumentos)
    except Exception as e:
        texto = f"{type(e).__name__} {e}".lower()
        if "access_denied" in texto or "accessdenied" in texto:
            raise ErrorRegistro(
                "Google no dejó entrar con esa cuenta (error 403, access_denied).\n\n"
                "Pasa cuando la app todavía está en «modo de prueba» en Google Cloud y esa cuenta no está en la lista "
                "de usuarios de prueba. Quien administra la llave de Google debe PUBLICAR la app "
                "(Google Auth Platform → Público → Publicar app) para que cualquier cuenta pueda conectarse. "
                "Mientras tanto puede agregar tu correo como usuario de prueba.")
        if "scope has changed" in texto:
            raise ErrorRegistro(
                "Entraste con tu cuenta, pero no marcaste el permiso de Google Sheets.\n\n"
                "Vuelve a pulsar «Conectar con Google». En la pantalla de permisos de Google aparece una casilla "
                "«Ver, editar, crear y borrar todas tus hojas de cálculo de Google Drive». "
                "Debe quedar MARCADA (viene sin marcar). Luego pulsa «Continuar».")
        if "timeout" in texto or "timed out" in texto:
            raise ErrorRegistro("Se acabó el tiempo esperando que eligieras tu cuenta en el navegador. Vuelve a intentarlo.")
        raise ErrorRegistro(f"No se pudo conectar con Google: {e}")
    (carpeta / "token.json").write_text(creds.to_json())
    _CACHE.update(mtime=None, servicio=None, correo=None, gen=_CACHE["gen"] + 1)


def desconectar(carpeta=CARPETA):
    token = carpeta / "token.json"
    if token.exists():
        token.unlink()
    _CACHE.update(mtime=None, servicio=None, correo=None, gen=_CACHE["gen"] + 1)


def _http_seguro(creds):
    """Conexión a Google con tiempo máximo (20 s) y un reintento si falla la red. Se crea UNA por hilo (httplib2 no se
    puede compartir entre hilos); antes todo pasaba por un candado global y las lecturas hacían fila una detrás de otra."""
    import ssl
    import time

    import google_auth_httplib2
    import httplib2

    class _Http(google_auth_httplib2.AuthorizedHttp):
        def request(self, *a, **k):
            ultimo = None
            for intento in range(2):
                try:
                    return super().request(*a, **k)
                except (ssl.SSLError, ConnectionError, TimeoutError, OSError, EOFError, httplib2.HttpLib2Error) as e:
                    ultimo = e
                    time.sleep(0.4)
            raise ultimo

    return _Http(creds, http=httplib2.Http(timeout=20))


def tiene_permiso(permiso, carpeta=CARPETA):
    try:
        return permiso in (json.loads((carpeta / "token.json").read_text()).get("scopes") or [])
    except Exception:
        return False


def tiene_permiso_drive(carpeta=CARPETA):
    """True si la sesión guardada ya incluye el permiso para encontrar la hoja de sincronización."""
    try:
        permisos = json.loads((carpeta / "token.json").read_text()).get("scopes") or []
        return PERMISO_DRIVE in permisos or PERMISO_DRIVE_VIEJO in permisos or PERMISO_COMPARTIR in permisos
    except Exception:
        return False


def transporte_http(carpeta=CARPETA):
    """Función http(metodo, url, cuerpo)->(código, texto) con tu sesión de Google (para la sincronización)."""
    g = _google()
    creds, motivo = _cargar_credenciales(carpeta, g)
    if not creds:
        raise ErrorRegistro(NO_CONECTADO if motivo != "sin_internet" else "No hay conexión con Google.")
    ses = g.AuthorizedSession(creds)

    def http(metodo, url, cuerpo=None):
        try:
            r = ses.request(metodo, url, json=cuerpo, timeout=25)
            return r.status_code, r.text
        except Exception as e:
            return 0, str(e)
    return http


def conectar(carpeta=CARPETA, interactivo=False):
    """Devuelve el servicio de Google Sheets (uno por hilo, y se reutiliza mientras la sesión no cambie: es lo más rápido).
    Si no hay cuenta conectada avisa; no abre el navegador."""
    mt = _mtime(carpeta)
    if getattr(_LOCAL, "servicio", None) is not None and _LOCAL.mtime == mt and _LOCAL.gen == _CACHE["gen"] and mt is not None:
        return _LOCAL.servicio
    g = _google()
    creds, motivo = _cargar_credenciales(carpeta, g)
    if not creds:
        if motivo == "sin_internet":
            raise ErrorRegistro("No hay conexión con Google. Revisa tu internet y vuelve a intentar.")
        if not interactivo:
            raise ErrorRegistro(NO_CONECTADO)
        conectar_cuenta(carpeta)
        creds, _ = _cargar_credenciales(carpeta, g)
    try:
        servicio = g.build("sheets", "v4", http=_http_seguro(creds), cache_discovery=False)
    except ImportError:                                  # sin las piezas extra: conexión normal
        servicio = g.build("sheets", "v4", credentials=creds, cache_discovery=False)
    _LOCAL.servicio, _LOCAL.mtime, _LOCAL.gen = servicio, _mtime(carpeta), _CACHE["gen"]
    _CACHE.update(mtime=_mtime(carpeta))
    return servicio


def titulo_hoja(servicio, sid):
    """El nombre real del archivo en Google (para que sepas EN CUÁL escribe). Se pregunta una vez por sesión."""
    import time
    if sid in _TITULOS and time.time() - _TITULOS[sid][1] < 600:
        return _TITULOS[sid][0]
    _titulo_y_pestanas(servicio, sid)
    return _TITULOS[sid][0]


def _titulo_y_pestanas(servicio, sid):
    """El nombre del archivo y sus pestañas en UNA consulta (antes eran dos: una para cada cosa); quedan en memoria 10 min."""
    import time
    try:
        r = servicio.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties(title,sheetType)").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    ahora = time.time()
    _TITULOS[sid] = (r.get("properties", {}).get("title", ""), ahora)
    _PESTANAS[sid] = ([h["properties"]["title"] for h in r.get("sheets", []) if h["properties"].get("sheetType", "GRID") == "GRID"], ahora)


def info_completa(servicio, sid, pestana=None):
    """TODO en una sola consulta: nombre de la hoja, sus pestañas y, si das una pestaña,
    su id y cuántas filas tiene."""
    try:
        r = servicio.spreadsheets().get(
            spreadsheetId=sid,
            fields="properties.title,sheets.properties(sheetId,title,sheetType,gridProperties.rowCount),sheets.merges").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    completas = [h for h in r.get("sheets", []) if h["properties"].get("sheetType", "GRID") == "GRID"]
    hojas = [h["properties"] for h in completas]
    info = {"titulo": r["properties"]["title"], "pestanas": [h["title"] for h in hojas],
            "sheet_id": None, "filas": None, "merges": None}
    if pestana is not None:
        for h, completa in zip(hojas, completas):
            if h["title"] == pestana:
                info.update(sheet_id=h["sheetId"], filas=h["gridProperties"]["rowCount"], merges=completa.get("merges", []))
                break
        else:
            raise ErrorRegistro(f"No encuentro la pestaña «{pestana}» en la hoja. Las que hay son: {', '.join(info['pestanas'])}.")
    return info


def listar_pestanas(servicio, sid):
    """Los nombres de las pestañas de la hoja (para elegir en cuál se escribe)."""
    try:
        r = servicio.spreadsheets().get(
            spreadsheetId=sid, fields="sheets.properties(title,sheetType)").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return [h["properties"]["title"] for h in r.get("sheets", [])
            if h["properties"].get("sheetType", "GRID") == "GRID"]


def _hex(color):
    return "#{:02X}{:02X}{:02X}".format(*(int(round(color.get(k, 0) * 255)) for k in ("red", "green", "blue")))


def _letra_de_columna(i):
    return _letras(i)


def color_de_filas(servicio, sid, pestana, filas, columna=3):
    """{fila: '#RRGGBB'}: el color real que tiene hoy la columna CAM en esas filas."""
    filas = sorted(set(filas))
    if not filas:
        return {}
    nombre = _nombre_pestana(pestana)
    try:
        r = servicio.spreadsheets().get(
            spreadsheetId=sid, ranges=[f"{nombre}!{_letra_de_columna(columna)}{f}:{_letra_de_columna(columna)}{f}" for f in filas], includeGridData=True,
            fields="sheets.data.rowData.values.effectiveFormat.backgroundColor").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    salida = {}
    for fila, bloque in zip(filas, (r.get("sheets") or [{}])[0].get("data", [])):
        try:
            salida[fila] = _hex(bloque["rowData"][0]["values"][0]["effectiveFormat"]["backgroundColor"])
        except (KeyError, IndexError, TypeError):
            pass
    return salida


def _letras(i):
    """Número de columna (desde 0) -> letras de Google: 0 -> A, 26 -> AA."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def fondos(servicio, sid, pestana, filas, columnas):
    """{(fila desde 1, columna desde 0): '#RRGGBB'}: el color de fondo REAL que muestra hoy la hoja en esas celdas
    (ya con el formato condicional: por ejemplo, los ceros se ven blancos)."""
    filas, columnas = sorted(set(filas)), sorted(set(columnas))
    if not filas or not columnas:
        return {}
    nombre, c0, c1 = _nombre_pestana(pestana), columnas[0], columnas[-1]
    try:
        r = servicio.spreadsheets().get(
            spreadsheetId=sid, ranges=[f"{nombre}!{_letras(c0)}{f}:{_letras(c1)}{f}" for f in filas], includeGridData=True,
            fields="sheets.data.rowData.values.effectiveFormat.backgroundColor").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    salida = {}
    for fila, bloque in zip(filas, (r.get("sheets") or [{}])[0].get("data", [])):
        for i, v in enumerate((bloque.get("rowData") or [{}])[0].get("values", [])):
            color = (v.get("effectiveFormat") or {}).get("backgroundColor")
            if color is not None and c0 + i in columnas:
                salida[(fila, c0 + i)] = _hex(color)
    return salida


def info_hoja(servicio, sid, pestana):
    """Devuelve (id_de_la_pestaña, cantidad_de_filas_que_tiene)."""
    try:
        r = servicio.spreadsheets().get(
            spreadsheetId=sid, fields="sheets.properties(sheetId,title,gridProperties(rowCount))").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    for hoja in r.get("sheets", []):
        p = hoja["properties"]
        if p["title"] == pestana:
            return p["sheetId"], p["gridProperties"]["rowCount"]
    nombres = ", ".join(h["properties"]["title"] for h in r.get("sheets", []))
    raise ErrorRegistro(f"No encuentro la pestaña «{pestana}» en la hoja. Las que hay son: {nombres}.")


def leer_hoja(servicio, sid, pestana):
    """Lee la pestaña completa con las fórmulas como texto y devuelve sus filas de datos (las que van debajo de la fila de títulos,
    esté donde esté) con el formato de esa hoja (`.fmt`: fila de inicio y columna de cada cosa). Ver registro_core.tabla_de_hoja."""
    import registro_core as rc
    try:
        r = servicio.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{_nombre_pestana(pestana)}!A1:Z",
            valueRenderOption="FORMULA").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return rc.tabla_de_hoja(r.get("values", []))


def leer_pestanas_valores(servicio, sid, pestanas):
    """Varias pestañas con sus VALORES reales en UNA sola consulta: {pestaña: filas}. Solo lectura."""
    pestanas = list(pestanas)
    if len(pestanas) == 1:
        return {pestanas[0]: leer_hoja_valores(servicio, sid, pestanas[0])}
    try:
        r = servicio.spreadsheets().values().batchGet(
            spreadsheetId=sid, ranges=[f"{_nombre_pestana(p)}!A1:Z" for p in pestanas],
            valueRenderOption="UNFORMATTED_VALUE").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return {p: b.get("values", []) for p, b in zip(pestanas, r.get("valueRanges", []))}


_PESTANAS = {}                      # lista de pestañas de cada hoja: (lista, hora); se vuelve a preguntar cada 10 minutos


def olvidar_pestanas(sid=None):
    """Borra la memoria de pestañas y nombres (por ejemplo al pulsar «Actualizar» a la fuerza)."""
    for memoria in (_PESTANAS, _TITULOS):
        if sid is None:
            memoria.clear()
        else:
            memoria.pop(sid, None)


def pestanas_de(servicio, sid):
    """Los nombres de las pestañas (con memoria de 10 minutos para no preguntar en cada actualización)."""
    hoy = time.time()
    previo = _PESTANAS.get(sid)
    if previo and hoy - previo[1] < 600:
        return previo[0]
    _titulo_y_pestanas(servicio, sid)
    return _PESTANAS[sid][0]


def leer_hoja_valores(servicio, sid, pestana):
    """La pestaña completa con los VALORES reales (fechas y horas como números), para el Resumen. Solo lectura."""
    try:
        r = servicio.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{_nombre_pestana(pestana)}!A1:Z",
            valueRenderOption="UNFORMATTED_VALUE").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return r.get("values", [])


def _partir_encabezado(filas):
    import registro_core as rc
    hallado = rc.encontrar_encabezado(filas)
    if hallado:
        i, columnas = hallado
        return filas[i + 1:], i + 2, filas[:i], columnas
    return filas[PRIMERA_FILA - 1:], PRIMERA_FILA, filas[:PRIMERA_FILA - 1], {}


def leer_hoja_desde_encabezado(servicio, sid, pestana):
    """Lee la pestaña completa y busca por sí sola la fila de títulos (la que tiene «CAM», «RENTAL»…),
    sin importar en qué fila o columna esté. Devuelve (filas_de_datos, número_de_la_primera_fila,
    filas_de_arriba, columnas). Si no encuentra los títulos usa el orden del formato (datos desde la fila 7)."""
    import registro_core as rc
    try:
        r = servicio.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{_nombre_pestana(pestana)}!A1:Z",
            valueRenderOption="FORMULA").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    filas = r.get("values", [])
    hallado = rc.encontrar_encabezado(filas)
    if hallado:
        i, columnas = hallado
        return filas[i + 1:], i + 2, filas[:i], columnas
    return filas[PRIMERA_FILA - 1:], PRIMERA_FILA, filas[:PRIMERA_FILA - 1], {}


def descubrir_rollos(servicio, sid, pestana_principal, pestanas, titulo_hoja=""):
    """Recorre las pestañas de la hoja (primero la elegida) y devuelve {"rollos": …, "proyecto": nombre
    escrito en la hoja}: los rollos que ya existen, con el color que tienen en la hoja. Una pestaña que no se pueda leer o no tenga el formato se salta."""
    import registro_core as rc
    orden = [pestana_principal] + [p for p in pestanas if p != pestana_principal][:7]
    listas, proyecto = [], ""
    precargadas = {}
    if len(orden) > 1:                                  # todas las pestañas en UNA consulta (antes: una consulta por pestaña)
        try:
            r = servicio.spreadsheets().values().batchGet(
                spreadsheetId=sid, ranges=[f"{_nombre_pestana(p)}!A1:Z" for p in orden],
                valueRenderOption="FORMULA").execute()
            for p, bloque in zip(orden, r.get("valueRanges", [])):
                precargadas[p] = bloque.get("values", [])
        except Exception:
            precargadas = {}                            # si algo falla se lee pestaña por pestaña, como antes
    for p in orden:
        try:
            if p in precargadas:
                valores, primera, arriba, columnas = _partir_encabezado(precargadas[p])
            else:
                valores, primera, arriba, columnas = leer_hoja_desde_encabezado(servicio, sid, p)
            rollos = rc.inferir_rollos(valores, primera, columnas)
            for r in rollos:
                r["_columna"] = columnas.get("cam", 3)
            if p == pestana_principal:
                proyecto = rc.titulo_de_proyecto(arriba, (p, titulo_hoja))
        except ErrorRegistro as e:
            if p == pestana_principal or "No pude hablar con Google" in str(e):      # sin conexión no tiene caso seguir con las demás
                raise
            continue
        if rollos:
            listas.append((p, rollos))
    hallados = rc.combinar_hallazgos(listas)
    for p in {r["pestana_fila"] for r in hallados}:
        propios = [r for r in hallados if r["pestana_fila"] == p]
        try:
            colores = color_de_filas(servicio, sid, p, [r["fila"] for r in propios], propios[0].get("_columna", 3))
        except ErrorRegistro:
            colores = {}
        for r in propios:
            c = colores.get(r["fila"], "")
            r["color"] = "" if c.upper() in ("", "#FFFFFF") else c
    return {"rollos": hallados, "proyecto": proyecto}


def insertar_fila(servicio, sid, pestana, fila0):
    """Inserta UNA fila vacía en `pestana` en la posición `fila0` (desde 0), con el formato de la fila de arriba.
    Para el estadístico: un día que no tiene fila (HDT: «DIA 903» después de «DIA 902») se agrega debajo del anterior."""
    hoja_id, _n = info_hoja(servicio, sid, pestana)
    escribir(servicio, sid, [{"insertDimension": {"range": {"sheetId": hoja_id, "dimension": "ROWS", "startIndex": fila0,
                                                            "endIndex": fila0 + 1}, "inheritFromBefore": fila0 > 0}}])


def _letra_col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def escribir_valores(servicio, sid, celdas):
    """Como escribir_celdas, pero Google interpreta lo escrito como si se tecleara (las fórmulas «=SUM(…)» quedan como fórmulas)."""
    datos = [{"range": f"{_nombre_pestana(p)}!{c}", "values": [[v]]} for p, c, v in celdas]
    if not datos:
        return
    try:
        servicio.spreadsheets().values().batchUpdate(
            spreadsheetId=sid, body={"valueInputOption": "USER_ENTERED", "data": datos}).execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))


def _formulas_de(servicio, sid, pestana, rango):
    try:
        r = servicio.spreadsheets().values().get(spreadsheetId=sid, range=f"{_nombre_pestana(pestana)}!{rango}",
                                                 valueRenderOption="FORMULA").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return r.get("values", [])


def aplicar_estructura(servicio, sid, pestanas, est):
    """Cambios de forma del estadístico antes de escribir los números (los arma estadistico_core.proponer):
    1) inserta columnas (cámara nueva) y filas (su fila en el Resumen General, o el día que no tenía fila), con el formato de al lado;
    2) copia lo que hace falta (la fórmula de la fila TOTAL, la fila modelo del Resumen) y las fórmulas de la fila de arriba en un día
       insertado (TOTAL (GB)…); 3) escribe títulos, ceros y fórmulas; 4) si una cámara quedó al final del grupo, amplía la suma de
       «TOTAL (GB)» de cada día (también la del día que se escribe si no suma una cámara con material: AAZ =SUM(E5:L5)+AA5 sin la CAM J).
    `pestanas` = {'datos': nombre, 'resumen': nombre}."""
    if not est:
        return
    if est.get("ops"):
        _aplicar_forma(servicio, sid, pestanas, est)
    _ampliar_totales(servicio, sid, pestanas, est)


def _aplicar_forma(servicio, sid, pestanas, est):
    try:                                                   # una sola consulta para los id de las pestañas (antes una por pestaña)
        meta = servicio.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties(sheetId,title)").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    por_titulo = {h["properties"]["title"]: h["properties"]["sheetId"] for h in meta.get("sheets", [])}
    ids = {}
    for h, p in pestanas.items():
        if p:
            if p not in por_titulo:
                raise ErrorRegistro(f"No encuentro la pestaña «{p}» en el estadístico.")
            ids[h] = por_titulo[p]
    reqs = []
    for tipo, hoja, idx, heredar in est["ops"]:
        reqs.append({"insertDimension": {"range": {"sheetId": ids[hoja], "dimension": "COLUMNS" if tipo == "col" else "ROWS",
                                                   "startIndex": idx, "endIndex": idx + 1}, "inheritFromBefore": bool(heredar and idx > 0)}})
    escribir(servicio, sid, reqs)
    reqs = []
    for hoja, sr, sc, dr, dc in est.get("copias", []):
        rango = lambda r, c: ({"sheetId": ids[hoja], "startRowIndex": r, "endRowIndex": r + 1} if c is None else
                              {"sheetId": ids[hoja], "startRowIndex": r, "endRowIndex": r + 1, "startColumnIndex": c, "endColumnIndex": c + 1})
        reqs.append({"copyPaste": {"source": rango(sr, sc), "destination": rango(dr, dc), "pasteType": "PASTE_NORMAL",
                                   "pasteOrientation": "NORMAL"}})
    for r in est.get("formulas_de_arriba", []):           # un día insertado: las fórmulas de su fila de al lado (TOTAL (GB) = SUM…)
        if r >= 0:
            src, dst = r - 1, r                             # de la fila de arriba
        else:
            dst = -r - 1
            src = dst + 1                                   # (va encima del primer día: de la fila de abajo)
        fila = (_formulas_de(servicio, sid, pestanas["datos"], f"A{src + 1}:BZ{src + 1}") or [[]])[0]
        for c, v in enumerate(fila):
            if isinstance(v, str) and v.startswith("="):
                reqs.append({"copyPaste": {"source": {"sheetId": ids["datos"], "startRowIndex": src, "endRowIndex": src + 1,
                                                      "startColumnIndex": c, "endColumnIndex": c + 1},
                                           "destination": {"sheetId": ids["datos"], "startRowIndex": dst, "endRowIndex": dst + 1,
                                                           "startColumnIndex": c, "endColumnIndex": c + 1},
                                           "pasteType": "PASTE_NORMAL", "pasteOrientation": "NORMAL"}})
    if reqs:
        escribir(servicio, sid, reqs)
    hoja_datos = "'" + str(pestanas["datos"]).replace("'", "''") + "'"
    escribir_valores(servicio, sid, [(pestanas[h], f"{_letra_col(c)}{r + 1}", v.replace("{DATOS}", hoja_datos) if isinstance(v, str) else v)
                                     for h, r, c, v in est.get("celdas", [])])
    if pestanas.get("resumen"):
        _empezar_sumas_en(servicio, sid, pestanas["resumen"], est.get("inicio_resumen", []))
    _sumas_con_dia_nuevo(servicio, sid, pestanas["datos"], est.get("sumas_total", []))


def _ampliar_totales(servicio, sid, pestanas, est):
    for a in est.get("ampliar", []):                       # que «TOTAL (GB)» de cada día sume también la cámara nueva
        letra = _letra_col(a["col_total"])
        filas_ = sorted(set(a["filas"]) | {r if r >= 0 else -r - 1 for r in est.get("formulas_de_arriba", [])})
        if not filas_:
            continue
        r0, r1 = filas_[0] + 1, filas_[-1] + 1
        valores = _formulas_de(servicio, sid, pestanas["datos"], f"{letra}{r0}:{letra}{r1}")
        nuevas = []
        for i, fila in enumerate(valores):
            v = fila[0] if fila else ""
            w = sumar_columna(v, a["nueva"], a["cams"], r0 + i)
            if w != v:
                nuevas.append((pestanas["datos"], f"{letra}{r0 + i}", w))
        escribir_valores(servicio, sid, nuevas)


def _empezar_sumas_en(servicio, sid, pestana, inicios):
    """Filas nuevas de cámara ENCIMA de las demás en el Resumen General: Google corre las sumas (=SUM(F17:F20) → F19:F22) en vez de
    agrandarlas. Cada suma de esa columna que empieza justo debajo de filas «CAM …» se hace empezar en la primera de ellas."""
    if not inicios:
        return
    valores = _formulas_de(servicio, sid, pestana, "A1:Z300")
    es_cam = [any(isinstance(x, str) and re.fullmatch(r"\s*CAM\s+[A-Z]{1,3}\s*", x, re.I) for x in fila) for fila in valores]
    letras = sorted({_letra_col(a["col"]) for a in inicios})
    nuevas = []
    for r, fila in enumerate(valores):
        for c, v in enumerate(fila):
            if not (isinstance(v, str) and v.startswith("=")):
                continue
            w = v
            for letra in letras:                         # todas las letras sobre la MISMA fórmula (antes la 2.ª borraba la 1.ª)
                # (?<![!\w$]): no toca referencias a OTRA pestaña ('Datos Generales'!F19:F40)
                patron = re.compile(r"(?<![!\w$'])(\$?)" + letra + r"(\$?)(\d+)(:\$?" + letra + r"\$?\d+)")

                def mover(m, letra=letra):
                    ini = int(m.group(3))                    # (desde 1)
                    while ini - 2 >= 0 and ini - 2 < len(es_cam) and es_cam[ini - 2]:
                        ini -= 1
                    return f"{m.group(1)}{letra}{m.group(2)}{ini}{m.group(4)}"
                w = patron.sub(mover, w)
            if w != v:
                nuevas.append((pestana, f"{_letra_col(c)}{r + 1}", w))
    escribir_valores(servicio, sid, nuevas)


def _sumas_con_dia_nuevo(servicio, sid, pestana, filas0):
    """Un día insertado justo DESPUÉS del último (o ANTES del primero): las sumas de la fila TOTAL (=SUM(E4:E21)) no lo incluyen
    solas. Se agrandan para que empiecen o terminen en él."""
    if not filas0:
        return
    valores = _formulas_de(servicio, sid, pestana, "A1:BZ1500")
    nuevas = []
    for r, fila in enumerate(valores):
        if not (fila and isinstance(fila[0], str) and fila[0].strip().upper().startswith("TOTAL")):
            continue
        for c, v in enumerate(fila):
            if not (isinstance(v, str) and v.startswith("=")):
                continue
            w = v
            for r0 in filas0:
                nueva1 = r0 + 1                              # la fila nueva (desde 1)

                def mover(m):
                    a, b = int(m.group(3)), int(m.group(6))
                    if m.group(1) != m.group(4):
                        return m.group(0)
                    if b == nueva1 - 1:
                        b = nueva1                          # terminaba en el día de arriba: ahora termina en el nuevo
                    if a == nueva1 + 1:
                        a = nueva1                          # empezaba en el día de abajo: ahora empieza en el nuevo
                    return f"{m.group(1)}{m.group(2)}{a}:{m.group(4)}{m.group(5)}{b}"
                w = re.sub(r"(?<![!A-Z$])(\$?[A-Z]{1,3})(\$?)(\d+):(\$?[A-Z]{1,3})(\$?)(\d+)", mover, w)
            if w != v:
                nuevas.append((pestana, f"{_letra_col(c)}{r + 1}", w))
    escribir_valores(servicio, sid, nuevas)


def columnas_de_formula(formula):
    """Las columnas (desde 0) que suma una fórmula de la misma fila: «=SUM(E4:K4,U4)» → {4…10, 20}."""
    cols = set()
    for m in re.finditer(r"\$?([A-Z]{1,3})\$?\d+(?::\$?([A-Z]{1,3})\$?\d+)?", formula or ""):
        a = _num_col(m.group(1))
        b = _num_col(m.group(2)) if m.group(2) else a
        cols.update(range(min(a, b), max(a, b) + 1))
    return cols


def _num_col(letras):
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n - 1


def sumar_columna(formula, nueva, cams, fila1):
    """Si la fórmula del día suma otras cámaras pero no la columna `nueva`, se la agrega: «=SUM(E4,F4,G4,M4)» → «=SUM(E4,F4,G4,M4,H4)»."""
    if not (isinstance(formula, str) and formula.startswith("=")):
        return formula
    cubre = columnas_de_formula(formula)
    if nueva in cubre or not any(c in cubre for c in cams):
        return formula
    ref = f"{_letra_col(nueva)}{fila1}"
    if re.match(r"^=\s*SUM\(", formula, re.I) and formula.rstrip().endswith(")"):
        return formula.rstrip()[:-1] + "," + ref + ")"
    return formula + "+" + ref


def escribir(servicio, sid, solicitudes):
    try:
        servicio.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": solicitudes}).execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))


def leer_para_comprobar(servicio, sid, pestana, inicio, total):
    """Lee lo escrito: valores reales de inicio..total y las fórmulas de la fila total (`total` = la última fila escrita)."""
    nombre = _nombre_pestana(pestana)
    try:
        v = servicio.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{nombre}!A{inicio}:Z{total}",
            valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        f = servicio.spreadsheets().values().get(
            spreadsheetId=sid, range=f"{nombre}!A{total}:Z{total}",
            valueRenderOption="FORMULA").execute().get("values", [])
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return v, f


# =============================================================================
# Segundo Excel (estadístico FO-07): leer celdas, escribir valores sueltos y comprobarlos
# =============================================================================
def leer_cuadriculas(servicio, sid, pestanas, rango="A1:BZ1200"):
    """Varias pestañas de una misma hoja en UNA sola consulta, con los valores reales
    (fechas y horas como números). Devuelve una lista de cuadrículas en el mismo orden."""
    try:
        r = servicio.spreadsheets().values().batchGet(
            spreadsheetId=sid, ranges=[f"{_nombre_pestana(p)}!{rango}" for p in pestanas],
            valueRenderOption="UNFORMATTED_VALUE").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    return [bloque.get("values", []) for bloque in r.get("valueRanges", [])]


def escribir_celdas(servicio, sid, celdas):
    """`celdas`: lista de (pestaña, 'E46', valor). Escribe solo esas celdas, tal cual (sin tocar formatos)."""
    datos = [{"range": f"{_nombre_pestana(p)}!{c}", "values": [[v]]} for p, c, v in celdas]
    try:
        servicio.spreadsheets().values().batchUpdate(
            spreadsheetId=sid, body={"valueInputOption": "RAW", "data": datos}).execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))


def leer_celdas(servicio, sid, celdas):
    """`celdas`: lista de (pestaña, 'E46'). Devuelve {(pestaña, 'E46'): valor}."""
    if not celdas:
        return {}
    rangos = [f"{_nombre_pestana(p)}!{c}" for p, c in celdas]
    try:
        r = servicio.spreadsheets().values().batchGet(
            spreadsheetId=sid, ranges=rangos, valueRenderOption="UNFORMATTED_VALUE").execute()
    except Exception as e:
        raise ErrorRegistro(_traducir(e))
    salida = {}
    for (p, c), bloque in zip(celdas, r.get("valueRanges", [])):
        v = bloque.get("values", [[""]])
        salida[(p, c)] = v[0][0] if v and v[0] else ""
    return salida
