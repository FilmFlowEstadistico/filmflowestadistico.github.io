"""Piezas de pantalla del teléfono: devuelven HTML. Los textos son los mismos de la app del Mac."""
import html
import json
import math
import re

import tema_web as tema

esc = html.escape


def a(accion, **datos):
    """Atributos de un elemento que al tocarlo llama a la acción de Python."""
    return f'data-a="{esc(accion)}" data-p="{esc(json.dumps(datos, ensure_ascii=False))}"'


def boton(texto, accion, estilo="", **datos):
    return f'<button class="btn {estilo}" {a(accion, **datos)}>{esc(texto)}</button>'


def chip(texto, tipo="info"):
    return f'<span class="chip {tipo}">{esc(texto)}</span>'


ICONOS = {"ok": "✔", "aviso": "⚠", "error": "✕", "info": "ⓘ"}


def aviso(tipo, texto):
    tipo = "ok" if tipo in ("ok", "exito") else tipo if tipo in ("aviso", "error") else "info"
    return f'<div class="estado {tipo}"><span class="ico">{ICONOS[tipo]}</span><span>{esc(texto)}</span></div>'


def tarjeta(cuerpo, titulo="", extra="", clase=""):
    cab = f'<div class="tj-titulo"><h3>{esc(titulo)}</h3>{extra}</div>' if titulo else ""
    return f'<section class="tarjeta {clase}">{cab}{cuerpo}</section>'


def cabecera(titulo, codigo, texto_chip, tipo_chip, subtitulo=""):
    sub = f'<p class="sub">{esc(subtitulo)}</p>' if subtitulo else ""
    return (f'<div class="tj-cab"><h3>{esc(titulo)}</h3><span class="nota">{esc(codigo)}</span>'
            f'<span class="espacio"></span>{chip(texto_chip, tipo_chip)}</div>{sub}')


def casilla(texto, marcada, accion, **datos):
    return (f'<label class="casilla"><input type="checkbox" {"checked" if marcada else ""} {a(accion, **datos)} data-ev="change">'
            f'<span class="caja"></span><span class="txt">{esc(texto)}</span></label>')


def segmentado(opciones, valor, accion, **datos):
    bs = "".join(f'<button class="seg {"on" if v == valor else ""}" {a(accion, valor=v, **datos)}>{esc(t)}</button>' for v, t in opciones)
    return f'<div class="segmentado">{bs}</div>'


def metrica(icono, titulo, valor, sub="", ancha=False):
    return (f'<div class="metrica{" ancha" if ancha else ""}"><div class="m-t">{(icono + " ") if icono else ""}{esc(titulo)}</div>'
            f'<div class="m-v">{esc(valor)}</div><div class="m-s">{esc(sub)}</div></div>')


def grupo(titulo):
    return f'<h2 class="grupo-t">{esc(titulo)}</h2>'


def plegable(clave, titulo, cuerpo, chip_html="", sub="", abierto=False, simple=False):
    """Un bloque que se abre y se cierra (la app recuerda cuáles dejaste abiertos mientras no cambies de pantalla)."""
    s = f'<small>{esc(sub)}</small>' if sub else ""
    return (f'<details class="plegable{" simple" if simple else ""}" data-k="{esc(clave)}"{" open" if abierto else ""}>'
            f'<summary><span class="tit">{esc(titulo)}{s}</span>{chip_html}</summary><div class="cuerpo">{cuerpo}</div></details>')


def fila_camara(nombre, color, rollo, extras, volumen, clave=""):
    """Una cámara en el Resumen, compacta: nombre, rollo actual y volumen en una fila. Al tocarla se ven los demás datos
    (extras: lista de (etiqueta, valor))."""
    r = f'<span class="cam-rollo">{esc(rollo)}</span>' if rollo else '<span class="cam-rollo vacio">Sin rollo todavía</span>'
    kv = "".join(f'<div class="kv-f"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in extras if v not in ("", None))
    return (f'<details class="cam-fila" data-k="cam-{esc(clave or nombre)}"><summary><span class="punto" style="background:{color}"></span>'
            f'<span class="cam-tx"><span class="cam-nom">{esc(nombre)}</span>{r}</span><span class="cam-vol">{esc(volumen)}</span></summary>'
            f'<div class="kv">{kv}</div></details>')


def barras(items):
    """items: (nombre, color, fracción, texto_peso, texto_pct)"""
    filas = []
    for nombre, color, fr, peso, pct in items:
        filas.append(f'<div class="barra"><div class="b-t"><span class="punto" style="background:{color}"></span>'
                     f'<span class="b-n">{esc(nombre)}</span><span class="b-p">{esc(peso)} · {esc(pct)}</span></div>'
                     f'<div class="pista"><div class="relleno" style="width:{max(0.5, min(100, fr * 100)):.1f}%;background:{color}"></div></div></div>')
    return "".join(filas)


def dona(partes, centro, sub):
    total = sum(g for g, _c in partes) or 1
    r, grosor, cx = 70, 26, 90
    ang, trozos = -math.pi / 2, []
    for g, color in partes:
        fr = g / total
        if fr <= 0:
            continue
        if fr > 0.9995:
            trozos.append(f'<circle cx="{cx}" cy="{cx}" r="{r}" fill="none" stroke="{color}" stroke-width="{grosor}"/>')
            continue
        a2 = ang + fr * 2 * math.pi
        x1, y1, x2, y2 = cx + r * math.cos(ang), cx + r * math.sin(ang), cx + r * math.cos(a2), cx + r * math.sin(a2)
        trozos.append(f'<path d="M{x1:.2f},{y1:.2f} A{r},{r} 0 {1 if fr > 0.5 else 0} 1 {x2:.2f},{y2:.2f}" fill="none" '
                      f'stroke="{color}" stroke-width="{grosor}"/>')
        ang = a2
    return (f'<svg viewBox="0 0 180 180" class="dona">{"".join(trozos)}'
            f'<text x="90" y="88" text-anchor="middle" class="d-v">{esc(centro)}</text>'
            f'<text x="90" y="106" text-anchor="middle" class="d-s">{esc(sub)}</text></svg>')


def _eje(gb):
    """Rótulo del eje: en TB, o en GB cuando el proyecto es pequeño (si no, todo saldría «0.0 TB»)."""
    return f"{gb / 1000:.1f} TB" if gb >= 1000 else f"{gb:,.0f} GB"


def columnas(datos, promedio, promedio_txt=""):
    """Volumen por día, igual que en el Mac: eje en TB, barras (la última destacada), línea de promedio rotulada y,
    al tocar o arrastrar el dedo por las barras, el detalle de ese día. datos: (dia, gb, texto_ayuda)"""
    if not datos:
        return ""
    W, Hh, izq, der, arr, aba = 360, 200, 40, 6, 24, 24
    mayor = max([g for _d, g, _t in datos] + [1])
    techo = mayor * 1.08
    base = Hh - aba
    n = len(datos)
    paso = (W - izq - der) / n
    ancho = max(2.0, paso * 0.68)
    out = []
    for fr in (0, 0.5, 1.0):
        y = base - (base - arr) * fr
        out.append(f'<line x1="{izq}" x2="{W - der}" y1="{y:.1f}" y2="{y:.1f}" class="rej"/>')
        out.append(f'<text x="{izq - 5}" y="{y + 4:.1f}" text-anchor="end" class="eje" font-size="11">{(_eje(techo * fr) if fr else "0")}</text>')
    for i, (dia, gb, ayuda) in enumerate(datos):
        x = izq + paso * i + (paso - ancho) / 2
        h = (base - arr) * gb / techo
        if h > 0.5:
            out.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{ancho:.1f}" height="{h:.1f}" rx="{min(ancho / 2, 4):.1f}" '
                       f'class="col{" ult" if i == n - 1 else ""}" data-i="{i}"/>')
    if promedio:
        y = base - (base - arr) * promedio / techo
        out.append(f'<line x1="{izq}" x2="{W - der}" y1="{y:.1f}" y2="{y:.1f}" class="prom"/>')
        out.append(f'<text x="{W - der}" y="{y - 5:.1f}" text-anchor="end" class="prom-t" font-size="11">promedio{(" " + esc(promedio_txt)) if promedio_txt else ""}</text>')
    cada = max(1, n // 8)
    for i in range(0, n, cada):
        out.append(f'<text x="{izq + paso * i + paso / 2:.1f}" y="{base + 15}" text-anchor="middle" class="eje" font-size="11">{esc(str(datos[i][0]).lstrip("D").lstrip("0") or "0")}</text>')
    ayudas = "|".join(esc(a.replace("|", "/")) for _d, _g, a in datos)
    out.append(f'<rect class="hit" x="{izq}" y="0" width="{W - izq - der}" height="{base + 4}" fill="transparent"/>')
    out.append('<g class="tip" pointer-events="none" visibility="hidden"><rect rx="11" height="24"/><text y="16" font-size="12" font-weight="700"></text></g>')
    pie = (f'<p class="sub g-pie"><span class="g-raya"></span> Promedio{(": " + esc(promedio_txt)) if promedio_txt else ""} · toca o desliza el dedo por las barras para ver cada día</p>')
    # data-g: lo mismo en datos para que el navegador la vuelva a dibujar al ancho REAL de la pantalla (si no, en el computador todo se
    # agrandaba: letras gigantes y barras gordas). El SVG de aquí queda de reserva (360 de ancho, el de un teléfono).
    g = {"d": [str(d).lstrip("D").lstrip("0") or "0" for d, _g, _t in datos], "v": [round(float(x or 0), 3) for _d, x, _t in datos],
         "p": round(float(promedio or 0), 3), "pt": promedio_txt or "", "e": [_eje(techo * 0.5), _eje(techo)]}
    return (f'<div class="grafico" data-g="{html.escape(json.dumps(g, ensure_ascii=False), quote=True)}" data-ayudas="{ayudas}"><svg viewBox="0 0 {W} {Hh}" style="width:100%;height:auto;display:block" '
            f'role="img" aria-label="Volumen por día">{"".join(out)}</svg></div>{pie}')


def tabla(columnas_, filas):
    """columnas_: (titulo, alineación); filas: lista de listas de celdas (str o dict con texto/punto/negrita/color)."""
    cab = "".join(f'<th class="{"d" if al == "e" else ""}">{esc(t)}</th>' for t, al in columnas_)
    cuerpo = []
    for f in filas:
        tds = []
        for (t, al), c in zip(columnas_, f):
            if isinstance(c, dict):
                punto = f'<span class="punto" style="background:{c["punto"]}"></span>' if c.get("punto") else ""
                cls = ("neg " if c.get("negrita") else "") + (c.get("color") or "")
                tds.append(f'<td class="{"d" if al == "e" else ""} {cls}">{punto}{esc(c["texto"])}</td>')
            else:
                tds.append(f'<td class="{"d" if al == "e" else ""}">{esc(str(c))}</td>')
        cuerpo.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="desliza"><table class="tabla"><thead><tr>{cab}</tr></thead><tbody>{"".join(cuerpo)}</tbody></table></div>'


def vacia(titulo, texto, boton_html="", tipo="info"):
    ico = {"info": "▤", "error": "✕", "aviso": "⚠", "carga": "↻"}[tipo]
    return (f'<section class="tarjeta vacia"><div class="grande {tipo}">{ico}</div><h3>{esc(titulo)}</h3>'
            f'<p class="sub">{esc(texto)}</p>{boton_html}</section>')


# ---------------- vista de hoja (imita la hoja de Google, siempre blanca) ----------------
H = tema.HOJA


def _tinte(hx, f):
    if not f["dia"] or not re.fullmatch(r"#[0-9A-Fa-f]{6}", hx or ""):
        return hx
    a_ = [int(hx[k:k + 2], 16) for k in (1, 3, 5)]
    b = (0x2F, 0x6F, 0xD6)
    return "#%02X%02X%02X" % tuple(round(x * 0.82 + y * 0.18) for x, y in zip(a_, b))


def cuadricula(bloque, ancho_col=62):
    """Filas de una pestaña tal como quedarían: encabezado verde, número de fila y las celdas nuevas resaltadas."""
    fondos = bloque.get("fondos")
    cols_hoja = bloque.get("cols") or []
    base_col = {}
    if fondos:
        for (_f, c_), hx_ in fondos.items():
            if hx_.upper() != "#FFFFFF":
                base_col.setdefault(c_, {}).setdefault(hx_, 0)
                base_col[c_][hx_] += 1

    def fondo_real(n_fila, k, texto):
        c_ = cols_hoja[k] if k < len(cols_hoja) else None
        propio = fondos.get((n_fila, c_), "#FFFFFF")
        if re.fullmatch(r"-?0([.,]0+)?", texto.strip()):
            return "#FFFFFF"
        if propio.upper() != "#FFFFFF" or not texto.strip():
            return propio
        if base_col.get(c_):
            return max(base_col[c_], key=base_col[c_].get)
        fila_c = [hx_ for (f_, _c), hx_ in fondos.items() if f_ == n_fila and hx_.upper() != "#FFFFFF"]
        return max(set(fila_c), key=fila_c.count) if fila_c else "#FFFFFF"

    def td(texto, bg, fg=H["texto"], neg=False):
        return f'<td style="background:{bg};color:{fg};{"font-weight:700;" if neg else ""}">{esc(texto)}</td>'

    filas = []
    if bloque["titulos"]:
        filas.append("<tr>" + td("", H["encabezado"]) + "".join(
            f'<th style="background:{H["encabezado"]};min-width:{ancho_col}px">{esc(t)}</th>' for t in bloque["titulos"]) + "</tr>")
    for f in bloque["filas"]:
        fila = [td(("▶ " if f["dia"] else "") + str(f["n"]), H["encabezado"] if f["dia"] else H["num_fila"],
                   "#FFFFFF" if f["dia"] else H["num_fila_texto"], f["dia"])]
        for c, (texto, nuevo_) in enumerate(f["celdas"], start=1):
            if nuevo_ == "mal":
                fila.append(td(texto, H["mal_fondo"], H["mal_texto"], True))
            elif nuevo_ and fondos:
                fila.append(td(texto, H["cambio_hoja_fondo"], H["cambio_hoja_texto"], True))
            elif nuevo_:
                fila.append(td(texto, H["cambio_fondo"], H["cambio_texto"], True))
            else:
                fila.append(td(texto, _tinte(fondo_real(f["n"], c - 1, texto) if fondos else "#FFFFFF", f),
                               H["tenue"] if texto == "fórmula" else H["texto"]))
        filas.append("<tr>" + "".join(fila) + "</tr>")
    return f'<div class="desliza"><table class="hoja">{"".join(filas)}</table></div>'
