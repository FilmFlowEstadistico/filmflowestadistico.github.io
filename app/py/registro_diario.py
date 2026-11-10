#!/usr/bin/env python3
"""
REGISTRO DIARIO DE DESCARGAS
============================
Lee el "Shooting Day Report" (PDF) de Silverstack XT y agrega el bloque de ese
día a una copia de tu registro (Excel), con el mismo formato de los días
anteriores y la fila verde de totales.

Uso (desde una terminal, en la carpeta donde están los archivos):

    python registro_diario.py  reporte.pdf  registro.xlsx

Resultado: un archivo nuevo  registro_actualizado.xlsx  con el día agregado
al final. Tu archivo original NO se modifica.

Requiere:  pip install pdfplumber openpyxl
"""
import argparse
import copy
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
import pdfplumber

# =============================================================================
# CONFIGURACIÓN: lo único que quizá necesites cambiar algún día
# =============================================================================
META = {
    "A": ("CONGO", "ARRI ALEXA 35"),
    "B": ("CONGO", "ARRI ALEXA 35"),
    "C": ("CONGO", "ARRI ALEXA 35"),
    "DRON": ("EAGLE FILMS", "DJI INSPIRE 3"),
    "PROPS": ("PROPS", "IPHONE 17 PRO MAX"),
    "SONIDO": ("JAIME CUJABAN", "SOUND DEVICE SCORPIO"),
}
# Cuántas tarjetas (# Mag) rotan en cada grupo antes de volver a 1.
# Los celulares (PROPS) siempre llevan # Mag = 1 (ver MAG_FIJO).
CICLO_MAG = {"A": 6, "B": 6, "C": 4, "DRON": 5, "SONIDO": 5}
MAG_FIJO = {"PROPS": 1}
# Orden de las filas dentro de cada día (el sonido siempre al final).
ORDEN = ["A", "B", "C", "DRON", "PROPS", "SONIDO"]
# =============================================================================

COL_DIA, COL_FECHA, COL_RENTAL, COL_CAM, COL_MODELO = 1, 2, 3, 4, 5
COL_MAG, COL_CLIPS, COL_DUR, COL_GB, COL_SEMANA = 6, 7, 8, 9, 10
PRIMERA_FILA_DATOS = 7

FOLDER_RE = re.compile(r"(\d{8})_DAY(\d{3})")
FILA_BIN = re.compile(
    r"^\s*(\S+)\s+(?:([A-Z]_)\s+)?(\d+)\s+(\d+(?::\d+){0,2})\s*(h|min|sec)"
    r"\s+(\d+)\s+([\d.,]+)\s*(KB|MB|GB|TB)\s*$",
    re.M,
)
GB_POR_UNIDAD = {"KB": 1e-6, "MB": 1e-3, "GB": 1.0, "TB": 1000.0}

# Silverstack incrusta una fuente cuyos números salen como caracteres raros
# al leer el PDF con algunas herramientas. Esta tabla los traduce.
PUA = {chr(0xE071 + d): str(d) for d in range(10)}
PUA.update({"\ue094": ".", "\ue092": ":", "\uee47": ":", "\uee48": "(", "\uee49": ")"})


# -----------------------------------------------------------------------------
# 1. LEER EL PDF
# -----------------------------------------------------------------------------
def texto_del_pdf(ruta):
    """Devuelve el texto del PDF. Primero intenta con pdftotext; si no está
    instalado, usa pdfplumber (que viene con el pip install de arriba)."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(ruta), "-"],
            capture_output=True, text=True, check=True,
        ).stdout
        if FILA_BIN.search(out):
            return out
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    with pdfplumber.open(ruta) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    return texto.translate(str.maketrans(PUA))


def a_segundos(txt, unidad):
    p = [int(x) for x in txt.split(":")]
    if unidad == "sec":
        return p[0]
    if unidad == "min":                      # mm:ss
        return p[0] * 60 + (p[1] if len(p) > 1 else 0)
    p += [0] * (3 - len(p))                  # h:mm:ss
    return p[0] * 3600 + p[1] * 60 + p[2]


def leer_reporte(ruta):
    texto = texto_del_pdf(ruta)

    m = FOLDER_RE.search(texto) or FOLDER_RE.search(Path(ruta).name)
    if not m:
        sys.exit("No encontré el día de rodaje (algo como 20260930_DAY036) en el PDF.")
    fecha = datetime.strptime(m.group(1), "%Y%m%d")
    dia = f"D{int(m.group(2)):03d}"

    # Solo la tabla "Bins": el reporte repite los mismos datos más abajo
    # (Video Reels, Audio Tapes) y no queremos contarlos dos veces.
    ini = re.search(r"Bin\s*Name\s+Camera", texto)
    if not ini:
        sys.exit("No encontré la tabla 'Bins' en el PDF. ¿Cambió el formato del reporte?")
    resto = texto[ini.end():]
    fin = re.search(r"Video\s+Reels|Camera\s+Sums|Audio\s+Tapes", resto)
    seccion = resto[: fin.start()] if fin else resto

    bins = []
    for nombre, _cam, clips, dur, unidad, _files, tam, u_tam in FILA_BIN.findall(seccion):
        bins.append({
            "nombre": nombre,
            "clips": int(clips),
            "seg": a_segundos(dur, unidad),
            "gb": round(float(tam.replace(",", "")) * GB_POR_UNIDAD[u_tam], 2),
        })
    if not bins:
        sys.exit("No encontré filas en la tabla 'Bins'. ¿Cambió el formato del reporte?")
    return {"dia": dia, "fecha": fecha, "bins": bins}


# -----------------------------------------------------------------------------
# 2. CLASIFICAR Y LEER EL HISTORIAL DE TU REGISTRO
# -----------------------------------------------------------------------------
def grupo_de(nombre):
    n = str(nombre).strip()
    if re.match(r"^[ABC]_\d{4}_", n):
        return n[0]                          # cámaras A, B, C
    if re.match(r"^D\d{3}_", n):
        return "DRON"                        # Eagle Films
    if re.match(r"^[IJ]\d{3}", n):
        return "PROPS"                       # celulares
    if re.match(r"^\d{2}Y\d{2}M\d+", n):
        return "SONIDO"                      # Jaime Cujaban
    return None


def leer_historial(ws, hasta=None):
    """Recorre tu registro para saber: qué días ya existen, cuál fue el último
    # Mag de cada grupo, dónde quedó la última fila de totales y qué filas
    usar como molde de formato."""
    h = {"dias": set(), "ultimo_mag": {}, "ultima_fila": {}, "totales": []}
    for r in range(PRIMERA_FILA_DATOS, (hasta or ws.max_row) + 1):
        a = ws.cell(r, COL_DIA).value
        if isinstance(a, str) and re.match(r"^D\d{3}$", a.strip()):
            h["dias"].add(a.strip())
        g = ws.cell(r, COL_CLIPS).value
        if isinstance(g, str) and g.startswith("=SUM("):
            h["totales"].append(r)
        nombre = ws.cell(r, COL_CAM).value
        grupo = grupo_de(nombre) if nombre else None
        if grupo:
            h["ultima_fila"][grupo] = r
            mag = ws.cell(r, COL_MAG).value
            if isinstance(mag, (int, float)):
                h["ultimo_mag"][grupo] = int(mag)
    if len(h["totales"]) < 2:
        sys.exit("No encontré al menos dos días con fila de totales en tu registro.")
    return h


# -----------------------------------------------------------------------------
# 3. ARMAR LAS FILAS DEL DÍA
# -----------------------------------------------------------------------------
def armar_filas(reporte, h):
    por_grupo = {g: [] for g in ORDEN}
    sin_clasificar = []
    for b in reporte["bins"]:
        g = grupo_de(b["nombre"])
        (por_grupo[g] if g else sin_clasificar).append(b)

    mags = dict(h["ultimo_mag"])
    filas, avisos = [], []
    for g in ORDEN:
        for b in sorted(por_grupo[g], key=lambda x: x["nombre"]):
            if g in CICLO_MAG:
                ult = mags.get(g)
                mag = 1 if ult is None else ult % CICLO_MAG[g] + 1
                mags[g] = mag
            else:
                mag = MAG_FIJO.get(g)
            rental, modelo = META[g]
            filas.append({"grupo": g, "rental": rental, "nombre": b["nombre"],
                          "modelo": modelo, "mag": mag, "clips": b["clips"],
                          "seg": b["seg"], "gb": b["gb"]})

    if not por_grupo["SONIDO"]:
        avisos.append("El reporte NO trae sonido (cinta tipo 26Y09M30). El día quedó "
                      "sin la fila de JAIME CUJABAN y los totales no lo incluyen.")
    if not any(por_grupo[g] for g in "ABC"):
        avisos.append("El reporte no trae ninguna cámara A, B o C.")
    for b in sin_clasificar:
        avisos.append(f"No supe clasificar '{b['nombre']}': no lo agregué. Revísalo.")
    return filas, avisos


# -----------------------------------------------------------------------------
# 4. ESCRIBIR EL BLOQUE EN EL EXCEL (con el formato de tus días anteriores)
# -----------------------------------------------------------------------------
def copiar_estilo(origen, destino):
    destino._style = copy.copy(origen._style)


def escribir_bloque(ws, reporte, filas, h):
    ult_total = h["totales"][-1]
    primera_prev = h["totales"][-2] + 1
    molde_base = h["ultima_fila"].get("SONIDO", ult_total - 1)

    inicio = ult_total + 1
    final = inicio + len(filas) - 1
    total = final + 1

    for i, f in enumerate(filas):
        r = inicio + i
        molde_ab = primera_prev if i == 0 else molde_base
        molde_def = h["ultima_fila"].get(f["grupo"], molde_base)   # color por cámara
        for col in range(1, 11):
            if col in (COL_DIA, COL_FECHA):
                origen = molde_ab
            elif col in (COL_CAM, COL_MODELO, COL_MAG):
                origen = molde_def
            else:
                origen = molde_base
            copiar_estilo(ws.cell(origen, col), ws.cell(r, col))
        ws.row_dimensions[r].height = ws.row_dimensions[molde_base].height

        if i == 0:
            ws.cell(r, COL_DIA, reporte["dia"])
            ws.cell(r, COL_FECHA, reporte["fecha"])
        ws.cell(r, COL_RENTAL, f["rental"])
        ws.cell(r, COL_CAM, f["nombre"])
        ws.cell(r, COL_MODELO, f["modelo"])
        if f["mag"] is not None:
            ws.cell(r, COL_MAG, f["mag"])
        ws.cell(r, COL_CLIPS, f["clips"])
        ws.cell(r, COL_DUR, timedelta(seconds=f["seg"]))
        ws.cell(r, COL_GB, f["gb"])

    if len(filas) > 1:
        ws.merge_cells(start_row=inicio, end_row=final, start_column=COL_DIA, end_column=COL_DIA)
        ws.merge_cells(start_row=inicio, end_row=final, start_column=COL_FECHA, end_column=COL_FECHA)

    for col in range(1, 11):
        copiar_estilo(ws.cell(ult_total, col), ws.cell(total, col))
    ws.row_dimensions[total].height = ws.row_dimensions[ult_total].height
    for col in (COL_CLIPS, COL_DUR, COL_GB):
        letra = openpyxl.utils.get_column_letter(col)
        ws.cell(total, col, f"=SUM({letra}{inicio}:{letra}{final})")
    ws.merge_cells(start_row=total, end_row=total, start_column=COL_FECHA, end_column=COL_MODELO + 1)
    return inicio, final, total


# -----------------------------------------------------------------------------
# 5. PROGRAMA PRINCIPAL
# -----------------------------------------------------------------------------
def hms(seg):
    return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description="Agrega el día del reporte de Silverstack a tu registro.")
    ap.add_argument("pdf", help="reporte de Silverstack (PDF)")
    ap.add_argument("xlsx", help="tu registro descargado de Google Sheets (.xlsx)")
    ap.add_argument("--salida", help="nombre del archivo nuevo (opcional)")
    args = ap.parse_args()

    reporte = leer_reporte(args.pdf)
    wb = openpyxl.load_workbook(args.xlsx)
    ws = wb.active
    h = leer_historial(ws)

    if reporte["dia"] in h["dias"]:
        sys.exit(f"{reporte['dia']} ya está en tu registro. No agregué nada para no duplicarlo.")

    filas, avisos = armar_filas(reporte, h)
    inicio, final, total = escribir_bloque(ws, reporte, filas, h)

    nombre = Path(args.xlsx).stem + "_actualizado.xlsx"
    salida = Path(args.salida) if args.salida else Path(args.xlsx).with_name(nombre)
    try:
        wb.save(salida)
    except OSError:
        salida = Path.cwd() / salida.name
        wb.save(salida)

    print(f"\n{reporte['dia']}  ·  {reporte['fecha']:%d/%m/%Y}\n")
    print(f"{'Fila':<5}{'RENTAL':<15}{'CAM':<18}{'MAG':<5}{'CLIPS':<7}{'DURACIÓN':<10}{'GB':>8}")
    for i, f in enumerate(filas):
        print(f"{inicio + i:<5}{f['rental']:<15}{f['nombre']:<18}{str(f['mag'] or ''):<5}"
              f"{f['clips']:<7}{hms(f['seg']):<10}{f['gb']:>8.2f}")
    print(f"{total:<5}{'TOTAL':<38}{sum(f['clips'] for f in filas):<7}"
          f"{hms(sum(f['seg'] for f in filas)):<10}{sum(f['gb'] for f in filas):>8.2f}")
    for a in avisos:
        print(f"\n⚠  {a}")
    print(f"\nListo. Copia las filas {inicio} a {total} de  {salida}")


if __name__ == "__main__":
    main()
