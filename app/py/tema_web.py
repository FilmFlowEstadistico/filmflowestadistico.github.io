"""
SISTEMA DE DISEÑO DE FILMFLOW (un solo lugar para colores, medidas y tipografía)
================================================================================
Inspirado en las Human Interface Guidelines de Apple (macOS):
- Colores SEMÁNTICOS con dos paletas separadas (claro y oscuro); el oscuro no es el claro invertido.
- El verde de FilmFlow (#00B85A) es el único color de acento: acciones principales, selección y progreso.
- Tipografía del sistema (en macOS es San Francisco), tamaños de las HIG: 13 para el texto, 11 para notas.
- Medidas (espacio, radios) en una sola escala.

Este archivo no usa tkinter: se puede probar solo (python3 tema.py comprueba el contraste de todas las parejas).
"""
import json
import subprocess
import sys

VERDE_MARCA = "#00B85A"

# ---------------------------------------------------------------------------------------------------
# Paletas semánticas. Cada clave se usa por lo que significa, no por su color.
# ---------------------------------------------------------------------------------------------------
OSCURO = {
    "fondo": "#171918",            # fondo de la ventana
    "lateral": "#1C1F1D",          # barra lateral
    "superficie": "#242725",       # tarjetas y paneles elevados
    "campo": "#1B1D1C",            # campos de texto
    "boton": "#303432",            # botón secundario
    "boton_hover": "#3A3F3C",
    "boton_pulsado": "#262A28",
    "separador": "#383C3A",
    "borde_campo": "#454A47",
    "texto": "#F2F4F3",
    "texto2": "#A9B1AC",           # secundario
    "texto_off": "#707975",        # deshabilitado
    "acento": VERDE_MARCA,
    "acento_hover": "#1FCB72",
    "acento_pulsado": "#009B4B",
    "acento_ui": VERDE_MARCA,      # verde de controles (casilla, progreso, foco)
    "acento_texto": "#2BD97A",     # verde cuando es texto sobre fondo oscuro
    "sobre_acento": "#06140B",     # texto encima del verde (contraste alto)
    "seleccion": "#1F4A33",        # fila/elemento seleccionado (verde suave)
    "exito": "#2BD97A",
    "aviso": "#F0B03A",
    "error": "#FF7B72",
    "info": "#A9B1AC",
    "aviso_fondo": "#3A311B",
    "error_fondo": "#3E2423",
    "exito_fondo": "#173A28",
}
CLARO = {
    "fondo": "#F5F5F7",
    "lateral": "#E9E9EC",
    "superficie": "#FFFFFF",
    "campo": "#FFFFFF",
    "boton": "#FFFFFF",
    "boton_hover": "#F0F0F3",
    "boton_pulsado": "#E3E3E8",
    "separador": "#E0E0E5",
    "borde_campo": "#C9C9CF",
    "texto": "#1D1D1F",
    "texto2": "#5F5F65",
    "texto_off": "#A1A1A8",
    "acento": VERDE_MARCA,
    "acento_hover": "#00A651",
    "acento_pulsado": "#008F46",
    "acento_ui": "#009A4E",         # el verde de marca es muy claro sobre blanco para un control: este cumple 3:1
    "acento_texto": "#066F3C",     # verde profundo para texto sobre fondo claro (cumple contraste)
    "sobre_acento": "#04130A",
    "seleccion": "#D5F1E1",
    "exito": "#087A42",
    "aviso": "#8F5600",
    "error": "#C4001A",
    "info": "#5F5F65",
    "aviso_fondo": "#FFF3D6",
    "error_fondo": "#FDE4E4",
    "exito_fondo": "#DDF3E6",
}
PALETAS = {"oscuro": OSCURO, "claro": CLARO}

# La hoja de Google siempre es blanca: la vista previa imita la hoja, no el tema de la app.
HOJA = {"encabezado": "#70AD47", "rental": "#B7B7B7", "sin_color": "#DDDDDD", "texto": "#000000",
        "tenue": "#888888", "cambio_fondo": "#C6EFCE", "cambio_texto": "#006100", "cambio_hoja_fondo": "#FFE08A", "cambio_hoja_texto": "#5C4400", "num_fila": "#E8E8E8",
        "num_fila_texto": "#666666",
        "mal_fondo": "#FFC7CE", "mal_texto": "#9C0006"}

# Colores que se ofrecen para pintar los rollos (los mismos del sistema de Apple, para que se vean familiares)
PALETA_ROLLOS = ["#E24A38", "#F28C28", "#FFD60A", "#34C759", "#70A6DD",
                 "#5E5CE6", "#BF5AF2", "#FF6FB5", "#A2845E", "#CCCCCC"]

# ---------------------------------------------------------------------------------------------------
# Medidas (todo se saca de aquí)
# ---------------------------------------------------------------------------------------------------
ESPACIO = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
RADIO = {"boton": 17, "campo": 13, "tarjeta": 22, "chip": 12, "item": 14}
TAM = {"nota": 11, "cuerpo": 13, "subtitulo": 15, "titulo": 22, "pie": 10}
ALTO_BOTON, ALTO_BOTON_MINI = 34, 26
ANCHO_LATERAL = 262
ANCHO_CONTENIDO = 960
ANIMACION_MS = 120


def mezclar(a, b, t):
    """Color entre `a` y `b` (t=0 → a, t=1 → b)."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminancia(h):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Parejas (texto, fondo, mínimo) que se comprueban. Texto normal: 4.5. Elementos grandes o de interfaz: 3.
PAREJAS = [
    ("texto", "fondo", 4.5), ("texto", "superficie", 4.5), ("texto", "lateral", 4.5),
    ("texto2", "fondo", 4.5), ("texto2", "superficie", 4.5), ("texto2", "lateral", 4.5),
    ("acento_texto", "fondo", 4.5), ("acento_texto", "superficie", 4.5), ("acento_texto", "lateral", 4.5),
    ("sobre_acento", "acento", 4.5), ("sobre_acento", "acento_hover", 4.5), ("sobre_acento", "acento_pulsado", 3.0),
    ("texto", "seleccion", 4.5), ("texto", "boton", 4.5), ("texto", "boton_hover", 4.5),
    ("exito", "superficie", 4.5), ("aviso", "superficie", 4.5), ("error", "superficie", 4.5),
    ("aviso", "fondo", 4.5), ("error", "fondo", 4.5),
    ("texto", "aviso_fondo", 4.5), ("texto", "error_fondo", 4.5), ("texto", "exito_fondo", 4.5),
    ("acento_ui", "superficie", 3.0), ("acento_ui", "fondo", 3.0), ("acento_ui", "lateral", 3.0),
    ("borde_campo", "superficie", 1.5),
]


def comprobar_contraste():
    """Lista de (modo, texto, fondo, razón, mínimo) que NO cumplen. Vacía = todo bien."""
    fallos = []
    for modo, p in PALETAS.items():
        for t, f, minimo in PAREJAS:
            r = contraste(p[t], p[f])
            if r < minimo:
                fallos.append((modo, t, f, round(r, 2), minimo))
    return fallos


# ---------------------------------------------------------------------------------------------------
# Apariencia del sistema y preferencia de la persona
# ---------------------------------------------------------------------------------------------------
def apariencia_del_sistema():
    """«claro» u «oscuro» según el Mac (Ajustes del Sistema > Apariencia). En otros sistemas, «oscuro»."""
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2)
            return "oscuro" if r.returncode == 0 and "dark" in r.stdout.lower() else "claro"
        except Exception:
            return "claro"
    return "oscuro"


def leer_preferencia(carpeta):
    """«sistema», «claro» u «oscuro» (por defecto, «sistema»)."""
    try:
        valor = json.loads((carpeta / "preferencias.json").read_text(encoding="utf-8")).get("apariencia", "sistema")
        return valor if valor in ("sistema", "claro", "oscuro") else "sistema"
    except Exception:
        return "sistema"


def _guardar_preferencias(carpeta, cambios):
    """Cambia solo esas claves de preferencias.json y lo guarda de forma segura (archivo temporal + reemplazo, para que nunca quede a medias)."""
    import os
    try:
        ruta = carpeta / "preferencias.json"
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            if not isinstance(datos, dict):
                datos = {}
        except Exception:
            datos = {}
        datos.update(cambios)
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, ruta)
    except Exception:
        pass


def guardar_preferencia(carpeta, valor):
    _guardar_preferencias(carpeta, {"apariencia": valor})


MINUTOS_DESCANSO = (0, 5, 15, 30, 60)          # 0 = nunca
DESCANSO_POR_DEFECTO = 15


def leer_descanso(carpeta):
    """Minutos sin usar la app antes de que se ponga en descanso (0 = nunca)."""
    try:
        valor = int(json.loads((carpeta / "preferencias.json").read_text(encoding="utf-8")).get("descanso_min", DESCANSO_POR_DEFECTO))
        return valor if valor in MINUTOS_DESCANSO else DESCANSO_POR_DEFECTO
    except Exception:
        return DESCANSO_POR_DEFECTO


def guardar_descanso(carpeta, minutos):
    _guardar_preferencias(carpeta, {"descanso_min": int(minutos)})


SEGUNDOS_FOTO = (10, 30, 60, 300)
FOTOS_POR_DEFECTO = {"fotos": [], "seg": 30, "azar": False}


def leer_fotos(carpeta):
    """Las fotos de la pantalla de descanso: {'fotos': [nombres de archivo en carpeta/fotos_descanso], 'seg': cada cuánto cambia, 'azar': bool}."""
    try:
        d = json.loads((carpeta / "preferencias.json").read_text(encoding="utf-8")).get("fotos_descanso") or {}
        seg = int(d.get("seg", 30))
        fotos = [str(n) for n in d.get("fotos", []) if (carpeta / "fotos_descanso" / str(n)).is_file()]
        return {"fotos": fotos, "seg": seg if seg in SEGUNDOS_FOTO else 30, "azar": bool(d.get("azar", False))}
    except Exception:
        return dict(FOTOS_POR_DEFECTO, fotos=[])


def guardar_fotos(carpeta, datos):
    _guardar_preferencias(carpeta, {"fotos_descanso": {"fotos": list(datos["fotos"]), "seg": int(datos["seg"]), "azar": bool(datos["azar"])}})


def modo_efectivo(preferencia):
    return apariencia_del_sistema() if preferencia == "sistema" else preferencia


if __name__ == "__main__":
    malos = comprobar_contraste()
    for m in malos:
        print("NO CUMPLE:", m)
    print("Contraste: todo bien." if not malos else f"{len(malos)} pareja(s) por corregir.")


def fondo_de_foto(ruta, w, h):
    """La foto lista para la pantalla de descanso (imagen de Pillow, RGB w×h): recortada para llenar, con las orillas algo
    oscuras (viñeta) y, detrás del logo y la hora, una zona difuminada y oscura para que todo se lea y se integre con la foto."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    w, h = max(int(w), 2), max(int(h), 2)
    foto = ImageOps.fit(ImageOps.exif_transpose(Image.open(ruta)).convert("RGB"), (w, h), Image.LANCZOS)
    base = ImageEnhance.Brightness(foto).enhance(0.78)
    # viñeta: las orillas bajan un poco más
    vig = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vig).ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(max(w, h) * 0.12))
    base = Image.composite(base, ImageEnhance.Brightness(base).enhance(0.62), vig)
    # zona central difuminada y oscura (detrás del logo, la hora y el texto)
    suave = ImageEnhance.Brightness(foto.filter(ImageFilter.GaussianBlur(max(w, h) * 0.018))).enhance(0.38)
    masc = Image.new("L", (w, h), 0)
    ancho, alto = min(w * 0.46, 760), min(h * 0.80, 700)
    ImageDraw.Draw(masc).rounded_rectangle((w / 2 - ancho / 2, h / 2 - alto / 2, w / 2 + ancho / 2, h / 2 + alto / 2),
                                           radius=min(ancho, alto) * 0.22, fill=235)
    masc = masc.filter(ImageFilter.GaussianBlur(min(ancho, alto) * 0.16))
    return Image.composite(suave, base, masc)
