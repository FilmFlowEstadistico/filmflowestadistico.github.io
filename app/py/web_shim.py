"""Piezas que cambian en el teléfono (todo lo demás es EXACTAMENTE el mismo código que la app del Mac).

- Sustituye openpyxl / pdfplumber (no se usan aquí: el PDF lo lee el navegador).
- Reemplaza la conexión a Google: en vez de la librería de Google para Python, habla directo con la API de Google Sheets
  usando el permiso (token) que el navegador consiguió al iniciar sesión.
"""
import json
import sys
import types
from types import SimpleNamespace
from urllib.parse import quote, urlencode


def instalar_stubs():
    for nombre in ("openpyxl", "pdfplumber"):
        if nombre not in sys.modules:
            sys.modules[nombre] = types.ModuleType(nombre)


BASE = "https://sheets.googleapis.com/v4/spreadsheets"
# transporte(metodo, url, cuerpo_texto_o_None, token) -> (codigo_http, texto). Lo pone el worker (XHR síncrono) o las pruebas.
ESTADO = {"transporte": None, "token": None, "correo": None, "conectado": False}


class ErrorHttp(Exception):
    """Imita el error de la librería de Google (tiene .resp.status), así los mensajes en español son los mismos."""

    def __init__(self, status, detalle=""):
        super().__init__(detalle or f"HTTP {status}")
        self.resp = SimpleNamespace(status=status)


class _Peticion:
    def __init__(self, metodo, url, cuerpo=None):
        self.metodo, self.url, self.cuerpo = metodo, url, cuerpo

    def execute(self):
        if not ESTADO["token"]:
            raise ErrorHttp(401, "sin sesión")
        codigo, texto = ESTADO["transporte"](self.metodo, self.url,
                                             json.dumps(self.cuerpo) if self.cuerpo is not None else None, ESTADO["token"])
        if codigo == 0:
            raise ConnectionError(texto)
        if codigo >= 400:
            raise ErrorHttp(codigo, texto[:300])
        return json.loads(texto) if texto else {}


def _consulta(**kv):
    pares = []
    for k, v in kv.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        if isinstance(v, (list, tuple)):
            pares += [(k, x) for x in v]
        else:
            pares.append((k, v))
    return ("?" + urlencode(pares, quote_via=quote)) if pares else ""


class _Valores:
    def get(self, spreadsheetId, range, valueRenderOption=None):
        return _Peticion("GET", f"{BASE}/{spreadsheetId}/values/{quote(range, safe='')}"
                         + _consulta(valueRenderOption=valueRenderOption))

    def batchGet(self, spreadsheetId, ranges, valueRenderOption=None):
        return _Peticion("GET", f"{BASE}/{spreadsheetId}/values:batchGet"
                         + _consulta(ranges=ranges, valueRenderOption=valueRenderOption))

    def batchUpdate(self, spreadsheetId, body):
        return _Peticion("POST", f"{BASE}/{spreadsheetId}/values:batchUpdate", body)


class _Hojas:
    def get(self, spreadsheetId, fields=None, ranges=None, includeGridData=None):
        return _Peticion("GET", f"{BASE}/{spreadsheetId}" + _consulta(fields=fields, ranges=ranges, includeGridData=includeGridData))

    def batchUpdate(self, spreadsheetId, body):
        return _Peticion("POST", f"{BASE}/{spreadsheetId}:batchUpdate", body)

    def values(self):
        return _Valores()


class ServicioWeb:
    def spreadsheets(self):
        return _Hojas()


def instalar_google(rg):
    """Cambia, dentro de registro_google, lo que dependía de la librería de Google para Python."""
    from registro_core import ErrorRegistro

    def conectar(carpeta=None, interactivo=False):
        if not ESTADO["token"]:
            raise ErrorRegistro(rg.NO_CONECTADO)
        return ServicioWeb()

    def estado_cuenta(carpeta=None):
        if ESTADO["conectado"]:
            return {"conectado": True, "correo": ESTADO["correo"], "motivo": ""}
        return {"conectado": False, "correo": None, "motivo": "Todavía no has iniciado sesión."}

    def tiene_llave(carpeta=None):
        return True

    rg.conectar, rg.estado_cuenta, rg.tiene_llave = conectar, estado_cuenta, tiene_llave


def http_directo(metodo, url, cuerpo=None):
    """Para sync_core: una petición suelta a Google con la sesión actual. Devuelve (código, texto); 0 = sin internet."""
    if not ESTADO["token"]:
        return 401, "sin sesión"
    return ESTADO["transporte"](metodo, url, json.dumps(cuerpo) if cuerpo is not None else None, ESTADO["token"])
