#!/usr/bin/env python3
"""
ESTADÍSTICO (FF-GS-FO-07) - LÓGICA
==================================
Con lo que sale del PDF de un día (las mismas filas que se escriben en el FO-06) calcula la
fila de ese día en el segundo Excel («Datos Generales») y los datos del «Resumen General».

No habla con Google: recibe las celdas ya leídas (una lista de filas) y devuelve la lista de
cambios que se proponen. Así se puede probar sin internet.

Reglas (confirmadas contra los Excel reales de DSMD y Primera Plana):
  - GB y clips de cada cámara = suma de sus rollos del día. La cámara es la primera letra del rollo.
  - ROLLOS = cantidad de filas de video (todo lo que no es sonido).
  - DURACIÓN = suma de las duraciones de esas filas.
  - AUDIO (GB y clips) = suma de las filas de sonido.
  - Las columnas se buscan por su título («CAM A (GB)»…), nunca por posición.
  - No se tocan SEMANA, DÍA, UNIDAD, TOTAL (GB) ni las fórmulas.
"""
import math
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta

from registro_core import ErrorRegistro, clave_de_bin, hms

ORIGEN_EXCEL = datetime(1899, 12, 30)


# =============================================================================
# Utilidades de celdas
# =============================================================================
def _n(t):
    """Texto en minúsculas, sin acentos y con un solo espacio entre palabras."""
    t = unicodedata.normalize("NFD", str(t if t is not None else ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


def letra_de_columna(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def a1(fila, col):
    """(fila, columna) con base 0 -> 'E46'."""
    return f"{letra_de_columna(col)}{fila + 1}"


def cel(grid, fila, col):
    try:
        v = grid[fila][col]
    except IndexError:
        return ""
    return "" if v is None else v


def es_numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def serial_de_fecha(fecha):
    return (datetime(fecha.year, fecha.month, fecha.day) - ORIGEN_EXCEL).days


def fecha_de_serial(n):
    return ORIGEN_EXCEL + timedelta(days=int(n))


def _es_serial(n):
    return 20000 <= n < 80000                      # fechas de 1954 a 2119 como las cuenta Excel / Google Sheets


def _formato_de_numero(n):
    """Cómo está escrita una fecha que es un número: ('serial'|'ddmmyyyy'|'yyyymmdd', date) o None.
    Serial = 46293 (lo normal); ddmmyyyy = 28092026 o 1102026 (sin el cero); yyyymmdd = 20260928."""
    try:
        n = int(float(n))
    except (TypeError, ValueError, OverflowError):
        return None
    if _es_serial(n):
        return "serial", fecha_de_serial(n).date()
    t = str(n)
    if len(t) in (7, 8):
        t8 = t.zfill(8)
        d, m, a = int(t8[:2]), int(t8[2:4]), int(t8[4:])
        if 1990 <= a <= 2100:
            try:
                return "ddmmyyyy", date(a, m, d)
            except ValueError:
                pass
        if len(t) == 8:
            a, m, d = int(t8[:4]), int(t8[4:6]), int(t8[6:])
            if 1990 <= a <= 2100:
                try:
                    return "yyyymmdd", date(a, m, d)
                except ValueError:
                    pass
    return None


class _OrdenPorHilo:
    """Igual que un diccionario {"texto": "dmy"}, pero cada hilo tiene el suyo (dos lecturas a la vez no se pisan)."""
    def __init__(self):
        self._l = threading.local()

    def __getitem__(self, k):
        return getattr(self._l, "v", "dmy")

    def __setitem__(self, k, v):
        self._l.v = v


ORDEN_FECHA = _OrdenPorHilo()      # cómo se escriben las fechas de texto con «/» en la hoja abierta: dmy (28/09/2026) o mdy (9/28/2026, CELOS)


def detectar_orden_fecha(textos):
    """Mira las fechas escritas como texto de una hoja: si alguna tiene el 2.º número > 12 es mes/día/año; si el 1.º > 12, día/mes/año."""
    orden = "dmy"
    for v in textos:
        m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*", str(v)) if isinstance(v, str) else None
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12:
                orden = "dmy"; break
            if b > 12:
                orden = "mdy"; break
    ORDEN_FECHA["texto"] = orden
    return orden


class orden_de_fechas:
    """`with orden_de_fechas(textos):` mientras se leen las fechas de UNA hoja: usa el orden (día/mes o mes/día) de esa hoja y,
    al terminar, deja el que había (así leer el estatus no cambia cómo se leen las fechas del estadístico)."""
    def __init__(self, textos):
        self.textos = list(textos)

    def __enter__(self):
        self.previo = ORDEN_FECHA["texto"]
        detectar_orden_fecha(self.textos)
        return self

    def __exit__(self, *_a):
        ORDEN_FECHA["texto"] = self.previo
        return False


def fecha_segun_sonido(fecha, nombres):
    """Corrige una fecha con el día y el mes al revés (Google con formato de EE. UU. guarda «07/09/2026» como 9 de julio): si el archivo
    de la grabadora de ese día (26Y09M07 = 07/09/2026) queda cerca de la fecha con día y mes cambiados, se usa esa. Si no, la misma."""
    if not fecha:
        return fecha
    for n in nombres:
        m = re.match(r"\s*(\d{2})Y(\d{2})M(\d{2})", str(n or ""))
        if not m:
            continue
        try:
            s = date(2000 + int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            continue
        if fecha.day > 12 or fecha.day == fecha.month:
            return fecha                                  # no puede estar al revés
        al_reves = date(fecha.year, fecha.day, fecha.month)
        if abs((al_reves - s).days) <= 3 < abs((fecha - s).days):
            return al_reves                               # al revés cuadra con la grabadora (o casi: un día de diferencia se avisa aparte)
        return fecha
    return fecha


def fecha_de_celda(v):
    """La fecha (date) que hay en una celda, o None. Entiende fechas de Excel, 28092026, 20260928, «28/09/2026» y fechas reales.
    Nunca falla: si no la entiende, None."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if es_numero(v):
        r = _formato_de_numero(v)
        return r[1] if r else None
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*", v)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            mdy = a <= 12 and (b > 12 or ORDEN_FECHA["texto"] == "mdy")
            try:
                return date(y, a, b) if mdy else date(y, b, a)
            except ValueError:
                return None
        m = re.fullmatch(r"\s*(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\s*", v) or re.fullmatch(r"\s*(\d{4})(\d{2})(\d{2})\s*", v)
        if m:                                           # «2026/10/07» (La Casamentera) o «20250821» escritos como texto (EDLLB)
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def convencion_de_fecha(datos, tabla):
    """Cómo escribe las fechas ESTE estadístico: 'serial' (lo normal), 'ddmmyyyy', 'yyyymmdd' o 'texto'. Se mira lo que ya hay."""
    for d in tabla["dias"]:
        v = cel(datos, d["fila"], tabla["fecha"])
        if es_numero(v):
            r = _formato_de_numero(v)
            if r:
                return r[0]
        elif isinstance(v, str) and fecha_de_celda(v):
            return "texto"
    return "serial"


def valor_de_fecha(fecha, convencion):
    """La fecha escrita como la escribe el estadístico (para no cambiarle el formato a la hoja)."""
    if convencion == "ddmmyyyy":
        return int(f"{fecha.day:02d}{fecha.month:02d}{fecha.year}")
    if convencion == "yyyymmdd":
        return int(f"{fecha.year}{fecha.month:02d}{fecha.day:02d}")
    if convencion == "texto":
        if ORDEN_FECHA["texto"] == "mdy":
            return f"{fecha.month}/{fecha.day}/{fecha.year}"
        return f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year}"
    return serial_de_fecha(fecha)


def _texto_fecha(v, formato="{d}/{m}/{y}"):
    """Una fecha para mostrar. Si es un número que no es fecha de Excel (28092026) se muestra tal cual, como lo ve la hoja."""
    if es_numero(v):
        n = int(float(v))
        if _es_serial(n):
            f = fecha_de_serial(n)
            return formato.format(d=f.day, m=f.month, y=f.year)
        return str(n)
    return str(v)


def numero_de_dia(texto):
    """'D051' → 51; '20261009_DAY051' → 51; 'DAY_001 LMA' → 1; 'DIA 01 Piloto' → 1. None si no hay número."""
    return partir_dia(texto)[0]


def partir_dia(texto):
    """('DAY_001 LMA') → (1, 'LMA'): el número del día y lo que le sigue (para distinguir DAY_001 LMA de DAY_001 MGF)."""
    t = str(texto)
    m = re.search(r"DAY[_\s-]*0*(\d+)", t, re.IGNORECASE) or re.search(r"(\d+)", t)
    if not m:
        return None, ""
    return int(m.group(1)), re.sub(r"[^A-Z0-9]", "", t[m.end():].upper())


def emparejar_dias(dias06, dias07):
    """Qué fila del estadístico corresponde a cada día del estatus. `dias06` y `dias07`: listas de (número, sufijo, fecha|None).
    1) mismo número y mismo sufijo (DAY_001 LMA con DAY01 LMA); 2) mismo número y la misma fecha; 3) mismo número y es la única
    que queda (D001 con «DIA 01 Piloto»). Si hay dudas no adivina. Devuelve {posición_06: posición_07}."""
    res, usados = {}, set()
    for i, (n, s, _f) in enumerate(dias06):
        for j, (n2, s2, _f2) in enumerate(dias07):
            if j not in usados and n is not None and n == n2 and s == s2:
                res[i] = j
                usados.add(j)
                break
    for i, (n, _s, f) in enumerate(dias06):
        if i in res or n is None:
            continue
        libres = [j for j, (n2, _s2, _f2) in enumerate(dias07) if n2 == n and j not in usados]
        por_fecha = [j for j in libres if f is not None and dias07[j][2] == f]
        elegido = por_fecha[0] if por_fecha else (libres[0] if len(libres) == 1 else None)
        if elegido is not None:
            res[i] = elegido
            usados.add(elegido)
    return res


def igual(a, b):
    """Dos valores de celda son «lo mismo» (números con tolerancia, el resto como texto)."""
    if es_numero(a) and es_numero(b):
        return abs(float(a) - float(b)) < 0.005
    return str(a if a is not None else "") == str(b if b is not None else "")


class _Vista:
    """Las celdas de «Datos Generales» tal como quedarían con los cambios (sin copiar toda la hoja)."""

    def __init__(self, datos, cambios):
        self.datos = datos
        self.nuevo = {(c["fila"], c["col"]): c["nuevo"] for c in cambios if c["hoja"] == "datos"}

    def __call__(self, fila, col):
        if (fila, col) in self.nuevo:
            return self.nuevo[(fila, col)]
        return cel(self.datos, fila, col)


# =============================================================================
# 1. Encontrar la tabla de «Datos Generales» por sus títulos
# =============================================================================
# «CAM A (GB)», «CAM A (clips)», pero también «CAM D» (solo, es el GB) y «CAM P (P)» (otra unidad: se toma como GB si no hay otra)
_CAM = re.compile(r"^cam(?:ara)?\s+([a-z0-9]+)\s*(?:\(\s*([a-z]*)\s*\)?)?$")
_DIA = ("dia", "day", "jornada")
_FECHA = ("fecha", "date")


def encontrar_tabla(grid, limite=40):
    """Busca la fila de títulos (la que tiene DÍA y FECHA) y devuelve
    {'fila_enc', 'dia', 'fecha', 'gb': {letra: col}, 'clips': {...}, 'rollos', 'duracion',
     'audio_gb', 'audio_clips', 'total', 'editorial', 'executives', 'dias': [{'fila','num','texto'}]}."""
    for i, fila in enumerate(grid[:limite]):
        t = [_n(x) for x in fila]
        idx_dia = next((j for j, x in enumerate(t) if x in _DIA), None)
        idx_fecha = next((j for j, x in enumerate(t) if x in _FECHA), None)
        if idx_dia is None or idx_fecha is None:
            continue
        tabla = {"fila_enc": i, "dia": idx_dia, "fecha": idx_fecha,
                 "gb": {}, "clips": {}, "rollos": None, "duracion": None, "audio_gb": None,
                 "audio_clips": None, "total": None, "editorial": None, "executives": None, "unidad": None}
        sueltas = {}                                   # unidades raras («CAM P (P)»): GB solo si esa cámara no trae otra
        for j, x in enumerate(t):
            m = _CAM.match(x)
            if m:
                unidad = m.group(2) or "gb"
                clave = m.group(1).upper()
                if unidad.startswith("clip"):
                    tabla["clips"][clave] = j
                elif unidad == "gb" or not m.group(2):
                    tabla["gb"][clave] = j
                else:
                    sueltas.setdefault(clave, j)
            elif x in ("unidad", "unit", "unidad de rodaje") and tabla["unidad"] is None:
                tabla["unidad"] = j
            elif x in ("rollos", "reels", "rolls"):
                tabla["rollos"] = j
            elif x.startswith("duracion") or x.startswith("duration"):
                tabla["duracion"] = j
            elif x.startswith("audio") and "gb" in x:
                tabla["audio_gb"] = j
            elif x.startswith("audio") and "clip" in x:
                tabla["audio_clips"] = j
            elif x.startswith("total") and "gb" in x:
                tabla["total"] = j
            elif re.match(r"^(editorial|executiv|ejecutiv)", x):          # «EDITORIAL (GB)», «EDITORIALES (GB)», «EXECUTIVES (GB)»
                tabla["editorial" if x.startswith("editorial") else "executives"] = j
            elif x.startswith("dailies") and tabla.get("dailies") is None:      # La Casamentera: «DAILIES (GB)», se deja como está
                tabla["dailies"] = j
        for clave, j in sueltas.items():
            tabla["gb"].setdefault(clave, j)
        if not tabla["gb"] and tabla["rollos"] is None:
            continue
        dias = []
        orden_previo = ORDEN_FECHA["texto"]                  # (se restaura al final: no se queda pegado en el hilo para otras hojas)
        tabla["orden_fecha"] = detectar_orden_fecha([cel(grid, r, tabla["fecha"]) for r in range(i + 1, len(grid))
                              if not _n(cel(grid, r, 0)).startswith("total")])
        for r in range(i + 1, len(grid)):
            if _n(cel(grid, r, 0)).startswith("total"):
                break
            texto = str(cel(grid, r, tabla["dia"]))
            num, suf = partir_dia(texto)
            if num is not None:
                u = cel(grid, r, tabla["unidad"]) if tabla["unidad"] is not None else None
                dias.append({"fila": r, "num": num, "suf": suf, "texto": texto,
                             "fecha": fecha_de_celda(cel(grid, r, tabla["fecha"])),
                             "unidad": int(u) if es_numero(u) else None})
        tabla["dias"] = dias
        ORDEN_FECHA["texto"] = orden_previo
        return tabla
    raise ErrorRegistro("No encontré la tabla de «Datos Generales» en esa pestaña "
                        "(busco una fila de títulos con DÍA, FECHA y las cámaras como «CAM A (GB)»).")


def describir_tabla(grid, tabla):
    """Lo que entendió la app del «Datos Generales», en una frase: «cámaras A, B, C, D (E, F, G aún vacías) · 29 días, 3 con datos»."""
    con = set()
    dias_con = 0
    for d in tabla["dias"]:
        hay = False
        for k, c in tabla["gb"].items():
            v = cel(grid, d["fila"], c)
            if es_numero(v) and float(v) > 0:
                con.add(k)
                hay = True
        dias_con += hay
    letras = sorted(tabla["gb"])
    usadas = [k for k in letras if k in con] or letras
    vacias = [k for k in letras if k not in usadas]
    return (f"{'cámara' if len(usadas) == 1 else 'cámaras'} {', '.join(usadas)}"
            + (f" ({', '.join(vacias)} aún {'vacía' if len(vacias) == 1 else 'vacías'})" if vacias else "")
            + f" · {len(tabla['dias'])} días, {dias_con} con datos")


# =============================================================================
# 2. Calcular el día desde las filas del PDF
# =============================================================================
def calcular_dia(filas, es_sonido, claves=None):
    """`filas`: las filas armadas del día; `es_sonido(fila)` -> True si es audio.
    `claves`: las cámaras (columnas) que tiene el estadístico; con ellas M001L se cuenta en la columna ML. Sin ellas, por la primera letra."""
    gb, clips = {}, {}
    rollos, seg, a_gb, a_clips = 0, 0, 0.0, 0
    for f in filas:
        if es_sonido(f):
            a_gb += f["gb"]
            a_clips += f["clips"]
        else:
            letra = f.get("cam_forzada")
            if not letra:
                nom = str(f["nombre"]).strip()
                # un nombre sin ningún número («BETACAM_TEST») no dice de qué cámara es: no se mete en la columna de su primera letra
                letra = clave_de_bin(nom, claves) if nom else "?"          # BETACAM_TEST → «BETACAM», su propia cámara
            mez = f.get("audio_mezclado") or {}            # tarjeta de cámara que trae también audio (HDT DAY902): esa parte va a AUDIO
            gb[letra] = gb.get(letra, 0.0) + f["gb"] - mez.get("gb", 0.0)
            clips[letra] = clips.get(letra, 0) + f["clips"] - mez.get("clips", 0)
            a_gb += mez.get("gb", 0.0)
            a_clips += mez.get("clips", 0)
            rollos += 1
            seg += f["seg"] - mez.get("seg", 0)
    gb = {k: round(v, 2) for k, v in gb.items()}
    return {"gb": gb, "clips": clips, "rollos": rollos, "seg": int(round(seg)),
            "audio_gb": round(a_gb, 2), "audio_clips": a_clips,
            "gb_video": round(sum(gb.values()), 2), "clips_video": sum(clips.values())}


# =============================================================================
# 3. Proponer los cambios
# =============================================================================
def _bonito(v, tipo):
    if v is None or v == "":
        return "—"
    if tipo == "gb":
        return f"{float(v):,.2f}" if es_numero(v) else str(v)
    if tipo == "hora":
        return hms(round(float(v) * 86400)) if es_numero(v) else str(v)
    if tipo == "fecha":
        return _texto_fecha(v, "{d:02d}/{m:02d}/{y}") if es_numero(v) else str(v)
    if tipo == "num":
        return str(int(v)) if es_numero(v) and float(v) == int(v) else str(v)
    return str(v)


def _cambio(hoja, fila, col, concepto, antes, nuevo, tipo):
    return {"hoja": hoja, "celda": a1(fila, col), "fila": fila, "col": col, "concepto": concepto,
            "antes": antes, "nuevo": nuevo, "tipo": tipo,
            "antes_txt": _bonito(antes, tipo), "nuevo_txt": _bonito(nuevo, tipo)}


def _fila_del_dia(tabla, num, fecha=None, datos=None, unidad=1, dedicado=False, por_fecha=True):
    """La fila del día `num`. Si el número se repite (DAY_001 LMA y DAY_001 MGF): la de la misma fecha; si no, la primera
    que todavía está vacía; si no, la primera."""
    candidatas = [d for d in tabla["dias"] if d["num"] == num]
    if not candidatas and fecha is not None and por_fecha:   # el PDF trae el día «relativo» (Camera_Media: Shooting Day 1) → la fila por la FECHA
        # (si la carpeta del PDF dice el día —20261123_DAY031— NO se busca por fecha: CODT/PP traen fechas PLANEADAS en las filas
        #  futuras y el 31 caería en la fila del «DIA 30»)
        f0 = fecha.date() if isinstance(fecha, datetime) else fecha
        candidatas = [d for d in tabla["dias"] if d.get("fecha") == f0 and (dedicado or d.get("unidad") in (None, unidad))]
    if dedicado:                                        # este estadístico es SOLO de una unidad (hay uno por unidad): no se filtra por unidad
        pass
    elif tabla.get("unidad") is not None:                 # un estadístico con columna UNIDAD: cada unidad tiene sus filas
        de_la_unidad = [d for d in candidatas if d.get("unidad") in (None, unidad)]
        if candidatas and not de_la_unidad:
            raise ErrorRegistro(f"Este reporte es de la unidad {unidad}, y en «Datos Generales» el día {num} solo existe para la unidad "
                                f"{sorted({d['unidad'] for d in candidatas})}. No escribí el estadístico para no pisar los datos de otra unidad. "
                                f"Agrega la fila del día {num} para la unidad {unidad} (columna UNIDAD) y vuelve a intentar.")
        candidatas = de_la_unidad
    elif unidad > 1:
        raise ErrorRegistro(f"Este reporte es de la unidad {unidad}, pero tu estadístico no tiene columna UNIDAD ni filas para esa unidad. "
                            "No escribí el estadístico para no sobrescribir los datos de la unidad 1. Si la unidad "
                            f"{unidad} lleva su propio estadístico, conéctalo en «Hojas conectadas → Agregar otro estadístico».")
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    if not candidatas:
        libre = _fila_libre_para(tabla, num, datos, unidad, dedicado)
        if libre is not None:
            return libre, False
        ultima = tabla["dias"][-1]["texto"] if tabla["dias"] else "ninguna"
        raise ErrorRegistro(f"No encuentro la fila del día {num} en «Datos Generales» (la última fila con día es «{ultima}», "
                            f"y debajo del día {num - 1} no hay una fila vacía para usar). Agrega esa fila en el estadístico y vuelve a intentar.")
    if len(candidatas) == 1:
        return candidatas[0], False
    if fecha is not None:
        misma = [d for d in candidatas if d.get("fecha") == fecha]
        if len(misma) == 1:
            return misma[0], False
    if datos is not None:
        cols = list(tabla["gb"].values()) + ([tabla["rollos"]] if tabla["rollos"] is not None else [])
        vacias = [d for d in candidatas if not any(es_numero(cel(datos, d["fila"], c)) and cel(datos, d["fila"], c) > 0 for c in cols)]
        if vacias:
            return vacias[0], len(vacias) > 1
    return candidatas[0], True


def _siguiente_etiqueta(texto, num):
    """«DIA 901» → «DIA 902» · «DAY_007» → «DAY_008» · «D049» → «D050»: el mismo estilo, con el número nuevo (mismos ceros a la izquierda)."""
    m = re.search(r"DAY[_\s-]*(\d+)", texto, re.IGNORECASE) or re.search(r"(\d+)", texto)
    viejo = m.group(1)
    return texto[:m.start(1)] + str(num).zfill(len(viejo)) + texto[m.end(1):]


def _fila_usable(tabla, datos, r):
    """Una fila de «Datos Generales» sin etiqueta de día y sin datos (ceros o vacío): se puede usar para un día que no está escrito."""
    if r < len(datos) and (_n(cel(datos, r, 0)).startswith("total") or str(cel(datos, r, tabla["dia"])).strip()):
        return False
    cols = list(tabla["gb"].values()) + list(tabla["clips"].values()) + ([tabla["rollos"]] if tabla["rollos"] is not None else [])
    return not any(es_numero(cel(datos, r, c)) and cel(datos, r, c) > 0 for c in cols)


def _fila_libre_para(tabla, num, datos, unidad=1, dedicado=False):
    """El día `num` no tiene fila escrita. Se usa una fila sin etiqueta y sin datos: la de justo debajo del día anterior
    («DIA 901» → «DIA 902»), la de justo encima del día siguiente («DIA 902» → «DIA 901»), o, si no hay ningún día escrito,
    la primera debajo de los títulos; y se propone escribir la etiqueta del día con el estilo de la hoja.
    Devuelve el día (con «nueva_etiqueta») o None."""
    if datos is None:
        return None
    if not tabla["dias"]:
        # estadístico SIN ningún día escrito (plantilla vacía): el primero va en la primera fila debajo de los títulos, «DIA 901»
        r, base, suf, u = tabla["fila_enc"] + 1, None, "", (unidad if tabla.get("unidad") is not None else None)
        etiqueta = f"DIA {num}"
    else:
        de_unidad = lambda d: dedicado or tabla.get("unidad") is None or d.get("unidad") in (None, unidad)
        previos = [d for d in tabla["dias"] if d["num"] == num - 1 and de_unidad(d)]
        siguientes = [d for d in tabla["dias"] if d["num"] == num + 1 and de_unidad(d)]
        if len(previos) == 1 and _fila_usable(tabla, datos, previos[0]["fila"] + 1):
            # debajo del día anterior («DIA 901» y debajo la fila sin etiqueta → «DIA 902»)
            r, base, suf, u = previos[0]["fila"] + 1, previos[0]["texto"].strip(), previos[0]["suf"], previos[0].get("unidad")
            etiqueta = _siguiente_etiqueta(base, num)
        elif len(siguientes) == 1 and siguientes[0]["fila"] - 1 > tabla["fila_enc"] and _fila_usable(tabla, datos, siguientes[0]["fila"] - 1):
            # encima del día siguiente (HDT: la fila de «DIA 901» quedó sin etiqueta y debajo está «DIA 902»)
            r, suf, u = siguientes[0]["fila"] - 1, siguientes[0]["suf"], siguientes[0].get("unidad")
            etiqueta = _siguiente_etiqueta(siguientes[0]["texto"].strip(), num)
            return {"fila": r, "num": num, "suf": suf, "texto": etiqueta, "fecha": None, "unidad": u,
                    "nueva_etiqueta": etiqueta, "debajo_de": None, "encima_de": siguientes[0]["texto"].strip()}
        elif len(previos) == 1:
            # no hay fila libre (HDT: «DIA 902» y debajo ya está «DIA 1»): se INSERTA una fila nueva justo debajo del día anterior
            base = previos[0]["texto"].strip()
            etiqueta = _siguiente_etiqueta(base, num)
            return {"fila": previos[0]["fila"] + 1, "num": num, "suf": previos[0]["suf"], "texto": etiqueta, "fecha": None,
                    "unidad": previos[0].get("unidad"), "nueva_etiqueta": etiqueta, "debajo_de": base, "insertar": True}
        else:
            # tampoco está el día anterior (la plantilla llega hasta «DIA 30» y el reporte es el 68): se inserta después del día
            # escrito más alto que sea menor, para que los días sigan en orden
            menores = [d for d in tabla["dias"] if d["num"] < num and de_unidad(d)]
            if not menores:
                # solo hay días mayores (el 5 y el 6 escritos y llega el 2): se inserta encima del menor de ellos
                mayores = [d for d in tabla["dias"] if d["num"] > num and de_unidad(d)]
                if not mayores:
                    return None
                sig = min(mayores, key=lambda d: (d["num"], d["fila"]))
                etiqueta = _siguiente_etiqueta(sig["texto"].strip(), num)
                return {"fila": sig["fila"], "num": num, "suf": sig["suf"], "texto": etiqueta, "fecha": None,
                        "unidad": sig.get("unidad"), "nueva_etiqueta": etiqueta, "debajo_de": None,
                        "encima_de": sig["texto"].strip(), "insertar": True}
            ant = max(menores, key=lambda d: (d["num"], d["fila"]))
            base = ant["texto"].strip()
            etiqueta = _siguiente_etiqueta(base, num)
            return {"fila": ant["fila"] + 1, "num": num, "suf": ant["suf"], "texto": etiqueta, "fecha": None,
                    "unidad": ant.get("unidad"), "nueva_etiqueta": etiqueta, "debajo_de": base, "insertar": True}
    if not _fila_usable(tabla, datos, r):      # (una fila más allá de la cuadrícula está vacía: Google no devuelve las del final)
        return None
    return {"fila": r, "num": num, "suf": suf, "texto": etiqueta, "fecha": None,
            "unidad": u, "nueva_etiqueta": etiqueta, "debajo_de": base}


# =============================================================================
# 3a. Cámaras nuevas: crear su columna (y su fila en el Resumen) como las demás
# =============================================================================
_ETIQUETA_CAM = re.compile(r"^\s*CAM\s+([A-Z]{1,3})\s*$", re.I)


def _insertar_col(grid, pos):
    for f in grid:
        if len(f) > pos:
            f.insert(pos, "")


def _desplazar(estructura, hoja, eje, idx):
    """Tras insertar una fila/columna en `idx`, mueve las celdas ya anotadas en la estructura que quedaban en o después de ella."""
    k = 1 if eje == "fila" else 2
    for lista in ("celdas", "copias"):
        nuevas = []
        for it in estructura[lista]:
            it = list(it)
            if it[0] == hoja:
                if it[k] >= idx:
                    it[k] += 1
                if lista == "copias" and it[k + 2] >= idx:
                    it[k + 2] += 1
            nuevas.append(tuple(it))
        estructura[lista] = nuevas
    for a in estructura.get("inicio_resumen", []):
        if hoja == "resumen" and eje == "fila" and a["fila"] >= idx:
            a["fila"] += 1
    for a in estructura["ampliar"]:
        if a["hoja"] == hoja and eje == "col":
            for clave in ("col_total", "nueva"):
                if a[clave] >= idx:
                    a[clave] += 1
            a["cams"] = [c + 1 if c >= idx else c for c in a["cams"]]
        if a["hoja"] == hoja and eje == "fila":
            a["filas"] = [r + 1 if r >= idx else r for r in a["filas"]]


def _nuevas_camaras(datos, resumen, letras, nombre_datos):
    """Las cámaras del reporte que NO tienen columna en «Datos Generales» (HDT: llega la M y solo hay A, B, C, X, Y).
    En una copia de las hojas: inserta «CAM M (GB)» y «CAM M (clips)» en su lugar (orden alfabético, con el formato de las de al lado),
    pone 0 en los días, copia la fórmula de la fila TOTAL, y en el «Resumen General» agrega la fila «CAM M» (dentro de la suma del
    «Espacio utilizado OCF») apuntando al total de su columna. Si la columna queda al final del grupo, anota que hay que ampliar la
    suma de «TOTAL (GB)» de cada día. Devuelve (datos, resumen, estructura) con todo en las posiciones finales."""
    datos = [list(f) for f in datos]
    resumen = [list(f) for f in resumen] if resumen is not None else None
    est = {"ops": [], "celdas": [], "copias": [], "ampliar": [], "creadas": [], "inicio_resumen": []}
    for L in sorted(letras):
        for grupo, sufijo in (("gb", "GB"), ("clips", "clips")):
            tabla = encontrar_tabla(datos)
            cols = tabla[grupo]
            if not cols or L in cols:
                continue
            despues = [c for l, c in cols.items() if l > L]
            al_final = not despues
            pos = (max(cols.values()) + 1) if al_final else min(despues)
            heredar_antes = (pos - 1) in cols.values()
            vecino = max(cols.values()) if al_final else min(despues)            # (antes de insertar)
            enc = tabla["fila_enc"]
            titulo_vecino = str(cel(datos, enc, vecino))
            titulo = re.sub(r"(CAM\s+)([A-Z]{1,3})", lambda m: m.group(1) + L, titulo_vecino, count=1, flags=re.I) \
                if re.search(r"CAM\s+[A-Z]{1,3}", titulo_vecino, re.I) else f"CAM {L} ({sufijo})"
            filas_dia = [d["fila"] for d in tabla["dias"]]
            r_tot = next((r for r in range(enc + 1, len(datos)) if _n(cel(datos, r, 0)).startswith("total")), None)
            col_total = tabla["total"]
            _insertar_col(datos, pos)
            _desplazar(est, "datos", "col", pos)
            est["ops"].append(("col", "datos", pos, heredar_antes))
            vec_post = vecino + (1 if vecino >= pos else 0)
            while len(datos[enc]) <= pos:
                datos[enc].append("")
            datos[enc][pos] = titulo
            est["celdas"].append(("datos", enc, pos, titulo))
            for r in filas_dia:
                if es_numero(cel(datos, r, vec_post)):
                    while len(datos[r]) <= pos:
                        datos[r].append("")
                    datos[r][pos] = 0
                    est["celdas"].append(("datos", r, pos, 0))
            if r_tot is not None and str(cel(datos, r_tot, vec_post)).strip() != "":
                est["copias"].append(("datos", r_tot, vec_post, r_tot, pos))     # la fórmula de la fila TOTAL (=SUM(H4:H34) → su columna)
                while len(datos[r_tot]) <= pos:
                    datos[r_tot].append("")
                datos[r_tot][pos] = datos[r_tot][vec_post]          # (para que la siguiente cámara nueva también la copie de esta)
            if grupo == "gb" and col_total is not None:
                # «TOTAL (GB)» de cada día debe sumar también esta cámara: si su fórmula no la incluye sola (la columna quedó al
                # final del rango, o la hoja suma celda por celda como Microhistorias: =SUM(E4,F4,G4,M4)), se le agrega
                est["ampliar"].append({"hoja": "datos", "col_total": col_total + (1 if col_total >= pos else 0),
                                       "nueva": pos, "cams": [c + (1 if c >= pos else 0) for c in cols.values()],
                                       "filas": list(filas_dia)})
            est["creadas"].append(titulo)
            if grupo == "gb" and resumen is not None:
                _fila_resumen(resumen, est, L, titulo)
    return datos, resumen, est


def _fila_resumen(resumen, est, L, titulo_col):
    """En el «Resumen General», la fila «CAM L» entre las de las demás cámaras (copia la de al lado y apunta al total de su columna)."""
    filas_cam = []
    for r, fila in enumerate(resumen[:80]):
        for c, v in enumerate(fila):
            m = _ETIQUETA_CAM.match(str(v)) if isinstance(v, str) else None
            if m:
                filas_cam.append((r, c, m.group(1).upper()))
                break
    if not filas_cam or any(l == L for _r, _c, l in filas_cam):
        return
    despues = [(r, c) for r, c, l in filas_cam if l > L]
    if despues:
        ins, c_et = min(despues)
        modelo = ins                                   # (antes de insertar) la fila de la cámara siguiente
    else:
        ultima = max(filas_cam)
        ins, c_et, modelo = ultima[0] + 1, ultima[1], ultima[0]
    col_valor = next((c for c in range(c_et + 1, c_et + 6) if str(cel(resumen, modelo, c)).strip() != ""), c_et + 2)
    nueva = list(resumen[modelo])
    primera = ins == min(r for r, _c, _l in filas_cam)
    resumen.insert(ins, nueva)
    _desplazar(est, "resumen", "fila", ins)
    est["ops"].append(("fila", "resumen", ins, bool(not despues)))
    if primera:
        # va ENCIMA de la primera cámara: Google corre la suma «Espacio utilizado OCF» (=SUM(F17:F20) → F18:F21) en vez de
        # agrandarla, así que se anota que hay que empezarla en esta fila nueva
        est["inicio_resumen"].append({"fila": ins, "col": col_valor})
    src = modelo + (1 if modelo >= ins else 0)
    est["copias"].append(("resumen", src, None, ins, None))                 # toda la fila: formato, «GB»…
    nueva[c_et] = f"CAM {L}"
    est["celdas"].append(("resumen", ins, c_et, f"CAM {L}"))
    ref = "=SUM({DATOS}!{TOT:" + titulo_col + "})"   # {DATOS}: el nombre real al escribir; {TOT:…}: la celda TOTAL de esa columna (o sus días)
    nueva[col_valor] = 0
    est["celdas"].append(("resumen", ins, col_valor, ref))
    est["creadas"].append(f"Resumen: CAM {L}")


def _resolver_totales(estructura, datos, tabla):
    """«{TOT:CAM M (GB)}» → la celda de la fila TOTAL en la columna con ese título, ya con la hoja en su forma final."""
    enc = tabla["fila_enc"]
    r_tot = next((r for r in range(enc + 1, len(datos)) if _n(cel(datos, r, 0)).startswith("total")), None)
    titulos = {str(v).strip(): c for c, v in enumerate(datos[enc])}

    filas_d = [d["fila"] for d in tabla["dias"]]

    def poner(m):
        c = titulos.get(m.group(1).strip())
        if c is None:
            return "A1"
        if r_tot is not None:
            return f"{letra_de_columna(c)}{r_tot + 1}"
        L = letra_de_columna(c)                       # sin fila TOTAL: la suma de la columna en los días
        return f"{L}{min(filas_d) + 1}:{L}{max(filas_d) + 1}" if filas_d else f"{L}{enc + 2}"
    estructura["celdas"] = [(h, r, c, re.sub(r"\{TOT:([^}]*)\}", poner, v) if isinstance(v, str) else v)
                            for h, r, c, v in estructura["celdas"]]


def _hoja_en_formula(nombre):
    return "'" + str(nombre).replace("'", "''") + "'"


def _antes_de(estructura, hoja, fila, col):
    """Dónde estaba ANTES de los cambios de estructura la celda (fila, col) de después. None si es una celda nueva."""
    for tipo, h, idx, _her in reversed(estructura["ops"]):
        if h != hoja:
            continue
        if tipo == "fila":
            if fila == idx:
                return None
            if fila > idx:
                fila -= 1
        else:
            if col == idx:
                return None
            if col > idx:
                col -= 1
    return fila, col


def proponer(datos, resumen, filas, reporte, es_sonido, dedicado=False, nombre_datos="Datos Generales"):
    """(ver _proponer). El orden de fechas de esta hoja se usa solo mientras se prepara: después queda el que había en el hilo."""
    previo = ORDEN_FECHA["texto"]
    try:
        return _proponer(datos, resumen, filas, reporte, es_sonido, dedicado, nombre_datos)
    finally:
        ORDEN_FECHA["texto"] = previo


def _proponer(datos, resumen, filas, reporte, es_sonido, dedicado=False, nombre_datos="Datos Generales"):
    """`datos` y `resumen`: celdas de las dos pestañas (resumen puede ser None).
    Devuelve {'dia', 'fecha', 'fila', 'texto_dia', 'cambios', 'avisos', 'lectura_total',
              'calc', 'suma_esperada'}."""
    tabla = encontrar_tabla(datos)
    num = numero_de_dia(reporte["dia"])
    if num is None:
        raise ErrorRegistro(f"No entiendo el número del día «{reporte['dia']}» del reporte.")
    dia, repetida = _fila_del_dia(tabla, num, reporte.get("fecha"), datos, reporte.get("unidad", 1), dedicado,
                                  por_fecha=not reporte.get("dia_de_carpeta", False))
    r = dia["fila"]
    cambios, avisos = [], []
    estructura = {"ops": [], "celdas": [], "copias": [], "ampliar": [], "creadas": [], "formulas_de_arriba": [], "inicio_resumen": [],
                  "sumas_total": []}
    # cámaras del reporte sin columna en el estadístico: se crean como las demás (también su fila en el Resumen General)
    calc0 = calcular_dia(filas, es_sonido, set(tabla["gb"]) | set(tabla["clips"]))
    faltan = sorted(l for l in calc0["gb"] if l not in tabla["gb"] and re.fullmatch(r"[A-Z]{1,3}", l))
    if faltan and tabla["gb"] and not all(es_sonido(f) for f in filas):
        datos, resumen, est_c = _nuevas_camaras(datos, resumen, faltan, nombre_datos)
        for k in ("ops", "celdas", "copias", "ampliar", "creadas", "inicio_resumen"):
            estructura[k] += est_c[k]
        tabla = encontrar_tabla(datos)
        avisos.append(f"{'La cámara' if len(faltan) == 1 else 'Las cámaras'} {', '.join(faltan)} no {'tenía' if len(faltan) == 1 else 'tenían'} "
                      "columna en el estadístico: la agrego como las demás (" + ", ".join(est_c["creadas"]) +
                      "), con 0 en los otros días, su total y su suma en el «Resumen General».")
    insertar = None
    if dia.get("insertar"):
        # se va a insertar una fila nueva en «r»: todo se calcula sobre la hoja como quedará (las filas de abajo bajan una)
        ancho = max((len(f) for f in datos), default=0)
        datos = [list(f) for f in datos[:r]] + [[""] * ancho] + [list(f) for f in datos[r:]]
        _desplazar(estructura, "datos", "fila", r)
        arriba_es_dia = r - 1 > tabla["fila_enc"]           # encima de la primera fila de días no se copia el formato de los títulos
        estructura["ops"].append(("fila", "datos", r, arriba_es_dia))
        estructura["formulas_de_arriba"].append(r if arriba_es_dia else -(r + 1))   # negativo: copiar de la fila de ABAJO
        # la fila TOTAL suma los días hasta el último (=SUM(E4:E21)): si el día va justo después del último o antes del primero,
        # Google no agranda esas sumas; se anota para hacerlo (si no, el día nuevo quedaba fuera del total y del Resumen)
        estructura["sumas_total"].append(r)
        tabla = encontrar_tabla(datos)
        insertar = {"hoja": "datos", "fila": r}
    _resolver_totales(estructura, datos, tabla)
    if dia.get("nueva_etiqueta") and not any(d["fila"] == r for d in tabla["dias"]):
        # la fila todavía no tiene etiqueta: se cuenta como día (si no, «Días rodados» quedaba uno corto y la semana no se cerraba)
        tabla["dias"] = sorted(tabla["dias"] + [{"fila": r, "num": num, "suf": dia.get("suf", ""), "texto": dia["nueva_etiqueta"],
                                                 "fecha": None, "unidad": dia.get("unidad")}], key=lambda d: d["fila"])
    calc = calcular_dia(filas, es_sonido, set(tabla["gb"]) | set(tabla["clips"]))
    if repetida:
        avisos.append(f"Hay más de una fila para el día {num} en el estadístico; uso la primera ({dia['texto']}).")

    columnas_clave = list(tabla["gb"].values()) + ([tabla["rollos"]] if tabla["rollos"] is not None else [])
    tenia_datos = any(es_numero(cel(datos, r, c)) and cel(datos, r, c) > 0 for c in columnas_clave)
    if tenia_datos:
        avisos.append(f"La fila «{dia['texto']}» ya tiene datos en el estadístico: si apruebas, se reemplazan por los del PDF.")

    todos = []

    def proponer_celda(col, concepto, nuevo, tipo):
        antes = cel(datos, r, col)
        if tipo == "hora":
            distinto = not (es_numero(antes) and abs(float(antes) - nuevo) < 0.6 / 86400)
        else:
            distinto = not igual(antes, nuevo)
        c_ = _cambio("datos", r, col, concepto, antes, nuevo, tipo)
        todos.append(c_)                                    # todas las celdas del día, aunque ya estén igual (para «escribir de nuevo»)
        if distinto:
            cambios.append(c_)

    if dia.get("nueva_etiqueta"):                                 # la fila del día no estaba escrita: se escribe con el estilo de la hoja
        proponer_celda(tabla["dia"], "Día", dia["nueva_etiqueta"], "texto")
        if tabla.get("unidad") is not None and dia.get("unidad") is not None:
            proponer_celda(tabla["unidad"], "Unidad", dia["unidad"], "num")
        donde = (f"justo debajo de «{dia['debajo_de']}»" if dia.get("debajo_de") else
                 f"justo encima de «{dia['encima_de']}»" if dia.get("encima_de") else "debajo de los títulos (es el primer día)")
        if insertar:
            avisos.append(f"El día {num} no tenía fila en «Datos Generales» y no había una vacía: agrego una fila nueva {donde} "
                          f"(con su mismo formato) y le escribo «{dia['nueva_etiqueta']}».")
        else:
            avisos.append(f"La fila del día {num} no estaba escrita en «Datos Generales»: uso la fila vacía {donde} "
                          f"y le escribo «{dia['nueva_etiqueta']}».")
    ORDEN_FECHA["texto"] = tabla.get("orden_fecha", "dmy")        # el orden de ESTA hoja (cada hilo guarda el suyo)
    proponer_celda(tabla["fecha"], "Fecha", valor_de_fecha(reporte["fecha"], convencion_de_fecha(datos, tabla)), "fecha")
    # reporte de SOLO sonido (PP «Sound_Media»): solo se tocan las columnas de AUDIO; las cámaras de ese día no vienen en él y
    # NO se ponen en 0 (las escribió el reporte del día)
    solo_sonido = bool(filas) and all(es_sonido(f) for f in filas)
    if solo_sonido and tenia_datos:
        avisos[:] = [a for a in avisos if "ya tiene datos" not in a]
        avisos.append(f"Este reporte es solo de sonido: en «{dia['texto']}» escribo únicamente AUDIO (GB) y AUDIO (clips); "
                      "las cámaras de ese día quedan como están.")
    for letra, c in ([] if solo_sonido else tabla["gb"].items()):          # las cámaras que no vinieron quedan en 0
        proponer_celda(c, f"CAM {letra} (GB)", calc["gb"].get(letra, 0.0), "gb")
    for letra, c in ([] if solo_sonido else tabla["clips"].items()):
        proponer_celda(c, f"CAM {letra} (clips)", calc["clips"].get(letra, 0), "num")
    for letra in calc["gb"]:
        if letra not in tabla["gb"]:
            avisos.append(f"La cámara {letra} ({calc['gb'][letra]:,.2f} GB, {calc['clips'].get(letra, 0)} clips) "
                          "NO tiene columna en el estadístico, así que no se escribe y no suma en sus totales. "
                          "Agrega la columna si la necesitas.")
        elif tabla["clips"] and letra not in tabla["clips"]:       # un estadístico sin ninguna columna de clips no lleva clips: no se avisa
            avisos.append(f"La cámara {letra} no tiene columna de clips en el estadístico: se escriben sus GB, pero sus "
                          f"{calc['clips'].get(letra, 0)} clips no. Agrega la columna «CAM {letra} (clips)» si la necesitas.")
    for clave, nombre, nuevo, tipo in (("rollos", "ROLLOS", calc["rollos"], "num"),
                                       ("duracion", "DURACIÓN", calc["seg"] / 86400.0, "hora"),
                                       ("audio_gb", "AUDIO (GB)", calc["audio_gb"], "gb"),
                                       ("audio_clips", "AUDIO (clips)", calc["audio_clips"], "num")):
        if solo_sonido and clave in ("rollos", "duracion"):
            continue
        if tabla[clave] is None:
            avisos.append(f"No encuentro la columna «{nombre}» en el estadístico; no la escribo.")
        else:
            proponer_celda(tabla[clave], nombre, nuevo, tipo)
    if tabla["editorial"] is not None or tabla["executives"] is not None or tabla.get("dailies") is not None:
        avisos.append("Este estadístico tiene las columnas EDITORIAL / EXECUTIVOS / DAILIES: por ahora no las lleno (quedan como están).")

    if resumen is not None:
        extra = _cambios_resumen(tabla, _Vista(datos, cambios), datos, resumen, r, avisos)
        cambios += extra
        todos += extra

    for c_ in cambios + [x for x in todos if x not in cambios]:            # dónde estaba cada celda antes de crear filas/columnas
        a_ = _antes_de(estructura, c_["hoja"], c_["fila"], c_["col"])
        c_["celda_antes"] = a1(*a_) if a_ else None
    return {"dia": reporte["dia"], "fecha": reporte["fecha"], "fila": r, "texto_dia": dia["texto"], "insertar_fila": insertar,
            "estructura": estructura if estructura["ops"] else None,
            "cambios": cambios, "cambios_todos": todos, "avisos": avisos, "calc": calc, "tenia_datos": tenia_datos,
            "vista": vista_previa(datos, resumen, tabla, dia, cambios, calc),
            "lectura_total": a1(r, tabla["total"]) if tabla["total"] is not None else None,
            "suma_esperada": (sum(float(cel(datos, r, c)) for c in tabla["gb"].values() if es_numero(cel(datos, r, c))) if solo_sonido
                              else sum(calc["gb"].get(l, 0.0) for l in tabla["gb"])) + calc["audio_gb"]}


# =============================================================================
# 3b. Vista previa: las filas de la hoja tal como quedarían
# =============================================================================
def _texto_celda(v, tipo):
    if v is None or v == "":
        return ""
    if tipo == "fecha" and es_numero(v):
        return _texto_fecha(v, "{d:02d}/{m:02d}/{y}")          # como la ven tus hojas (Colombia: día/mes/año)
    if tipo == "hora" and es_numero(v):
        s = int(round(float(v) * 86400))
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    if tipo == "gb" and es_numero(v):
        return f"{float(v):,.2f}"
    if es_numero(v):
        return f"{int(v):,}" if float(v).is_integer() else f"{float(v):,.2f}"
    return str(v)


def vista_previa(datos, resumen, tabla, dia, cambios, calc):
    """Lo que se dibuja en la app: {'datos': bloque, 'resumen': bloque o None}.
    Bloque = {'titulos': [...], 'filas': [{'n': fila_en_la_hoja, 'celdas': [(texto, cambiado)], 'dia': bool}]}."""
    nuevo = {h: {(c["fila"], c["col"]): c["nuevo"] for c in cambios if c["hoja"] == h} for h in ("datos", "resumen")}
    tipos = {tabla["fecha"]: "fecha", tabla["duracion"]: "hora"}
    tipos.update({c: "gb" for c in list(tabla["gb"].values()) + [tabla["audio_gb"], tabla["total"]] if c is not None})

    def bloque(grid, hoja, filas, tipos_col, cols):
        out = []
        for r in filas:
            celdas = []
            for c in cols:
                cambiado = (r, c) in nuevo[hoja]
                v = nuevo[hoja][(r, c)] if cambiado else cel(grid, r, c)
                celdas.append((_texto_celda(v, tipos_col.get(c)), cambiado))
            out.append({"n": r + 1, "celdas": celdas, "dia": r == dia["fila"]})
        return out

    enc = tabla["fila_enc"]
    cols = [c for c in range(len(datos[enc])) if str(cel(datos, enc, c)).strip()][:40]
    previas = [d["fila"] for d in tabla["dias"] if d["fila"] < dia["fila"]][-2:]
    siguientes = [d["fila"] for d in tabla["dias"] if d["fila"] > dia["fila"]][:1]
    filas = previas + [dia["fila"]] + siguientes
    vista = {"datos": {"titulos": [str(cel(datos, enc, c)) for c in cols],
                       "filas": bloque(datos, "datos", filas, tipos, cols), "cols": cols}, "resumen": None}
    if tabla["total"] is not None:                    # el TOTAL es una fórmula del Excel: no la adivino
        k = cols.index(tabla["total"]) if tabla["total"] in cols else None
        if k is not None:
            for f in vista["datos"]["filas"]:
                if f["dia"]:
                    f["celdas"][k] = ("fórmula", False)
    r_cambios = sorted({c["fila"] for c in cambios if c["hoja"] == "resumen"})
    if resumen is not None and r_cambios:
        ancho = max(len(resumen[r]) if r < len(resumen) else 0 for r in r_cambios)
        cols_r = [c for c in range(ancho) if any(str(cel(resumen, r, c)).strip() or (r, c) in nuevo["resumen"]
                                                 for r in r_cambios)]
        vista["resumen"] = {"titulos": [], "filas": bloque(resumen, "resumen", r_cambios, {}, cols_r), "cols": cols_r}
    return vista


# =============================================================================
# 4. Resumen General
# =============================================================================
def _buscar(resumen, condicion, limite=60):
    for r, fila in enumerate(resumen[:limite]):
        for c, v in enumerate(fila):
            if v not in ("", None) and condicion(v):
                return r, c
    return None


def dias_con_datos(valor, tabla, filas=None):
    """Cuántos días tienen datos (ROLLOS > 0), todos o solo los de `filas`."""
    c = tabla["rollos"]
    cols = [c] if c is not None else list(tabla["gb"].values()) + ([tabla["audio_gb"]] if tabla["audio_gb"] is not None else [])
    return sum(1 for d in tabla["dias"]                  # sin columna ROLLOS (antes daba 0 y ponía «Días rodados» en 0): cuenta si tiene GB
               if (filas is None or d["fila"] in filas) and any(es_numero(valor(d["fila"], x)) and valor(d["fila"], x) > 0 for x in cols))


def _semana_cerrada(tabla, datos, fila):
    """Si `fila` es el último día de su semana (según los bloques de la columna A)
    devuelve (número_de_semana, filas_hasta_aquí). Si no, None."""
    dias = tabla["dias"]
    pos = next((k for k, d in enumerate(dias) if d["fila"] == fila), None)
    if pos is None:
        return None
    sin_semana = lambda k: str(cel(datos, dias[k]["fila"], 0)).strip() == ""      # noqa: E731
    ini = pos
    while ini > 0 and sin_semana(ini):
        ini -= 1
    etiqueta = str(cel(datos, dias[ini]["fila"], 0))
    m = re.search(r"\d+", etiqueta)
    if "piloto" in _n(etiqueta) or not m:
        return None
    if pos + 1 < len(dias) and sin_semana(pos + 1):
        return None                                      # todavía quedan días en esa semana
    return int(m.group()), {d["fila"] for d in dias[: pos + 1]}


def texto_semana(viejo, semana, tb, promedio):
    """Cambia solo los números del texto «Semana 6: 86.32 TB OCF promedio día: 2.21 TB» (también «Semana 1: 2.72TB OCF promedio día: 680 GB»:
    el promedio se escribe en la misma unidad que ya usa la hoja). `promedio` va en TB."""
    m = re.match(r"^(\s*Semana\s+)\d+(\s*:\s*)[\d.,]+(\s*TB\b.*?:\s*)[\d.,]+(\s*)(TB|GB)\b(.*)$", str(viejo), re.S | re.I)
    if not m:
        return None
    prom = f"{round(promedio * 1000)}" if m.group(5).upper() == "GB" else f"{promedio:.2f}"
    return f"{m.group(1)}{semana}{m.group(2)}{tb:.2f}{m.group(3)}{prom}{m.group(4)}{m.group(5)}{m.group(6)}"


def _cambios_resumen(tabla, valor, datos, resumen, fila_dia, avisos):
    """`valor(fila, col)` = celdas de datos con el día nuevo ya aplicado; `datos` = las originales."""
    cambios = []
    pos = _buscar(resumen, lambda v: _n(v) == "dias rodados")
    if pos:
        r, c = pos
        destino = next((cc for cc in range(c + 1, c + 9) if es_numero(cel(resumen, r, cc))), None)
        if destino is None:
            avisos.append("Encontré «Días rodados» en el Resumen pero no su número; no lo cambio.")
        else:
            nuevo, antes = dias_con_datos(valor, tabla), cel(resumen, r, destino)
            if not igual(antes, nuevo):
                cambios.append(_cambio("resumen", r, destino, "Días rodados", antes, nuevo, "num"))
    cerrada = _semana_cerrada(tabla, datos, fila_dia)
    if cerrada:
        semana, filas_hasta = cerrada
        pos = _buscar(resumen, lambda v: isinstance(v, str) and re.match(r"^\s*Semana\s+\d+\s*:", v))
        if pos:
            columnas = list(tabla["gb"].values()) + ([tabla["audio_gb"]] if tabla["audio_gb"] is not None else [])
            total_gb = sum(v for f in filas_hasta for c in columnas if es_numero(v := valor(f, c)))
            dias = max(1, dias_con_datos(valor, tabla, filas_hasta))
            tb = total_gb / 1000.0
            viejo = cel(resumen, pos[0], pos[1])
            nuevo = texto_semana(viejo, semana, tb, math.floor(tb / dias * 100 + 1e-9) / 100.0)
            if nuevo is None:
                avisos.append("La semana se cerró, pero no entendí el formato del texto del Resumen; no lo cambio.")
            elif nuevo != viejo:
                cambios.append(_cambio("resumen", pos[0], pos[1], "Texto de la semana", viejo, nuevo, "texto"))
    return cambios


# =============================================================================
# 5. Comprobar lo escrito
# =============================================================================
def comprobar(propuesta, leidos, total_leido=None):
    """`leidos`: {(hoja, celda): valor_leido}. Devuelve [(estado, mensaje)]."""
    mal = []
    for ch in propuesta["cambios"]:
        v = leidos.get((ch["hoja"], ch["celda"]))
        if es_numero(v) and es_numero(ch["nuevo"]):
            ok = abs(float(v) - float(ch["nuevo"])) < (1.0 / 86400 if ch["tipo"] == "hora" else 0.006)
        else:
            ok = str(v) == str(ch["nuevo"])
        if not ok:
            mal.append(f"{ch['concepto']} ({ch['celda']}): escribí {ch['nuevo_txt']} y la hoja dice {_bonito(v, ch['tipo'])}")
    n = len(propuesta["cambios"])
    res = [("ok", f"{n} {'celda' if n == 1 else 'celdas'} escritas y comprobadas leyendo de vuelta: todo coincide.") if not mal
           else ("aviso", "Estas celdas no quedaron como esperaba: " + "; ".join(mal))]
    if es_numero(total_leido):
        esperado = propuesta["suma_esperada"]
        if abs(total_leido - esperado) <= 0.05:
            res.append(("ok", f"TOTAL (GB) del día: {total_leido:,.2f} GB (coincide con la suma)."))
        else:
            res.append(("aviso", f"El TOTAL (GB) de ese día muestra {total_leido:,.2f} GB pero la suma de lo escrito es "
                                 f"{esperado:,.2f} GB. Probablemente la fórmula de esa columna no suma todas las cámaras; "
                                 "no la toqué."))
    return res
