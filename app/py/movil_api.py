"""Lógica de las pantallas del teléfono. Hace lo MISMO que la ventana del Mac (mismas funciones de los módulos
registro_core, resumen_core, estadistico_core, cruce_core…), pero en vez de dibujar con Tk devuelve HTML.
Cada acción recibe un diccionario y devuelve {"html": ..., "pagina": ..., "aviso": ...}."""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import web_shim
web_shim.instalar_stubs()

import registro_core as rc
import registro_google as rg
import resumen_core as rsm
import reporte_core as rpt
import estadistico_core as ec
import cruce_core as cc
import registro_diario as rd
import correo_core
import sync_core as sc
import movil_html as H
import tema_web as tema
from movil_html import a, esc
from registro_core import ErrorRegistro

web_shim.instalar_google(rg)

PAGINAS = ("resumen", "registrar", "hojas", "correo", "ajustes", "app")
ICO_PDF = '<svg viewBox="0 0 24 24"><path d="M6 3.5h9l4 4V20a.5.5 0 0 1-.5.5h-12A.5.5 0 0 1 6 20z"/><path d="M14.5 3.5V8H19M9 13h6M9 16.5h4"/></svg>'

E = {   # el estado de la sesión (lo que en el Mac vive en el diccionario «estado»)
    "resumen": None, "lectura": {}, "resumen_hora": None, "resumen_error": None, "proyecto": None, "cache_firma": {},
    "vista_unidad": "todo", "corr_res": set(), "msg_corr": [], "msg_err": [], "n_hall": {}, "vistas": {},
    "pdf": None, "pdf_texto": None, "plan": None, "decision": {"06": "dejar", "07": "dejar"}, "correcciones": set(),
    "var06": True, "var07": True, "banner": None, "checks": [], "escrito": False, "formulario": None, "titulo": None,
    "reporte": None,
}


def iniciar(carpeta_datos=None):
    """Prepara la carpeta de datos (en el teléfono es una carpeta que el navegador guarda) y devuelve el estado inicial."""
    if not rc.RUTA_CONFIG.exists():
        inicial = Path(__file__).with_name("config_inicial.json")
        rc.CARPETA.mkdir(parents=True, exist_ok=True)
        rc.RUTA_CONFIG.write_text(inicial.read_text(encoding="utf-8"), encoding="utf-8")
    return info_shell()


def info_shell():
    proyectos, activo = rc.listar_proyectos()
    return {"proyectos": proyectos, "activo": activo}


def texto_error(error, que="no pude terminar."):
    if isinstance(error, ErrorRegistro):
        return str(error)
    return f"Algo salió mal y {que}\n\nDetalle técnico (cópialo y envíamelo): {type(error).__name__}: {error}"


def hace_cuanto(momento):
    if not momento:
        return ""
    seg = int((datetime.now() - momento).total_seconds())
    if seg < 45:
        return "justo ahora"
    if seg < 3600:
        return f"hace {max(1, round(seg / 60))} min"
    return f"hace {seg // 3600} h"


def _color_de(c, i):
    h = c.get("color") or ""
    return h if re.fullmatch(r"#[0-9A-Fa-f]{6}", h) else tema.PALETA_ROLLOS[i % len(tema.PALETA_ROLLOS)]


def _intentar(f):
    try:
        return f(), None
    except Exception as e:
        return None, e


# =============================================================================
# RESUMEN: leer las hojas y armar el modelo (igual que «cargar_resumen» del Mac)
# =============================================================================
def leer_resumen(forzar=False):
    proyecto = rc.listar_proyectos()[1]
    if E["proyecto"] != proyecto:
        E.update(proyecto=proyecto, resumen=None, lectura={}, resumen_error=None, resumen_hora=None, vista_unidad="todo", reporte=None,
                 corr_res=set(), msg_corr=[], msg_err=[], plan=None, pdf=None, pdf_texto=None, formulario=None)
    try:
        cfg = rc.cargar_config()
    except ErrorRegistro:
        return
    todos07 = rc.estadisticos(cfg)
    tiene06, tiene07 = bool(cfg["hoja"]["enlace"]), bool(todos07)
    if not (tiene06 or tiene07) or not rg.estado_cuenta()["conectado"]:
        E.update(resumen=None, lectura={}, resumen_error=None, resumen_hora=None)
        return
    if forzar:
        rg.olvidar_pestanas()
    E["resumen_error"] = None

    def titulo06():
        try:
            return rg.titulo_hoja(rg.conectar(), rg.id_de_enlace(cfg["hoja"]["enlace"]))
        except Exception:
            return None

    def leer06():
        servicio = rg.conectar()
        sid = rg.id_de_enlace(cfg["hoja"]["enlace"])
        principal = cfg["hoja"]["pestana"]
        try:
            nombres = rg.pestanas_de(servicio, sid)
        except ErrorRegistro:
            nombres = [principal]
        if principal not in nombres:
            nombres = [principal]
        pedir = [principal] + [n for n in nombres if n != principal][:30]
        try:
            valores = rg.leer_pestanas_valores(servicio, sid, pedir)
        except ErrorRegistro:
            rg.olvidar_pestanas(sid)
            nombres = rg.pestanas_de(servicio, sid)
            if principal not in nombres:
                raise
            pedir = [principal] + [n for n in nombres if n != principal][:30]
            valores = rg.leer_pestanas_valores(servicio, sid, pedir)
        valores = dict(valores)
        fallos06 = []
        for k_, otro in enumerate(rc.estatus(cfg)[1:], start=2):
            try:
                sid_o = rg.id_de_enlace(otro["enlace"])
                nombres_o = rg.pestanas_de(servicio, sid_o)[:30]
                vals_o = rg.leer_pestanas_valores(servicio, sid_o, nombres_o)
            except Exception as e_:
                fallos06.append(f"{otro.get('titulo') or 'Un estatus'}: {texto_error(e_, 'no pude leerlo.')}")
                continue
            for n_ in nombres_o:
                if n_ not in vals_o:
                    continue
                dest = n_
                if dest in valores:
                    dest = f"{n_} ({otro.get('titulo') or 'archivo ' + str(k_)})"
                    while dest in valores:
                        dest += "·"
                valores[dest] = vals_o[n_]
        f06_ = rsm.resumir_f06_pestanas(valores, principal, cfg)
        f06_["_valores"] = valores
        f06_["fallos06"] = fallos06
        return valores[principal], f06_

    def leer07_de(est_i):
        servicio = rg.conectar()
        pestanas = [est_i["datos"]] + ([est_i["resumen"]] if est_i.get("resumen") else [])
        g = rg.leer_cuadriculas(servicio, rg.id_de_enlace(est_i["enlace"]), pestanas)
        return g[0], rsm.resumir_f07(g[0], g[1] if len(g) > 1 else None)

    def leer07():
        lecturas = [_intentar(lambda e_=e_: leer07_de(e_)) for e_ in todos07]
        buenas, fallos = [], []
        for j, (e_, lectura_) in enumerate(zip(todos07, lecturas)):
            r_, err = lectura_
            (buenas.append((j, e_, r_)) if err is None else fallos.append((e_, err)))
        if not buenas:
            raise fallos[0][1]
        grids = {j: r_[0] for j, _e, r_ in buenas}
        partes = [((e_.get("etiqueta") or e_.get("titulo") or f"Estadístico {j + 1}"), r_[1], j) for j, e_, r_ in buenas]
        f07_ = rsm.unir_f07(partes)
        f07_["textos07"] = {k: (buenas[k][1].get("titulo") or "") for k in range(len(buenas))}
        f07_["fallos"] = [f"{e_.get('titulo') or e_.get('etiqueta') or 'Un estadístico'}: {err}" for e_, err in fallos]
        return grids, f07_

    lect, f06, f07, primero = {}, None, None, None
    filas06 = g07 = None
    titulo = titulo06() if tiene06 else None
    res06 = _intentar(leer06) if tiene06 else None
    res07 = _intentar(leer07) if tiene07 else None
    try:
        if res06 is not None:
            r, e = res06
            if e is None:
                filas06, f06 = r
                if titulo:
                    lect["titulo06"] = titulo
                lect["f06"] = "ok"
            else:
                lect["f06"] = str(e)
                primero = primero or e
        if res07 is not None:
            r, e = res07
            if e is None:
                g07, f07 = r
                lect["f07"] = "ok"
            else:
                lect["f07"] = str(e)
                primero = primero or e
        if f06 is None and f07 is None:
            raise primero or ErrorRegistro("No pude leer tus hojas.")
        firma = (repr((f06 or {}).get("_valores", filas06)), repr(g07), json.dumps(cfg, sort_keys=True, default=str))
        previo = E["cache_firma"].get(proyecto)
        if previo is not None and previo[0] == firma and previo[1] is not None:
            E.update(resumen=previo[1], lectura=lect, resumen_hora=datetime.now())
            return
        modelo = rsm.construir(cfg, f06, f07, proyecto)
        for fallo_ in (f06 or {}).get("fallos06", []):
            modelo["avisos"].append(("aviso", "No pude leer un estatus de tarjetas: " + fallo_))
        for fallo_ in (f07 or {}).get("fallos", []):
            modelo["avisos"].append(("aviso", "No pude leer un estadístico: " + fallo_))
        modelo["cruce"], modelo["cruce_error"] = None, None
        if filas06 is not None and g07:
            try:
                pares_ = rsm.emparejar_f07(f06, f07["unidades07"], f07.get("textos07"))
                todas06 = f06.get("_valores") or {}
                partes_cr = []
                for u7, i_ in zip(f07["unidades07"], pares_):
                    if f06.get("por_unidad"):
                        if i_ is None:
                            continue
                        tab_ = f06["por_unidad"][i_]["pestana"]
                    elif i_ is None:
                        continue
                    else:
                        tab_ = cfg["hoja"]["pestana"]
                    partes_cr.append((tab_, u7["indice"], cc.cruzar(todas06.get(tab_) or filas06, g07[u7["indice"]], cfg)))
                if partes_cr:
                    modelo["cruce"] = cc.unir_cruces(partes_cr)
            except Exception as e:
                modelo["cruce_error"] = str(e)
        for clave, txt in lect.items():
            if clave in ("f06", "f07") and txt != "ok":
                modelo["avisos"].insert(0, ("aviso", f"No pude leer {'el estatus de tarjetas' if clave == 'f06' else 'el estadístico'}: {txt}. "
                                                     f"Este resumen usa solo {'el estadístico' if clave == 'f06' else 'el estatus de tarjetas'}, "
                                                     "por eso puede faltar información."))
        if lect.get("f06") == "ok" and (g07 is None or lect.get("f07") == "ok"):
            E["cache_firma"][proyecto] = (firma, modelo)
        E.update(resumen=modelo, lectura=lect, resumen_hora=datetime.now(), corr_res=set(), n_hall={})
        if not E.pop("msg_conservar", False):
            E["msg_corr"], E["msg_err"] = [], []
        if lect.get("titulo06"):
            E["titulo"] = lect["titulo06"]
    except Exception as e:
        E["resumen_error"] = texto_error(e, "no pude leer tus hojas.")
        E["lectura"] = {}


# ---------------- tarjetas del Resumen ----------------
POR_PAGINA_HALL = 5


def _vista_hojas(h, clave, pos, total):
    vistas = [(r, h[k]) for r, k in (("Estatus de tarjetas (FO-06) · lo correcto", "vista06"),
                                      ("Estadístico (FO-07) · lo que está mal y cómo quedaría", "vista07")) if h.get(k)]
    if not vistas:
        return ""
    abierta = E["vistas"].get((clave, h["id"]), pos < (2 if total <= POR_PAGINA_HALL else 0))
    out = H.boton("Ocultar las hojas" if abierta else "Ver cómo se ve en las hojas", "alternar_vista", "mini",
                  clave=clave, id=h["id"], abierta=abierta)
    if abierta:
        for rotulo, bloque in vistas:
            out += f'<p class="nota">{esc(rotulo)}</p>' + H.cuadricula(bloque, 90 if "FO-06" in rotulo else 80)
        if any(b.get("recortado") for _r, b in vistas):
            out += '<p class="nota">(solo se muestran las primeras filas del día)</p>'
    return out


def html_incongruencias(cr, error, clave, elegidas, escrito=False, nota_error="", mensajes=(), accion=None):
    """Las incongruencias entre el estatus de tarjetas (la fuente) y el estadístico (igual que en el Mac)."""
    if error and cr is None:
        return H.tarjeta(H.cabecera("Revisión de las dos hojas", "FO-06 ↔ FO-07", "no se pudo revisar", "aviso")
                         + H.aviso("aviso", f"No pude comparar las dos hojas: {error}" + (f"\n{nota_error}" if nota_error else "")))
    hall, redondeos = cr["hallazgos"], cr.get("redondeos", [])
    ids_todos = {h["id"] for h in hall if h["corregible"]} | {h["id"] for h in redondeos}
    n_sel = len(elegidas & ids_todos)
    cuerpo = "".join(H.aviso("ok" if t == "ok" else "aviso", x) for t, x in mensajes)

    def bloque_redondeo():
        if not redondeos:
            return ""
        abierto = E["vistas"].get((clave, "redondeo"), False)
        s = (f'<div class="fila-info"><span class="nota">ℹ {len(redondeos)} {"día" if len(redondeos) == 1 else "días"} con diferencias mínimas de redondeo (menos de 1 GB o 30 s) · '
             f'no cuentan como errores</span> {H.boton("Ocultar" if abierto else "Ver / corregir", "alternar_vista", "mini", clave=clave, id="redondeo", abierta=abierto)}</div>')
        if abierto:
            if not escrito:
                n_r = len([h for h in redondeos if h["id"] in elegidas])
                s += ('<div class="barra-mini">' + H.boton("Marcar todas", "marcar", "mini", ids=[h["id"] for h in redondeos], valor=True)
                      + H.boton("Quitar todas", "marcar", "mini", ids=[h["id"] for h in redondeos], valor=False)
                      + f'<span class="nota">{n_r} de {len(redondeos)} marcadas para corregir</span></div>')
            for h in redondeos:
                cambios_r = "   ·   ".join(f"{c['celda']}  {c['concepto']}: {c['antes_txt']} → {c['nuevo_txt']}" for c in h["celdas"])
                s += '<div class="item">'
                s += (H.chip("✔ corregido" if h["id"] in elegidas else "sin corregir", "exito" if h["id"] in elegidas else "info") + f'<b>{esc(h["texto_dia"])}</b>'
                      if escrito else H.casilla(h["texto_dia"], h["id"] in elegidas, "marcar", ids=[h["id"]], clave=clave))
                s += f'<p class="nota sangria">Se cambiaría:  {esc(cambios_r)}</p></div>'
        return s

    def boton_accion():
        if not accion or escrito:
            return ""
        return ('<hr>' + (f'<button class="btn grande-btn {"acento" if n_sel else ""}" {a(accion[1])} {"" if n_sel else "disabled"}>'
                          f'{esc(accion[0])}{f" ({n_sel})" if n_sel else ""}</button>'))

    if not hall:
        cuerpo += H.cabecera("Revisión de las dos hojas", "FO-06 ↔ FO-07", "✔ todo cuadra", "exito",
                             f"Comparé {cr['comparados']} {'día' if cr['comparados'] == 1 else 'días'} que están en las dos hojas y coinciden: cámaras, clips, rollos, duración y audio.")
        cuerpo += "".join(H.aviso("info", x) for x in cr["avisos"]) + bloque_redondeo()
        if redondeos:
            cuerpo += boton_accion()
        return H.tarjeta(cuerpo)
    corregibles = [h for h in hall if h["corregible"]]
    cuerpo += ('<p class="sub">El estatus de tarjetas es la fuente: si eliges «Corregir», solo se cambian las celdas indicadas del estadístico. '
               'No se cambia nada hasta que lo confirmes. En las vistas de abajo: rojo = lo que está mal, verde = lo correcto.</p>')
    if len(corregibles) > 1 and not escrito:
        cuerpo += ('<div class="barra-mini">' + H.boton("Corregir todas las que se pueden", "marcar", "mini", ids=[h["id"] for h in corregibles], valor=True, clave=clave)
                   + H.boton("No corregir ninguna", "marcar", "mini", ids=sorted(ids_todos), valor=False, clave=clave) + '</div>')
    if len(hall) > POR_PAGINA_HALL:
        cuerpo += H.aviso("aviso", f"Hay {len(hall)} diferencias. Para que la app no se ponga lenta te muestro de a {POR_PAGINA_HALL}. "
                          "Si son muchísimas, lo más probable es que las dos hojas estén organizadas distinto (otro orden de días o de "
                          "columnas): revisa primero las primeras antes de corregir en bloque.")
    visibles = max(POR_PAGINA_HALL, E["n_hall"].get(clave, POR_PAGINA_HALL))
    for pos, h in enumerate(hall[:visibles]):
        cuerpo += f'<hr><div class="item"><b>{esc(h["titulo"])}</b><p class="sub">{esc(h["detalle"])}</p>'
        cuerpo += H.aviso("aviso", h["causa"]) + _vista_hojas(h, clave, pos, len(hall))
        if h["celdas"]:
            cuerpo += f'<p class="nota">{esc(cc.texto_cambios(h))}</p>'
        elegido = h["id"] in elegidas
        if escrito:
            cuerpo += H.chip(f"✔ corregido en {cc.donde_corto(h)}" if elegido else "sin corregir", "exito" if elegido else "info")
        elif h["corregible"]:
            cuerpo += H.segmentado([("dejar", "Dejar como está"), ("corregir", f"Corregir en {cc.donde_corto(h)}")],
                                   "corregir" if elegido else "dejar", "marcar_seg", id=h["id"], clave=clave)
        else:
            cuerpo += H.chip("revísalo a mano", "info") + '<span class="nota"> la app no puede saber cuál es el dato correcto</span>'
        cuerpo += "</div>"
    if len(hall) > visibles:
        cuerpo += H.boton(f"Mostrar {min(POR_PAGINA_HALL, len(hall) - visibles)} más (faltan {len(hall) - visibles})", "mas_hallazgos", "mini", clave=clave)
    cuerpo += "".join(H.aviso("info", x) for x in cr["avisos"]) + bloque_redondeo()
    if accion and not escrito:
        cuerpo += boton_accion()
    return H.plegable("inc-" + clave, "Incongruencias entre las dos hojas", cuerpo, H.chip(f"{len(hall)} por revisar", "aviso"),
                      f"FO-06 ↔ FO-07 · comparé {cr['comparados']} {'día' if cr['comparados'] == 1 else 'días'}", abierto=(clave == "reg" and len(hall) <= 3 and not escrito))


def html_errores_escritura(m):
    errores = m.get("errores_escritura") or []
    corregibles = [e for e in errores if e["corregible"]]
    ids = {e["id"] for e in corregibles}
    n = len(E["corr_res"] & ids)
    if errores:
        chip_ = H.chip(f"{len(errores)} por revisar", "aviso")
        c = ('<p class="sub">Hay celdas con un número u hora mal escrito. La hoja no las puede sumar, así que esa tarjeta cuenta como 0. '
             'Elige cuáles quieres que corrija la app; no se cambia nada hasta que lo confirmes.</p>')
    else:
        chip_ = H.chip("✔ corregido", "exito")
        c = ""
    c += "".join(H.aviso("ok" if t == "ok" else "aviso", x) for t, x in E["msg_err"])
    if len(corregibles) > 1:
        c += ('<div class="barra-mini">' + H.boton("Corregir todas las que se pueden", "marcar", "mini", ids=sorted(ids), valor=True)
              + H.boton("No corregir ninguna", "marcar", "mini", ids=sorted(ids), valor=False) + "</div>")
    for e in errores:
        titulo = f"{e['dia']} · {e['bin']} · fila {e['fila']} · {e['columna']}: «{e['valor']}»"
        c += "<hr><div class='item'>"
        if e["corregible"]:
            c += H.casilla(titulo, e["id"] in E["corr_res"], "marcar", ids=[e["id"]])
            c += (f'<p class="nota sangria">Se cambiaría la celda {esc(e["celda"])} por  {esc(e["nuevo_txt"])}  ({esc(e["motivo"])}). '
                  'Confírmalo con tu reporte de Silverstack.</p>')
        else:
            c += f"<b>{esc(titulo)}</b>" + H.aviso("aviso", f"No puedo adivinar qué quisiste escribir en {e['celda']}: corrígela a mano en la hoja.")
        c += "</div>"
    if corregibles:
        c += ("<hr>" + f'<button class="btn grande-btn {"acento" if n else ""}" {a("corregir_errores")} {"" if n else "disabled"}>'
              f'Corregir las elegidas{f" ({n})" if n else ""}</button>')
    return H.plegable("res-err", "Errores de escritura en el estatus", c, chip_, "FO-06", abierto=bool(E["msg_err"]) and not errores)


def html_resumen():
    m = E["resumen"]
    if m is None:
        try:
            cfg = rc.cargar_config()
        except ErrorRegistro as e:
            return H.vacia("No pude abrir tu configuración", str(e), tipo="error")
        cuenta = rg.estado_cuenta()
        if not (cfg["hoja"]["enlace"] or (cfg.get("estadistico") or {}).get("enlace")):
            return H.vacia("Todavía no hay hojas conectadas",
                           "Conecta tu estatus de tarjetas (FO-06) o tu estadístico (FO-07) y aquí verás cuántas cámaras hay, "
                           "cuántos TB lleva cada una y en qué rollo va.", H.boton("Conectar una hoja", "ir", "acento", pagina="hojas"))
        if not cuenta["conectado"]:
            return H.vacia("Conecta tu cuenta de Google", "Para leer tus hojas necesito tu cuenta de Google.",
                           '<button class="btn acento" data-js="conectar">Conectar con Google</button>', "aviso")
        if E["resumen_error"]:
            return H.vacia("No pude leer tus hojas", E["resumen_error"], H.boton("Reintentar", "actualizar", "acento"), "error")
        return H.vacia("Todavía no he leído tus hojas", "Pulsa Actualizar para leerlas.", H.boton("Actualizar", "actualizar", "acento"), "carga")
    unidades = m.get("unidades") or []
    vista_id = E["vista_unidad"] if E["vista_unidad"] in {u["id"] for u in unidades} else "todo"
    vista = next((u for u in unidades if u["id"] == vista_id), None)
    t = (vista or m)["totales"]
    camaras_v = vista["camaras"] if vista else m["camaras"]
    serie_v = vista["serie"] if vista else m["serie"]
    out = []
    if E["reporte"]:
        out.append(html_reporte(m))                    # el panel va ARRIBA; el Resumen sigue completo debajo
    elif m["serie"]:
        out.append(f'<div class="reporte-abrir"><button class="btn reporte-btn" {a("reporte_abrir")}><span class="ico">📄</span>'
                   '<span><b>Sacar reporte para enviar</b><small>Un día, una semana o las fechas que quieras</small></span>'
                   '<span class="flecha">›</span></button></div>')
    repetidos = [x for x in m["avisos"] if x[1].startswith(("Rollo repetido", "Revisa el último rollo"))]
    if repetidos:
        c = ('<p class="sub">Cada rollo de una cámara debe tener un número único, y el último rollo debería ser a la vez el de número '
             'más alto y el de fecha más reciente. Corrígelo en tu hoja de estatus de tarjetas.</p>')
        out.append(H.plegable("res-rollos", "Rollos por revisar", c + "".join(H.aviso("aviso", x) for _t, x in repetidos),
                              H.chip(f"{len(repetidos)} por revisar", "aviso"), "número y fecha"))
    if m.get("errores_escritura") or E["msg_err"]:
        out.append(html_errores_escritura(m))
    if m.get("cruce") is not None or m.get("cruce_error"):
        out.append(html_incongruencias(m.get("cruce"), m.get("cruce_error"), "res", E["corr_res"], mensajes=E["msg_corr"],
                                       accion=("Corregir las elegidas", "corregir_cruce")))
    if len(unidades) > 1:
        out.append(H.segmentado([("todo", "Todo")] + [(u["id"], u["nombre"]) for u in unidades], vista_id, "unidad"))
    letras = " · ".join(t["letras"]) or "—"
    cifras = [("", "Total grabado", f"{t['tb']:,.2f} TB", f"promedio {rsm.texto_peso(t['promedio_gb'])} por día", True),
              ("", "Días rodados", f"{t['dias']}", (f"de {t['dias_previstos']} previstos" if t["dias_previstos"] else ""), False),
              ("", "Cámaras", f"{t['camaras']}", letras, False),
              ("", "Clips", f"{t['clips']:,}" if t["clips"] else "—",
               ("video" + (f" · +{t['clips_audio']:,} audio" if t.get("clips_audio") else "")) if t["clips"] else "", False),
              ("", "Duración", f"{int(t['seg']) // 3600:,} h" if t["seg"] else "—",
               ("video" + (f" · audio {int(t['seg_audio']) // 3600:,} h" if t.get("seg_audio") else "")) if t["seg"] else "", False)]
    out.append('<div class="cifras">' + "".join(H.metrica(*c) for c in cifras) + "</div>")
    con_datos = [c for c in m["camaras"] if c["gb"] > 0]
    colores = rpt.colores_de_camaras(m["camaras"], tema.PALETA_ROLLOS)       # el color de cada rollo tal cual (el de la hoja o el elegido)
    por_nombre = {c["nombre"]: colores[i] for i, c in enumerate(m["camaras"])}

    def color_nombre(c, i=0):
        return por_nombre.get(c["nombre"]) or _color_de(c, i)

    def barras_de(lista):
        return H.barras([(c["nombre"], color_nombre(c), c["pct"], rsm.texto_peso(c["gb"]), f"{c['pct'] * 100:.1f} %") for c in lista if c["gb"] > 0])
    if vista is None and len(unidades) > 1:
        cuerpo = ""
        for u in unidades:
            cuerpo += (f'<div class="tj-titulo"><b>{esc(u["nombre"])}</b><span class="nota">{u["totales"]["tb"]:,.2f} TB · porcentajes dentro de la unidad</span></div>'
                       + barras_de(u["camaras"]))
    else:
        cuerpo = barras_de(camaras_v)
    cuerpo = '<div class="centro">' + H.dona([(c["gb"], color_nombre(c)) for c in (vista["camaras"] if vista else con_datos) if c["gb"] > 0],
                                             f"{t['tb']:,.1f} TB", "en total" if not vista else vista["nombre"]) + "</div>" + cuerpo
    out.append(H.tarjeta(cuerpo, "Almacenamiento por cámara" + (f" · {vista['nombre']}" if vista else "")))
    varias = len(unidades) > 1
    nombre_unidad = {u["pestana"]: u["nombre"] for u in unidades}
    filas_c = []
    for c in m["camaras"]:
        bin_ = c["ultimo_bin"]
        rollo = "_".join(bin_.split("_")[:2]) if c["tipo"] == "camara" else bin_
        f_ = c.get("ultima_fecha")
        dia_txt = (c["ultimo_dia"] or "") + (f" · {f_.strftime('%d/%m')}" if (varias and f_ and c["ultimo_dia"]) else "")
        uni = nombre_unidad.get(c.get("ultima_unidad"), c.get("ultima_unidad") or "") if (varias and rollo) else ""
        extras = [("Rollo actual", bin_ if (bin_ and bin_ != rollo) else ""), ("# Mag", str(c["ultima_mag"]) if c["ultima_mag"] is not None else ""),
                  ("Último día", dia_txt), ("Clips", f"{c['clips']:,}" if c["clips"] else ""), ("Duración", rsm.hms(c["seg"]) if c["seg"] else ""),
                  ("Unidad", uni)]
        filas_c.append(H.fila_camara(c["nombre"], color_nombre(c), rollo, extras,
                                     "Sin material" if c.get("sin_material") else rsm.texto_peso(c["gb"]), c["nombre"]))
    nota = ('<p class="nota">Toca una cámara para ver todos sus datos. «Rollo actual», «Mag», «Unidad» y «Día» son el más reciente de todo el proyecto (el día de calendario más '
            'nuevo entre todas las unidades). Clips, duración y volumen suman todas las unidades.</p>') if varias else ""
    out.append(H.tarjeta('<div class="cam-lista">' + "".join(filas_c) + "</div>" + nota, "Rollo en el que va cada cámara" + (" · todo el proyecto" if varias else "")))
    if serie_v:
        mejor, ultimo = t["mejor"], t["ultimo"]
        ultimos = serie_v[-45:]
        cuerpo = f'<p class="nota">Mejor día {esc(mejor["dia"])}: {esc(rsm.texto_peso(mejor["gb"]))}</p>'
        cuerpo += H.columnas([(d["dia"], d["gb"], f"{d['dia']} · {d['fecha'].strftime('%d/%m/%Y') if d['fecha'] else '—'} · {rsm.texto_peso(d['gb'])}"
                               + (f" · {d['clips']} clips" if d["clips"] else "")) for d in ultimos], t["promedio_gb"],
                               f'{rsm.texto_peso(t["promedio_gb"])}/día' if t["promedio_gb"] else "")
        fecha_u = ultimo["fecha"].strftime("%d/%m/%Y") if ultimo["fecha"] else "—"
        cuerpo += (f'<p class="nota">Último día registrado: {esc(ultimo["dia"])} · {fecha_u} · {esc(rsm.texto_peso(ultimo["gb"]))}'
                   + (f"  ·  mostrando los últimos {len(ultimos)} de {len(serie_v)} días" if len(serie_v) > len(ultimos) else "") + "</p>")
        out.append(H.tarjeta(cuerpo, "Volumen por día"))
    if vista is not None:
        t = dict(t, dias_previstos=vista.get("dias_previstos"), espacio_previsto_gb=vista.get("espacio_previsto_gb"))
    if (vista is None or vista.get("estadistico")) and (t["dias_previstos"] or t["espacio_previsto_gb"]):
        cuerpo = ""
        for texto, hecho, total_, rotulo in (
                ("Días de rodaje", t["dias"], t["dias_previstos"], f"{t['dias']} de {t['dias_previstos']} días"),
                ("Espacio previsto", t["gb"], t["espacio_previsto_gb"],
                 (f"{t['tb']:,.2f} TB de {(t['espacio_previsto_gb'] or 0) / rsm.GB_POR_TB:,.2f} TB" if t["espacio_previsto_gb"] else ""))):
            if not total_:
                continue
            fr = min(1.0, hecho / total_)
            cuerpo += (f'<div class="prev"><div class="tj-titulo"><b>{esc(texto)}</b><span class="sub">{esc(rotulo)}  ·  {min(100, hecho / total_ * 100):.0f} %</span></div>'
                       f'<div class="pista"><div class="relleno" style="width:{fr * 100:.1f}%"></div></div></div>')
        sem = (vista.get("semana") if vista else None) or m["semana"]
        if sem:
            cuerpo += f'<p class="nota">{esc(sem)}</p>'
        out.append(H.tarjeta(cuerpo, "Avance según tu estadístico"))

    def equipo_html(equipo, formato, rotulo=""):
        if not (equipo or formato):
            return ""
        s = f'<h4>{esc(rotulo)}</h4>' if rotulo else ""
        for titulo, datos in (("Equipo", list(equipo.items())), ("Formato de grabación", formato)):
            if datos:
                s += f'<h4>{esc(titulo)}</h4>' + "".join(f'<div class="kv"><span class="sub">{esc(k)}</span><span>{esc(v)}</span></div>' for k, v in datos)
        return s
    if vista is not None:
        eq_html = equipo_html(vista.get("equipo") or m["equipo"], vista.get("formato") or m["formato"])
    else:
        propios = [(u["nombre"], u.get("equipo") or {}, u.get("formato") or []) for u in unidades if u.get("equipo") or u.get("formato")]
        if len(propios) > 1 and len({(repr(e_), repr(f_)) for _n, e_, f_ in propios}) > 1:
            eq_html = "".join(equipo_html(e_, f_, n_) for n_, e_, f_ in propios)
        else:
            eq_html = equipo_html(m["equipo"], m["formato"])
    if eq_html:
        out.append(H.plegable("res-equipo", "Equipo y formato de grabación", eq_html, "", "lo que dice tu estadístico"))
    for tipo, texto in m["avisos"]:
        if not texto.startswith(("Rollo repetido", "Revisa el último rollo")):
            out.append(H.aviso(tipo, texto))
    fuentes = {"FO-06": "estatus de tarjetas (FO-06)", "FO-07": "estadístico (FO-07)"}
    out.append(f'<p class="nota pie">Fuente: {fuentes.get(m["fuente"], "—")}. Esta pestaña solo lee tus hojas; únicamente escribe si tú eliges corregir algo.  '
               'Unidades: GB decimales, 1 TB = 1.000 GB.</p>')
    return "".join(out)


# ---------------- Reporte para enviar ----------------
def _f(texto):
    from datetime import date
    return date.fromisoformat(texto) if texto else None


def html_calendario(r, fechas):
    anio, mes_ = r["mes"]
    cab = (f'<div class="cal-cab"><b>{esc(rpt.titulo_mes(anio, mes_))}</b><span class="espacio"></span>'
           f'<button class="cal-flecha" {a("reporte_mes", paso=-1)} aria-label="Mes anterior">‹</button>'
           f'<button class="cal-flecha" {a("reporte_mes", paso=1)} aria-label="Mes siguiente">›</button></div>')
    dias = "".join(f'<span class="cal-ds">{d}</span>' for d in rpt.DIAS_SEMANA)
    celdas = []
    for sem in rpt.mes(anio, mes_, fechas, r["elegidos"]):
        for c in sem:
            if c is None:
                celdas.append('<span></span>')
                continue
            cl = ["cal-d"] + [k for k in ("rodado", "elegido", "inicio", "fin", "hoy") if c[k]]
            celdas.append(f'<button class="{" ".join(cl)}" {a("reporte_tocar", fecha=c["fecha"].isoformat())}>'
                          f'<span>{c["fecha"].day}</span></button>')
    return f'<div class="calendario">{cab}<div class="cal-grid">{dias}{"".join(celdas)}</div></div>'


def html_reporte(m):
    r = E["reporte"]
    fechas = rpt.rodados(m, r["unidad"])
    out = ['<div id="reporte-panel"></div>']
    cuerpo = ('<p class="sub">Elige un día, una semana o los días que quieras (seguidos o sueltos). Sale una página con el almacenamiento '
              'de esos días por cámara, sus gráficas y el avance del proyecto, lista para compartir o guardar en PDF.</p>')
    unidades = m.get("unidades") or []
    if len(unidades) > 1:                              # primero: de qué unidad (o todas juntas)
        cuerpo += ('<p class="nota"><b>¿De qué unidad?</b></p>'
                   + H.segmentado([("todo", "Todas")] + [(u["id"], u["nombre"]) for u in unidades], r["unidad"] or "todo", "reporte_unidad")
                   + '<p class="nota">«Todas» suma las unidades y muestra cuánto puso cada una; o elige una para su reporte por separado.</p>')
    cuerpo += H.segmentado(list(rpt.TIPOS), r["tipo"], "reporte_tipo")
    botones = [H.boton(t, "reporte_rango", "mini", tipo=tipo_, fechas=sorted(f.isoformat() for f in e))
               for t, tipo_, e in rpt.atajos(m, r["unidad"])]
    if r["tipo"] == "dias" and r["elegidos"]:
        botones.append(H.boton("Quitar todos", "reporte_rango", "mini", tipo="dias", fechas=[]))
    cuerpo += '<div class="atajos">' + "".join(botones) + "</div>"
    cuerpo += html_calendario(r, fechas)
    ayuda = {"dia": "Toca un día.", "semana": "Toca cualquier día: se elige su semana (lunes a domingo).",
             "dias": "Toca cada día que quieras; tócalo otra vez para quitarlo."}[r["tipo"]]
    cuerpo += f'<p class="nota">{esc(ayuda)} El punto verde marca los días con material.</p>'
    out.append(H.tarjeta(cuerpo, "Sacar un reporte", H.boton("Cerrar", "reporte_cerrar", "mini")))
    datos = rpt.armar(m, r["elegidos"], r["unidad"]) if r["elegidos"] else None
    res = (f'<span class="chip info">{esc(datos["unidad"])}</span>' if datos and datos.get("unidad") else "")
    res += f'<div class="periodo-txt">{esc(datos["periodo"] if datos else "Ningún día")}</div>'
    if datos and datos["dias"]:
        t = datos["totales"]
        linea = f"{t['dias']} día{'s' if t['dias'] != 1 else ''} de rodaje ({rpt.texto_dias(datos)}) · {rsm.texto_peso(t['gb'])}"
        if datos["semanas"]:
            linea += " · " + rpt.texto_semanas(datos["semanas"])
        res += f'<p class="sub">{esc(linea)}</p>'
    else:
        res += H.aviso("aviso", "No hay material registrado en los días elegidos." if r["elegidos"] else "Toca los días en el calendario.")
    res += '<p class="nota">Apariencia del reporte</p>' + H.segmentado([("claro", "Claro"), ("oscuro", "Oscuro")], r["modo"], "reporte_modo")
    res += '<p class="nota">Contenido</p>' + H.segmentado([("resumen", "Resumen"), ("detallado", "Detallado")],
                                                          "detallado" if r["completo"] else "resumen", "reporte_contenido")
    res += ('<p class="nota">' + ("Detallado agrega cada cámara con sus rollos, cada tarjeta y todos los días del proyecto." if r["completo"]
                                  else "Como el «Resumen General» de tu estadístico, solo con los días elegidos.") + "</p>")
    out.append(H.tarjeta(res, "Días elegidos"))
    return "".join(out)


def _repintar_reporte(extra=None):
    r = {"pagina": "resumen", "html": html_resumen()}
    rr = E["reporte"]
    m = E["resumen"]
    if rr and m:
        hay = any(d.get("fecha") in rr["elegidos"] for d in m["serie"])
        r["barra"] = ('<button class="btn acento" ' + a("reporte_crear") + (">" if hay else " disabled>") + "Crear reporte</button>")
    r.update(extra or {})
    return r


def reporte_abrir(p):
    m = E["resumen"]
    if m is None:
        return {"toast": "Primero tengo que leer tus hojas."}
    unidad = E["vista_unidad"] if E["vista_unidad"] in {u["id"] for u in m.get("unidades") or []} else None
    elegidos = rpt.inicial(m, unidad)
    ref = max(elegidos) if elegidos else datetime.now().date()
    E["reporte"] = {"tipo": "semana", "elegidos": elegidos, "mes": (ref.year, ref.month), "unidad": unidad,
                    "modo": p.get("modo") if p.get("modo") in ("claro", "oscuro") else "claro", "completo": False}
    return _repintar_reporte({"scroll": "#reporte-panel"})


def reporte_cerrar(p):
    E["reporte"] = None
    return _repintar_reporte()


def _con_reporte(f):
    if not E["reporte"] or E["resumen"] is None:
        E["reporte"] = None
        return _repintar_reporte()
    f(E["reporte"], rpt.rodados(E["resumen"], E["reporte"]["unidad"]))
    return _repintar_reporte()


def reporte_tipo(p):
    def f(r, fechas):
        e = rpt.ajustar(p["valor"], r["elegidos"], fechas)
        r.update(tipo=p["valor"], elegidos=e, mes=(max(e).year, max(e).month))
    return _con_reporte(f)


def reporte_tocar(p):
    def f(r, _fechas):
        r["elegidos"] = rpt.tocar(r["tipo"], r["elegidos"], _f(p["fecha"]))
    return _con_reporte(f)


def reporte_mes(p):
    return _con_reporte(lambda r, _f_: r.update(mes=rpt.mover_mes(*r["mes"], int(p["paso"]))))


def reporte_rango(p):
    def f(r, _fechas):
        e = {_f(x) for x in p["fechas"]}
        r.update(elegidos=e, tipo=p["tipo"], **({"mes": (max(e).year, max(e).month)} if e else {}))
    return _con_reporte(f)


def reporte_unidad(p):
    return _con_reporte(lambda r, _f_: r.update(unidad=None if p["valor"] == "todo" else p["valor"]))


def reporte_modo(p):
    return _con_reporte(lambda r, _f_: r.update(modo=p["valor"]))


def reporte_contenido(p):
    return _con_reporte(lambda r, _f_: r.update(completo=p["valor"] == "detallado"))


def reporte_crear(p):
    r, m = E["reporte"], E["resumen"]
    if not r or m is None or not r["elegidos"]:
        return _repintar_reporte()
    datos = rpt.armar(m, r["elegidos"], r["unidad"], paleta=tema.PALETA_ROLLOS)
    # el navegador cambia LOGO_CLARO / LOGO_OSCURO por los logos de verdad (así el archivo se puede mandar solo)
    # sin los botones de arriba: el archivo que se comparte desde el teléfono queda limpio (la app ya tiene Compartir y PDF)
    pagina_ = rpt.a_html(datos, r["modo"], {"claro": "LOGO_CLARO", "oscuro": "LOGO_OSCURO"}, barra=False, completo=r["completo"])
    return _repintar_reporte({"reporte": {"html": pagina_, "nombre": rpt.nombre_archivo(datos, "html"),
                                          "titulo": f"Reporte {datos['tipo']} · {datos['proyecto']} · {datos['periodo']}"}})


def pagina_resumen(p=None):
    forzar = bool(p and p.get("forzar"))
    vieja = bool(E["resumen_hora"] and (datetime.now() - E["resumen_hora"]).total_seconds() > 300)
    if forzar or vieja or E["resumen"] is None or E["proyecto"] != rc.listar_proyectos()[1]:
        leer_resumen(forzar)
    r = _repintar_reporte() if E["reporte"] else {"pagina": "resumen", "html": html_resumen()}
    if E["resumen_hora"]:
        r["subtitulo"] = f'Actualizado {esc(hace_cuanto(E["resumen_hora"]))} · jala hacia abajo para actualizar'
    return r


# =============================================================================
# REGISTRAR DÍA
# =============================================================================
VERDE_HOJA, GRIS_RENTAL, GRIS_SIN_COLOR = tema.HOJA["encabezado"], tema.HOJA["rental"], tema.HOJA["sin_color"]
ENCABEZADOS_HOJA = ["DIA RODAJE", "FECHA DE RODAJE", "RENTAL", "CAM", "Modelo de cámara", "# Mag", "# of Clips", "Duración", "Total GB", "Semana"]
TIPOS_FORM = [("camara", "Cámara"), ("sonido", "Sonido"), ("drones", "Drones"), ("celulares", "Celulares"), ("otro", "Otro")]
DESCRIPCION_TIPO = {"sonido": "Reconoceré el sonido solo: son los BIN con nombre tipo 26Y10M01.",
                    "drones": "Reconoceré los drones solos: son los BIN con nombre tipo D036_…",
                    "celulares": "Reconoceré los celulares solos: son los BIN con nombre tipo I001 o J001."}


def estados_de(plan):
    e06 = None
    if not plan.get("solo"):
        c = plan.get("cmp06")
        e06 = ("igual" if c["igual"] else "distinto") if plan.get("ya06") and c else "nuevo"
    e07 = None
    prop = plan.get("est")
    if prop:
        e07 = "nuevo" if not prop.get("tenia_datos") else ("igual" if not prop["cambios"] else "distinto")
    return {"06": e06, "07": e07}


def solo_resumen(plan):
    prop = plan.get("est")
    return bool(prop and prop.get("tenia_datos") and prop["cambios"] and all(c["hoja"] == "resumen" for c in prop["cambios"]))


def chip_de(plan, cual, escrito=False):
    est_ = estados_de(plan)[cual]
    marcado = plan.get("w06" if cual == "06" else "w07")
    if est_ == "igual":
        if marcado:
            return ("✔ escrito de nuevo", "exito") if escrito else ("se sobrescribirá", "aviso")
        return "✔ ya está igual", "exito"
    if est_ == "distinto":
        if marcado:
            return ("✔ reemplazado", "exito") if escrito else ("se reemplazará", "aviso")
        if not E["var06" if cual == "06" else "var07"]:
            return "no se escribirá", "info"
        return ("día igual · resumen distinto" if cual == "07" and solo_resumen(plan) else "ya está · distinto"), "aviso"
    n = len(plan["est"]["cambios"]) if (cual == "07" and plan.get("est")) else None
    if not marcado:
        return ("no se escribió" if escrito else "no se escribirá"), "info"
    if escrito:
        return "✔ escrito", "exito"
    return ("se escribirá" if n is None else f"se escribirá · {n} {'celda' if n == 1 else 'celdas'}"), "exito"


def control_decision(cual, texto, rotulo="Reemplazar"):
    return (f'<div class="decision"><p class="sub">{esc(texto)}</p>'
            + H.segmentado([("dejar", "Dejar como está"), ("reemplazar", rotulo)], E["decision"][cual], "decision", cual=cual) + "</div>")


def seleccionar(plan):
    est_, dec = estados_de(plan), E["decision"]
    c = plan.get("cmp06")
    quiere06 = est_["06"] == "nuevo" or (est_["06"] == "distinto" and bool(c and c["reemplazable"]) and dec["06"] == "reemplazar") \
        or (est_["06"] == "igual" and bool(c and c["reescribible"]) and dec["06"] == "reemplazar")
    quiere07 = est_["07"] == "nuevo" or (est_["07"] in ("distinto", "igual") and dec["07"] == "reemplazar")
    plan["w06"] = bool(E["var06"] and quiere06)
    plan["w07"] = bool(E["var07"] and quiere07 and (plan["est"]["cambios"] or est_["07"] == "igual"))
    plan["reescribe06"] = bool(plan["w06"] and est_["06"] == "igual")
    plan["reescribe07"] = bool(plan["w07"] and est_["07"] == "igual")
    cr = plan.get("cruce")
    plan["corr"] = [h for h in ((cr["hallazgos"] + cr.get("redondeos", [])) if cr else []) if h["corregible"] and h["id"] in E["correcciones"]]


def banner_de(plan):
    r = plan["reporte"]
    destinos = ([f"«{plan['titulo']}», pestaña «{plan['pestana']}», filas {plan['inicio']} a {plan['total']}"] if plan["w06"] else []) \
        + (["el estadístico"] if plan["w07"] else [])
    cabeza = f"{r['dia']} · {r['fecha']:%d/%m/%Y}  →  "
    if destinos:
        return cabeza + ("se sobrescribirá en " if plan.get("reescribe06") or plan.get("reescribe07") else
                         "se reemplazará en " if any(v == "distinto" for v in estados_de(plan).values()) else "se escribirá en ") \
            + " y en ".join(destinos) + (f"  ·  y {len(plan['corr'])} corrección(es) del estadístico" if plan.get("corr") else "")
    existentes = [v for v in estados_de(plan).values() if v]
    if plan.get("corr"):
        return cabeza + f"el día no se escribe; solo harás {len(plan['corr'])} corrección(es) en el estadístico"
    if existentes and all(v == "igual" for v in existentes):
        return cabeza + "ya está todo escrito y es igual al reporte"
    return cabeza + "no se escribirá nada por ahora"


def html_hoja06(plan):
    r = plan["reporte"]
    escrito = plan.get("escrito", False)
    texto_chip, tipo_chip = chip_de(plan, "06", escrito)
    c = H.cabecera("Estatus de tarjetas", "FF-GS-FO-06", texto_chip, tipo_chip,
                   (f"Día {r['dia']} · filas {plan['inicio']} a {plan['total']} de «{plan['titulo']}»" if not plan.get("ya06")
                    else f"Día {r['dia']} · ya está en «{plan['titulo']}», filas {plan['inicio']} a {plan['total']}"))
    if plan.get("ya06"):
        cm = plan["cmp06"]
        if cm["igual"]:
            if escrito and plan.get("w06"):
                c += '<p class="sub">Listo: el día se escribió de nuevo con los mismos datos y la hoja sigue igual al reporte.</p>'
            else:
                c += '<p class="sub">Lo que está en la hoja es exactamente igual al reporte: no hace falta escribir nada.</p>'
                if cm.get("reescribible") and not escrito:
                    c += control_decision("06", "Si eliges «Escribir de nuevo», se sobrescribe con los mismos datos.", "Escribir de nuevo")
        elif escrito and plan.get("w06"):
            c += '<p class="sub">Corregido: ahora el día en la hoja quedó igual al reporte.</p>'
        else:
            c += '<p class="sub">Esto es distinto entre tu hoja y el reporte:</p>' + "".join(f"<p>•  {esc(d)}</p>" for d in cm["diferencias"][:10])
            if len(cm["diferencias"]) > 10:
                c += f'<p class="nota">…y {len(cm["diferencias"]) - 10} {"diferencia" if len(cm["diferencias"]) - 10 == 1 else "diferencias"} más.</p>'
            if cm["reemplazable"]:
                c += control_decision("06", "«Reemplazar» corrige solo esos números en tu hoja; no mueve ni borra filas.")
            else:
                c += H.aviso("aviso", "Faltan o sobran BIN respecto al reporte. No lo reemplazo solo para no dañar tu hoja: corrígelo a mano (botón «Abrir hoja»).")
        c += '<p class="nota">Así quedaría el día según el reporte</p>'
    filas, n = plan["filas"], len(plan["filas"])
    colores = plan.get("colores_vista", {})
    hd = tema.HOJA

    def td(t, bg, fg=hd["texto"], neg=False, rs=1, cs=1):
        return (f'<td style="background:{bg};color:{fg};{"font-weight:700;" if neg else ""}" '
                f'{f"rowspan={rs}" if rs > 1 else ""} {f"colspan={cs}" if cs > 1 else ""}>{esc(t)}</td>')
    rows = ["<tr>" + "".join(f'<th style="background:{VERDE_HOJA}">{esc(t)}</th>' for t in ENCABEZADOS_HOJA) + "</tr>"]
    for i, f in enumerate(filas):
        color = colores.get(f["grupo"]) or GRIS_SIN_COLOR
        fila = ""
        if i == 0:
            fila += td(r["dia"], "#FFFFFF", rs=n) + td(f"{r['fecha']:%d/%m/%Y}", "#FFFFFF", rs=n)
        fila += (td(f["rental"], GRIS_RENTAL) + td(f["nombre"], color) + td(f["modelo"], color)
                 + td(str(f["mag"]) if f["mag"] is not None else "", color) + td(str(f["clips"]), "#FFFFFF")
                 + td(rc.hms(f["seg"]), "#FFFFFF") + td(f"{f['gb']:,.2f}", "#FFFFFF") + td("", "#FFFFFF"))
        rows.append("<tr>" + fila + "</tr>")
    rows.append("<tr>" + td("", VERDE_HOJA) + td("", VERDE_HOJA, cs=5) + td(str(sum(f["clips"] for f in filas)), VERDE_HOJA, "#FFFFFF", True)
                + td(rc.hms(sum(f["seg"] for f in filas)), VERDE_HOJA, "#FFFFFF", True)
                + td(f"{sum(f['gb'] for f in filas):,.2f}", VERDE_HOJA, "#FFFFFF", True) + td("", VERDE_HOJA) + "</tr>")
    c += f'<div class="desliza"><table class="hoja">{"".join(rows)}</table></div>'
    return H.tarjeta(c)


def html_estadistico(plan):
    escrito = plan.get("escrito", False)
    prop, error = plan.get("est"), plan.get("est_error")
    if error or not prop:
        return H.tarjeta(H.cabecera("Estadístico", "FF-GS-FO-07", "no se pudo preparar", "aviso")
                         + H.aviso("aviso", f"No pude preparar el estadístico: {error}\nEl estatus de tarjetas se puede escribir igual."))
    texto, tipo = chip_de(plan, "07", escrito)
    color_cambio = "amarillo" if (prop.get("vista", {}).get("datos") or {}).get("fondos") else "verde"
    c = H.cabecera("Estadístico", "FF-GS-FO-07", texto, tipo, f"Día {prop['dia']} · fila «{prop['texto_dia']}» · lo {color_cambio} es lo que cambia")
    for hoja, rotulo in (("datos", "Datos Generales"), ("resumen", "Resumen General")):
        bloque = prop["vista"].get(hoja)
        if bloque:
            c += f'<p class="nota">{rotulo}</p>' + H.cuadricula(bloque, 62 if hoja == "datos" else 90)
    if not prop["cambios"]:
        c += '<p class="sub">' + ("Lo que está en el estadístico es exactamente igual al reporte: no hace falta escribir nada."
                                  if prop.get("tenia_datos") else "Estos datos ya están en el estadístico: no hay nada que cambiar.") + "</p>"
        if prop.get("tenia_datos") and not escrito:
            c += control_decision("07", f"Este día ya está escrito en el estadístico (fila «{prop['texto_dia']}»). Si eliges «Escribir de nuevo», "
                                        "se sobrescribe con los mismos datos.", "Escribir de nuevo")
    elif prop.get("tenia_datos") and not escrito:
        c += control_decision("07", "El día ya está igual en «Datos Generales»; solo cambiaría el «Resumen General» (en " + color_cambio + "). ¿Lo actualizo?"
                              if solo_resumen(plan) else
                              "Este día ya tiene datos en el estadístico y son distintos al reporte (en " + color_cambio + ", lo que cambiaría).")
    for av in prop["avisos"]:
        if "ya tiene datos en el estadístico" not in av:
            c += H.aviso("aviso", av)
    return H.tarjeta(c)


def html_plan():
    plan = E["plan"]
    seleccionar(plan)
    r = plan["reporte"]
    escrito = plan.get("escrito", False)
    if not escrito:
        hay_aviso = any(t == "aviso" for t, _ in plan["validacion"]) or plan["avisos"] or plan["sin_leer"] or plan.get("est_error")
        checks = [("info", f"Se agregó el rollo nuevo «{n}» a tus ajustes.") for n in plan["nuevos"]]
        if plan["sin_leer"]:
            muestra = " | ".join(plan["sin_leer"][:3]) + ("…" if len(plan["sin_leer"]) > 3 else "")
            checks.append(("aviso", f"No pude leer {len(plan['sin_leer'])} {'línea' if len(plan['sin_leer']) == 1 else 'líneas'} de la tabla de BIN del PDF, así que podría faltar algo en el resultado: {muestra}"))
        est_ = estados_de(plan)
        if plan.get("ya06"):
            checks.append(("info", f"{r['dia']} ya está en «{plan['titulo']}»: "
                           + ("es exactamente igual al reporte." if est_["06"] == "igual" else "tiene diferencias con el reporte (mira arriba).")))
        checks += list(plan["validacion"]) + [("aviso", a_) for a_ in plan["avisos"]]
        hay_destino = plan["w06"] or plan["w07"]
        cr = plan.get("cruce")
        if cr and cr["hallazgos"]:
            checks.append(("aviso", f"Hay {len(cr['hallazgos'])} {'incongruencia' if len(cr['hallazgos']) == 1 else 'incongruencias'} entre tus dos hojas (más abajo). Revísalas: no se corrige nada sin que lo elijas."))
        existentes = [v for v in est_.values() if v]
        if not hay_destino and plan["corr"]:
            checks.append(("ok", "No se escribirá el día; solo las correcciones que elegiste."))
        elif not hay_destino and existentes and all(v == "igual" for v in existentes):
            checks.append(("ok", "Todo lo que ya estaba escrito es igual al reporte: no hay nada que escribir."))
        elif not hay_destino and "distinto" in existentes:
            checks.append(("aviso", "Ya hay datos distintos al reporte. Elige arriba para cada hoja: «Dejar como está» o «Reemplazar»."))
        elif not hay_destino:
            checks.append(("aviso", "Marca abajo qué hoja quieres llenar (estatus de tarjetas, estadístico o las dos)."))
        else:
            checks.append(("aviso" if hay_aviso else "ok",
                           "Revisa los avisos antes de escribir." if hay_aviso else "Todo cuadra con el PDF. Si lo que ves está bien, pulsa «Escribir»."))
        banner, color_b = banner_de(plan), ""
    else:
        banner, checks = E["banner"], E["checks"]
    out = [f'<div class="banner">{esc(banner)}</div>']
    if not plan.get("solo"):
        out.append(html_hoja06(plan))
    if plan.get("est") or plan.get("est_error"):
        out.append(html_estadistico(plan))
    if plan.get("cruce") is not None or plan.get("cruce_error"):
        out.append(html_incongruencias(plan.get("cruce"), plan.get("cruce_error"), "reg", E["correcciones"], escrito,
                                       nota_error="El día se puede escribir igual."))
    if checks:
        out.append(H.tarjeta("".join(H.aviso(t, x) for t, x in checks), "Comprobaciones"))
    if not escrito:
        if not plan.get("solo") or plan.get("est"):
            out.append(H.tarjeta((H.casilla("Estatus de tarjetas (FO-06)", E["var06"], "casilla", cual="06") if not plan.get("solo") else "")
                                 + (H.casilla("Estadístico (FO-07)", E["var07"], "casilla", cual="07") if plan.get("est") else ""), "Qué llenar"))
    return '<div id="resultado">' + "".join(out) + "</div>"


def barra_plan():
    """La barra fija de abajo en «Registrar día»: resume qué se va a escribir y tiene el botón (siempre a la mano)."""
    plan = E["plan"]
    if not plan:
        return None
    if plan.get("escrito"):
        return f'<button class="btn acento" {a("nuevo_dia")}>Registrar otro día</button>'
    seleccionar(plan)
    r = plan["reporte"]
    cosas = (["estatus de tarjetas"] if plan["w06"] else []) + (["estadístico"] if plan["w07"] else []) \
        + ([f"{len(plan['corr'])} corrección(es)"] if plan["corr"] else [])
    hay = bool(cosas)
    txt = f"{r['dia']} · se escribirá: " + " + ".join(cosas) if hay else f"{r['dia']} · nada por escribir con lo que está marcado"
    return (f'<p class="resumen-accion">{esc(txt)}</p>'
            f'<button class="btn acento" {a("escribir")} {"" if hay else "disabled"}>Escribir en las hojas</button>')


def nuevo_dia(p):
    E.update(pdf=None, pdf_texto=None, plan=None, formulario=None, escrito=False, banner=None, checks=[])
    E["decision"] = {"06": "dejar", "07": "dejar"}
    E["correcciones"] = set()
    return pagina_registrar()


def html_formulario_rollo(f):
    """Formulario para un rollo nuevo o para editar uno (igual de completo que el del Mac)."""
    base = f["base"]
    tipo = base.get("tipo", "camara")
    sin_mag = not (base.get("ciclo_mag") or rc.MAG_POR_TIPO.get(tipo))
    mag = base.get("ciclo_mag") or rc.MAG_POR_TIPO.get(tipo) or 6
    usados = {u.upper() for u in f.get("usados", []) if u}
    color = base.get("color", "")
    if "color" not in base:
        libres = [c for c in tema.PALETA_ROLLOS if c.upper() not in usados]
        color = (libres or tema.PALETA_ROLLOS)[0]
    nombres_pos = f.get("nombres_posicion")
    s = f'<form class="formulario" {a(f["accion"], **f.get("datos", {}))} data-ev="submit">'
    s += f'<h3>{esc(f["titulo"])}</h3>'
    if f.get("ayuda"):
        s += f'<div class="estado aviso"><span class="ico">⚠</span><span>{esc(f["ayuda"])}</span></div>'
    if f.get("error"):
        s += H.aviso("error", f["error"])
    if nombres_pos is not None:
        ops = ["Al principio"] + [f"Después de {x}" for x in nombres_pos]
        pos = f.get("posicion")
        if pos is None:
            idx = f.get("pos_camara") if (tipo == "camara" and f.get("pos_camara") is not None) else len(nombres_pos)
            pos = min(idx, len(ops) - 1)
        s += '<label>¿En qué lugar va?<select name="posicion">' + "".join(
            f'<option value="{i}" {"selected" if i == pos else ""}>{esc(o)}</option>' for i, o in enumerate(ops)) + "</select></label>"
        s += '<p class="nota">Es el orden de las filas de cada día en la hoja.</p>'
    s += f'<label class="casilla"><input type="checkbox" name="avisar" {"checked" if base.get("avisar_si_falta") else ""}><span class="caja"></span><span class="txt">Avisarme si este rollo no viene en un PDF</span></label>'
    s += '<label>Tipo de rollo</label><div class="radios">' + "".join(
        f'<label class="radio"><input type="radio" name="tipo" value="{k}" {"checked" if k == tipo else ""} data-form="tipo"><span>{esc(t)}</span></label>'
        for k, t in TIPOS_FORM if k in ("camara", "sonido") or k == tipo) + "</div>"
    s += f'<label data-solo="camara">Letra de la cámara<input name="letra" maxlength="1" value="{esc(base.get("letra", ""))}" autocapitalize="characters"></label>'
    s += '<p class="nota" data-solo="camara">una sola letra, ej. M</p>'
    s += f'<label data-solo="otro">El BIN empieza con<input name="otro" value="{esc(base.get("otro", ""))}"></label><p class="nota" data-solo="otro">ej. D###_   (# = un número)</p>'
    s += f'<label>Nombre del rollo<input name="nombre" value="{esc(base.get("nombre", ""))}" placeholder="se llena solo"></label>'
    s += f'<label>Rental<input name="rental" value="{esc(base.get("rental", ""))}" placeholder="ej. CONGO"></label>'
    s += f'<label>Modelo<input name="modelo" value="{esc(base.get("modelo", ""))}" placeholder="ej. ARRI ALEXA 35"></label>'
    s += (f'<label>Tarjetas (# Mag)<input name="mag" type="number" min="1" max="30" value="{mag}"></label>'
          f'<label class="casilla"><input type="checkbox" name="sin_mag" {"checked" if sin_mag else ""}><span class="caja"></span><span class="txt">No lleva # Mag</span></label>')
    s += '<label>Color en la hoja</label><div class="colores">'
    for hx in tema.PALETA_ROLLOS:
        ocupado = hx.upper() in usados
        s += (f'<label class="color {"ocupado" if ocupado else ""}"><input type="radio" name="color" value="{hx}" {"checked" if hx.upper() == color.upper() else ""}>'
              f'<span style="background:{hx}">{"✕" if ocupado else ""}</span></label>')
    s += (f'<label class="color"><input type="radio" name="color" value="" {"checked" if not color else ""}><span class="hoja-color">El de la hoja</span></label></div>')
    s += f'<label>Otro color (#RRGGBB)<input name="color_otro" value="{esc(color if color and color.upper() not in {c.upper() for c in tema.PALETA_ROLLOS} else "")}" placeholder="#E24A38"></label>'
    s += (f'<div class="botones"><button type="button" class="btn" {a("cancelar_formulario")}>Cancelar</button>'
          f'<button type="submit" class="btn acento">Guardar</button></div></form>')
    return s


def leer_formulario_rollo(p, f):
    """Valida lo que se llenó en el formulario (igual que «guardar» del Mac). Devuelve (valor, error)."""
    tipo = p.get("tipo", "camara")
    try:
        patrones = rc.patrones_de_tipo(tipo, p.get("letra", ""), p.get("otro", ""))
    except ErrorRegistro as e:
        return None, str(e)
    nombre = (p.get("nombre") or "").strip()
    if not nombre:
        if tipo == "camara":
            l = (p.get("letra") or "").strip().upper()
            nombre = f"Cámara {l}" if len(l) == 1 and l.isalpha() else ""
        elif tipo == "otro":
            pats = rc.normalizar_patrones(p.get("otro", ""))
            m = re.match(r"^([A-Za-z])(?![A-Za-z])", pats[0]) if pats else None
            nombre = f"Cámara {m.group(1).upper()}" if m else ""
        else:
            nombre = rc.NOMBRE_POR_TIPO.get(tipo, "")
    rental, modelo = (p.get("rental") or "").strip(), (p.get("modelo") or "").strip()
    if not (nombre and rental and modelo):
        return None, "Llena el nombre, el rental y el modelo."
    color = (p.get("color_otro") or "").strip().upper() or (p.get("color") or "")
    if color and not color.startswith("#"):
        color = "#" + color
    if color and not re.fullmatch(r"#[0-9A-F]{6}", color.upper()):
        return None, "Ese color no es válido. Debe verse así: #E24A38 (6 letras o números)."
    color = color.upper()
    if color and color in {u.upper() for u in f.get("usados", []) if u}:
        return None, "Ese color ya lo tienes aplicado a otro rollo. Elige otro color (los que tienen ✕ ya están usados)."
    def clave(pt):
        letra = rc.letra_de_camara([pt])
        return "cam:" + letra if letra else pt
    ya = {clave(pt) for pt in f.get("patrones_usados", [])}
    repetidos = [pt for pt in patrones if clave(pt) in ya]
    if repetidos:
        return None, f"Ya tienes un rollo que reconoce «{repetidos[0]}». Edítalo en lugar de agregar otro."
    ciclo = None
    if not p.get("sin_mag"):
        txt = str(p.get("mag") or "").strip()
        if not txt.isdigit() or int(txt) < 1:
            return None, "Escribe cuántas tarjetas rotan (1, 2, 3…) o marca «No lleva # Mag»."
        ciclo = int(txt)
    valor = {"nombre": nombre, "patrones": patrones, "rental": rental, "modelo": modelo, "ciclo_mag": ciclo,
             "color": color, "avisar_si_falta": bool(p.get("avisar"))}
    if p.get("posicion") not in (None, ""):
        valor["posicion"] = int(p["posicion"])
    return valor, None


def pagina_registrar(p=None):
    if E["formulario"] and E.get("pagina_form", "registrar") == "registrar":
        return {"pagina": "registrar", "html": html_formulario_rollo(E["formulario"])}
    cfg_ok = True
    try:
        cfg = rc.cargar_config()
    except ErrorRegistro as e:
        return {"pagina": "registrar", "html": H.vacia("No pude abrir tu configuración", str(e), tipo="error")}
    est = rc.estadistico_para_pestana(cfg, cfg["hoja"]["pestana"])
    if not (cfg["hoja"]["enlace"] or est.get("enlace")):
        return {"pagina": "registrar", "html": H.vacia("Primero conecta una hoja",
                "Conecta al menos una hoja de Google en «Hojas conectadas» para poder registrar un día.", H.boton("Ir a Hojas conectadas", "ir", "acento", pagina="hojas"))}
    if not rg.estado_cuenta()["conectado"]:
        return {"pagina": "registrar", "html": H.vacia("Conecta tu cuenta de Google", "Para leer y escribir en tus hojas necesito tu cuenta de Google.",
                '<button class="btn acento" data-js="conectar">Conectar con Google</button>', "aviso")}
    plan = E["plan"]
    hecho = bool(plan and plan.get("escrito"))
    paso = 3 if (plan and not hecho) else 1 if not E["pdf"] and not plan else 2
    if hecho:
        paso = 4
    etiquetas = ("Elegir PDF", "Revisar", "Escribir")
    st = '<div class="pasos-reg">' + "".join(
        f'<div class="paso-reg {"hecho" if i < paso else "on" if i == paso else ""}"><b>{"✓" if i < paso else i}</b>{t}</div>'
        for i, t in enumerate(etiquetas, start=1)) + "</div>"
    icono = ICO_PDF
    if E["pdf"] and not hecho:
        zona = (f'<div class="pdf-zona listo"><div class="ico-pdf">{icono}</div><div class="nombre">{esc(E["pdf"])}</div>'
                '<p class="nota">El PDF se lee aquí, en tu teléfono; no sale de él.</p>'
                '<button class="btn mini" data-js="elegir_pdf">Cambiar PDF</button></div>')
        zona += f'<button class="btn acento grande-btn" {a("revisar", nuevo=True)} style="margin-top:0">{"Revisar de nuevo" if plan else "Revisar"}</button>'
    elif not plan:
        zona = (f'<div class="pdf-zona"><div class="ico-pdf">{icono}</div><div class="nombre">Elige el PDF «Shooting Day» de Silverstack</div>'
                '<p class="nota">Lo leo aquí en tu teléfono (el PDF no sale de él), te muestro cómo quedaría en tus hojas y solo escribo cuando tú confirmes.</p>'
                '<button class="btn acento" data-js="elegir_pdf">Elegir PDF</button></div>')
    else:
        zona = ""
    cuerpo = html_plan() if plan else ""
    return {"pagina": "registrar", "html": st + zona + cuerpo, "barra": barra_plan()}


def pdf_elegido(p):
    E.update(pdf=p["nombre"], pdf_texto=rd_traducir(p["texto"]), plan=None, formulario=None, escrito=False)
    E["decision"] = {"06": "dejar", "07": "dejar"}
    E["correcciones"] = set()
    return pagina_registrar()


def rd_traducir(texto):
    return texto.translate(str.maketrans({**rd.PUA, "": "-"}))


def _resolver_sin_reconocer(cfg, reporte, nuevos):
    """Si el PDF trae un BIN que no está en los ajustes, devuelve el formulario que pide configurarlo (o None si todo se reconoce)."""
    _, sin = rc.clasificar(reporte, cfg)
    if not sin:
        return None
    nombre = sorted(b["nombre"] for b in sin)[0]
    es_audio = bool(next(b for b in sin if b["nombre"] == nombre).get("audio"))
    tipo, letra, otro = rc.adivinar_tipo(nombre)
    if es_audio and tipo != "sonido":
        tipo, letra, otro = "otro", "", rc.patron_corto(nombre)
    parecidos = sorted(b["nombre"] for b in sin if rc.adivinar_tipo(b["nombre"]) == rc.adivinar_tipo(nombre) and bool(b.get("audio")) == es_audio)
    que = rc.que_es_rollo(tipo, letra, nombre)
    if es_audio and tipo == "otro":
        que = "AUDIO (el reporte lo lista como grabación de audio). Llámalo «Sonido» para que cuente como audio"
    ejemplos = ", ".join(parecidos[:3]) + ("…" if len(parecidos) > 3 else "")
    ayuda = (f"Este PDF trae {que}, y todavía no está en tus rollos.\nBIN encontrados: {ejemplos}\n"
             "Complétalo para agregarlo: después te muestro cómo quedaría en la hoja antes de escribir.")
    idx_cam = [i for i, g in enumerate(cfg["grupos"]) if rc.letra_de_camara(g["patrones"])]
    base = {"tipo": tipo, "letra": letra, "otro": otro}
    if es_audio and tipo == "otro":
        base["nombre"] = "Sonido"
    return {"accion": "guardar_rollo_nuevo", "titulo": "Apareció un rollo nuevo en el PDF", "base": base, "ayuda": ayuda,
            "nombres_posicion": [g["nombre"] for g in cfg["grupos"]], "pos_camara": (idx_cam[-1] + 1) if idx_cam else 0,
            "usados": [g["color"] for g in cfg["grupos"]], "patrones_usados": [p for g in cfg["grupos"] for p in g["patrones"]],
            "datos": {"nombre_bin": nombre, "es_audio": es_audio, "ejemplos": ejemplos}}


def guardar_rollo_nuevo(p):
    f = E["formulario"]
    valor, error = leer_formulario_rollo(p, f)
    if error:
        f["error"], f["base"] = error, {**f["base"], **{k: p.get(k, "") for k in ("tipo", "letra", "otro", "nombre", "rental", "modelo")}}
        return pagina_registrar()
    cfg = rc.cargar_config()
    lugar = valor.pop("posicion", len(cfg["grupos"]))
    prueba = {**cfg, "grupos": list(cfg["grupos"])}
    g = rc.agregar_grupo(prueba, **valor)
    prueba["grupos"].remove(g)
    prueba["grupos"].insert(lugar, g)
    nombre, es_audio = f["datos"]["nombre_bin"], f["datos"]["es_audio"]
    if rc.grupo_de(nombre, prueba, audio=True if es_audio else None) is not g:
        f["error"] = f"Con lo que elegiste no se reconoce «{nombre}». Inténtalo de nuevo."
        return pagina_registrar()
    rc.guardar_config(prueba)
    E.setdefault("nuevos_tmp", []).append(g["nombre"])
    E["formulario"] = None
    return revisar({})


def colores_iniciales(cfg, hist, filas):
    usados = {f["grupo"] for f in filas}
    colores = {g["id"]: g["color"] for g in cfg["grupos"] if g["color"] and g["id"] in usados}
    pendientes = {g["id"]: hist["ultima_fila"][g["id"]] for g in cfg["grupos"]
                  if g["id"] in usados and not g["color"] and hist["ultima_fila"].get(g["id"])}
    return colores, pendientes


def revisar(p):
    """Lee el PDF y las hojas conectadas y arma lo que quedaría en cada una (igual que «revisar» del Mac)."""
    if not E["pdf"]:
        return pagina_registrar()
    nuevos = E.get("nuevos_tmp", [])
    try:
        cfg = rc.cargar_config()
        est = rc.estadistico_para_pestana(cfg, cfg["hoja"]["pestana"])
        tiene06, tiene07 = bool(cfg["hoja"]["enlace"]), bool(est.get("enlace"))
        if not (tiene06 or tiene07):
            raise ErrorRegistro("Primero conecta al menos una hoja de Google (botón «Cambiar…»).")
        sid = rg.id_de_enlace(cfg["hoja"]["enlace"]) if tiene06 else None
    except ErrorRegistro as e:
        return _con_mensaje(pagina_registrar(), str(e), "aviso")
    pestana, solo = cfg["hoja"]["pestana"], not tiene06
    if p.get("nuevo"):
        E["decision"] = {"06": "dejar", "07": "dejar"}
        E["correcciones"] = set()
    E["plan"] = None
    try:
        texto = E["pdf_texto"]
        reporte = rc.leer_reporte(E["pdf"], texto)
        servicio = rg.conectar()
        datos = {}
        if tiene06:
            datos["info"] = rg.info_completa(servicio, sid, pestana)
            datos["valores"] = rg.leer_hoja(servicio, sid, pestana)
        if tiene07:
            datos["est_grids"], datos["est_error"] = _leer_estadistico(servicio, est)
        if tiene06 and tiene07 and datos.get("est_grids"):
            try:
                datos["valores_reales"] = rg.leer_hoja_valores(servicio, sid, pestana)
            except ErrorRegistro as e:
                datos["cruce_error"] = str(e)
        aviso_dia = rc.dia_por_fecha(reporte, datos.get("valores"), (datos.get("est_grids") or [None])[0])   # reporte solo con la fecha
        if aviso_dia:
            reporte["avisos_lectura"] = [aviso_dia] + list(reporte.get("avisos_lectura") or [])
        if tiene06:
            problema_unidad = rc.revisar_unidad(reporte, pestana)
            if problema_unidad:
                raise ErrorRegistro(problema_unidad)
        formulario = _resolver_sin_reconocer(cfg, reporte, nuevos)
        if formulario:
            E["formulario"], E["pagina_form"] = formulario, "registrar"
            return pagina_registrar()
        pendientes, motivo06, hist = {}, "", None
        if not solo:
            info, valores = datos["info"], datos["valores"]
            E["titulo"] = info["titulo"]
            try:
                hist = rc.leer_historial(valores, cfg)
            except ErrorRegistro as e06:
                if not tiene07:
                    raise
                hist, motivo06 = None, str(e06)
        cfg2 = cfg
        if solo or hist is None:
            filas, avisos = rc.armar_filas(reporte, cfg2, {"ultimo_mag": {}})
            if motivo06:
                avisos = [f"No pude preparar el estatus de tarjetas (FO-06): {motivo06} Solo se puede escribir el estadístico (FO-07); "
                          "el estatus de tarjetas no se toca."] + avisos
            plan = {"solo": True, "cfg": cfg2, "filas": filas, "reporte": reporte, "avisos": avisos,
                    "validacion": rc.validar_contra_pdf(texto, filas), "nuevos": nuevos, "sin_leer": reporte["sin_leer"]}
        else:
            ya06 = reporte["dia"] in hist["dias"]
            hist = rc.leer_historial(valores, cfg2)
            filas, avisos = rc.armar_filas(reporte, cfg2, {"ultimo_mag": {}} if ya06 else hist)
            if ya06:
                cmp06 = rc.comparar_dia(valores, reporte, filas)
                for f_ in filas:
                    r_ = cmp06["filas_hoja"].get(f_["nombre"])
                    m_ = rc.celda_en(valores, r_, "mag") if r_ else None
                    if isinstance(m_, (int, float)) and not isinstance(m_, bool):
                        f_["mag"] = int(m_)
                for f_ in filas:
                    r_ = cmp06["filas_hoja"].get(f_["nombre"])
                    if r_:
                        pendientes.setdefault(f_["grupo"], r_)
                plan = {"ya06": True, "colores_vista": {}, "cmp06": cmp06, "cfg": cfg2, "filas": filas, "reporte": reporte, "avisos": avisos,
                        "validacion": rc.validar_contra_pdf(texto, filas), "titulo": info["titulo"], "pestana": pestana, "nuevos": nuevos,
                        "sin_leer": reporte["sin_leer"], "sid": sid, "sheet_id": info["sheet_id"], "inicio": cmp06["inicio"], "total": cmp06["total"] or cmp06["final"],
                        "solicitudes": rc.solicitudes_reemplazo(info["sheet_id"], cmp06["celdas"])}
            else:
                sol, inicio, _final, total = rc.construir_solicitudes(info["sheet_id"], reporte, filas, hist, cfg2, info["filas"], info.get("merges"))
                total = total or _final                    # hojas sin fila de total: la última fila escrita
                colores, pendientes = colores_iniciales(cfg2, hist, filas)
                plan = {"cfg": cfg2, "hist": hist, "filas": filas, "reporte": reporte, "avisos": avisos,
                        "validacion": rc.validar_contra_pdf(texto, filas), "solicitudes": sol, "inicio": inicio, "total": total, "sid": sid,
                        "pestana": pestana, "titulo": info["titulo"], "sheet_id": info["sheet_id"], "colores_vista": colores,
                        "nuevos": nuevos, "sin_leer": reporte["sin_leer"]}
                plan["avisos"] = list(plan["avisos"]) + rc.avisar_rollos_repetidos(valores, filas, cfg2)
        plan["avisos"] = rc.avisos_de_copias(reporte) + list(plan["avisos"])        # copias de seguridad: arriba, solo si faltan
        n_carpeta = int(reporte["dia"][1:])
        if reporte.get("fecha_dudosa"):
            plan["avisos"] = list(plan["avisos"]) + [
                f"La fecha que trae el reporte no es confiable (la ficha de Silverstack está sin llenar o la carpeta tiene la fecha mal escrita). "
                f"Usé el día en que se descargó: {reporte['fecha']:%d/%m/%Y}. Si no es la fecha de rodaje, corrígela antes de guardar."]
        if reporte.get("dia_rodaje") not in (None, 0, n_carpeta):
            plan["avisos"] = list(plan["avisos"]) + [
                f"El nombre de la carpeta dice día {n_carpeta}, pero el reporte dice «Shooting Day {reporte['dia_rodaje']:02d}». "
                "Usé el de la carpeta; revisa cuál es el número del día en tu hoja."]
        plan["cruce"], plan["cruce_error"] = None, datos.get("cruce_error")
        if datos.get("valores_reales") is not None and datos.get("est_grids"):
            try:
                plan["cruce"] = cc.cruzar(datos["valores_reales"], datos["est_grids"][0], cfg2, excluir_dias={cc.numero_de_dia(reporte["dia"])},
                                          agregar_dias=False)
            except Exception as e:
                plan["cruce_error"] = str(e)
        plan["est"], plan["est_error"] = _proponer_estadistico(cfg2, filas, reporte, datos.get("est_grids"))
        plan["est_error"] = datos.get("est_error") or plan["est_error"]
        if solo and not plan["est"]:
            raise ErrorRegistro("No pude preparar el estadístico: " + (plan["est_error"] or "no hay datos."))
        if pendientes or (plan.get("est") and tiene07):          # los colores reales de la hoja (se ven en la vista previa)
            try:
                if pendientes:
                    por_fila = rg.color_de_filas(servicio, sid, pestana, list(pendientes.values()))
                    plan.setdefault("colores_vista", {}).update({gid: por_fila[fila] for gid, fila in pendientes.items() if por_fila.get(fila)})
                prop = plan.get("est")
                if prop and tiene07:
                    for hoja, pest in (("datos", est.get("datos")), ("resumen", est.get("resumen"))):
                        b = prop["vista"].get(hoja)
                        if b and b.get("cols") and pest:
                            try:
                                mapa = rg.fondos(servicio, rg.id_de_enlace(est["enlace"]), pest, [f["n"] for f in b["filas"]], b["cols"])
                                if mapa:
                                    prop["vista"][hoja]["fondos"] = mapa
                            except ErrorRegistro:
                                pass
            except ErrorRegistro:
                pass
        plan["escrito"] = False
        E["plan"], E["nuevos_tmp"] = plan, []
        resp = pagina_registrar()
        resp["scroll"] = "#resultado"
        return resp
    except Exception as e:
        E["nuevos_tmp"] = []
        return _con_mensaje(pagina_registrar(), texto_error(e, "no pude terminar. No escribí nada en tus hojas."), "error")


def _con_mensaje(resp, texto, tipo):
    resp["html"] = H.aviso(tipo, texto) + resp["html"]
    return resp


def _leer_estadistico(servicio, est):
    try:
        pestanas = [est["datos"]] + ([est["resumen"]] if est.get("resumen") else [])
        return rg.leer_cuadriculas(servicio, rg.id_de_enlace(est["enlace"]), pestanas), None
    except ErrorRegistro as e:
        return None, str(e)


def _proponer_estadistico(cfg, filas, reporte, grids):
    if grids is None:
        return None, None
    sonido = {g["id"] for g in cfg["grupos"] if rc.grupo_es_sonido(g)}
    try:
        return ec.proponer(grids[0], grids[1] if len(grids) > 1 else None, filas, reporte,
                           lambda f: bool(f.get("audio")) or f["grupo"] in sonido, dedicado=len(rc.estadisticos(cfg)) > 1), None
    except ErrorRegistro as e:
        return None, str(e)


def _escribir_estadistico(servicio, est, prop):
    sid = rg.id_de_enlace(est["enlace"])
    pestana = {"datos": est["datos"], "resumen": est.get("resumen", "")}
    celdas = [(pestana[ch["hoja"]], ch["celda"]) for ch in prop["cambios"]]
    if celdas:
        # se compara cada celda donde está AHORA (antes de crear columnas/filas); las celdas nuevas no se comparan
        mirar = [((pestana[ch["hoja"]], ch["celda_antes"]), ch) for ch in prop["cambios"] if ch.get("celda_antes", ch["celda"])]
        mirar = [((p_, c_ or ch["celda"]), ch) for (p_, c_), ch in mirar]
        actuales = rg.leer_celdas(servicio, sid, [c for c, _ch in mirar]) if mirar else {}
        if any(not ec.igual(actuales.get(c, ""), ch["antes"]) for c, ch in mirar):
            raise ErrorRegistro("El estadístico cambió mientras tanto (alguien editó esas celdas). No escribí nada en él: pulsa «Revisar» otra vez.")
        if prop.get("estructura"):        # cámaras nuevas (columna y fila del Resumen) y días sin fila: primero la forma de la hoja
            rg.aplicar_estructura(servicio, sid, pestana, prop["estructura"])
        rg.escribir_celdas(servicio, sid, [(p, c, ch["nuevo"]) for (p, c), ch in zip(celdas, prop["cambios"])])
    try:
        total = prop["lectura_total"]
        leidos = rg.leer_celdas(servicio, sid, celdas + ([(est["datos"], total)] if total else []))
        por_celda = {(ch["hoja"], ch["celda"]): leidos.get(c) for c, ch in zip(celdas, prop["cambios"])}
        return ec.comprobar(prop, por_celda, leidos.get((est["datos"], total)) if total else None)
    except Exception as e:
        return [("aviso", f"Escribí el estadístico, pero no pude comprobarlo leyéndolo de vuelta: {e}")]


def _aplicar_correcciones(servicio, est, hallazgos):
    """Estadístico, estatus de tarjetas o el día que faltaba: cruce_core.aplicar_correcciones (igual en el Mac)."""
    return cc.aplicar_correcciones(servicio, rg, est, rc.cargar_config().get("hoja"), hallazgos)


def _aplicar_errores_escritura(servicio, cfg, errores):
    sid = rg.id_de_enlace(cfg["hoja"]["enlace"])

    def pestana(e):
        return e.get("unidad") or cfg["hoja"]["pestana"]
    claves = [(pestana(e), e["celda"]) for e in errores]
    actuales = rg.leer_celdas(servicio, sid, claves)
    if any(str(actuales.get(k, "")).strip() != e["valor"] for k, e in zip(claves, errores)):
        raise ErrorRegistro("El estatus de tarjetas cambió mientras tanto (alguien editó esas celdas). No corregí nada: pulsa «Actualizar».")
    rg.escribir_celdas(servicio, sid, [(pestana(e), e["celda"], e["nuevo"]) for e in errores])
    leidos = rg.leer_celdas(servicio, sid, claves)
    salida = []
    for k, e in zip(claves, errores):
        v = leidos.get(k, "")
        bien = isinstance(v, (int, float)) and not isinstance(v, bool) and abs(float(v) - float(e["nuevo"])) < 1e-6
        salida.append(("ok", f"Corregida la celda {e['celda']} ({e['dia']} · {e['bin']}): ahora dice {e['nuevo_txt']}.") if bien else
                      ("aviso", f"Escribí {e['nuevo_txt']} en {e['celda']}, pero al leerla de vuelta no quedó como número "
                                "(¿esa columna está en formato de texto?). Revísala en la hoja."))
    return salida


def escribir(p):
    """Primer paso: pregunta (igual que el cuadro «¿Escribo…?» del Mac). El segundo paso, escribir_ok, escribe de verdad."""
    plan = E["plan"]
    if not plan or plan.get("escrito"):
        return pagina_registrar()
    seleccionar(plan)
    r = plan["reporte"]
    w06, prop, corr = plan["w06"], (plan["est"] if plan["w07"] else None), plan.get("corr") or []
    if prop:
        prop = dict(prop, cambios=prop["cambios_todos"]) if plan.get("reescribe07") else prop
    partes = [] if not w06 else [
        (f"{len(plan['cmp06']['celdas_todas'])} {'celda' if len(plan['cmp06']['celdas_todas']) == 1 else 'celdas'} del día que ya estaba y es igual, en las filas {plan['inicio']} a {plan['total']} de "
         f"«{plan['titulo']}» (se sobrescriben con los mismos datos)") if plan.get("reescribe06") else
        (f"{len(plan['cmp06']['celdas'])} {'celda' if len(plan['cmp06']['celdas']) == 1 else 'celdas'} del día que ya estaba, en las filas {plan['inicio']} a {plan['total']} de «{plan['titulo']}» "
         f"(reemplazo lo distinto)") if plan.get("ya06") else
        f"el día en las filas {plan['inicio']} a {plan['total']} de «{plan['titulo']}» (pestaña «{plan['pestana']}»)"]
    if prop:
        partes.append(f"{len(prop['cambios'])} {'celda' if len(prop['cambios']) == 1 else 'celdas'} del estadístico (fila «{prop['texto_dia']}»)")
    if not partes and not corr:
        return _con_mensaje(pagina_registrar(), "No hay nada marcado para escribir.", "info")
    texto_corr = ""
    if corr:
        texto_corr = (f"{len(corr)} corrección(es) del estadístico en días anteriores ("
                      + "; ".join(f"{h['texto_dia']}: " + ", ".join(f"{c['celda']} {c['antes_txt']} → {c['nuevo_txt']}" for c in h["celdas"]) for h in corr[:4])
                      + ("…" if len(corr) > 4 else "") + ")")
    pregunta = (f"¿Escribo {r['dia']}: " + " y ".join(partes) + (" y " if partes and corr else "") + texto_corr + "?") if partes \
        else f"¿Hago {texto_corr}? (El día {r['dia']} no se escribe.)"
    if plan.get("reescribe06") or plan.get("reescribe07"):
        pregunta += "\n\nOjo: este día YA está escrito y es igual al reporte. Escribirlo de nuevo sobrescribe las mismas celdas con los mismos datos."
    resp = pagina_registrar()
    resp["confirmar"] = {"titulo": "Escribir en Google Sheets", "texto": pregunta, "accion": "escribir_ok", "boton": "Escribir"}
    return resp


def escribir_ok(p):
    plan = E["plan"]
    if not plan:                                    # (p. ej. el proyecto cambió en el otro equipo mientras se confirmaba)
        return _con_mensaje(pagina_registrar(), "No escribí nada: el registro se reinició. Elige el PDF y revisa otra vez.", "aviso")
    if plan.get("escrito"):
        return pagina_registrar()
    seleccionar(plan)
    cfg = rc.cargar_config()
    est = rc.estadistico_para_pestana(cfg, cfg["hoja"]["pestana"])
    r = plan["reporte"]
    w06, prop, corr = plan["w06"], (plan["est"] if plan["w07"] else None), plan.get("corr") or []
    if prop and plan.get("reescribe07"):
        prop = dict(prop, cambios=prop["cambios_todos"])
    try:
        servicio = rg.conectar()
        fo06 = fo07 = fo_corr = None
        if w06 and plan.get("ya06"):
            valores = rg.leer_hoja(servicio, plan["sid"], plan["pestana"])
            if rc.comparar_dia(valores, r, plan["filas"])["celdas"] != plan["cmp06"]["celdas"]:
                raise ErrorRegistro("Tu hoja cambió mientras tanto (alguien editó ese día). No escribí nada. Pulsa «Revisar» otra vez.")
            rg.escribir(servicio, plan["sid"],
                        rc.solicitudes_reemplazo(plan["sheet_id"], plan["cmp06"]["celdas_todas"]) if plan.get("reescribe06") else plan["solicitudes"])
            try:
                despues = rc.comparar_dia(rg.leer_hoja(rg.conectar(), plan["sid"], plan["pestana"]), r, plan["filas"])
                fo06 = [("ok", "El día en la hoja quedó igual al reporte.") if despues["igual"] else
                        ("aviso", "Después de escribir quedan diferencias: " + "; ".join(despues["diferencias"][:4]))]
            except Exception as e:
                fo06 = [("aviso", f"Reemplacé lo distinto, pero no pude comprobarlo leyendo la hoja: {e}")]
        elif w06:
            valores = rg.leer_hoja(servicio, plan["sid"], plan["pestana"])
            hist = rc.leer_historial(valores, plan["cfg"])
            if hist["ultima_fila_con_datos"] != plan["hist"]["ultima_fila_con_datos"] or r["dia"] in hist["dias"]:
                raise ErrorRegistro("Tu hoja cambió mientras tanto (alguien agregó filas). No escribí nada. Pulsa «Revisar» otra vez.")
            rg.escribir(servicio, plan["sid"], plan["solicitudes"])
            try:
                esc_ = plan["hist"].get("escritura") or {}
                v, f = rg.leer_para_comprobar(rg.conectar(), plan["sid"], plan["pestana"], plan["inicio"], plan["total"] or esc_.get("final"))
                fo06 = rc.comparar_escritura(v, f, plan["filas"], r, plan["inicio"], plan["total"], esc_)
            except Exception as e:
                fo06 = [("aviso", f"Escribí el día, pero no pude comprobarlo leyendo la hoja: {e}")]
        if prop:
            try:
                fo07 = _escribir_estadistico(servicio, est, prop)
            except Exception as e:
                fo07 = [("aviso", ("El estatus de tarjetas ya quedó escrito, pero no" if fo06 else "No") + f" pude escribir el estadístico: {e}")]
        if corr:
            try:
                fo_corr = _aplicar_correcciones(servicio, est, corr)
            except Exception as e:
                fo_corr = [("aviso", f"No pude hacer las correcciones del estadístico: {e}")]
    except Exception as e:
        return _con_mensaje(pagina_registrar(), texto_error(e, "no pude escribir. Revisa tus hojas antes de volver a intentar."), "error")
    comprobacion = (fo06 or []) + [(t, "Estadístico: " + m) for t, m in (fo07 or [])] + list(fo_corr or [])
    todo_ok = all(t == "ok" for t, _ in comprobacion)
    donde = " y en ".join(([f"«{plan['titulo']}», pestaña «{plan['pestana']}», filas {plan['inicio']} a {plan['total']}"] if w06 else [])
                          + (["el estadístico"] if prop else []))
    if not donde:
        banner = (f"✔ {len(corr)} corrección(es) hechas en el estadístico" if todo_ok else "⚠ Se hicieron las correcciones del estadístico, pero revisa los avisos")
    else:
        banner = f"✔ {r['dia']} quedó escrito en {donde}" if todo_ok else f"⚠ {r['dia']} se escribió en {donde}, pero revisa los avisos"
    plan["escrito"] = True
    E.update(banner=banner, escrito=True,
             checks=comprobacion + ([("info", "Abre la hoja desde «Hojas conectadas» para verlo (te lleva a la fila donde empieza el día).")] if w06 else []))
    resp = pagina_registrar()
    resp["tras_escribir"] = True
    resp["scroll"] = "#resultado"
    E["resumen"] = None                  # el Resumen se pone al día con lo que se acaba de escribir
    E["pdf"] = E["pdf_texto"] = None
    return resp


# =============================================================================
# ACCIONES DEL RESUMEN Y DE LAS CASILLAS
# =============================================================================
def _repintar(clave=None):
    return pagina_registrar() if clave == "reg" else pagina_resumen()


def unidad(p):
    E["vista_unidad"] = p["valor"]
    return pagina_resumen()


def marcar(p):
    clave = p.get("clave")
    destino = E["correcciones"] if clave == "reg" else E["corr_res"]
    valor = p.get("valor", True)
    for i in p["ids"]:
        (destino.add if valor else destino.discard)(i)
    return _repintar(clave)


def marcar_seg(p):
    destino = E["correcciones"] if p.get("clave") == "reg" else E["corr_res"]
    (destino.add if p["valor"] == "corregir" else destino.discard)(p["id"])
    return _repintar(p.get("clave"))


def alternar_vista(p):
    E["vistas"][(p["clave"], p["id"])] = not p.get("abierta")
    return _repintar(p["clave"])


def mas_hallazgos(p):
    E["n_hall"][p["clave"]] = max(POR_PAGINA_HALL, E["n_hall"].get(p["clave"], POR_PAGINA_HALL)) + POR_PAGINA_HALL
    return _repintar(p["clave"])


def decision(p):
    E["decision"][p["cual"]] = p["valor"]
    return pagina_registrar()


def casilla(p):
    E["var06" if p["cual"] == "06" else "var07"] = bool(p.get("valor"))
    return pagina_registrar()


def actualizar(p):
    return pagina_resumen({"forzar": True})


def corregir_cruce(p):
    m = E["resumen"] or {}
    cr = m.get("cruce")
    hall = [h for h in ((cr["hallazgos"] + cr.get("redondeos", [])) if cr else []) if h["corregible"] and h["id"] in E["corr_res"]]
    if not hall:
        return pagina_resumen()
    titulo_, texto_ = cc.texto_confirmar(hall)
    resp = pagina_resumen()
    resp["confirmar"] = {"titulo": titulo_, "texto": texto_, "accion": "corregir_cruce_ok", "boton": "Corregir"}
    return resp


def corregir_cruce_ok(p):
    m = E["resumen"] or {}
    cr = m.get("cruce")
    hall = [h for h in ((cr["hallazgos"] + cr.get("redondeos", [])) if cr else []) if h["corregible"] and h["id"] in E["corr_res"]]
    todos07 = rc.estadisticos(rc.cargar_config())
    try:
        servicio = rg.conectar()
        salida = []
        for j in sorted({h.get("est", 0) for h in hall}):
            if j < len(todos07):
                salida += _aplicar_correcciones(servicio, todos07[j], [h for h in hall if h.get("est", 0) == j])
        E["msg_corr"] = [("ok" if t == "ok" else "aviso", x) for t, x in salida]
    except Exception as e:
        E["msg_corr"] = [("aviso", texto_error(e, "no pude corregir."))]
    E["msg_conservar"] = True
    return pagina_resumen({"forzar": True})


def corregir_errores(p):
    m = E["resumen"] or {}
    err = [e for e in (m.get("errores_escritura") or []) if e["corregible"] and e["id"] in E["corr_res"]]
    if not err:
        return pagina_resumen()
    detalle = "\n".join(f"• fila {e['fila']} ({e['dia']} · {e['bin']}): «{e['valor']}» → {e['nuevo_txt']}" for e in err)
    resp = pagina_resumen()
    resp["confirmar"] = {"titulo": "Corregir el estatus de tarjetas",
                         "texto": f"¿Corrijo {len(err)} {'celda' if len(err) == 1 else 'celdas'} en el estatus de tarjetas?\n\n{detalle}\n\nAntes de escribir vuelvo a leer esas celdas; si alguien las cambió, no toco nada.",
                         "accion": "corregir_errores_ok", "boton": "Corregir"}
    return resp


def corregir_errores_ok(p):
    m = E["resumen"] or {}
    err = [e for e in (m.get("errores_escritura") or []) if e["corregible"] and e["id"] in E["corr_res"]]
    cfg = rc.cargar_config()
    try:
        salida = _aplicar_errores_escritura(rg.conectar(), cfg, err)
        E["msg_err"] = [("ok" if t == "ok" else "aviso", x) for t, x in salida]
    except Exception as e:
        E["msg_err"] = [("aviso", texto_error(e, "no pude corregir."))]
    E["msg_conservar"] = True
    return pagina_resumen({"forzar": True})


def ir(p):
    return {"ir": p["pagina"]}


# =============================================================================
# HOJAS CONECTADAS
# =============================================================================
NINGUNA = "(ninguna)"


def _url_hoja(enlace, gid=None):
    try:
        sid = rg.id_de_enlace(enlace)
    except ErrorRegistro:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit" + (f"#gid={gid}" if gid is not None else "")


def _chip_lectura(clave, conectada):
    lect = E.get("lectura") or {}
    hora = hace_cuanto(E.get("resumen_hora"))
    if not conectada:
        return H.chip("Sin conectar", "aviso" if clave == "f06" else "info"), ""
    r = lect.get(clave)
    if r is None:
        return H.chip("Conectada", "info"), "Todavía no se ha leído."
    if r == "ok":
        return H.chip("Conectada", "exito"), (f"Última lectura: {hora}" if hora else "")
    return H.chip("No se pudo leer", "error"), r


def detalle_estadistico(est):
    return f"datos «{est['datos']}»" + (f"  ·  resumen «{est['resumen']}»" if est.get("resumen") else "  ·  sin resumen")


def html_cuenta():
    e = rg.estado_cuenta()
    if e["conectado"]:
        c = (f'<div class="fila-cuenta"><span class="g-logo">G</span><div><p class="nota">Cuenta de Google</p>'
             f'<p class="titulo-ok">Cuenta conectada</p><p class="sub">{esc(e["correo"] or "Tu cuenta de Google está conectada.")}</p></div></div>'
             '<div class="barra-mini llena"><button class="btn" data-js="conectar">Cambiar de cuenta</button>'
             '<button class="btn" data-js="desconectar">Desconectar</button></div>')
    else:
        c = (f'<div class="fila-cuenta"><span class="g-logo">G</span><div><p class="nota">Cuenta de Google</p>'
             f'<p class="titulo-mal">Sin conectar</p><p class="sub">{esc(e["motivo"])} Pulsa el botón para conectar tu cuenta.</p></div></div>'
             '<div class="barra-mini llena"><button class="btn acento" data-js="conectar">Conectar con Google</button></div>')
    return H.tarjeta(c)


def html_guia(cfg):
    e = rg.estado_cuenta()
    if not e["conectado"]:
        txt = "Primero conecta tu cuenta de Google."
    elif not cfg["hoja"]["enlace"]:
        txt = "Ahora conecta la hoja de estatus de tarjetas (FO-06) en «Ajustes»."
    elif not cfg["grupos"]:
        txt = "Falta agregar tus rollos en «Ajustes» (o importarlos de tu hoja)."
    else:
        return ""
    return f'<div class="guia"><span>ⓘ</span><span>{esc(txt)}</span>{H.boton("Ir a Ajustes", "ir", "acento mini", pagina="ajustes")}</div>'


def fila_hoja_html(rotulo, nombre, detalle, chip_html, lectura, url, botones):
    return (f'<div class="fila-hoja"><p class="nota">{esc(rotulo)}</p><div class="tj-titulo"><b>{esc(nombre)}</b>{chip_html}</div>'
            f'<p class="sub">{esc(detalle)}</p>' + (f'<p class="nota">{esc(lectura)}</p>' if lectura else "")
            + '<div class="barra-mini llena">' + (f'<a class="btn" href="{esc(url)}" target="_blank" rel="noopener">Abrir ↗</a>' if url else "") + botones + "</div></div>")


def html_hojas_conectadas(cfg, editar=False):
    """Las hojas de este proyecto. Con editar=True salen los botones de cambiar/quitar (pantalla de Ajustes)."""
    _vol = "ajustes" if editar else "hojas"
    chip06, lect06 = _chip_lectura("f06", bool(cfg["hoja"]["enlace"]))
    todos06 = rc.estatus(cfg)
    if todos06:
        f1 = ""
        for k, est in enumerate(todos06):
            if k == 0:
                rot = "ESTATUS DE TARJETAS · FF-GS-FO-06" + ("  ·  donde se registra" if len(todos06) > 1 else "")
                det = f"pestaña «{est.get('pestana', '')}»"
            else:
                rot = f"ESTATUS DE TARJETAS · FF-GS-FO-06  ·  {k + 1}  (solo lectura)"
                det = "se leen todas sus pestañas"
            bots = H.boton("Cambiar…", "conectar_abrir", tipo="06", indice=k, volver=_vol)
            if k > 0:
                bots += H.boton("Usar para registrar", "estatus_principal", indice=k, volver=_vol)
            bots += H.boton("Quitar", "quitar_estatus", "peligro", indice=k, volver=_vol)
            nombre = (E.get("titulo") if k == 0 else None) or est.get("titulo") or "Hoja conectada"
            f1 += fila_hoja_html(rot, nombre, det, chip06, lect06, _url_hoja(est["enlace"], E.get("gid") if k == 0 else None), bots)
        f1 += H.boton("+ Agregar otro archivo de estatus", "conectar_abrir", "mini", tipo="06", indice=None, volver=_vol)
    else:
        f1 = fila_hoja_html("ESTATUS DE TARJETAS · FF-GS-FO-06", "Todavía no hay hoja conectada", "", chip06, "", "",
                            H.boton("Conectar hoja…", "conectar_abrir", "acento", tipo="06", indice=0, volver=_vol))
    todos07 = rc.estadisticos(cfg)
    chip07, lect07 = _chip_lectura("f07", bool(todos07))
    if not todos07:
        f2 = fila_hoja_html("ESTADÍSTICO · FF-GS-FO-07  (opcional)", "Sin conectar",
                            "El segundo Excel: se llena solo con los mismos datos del PDF, en el mismo paso.", chip07, "", "",
                            H.boton("Conectar estadístico…", "conectar_abrir", "acento", tipo="07", indice=0, volver=_vol))
    else:
        f2 = ""
        for k, est in enumerate(todos07):
            rot = "ESTADÍSTICO · FF-GS-FO-07" + (f"  ·  {est['etiqueta']}" if est.get("etiqueta") and len(todos07) > 1 else
                                                 "  (opcional)" if len(todos07) == 1 else f"  ·  {k + 1}")
            bots = H.boton("Cambiar…", "conectar_abrir", tipo="07", indice=k, volver=_vol) + H.boton("Quitar", "quitar_estadistico", "peligro", indice=k, volver=_vol)
            f2 += fila_hoja_html(rot, est.get("titulo") or "Estadístico conectado", detalle_estadistico(est), chip07, lect07,
                                 _url_hoja(est.get("enlace")), bots)
        if True:
            f2 += H.boton("+ Agregar otro estadístico (otra unidad)", "conectar_abrir", "mini", tipo="07", indice=None, volver=_vol)
    return H.tarjeta(f1 + "<hr>" + f2)


def html_conectar():
    """El cuadro de «Conectar hoja» (enlace → buscar → elegir pestaña → usar)."""
    cn = E["conectar"]
    es06 = cn["tipo"] == "06"
    cfg = rc.cargar_config()
    if es06:
        titulo = "Agregar otro archivo de estatus" if cn["indice"] is None else "Conectar la hoja de Google"
        instr = ("1. Abre tu hoja en el navegador y copia el enlace de la barra de direcciones.\n2. Pégalo aquí y pulsa «Buscar hoja».\n"
                 "3. Elige la pestaña donde quieres que se pegue el resultado.")
    else:
        titulo = "Agregar otro estadístico (otra unidad)" if cn["indice"] is None else "Conectar el estadístico (FO-07)"
        instr = (("Algunos proyectos llevan un estadístico por cada unidad. Agrega aquí el de otra unidad: cada uno se compara con la pestaña "
                  "de su unidad en el estatus de tarjetas.\n" if cn["indice"] is None else
                  "Es el segundo Excel, «Formato Estadístico». Se llena con los mismos datos del PDF, junto con el primero.\n")
                 + "1. Ábrelo en Google Sheets y copia el enlace de la barra de direcciones.\n2. Pégalo aquí y pulsa «Buscar hoja».\n"
                 "3. Elige la pestaña de datos («Datos Generales») y la del resumen («Resumen General»).")
    s = f'<form class="formulario" {a("conectar_buscar")} data-ev="submit"><h3>{esc(titulo)}</h3>'
    s += "".join(f'<p class="sub">{esc(l)}</p>' for l in instr.split("\n"))
    if cn.get("error"):
        s += H.aviso("error", cn["error"])
    s += f'<label>Enlace de la hoja<input name="enlace" value="{esc(cn.get("enlace", ""))}" placeholder="https://docs.google.com/spreadsheets/d/…" autocapitalize="off" autocorrect="off" inputmode="url"></label>'
    s += '<div class="botones"><button type="submit" class="btn">Buscar hoja</button></div></form>'
    if cn.get("info"):
        info = cn["info"]
        pest = info["pestanas"]
        s += (f'<form class="formulario" {a("conectar_usar")} data-ev="submit">'
              + H.aviso("ok", f"Encontré la hoja «{info['titulo']}» con {len(pest)} {'pestaña' if len(pest) == 1 else 'pestañas'}. "
                        f"Elige la pestaña y, si todo es correcto, pulsa «{'Usar esta hoja' if es06 else 'Usar este estadístico'}».")
              + "")
        campos = ([("pestana", "Pestaña donde pego el resultado:" if cn["indice"] in (0, None) and not (cn["indice"] is None and cfg["hoja"]["enlace"]) else "Pestaña principal de este archivo:",
                    cn["previo"].get("pestana", ""), "", False)] if es06 else
                  [("datos", "Pestaña de datos:", cn["previo"].get("datos", ""), "DATOS", False),
                   ("resumen", "Pestaña del resumen:", (cn["previo"].get("resumen") or NINGUNA) if cn["previo"].get("enlace") else "", "RESUMEN", True)])
        for clave, etq, valor, prefiere, opcional in campos:
            validas = pest + ([NINGUNA] if opcional else [])
            sel = valor if valor in validas else next((p for p in pest if prefiere in p.upper()), NINGUNA if opcional else pest[0])
            s += f'<label>{esc(etq)}<select name="{clave}">' + "".join(
                f'<option {"selected" if v == sel else ""}>{esc(v)}</option>' for v in validas) + "</select></label>"
        s += (f'<div class="botones"><button type="button" class="btn" {a("conectar_cancelar")}>Cancelar</button>'
              f'<button type="submit" class="btn acento">{"Usar esta hoja" if es06 else "Usar este estadístico"}</button></div></form>')
    else:
        s += f'<div class="botones">{H.boton("Cancelar", "conectar_cancelar")}</div>'
    return s


def conectar_abrir(p):
    cfg = rc.cargar_config()
    tipo, indice = p["tipo"], p.get("indice")
    todos = rc.estatus(cfg) if tipo == "06" else rc.estadisticos(cfg)
    previo = todos[indice] if indice is not None and indice < len(todos) else {}
    E["conectar"] = {"tipo": tipo, "indice": indice, "enlace": previo.get("enlace", ""), "previo": previo, "info": None, "error": None,
                     "volver": p.get("volver", "hojas"), "importar": bool(p.get("importar"))}
    return {"ir": E["conectar"]["volver"], "recargar": True}


def conectar_buscar(p):
    cn = E["conectar"]
    cn["enlace"] = (p.get("enlace") or "").strip()
    if not cn["enlace"] or "/d/" not in cn["enlace"]:                # el aviso habla de este mismo cuadro, no de otra pantalla
        cn["info"], cn["error"] = None, ("Primero pega aquí el enlace de la hoja." if not cn["enlace"] else
                                         "Ese enlace no parece de Google Sheets. Copia el enlace completo de la barra de direcciones "
                                         "(empieza con https://docs.google.com/spreadsheets/d/…).")
        return {"ir": cn["volver"], "recargar": True}
    try:
        cn["info"] = rg.info_completa(rg.conectar(), rg.id_de_enlace(cn["enlace"]))
        cn["error"] = None
        if not cn["info"]["pestanas"]:
            cn["info"], cn["error"] = None, "Esa hoja no tiene pestañas con datos."
    except Exception as e:
        msg = texto_error(e, "no pude abrir la hoja.")
        if msg.startswith("Google no encuentra esa hoja"):          # aquí mismo se corrige el enlace: no mandar a otra pantalla
            msg = ("Google no encuentra esa hoja. Revisa que el enlace esté completo (cópialo otra vez de la barra de direcciones) "
                   "y que tu cuenta de Google tenga acceso a ella.")
        cn["info"], cn["error"] = None, msg
    return {"ir": cn["volver"], "recargar": True}


def conectar_cancelar(p):
    cn = E.pop("conectar", None) or {}
    prov = E.pop("provisional", None)
    if prov:
        try:
            rc.eliminar_proyecto(prov["nuevo"])
            rc.cambiar_proyecto(prov["anterior"])
        except ErrorRegistro:
            pass
        E["proyecto"] = None
    return {"ir": cn.get("volver", "hojas"), "recargar": True, "proyectos": True}


def conectar_usar(p):
    cn = E["conectar"]
    info = cn["info"]
    cfg = rc.cargar_config()
    elegidas = {k: ("" if v == NINGUNA else v) for k, v in p.items()}
    if cn["tipo"] == "06":
        if elegidas.get("pestana") not in info["pestanas"]:
            cn["error"] = "Elige una de las pestañas de la lista."
            return {"ir": cn["volver"], "recargar": True}
        rc.guardar_estatus(cfg, {"enlace": cn["enlace"], "titulo": info["titulo"], "pestana": elegidas["pestana"]}, cn["indice"])
        rc.guardar_config(cfg)
        es_principal = cfg["hoja"]["enlace"] == cn["enlace"]
        if es_principal:
            E["titulo"] = info["titulo"]
        E["plan"] = None
        nota = None
    else:
        if elegidas.get("datos") not in info["pestanas"]:
            cn["error"] = "Elige una de las pestañas de la lista."
            return {"ir": cn["volver"], "recargar": True}
        try:
            sid = rg.id_de_enlace(cn["enlace"])
            pest = [elegidas["datos"]] + ([elegidas["resumen"]] if elegidas.get("resumen") else [])
            g = rg.leer_cuadriculas(rg.conectar(), sid, pest, "A1:BZ300")
            tabla = ec.encontrar_tabla(g[0])
            etiqueta = rsm._etiqueta_de_unidad07(g[1]) if len(g) > 1 else ""
            nota = ec.describir_tabla(g[0], tabla)
        except Exception as e:
            cn["error"] = texto_error(e, "no pude leer la hoja.")
            return {"ir": cn["volver"], "recargar": True}
        rc.guardar_estadistico(cfg, {"enlace": cn["enlace"], "titulo": info["titulo"], "datos": elegidas["datos"],
                                     "resumen": elegidas.get("resumen", ""), "etiqueta": etiqueta}, cn["indice"])
        rc.guardar_config(cfg)
    volver, importar = cn["volver"], cn["importar"]
    E.pop("conectar", None)
    E.update(resumen=None, cache_firma={})
    if cn["tipo"] == "06" and es_principal:
        r = importar_buscar({"silencioso": True, "volver": volver})
        if r:
            return r
    out = {"ir": volver, "recargar": True, "proyectos": True}
    if nota:
        out["toast"] = f"Listo. Entiendo la tabla: {nota}."
    return out


def _pagina_de(volver):
    return pagina_hojas() if volver == "hojas" else pagina_ajustes()


def quitar_estadistico(p):
    resp = _pagina_de(p.get("volver"))
    resp["confirmar"] = {"titulo": "Desconectar el estadístico", "texto": "¿Quito este estadístico? Tu hoja no se toca.",
                         "accion": "quitar_estadistico_ok", "boton": "Quitar", "p": {"indice": p["indice"], "volver": p.get("volver")}}
    return resp


def quitar_estadistico_ok(p):
    cfg = rc.cargar_config()
    rc.quitar_estadistico(cfg, p["indice"])
    rc.guardar_config(cfg)
    E.update(resumen=None, cache_firma={})
    return _pagina_de(p.get("volver"))


def quitar_estatus(p):
    resp = _pagina_de(p.get("volver"))
    cfg = rc.cargar_config()
    extra = (" Este es donde se registra: el siguiente archivo pasará a ser el principal." if p["indice"] == 0 and len(rc.estatus(cfg)) > 1 else "")
    resp["confirmar"] = {"titulo": "Quitar este archivo de estatus", "texto": "¿Quito este archivo? Tu hoja de Google no se toca." + extra,
                         "accion": "quitar_estatus_ok", "boton": "Quitar", "p": {"indice": p["indice"], "volver": p.get("volver")}}
    return resp


def quitar_estatus_ok(p):
    cfg = rc.cargar_config()
    rc.quitar_estatus(cfg, p["indice"])
    rc.guardar_config(cfg)
    E.update(resumen=None, cache_firma={}, plan=None)
    return _pagina_de(p.get("volver"))


def estatus_principal(p):
    cfg = rc.cargar_config()
    rc.hacer_principal_estatus(cfg, p["indice"])
    rc.guardar_config(cfg)
    E.update(resumen=None, cache_firma={}, plan=None)
    resp = _pagina_de(p.get("volver"))
    resp["toast"] = "Ahora el resultado se registra en este archivo."
    return resp


def pagina_hojas(p=None):
    if E.get("conectar") and E["conectar"].get("volver") == "hojas":
        return {"pagina": "hojas", "html": html_conectar()}
    cfg = rc.cargar_config()
    cuerpo = html_guia(cfg) + html_hojas_conectadas(cfg)
    cuerpo += ('<p class="nota pie">Cada vez que abres el Resumen la app vuelve a leer estas hojas. No escribe nada: solo lee. '
               'Aquí puedes agregar o quitar los archivos que quieras.</p>')
    if not rg.estado_cuenta()["conectado"]:
        cuerpo = html_cuenta() + cuerpo
    return {"pagina": "hojas", "html": cuerpo}


# =============================================================================
# IMPORTAR ROLLOS DE LA HOJA
# =============================================================================
def importar_buscar(p):
    cfg = rc.cargar_config()
    silencioso = p.get("silencioso", False)
    try:
        sid = rg.id_de_enlace(cfg["hoja"]["enlace"])
        servicio = rg.conectar()
        info = rg.info_completa(servicio, sid)
        descubierto = rg.descubrir_rollos(servicio, sid, cfg["hoja"]["pestana"], info["pestanas"], info.get("titulo", ""))
    except Exception as e:
        if silencioso:
            return None
        return _con_mensaje(pagina_ajustes(), texto_error(e, "no pude leer los rollos de tu hoja."), "aviso")
    hallados, proyecto = descubierto["rollos"], descubierto["proyecto"]
    nuevos = [r for r in hallados if not rc.hallado_ya_esta(r, cfg)]
    if not nuevos:
        if silencioso:
            return None
        return _con_mensaje(pagina_ajustes(), "No encontré rollos nuevos: todo lo que hay en tu hoja ya está en tus ajustes."
                            if hallados else "No encontré filas con rollos en tu hoja (¿está vacía?). Agrega tus rollos a mano con «Agregar rollo nuevo».", "info")
    E["importar"] = {"nuevos": nuevos, "proyecto": proyecto, "volver": p.get("volver", "ajustes")}
    return {"ir": E["importar"]["volver"], "recargar": True}


def html_importar():
    im = E["importar"]
    nuevos = im["nuevos"]
    pestanas_hoja = []
    for r in nuevos:
        for pt in r.get("pestanas", []):
            if pt not in pestanas_hoja:
                pestanas_hoja.append(pt)
    varias = len(pestanas_hoja) > 1
    todos, actual = rc.listar_proyectos()
    # el nombre que trae la hoja solo se propone si está libre (p. ej. ya llegó ese proyecto por la sincronización)
    # si ya le pusiste nombre al proyecto, se queda; el de la hoja solo se propone si aún se llama «Mi proyecto» y ese nombre está libre
    propuesto = (im["proyecto"] if im["proyecto"] and actual == "Mi proyecto" and im["proyecto"] not in todos else actual)
    s = f'<form class="formulario" {a("importar_aceptar")} data-ev="submit"><h3>Encontré esto en tu hoja</h3>'
    s += '<p class="sub">Lo saqué de lo que ya tienes escrito en tu hoja. Marca los que quieras agregar y corrige lo que haga falta.</p>'
    if im.get("error"):
        s += H.aviso("error", im["error"])
    s += f'<label>Nombre del proyecto<input name="proyecto" value="{esc(propuesto)}"></label>'
    for i, r in enumerate(nuevos):
        color = r.get("color")
        punto = f'<span class="punto grande" style="background:{color}"></span>' if color else '<span class="nota">color de la hoja</span>'
        s += (f'<div class="item rollo-imp"><label class="casilla"><input type="checkbox" name="usar_{i}" checked><span class="caja"></span>'
              f'<span class="txt"><b>{esc(r["nombre"])}</b> {punto}</span></label>'
              f'<label>Rollo<input name="nombre_{i}" value="{esc(r["nombre"])}"></label>'
              f'<label>Rental<input name="rental_{i}" value="{esc(r["rental"])}"></label>'
              f'<label>Modelo<input name="modelo_{i}" value="{esc(r["modelo"])}"></label>'
              f'<label># Mag<input name="mag_{i}" type="number" min="1" max="30" value="{r["ciclo_mag"] or ""}"></label>'
              + (f'<p class="nota">Pestañas: {esc(" · ".join(r.get("pestanas", [])))}</p>' if varias else "")
              + f'<p class="nota">Viene de: {esc(", ".join(r.get("pestanas", [])))} (por ejemplo {esc(r["ejemplo"])}).</p></div>')
    s += (f'<div class="botones"><button type="button" class="btn" {a("importar_cancelar")}>Ahora no</button>'
          '<button type="submit" class="btn acento">Agregar los marcados</button></div></form>')
    return s


def importar_cancelar(p):
    volver = (E.pop("importar", None) or {}).get("volver", "ajustes")
    _cerrar_provisional()
    return {"ir": volver, "recargar": True, "proyectos": True}


def _cerrar_provisional():
    E.pop("provisional", None)


def importar_aceptar(p):
    im = E["importar"]
    elegidos = []
    for i, r in enumerate(im["nuevos"]):
        if not p.get(f"usar_{i}"):
            continue
        nombre = (p.get(f"nombre_{i}") or "").strip()
        if not nombre:
            im["error"] = "Todos los rollos marcados necesitan un nombre."
            return {"ir": im["volver"], "recargar": True}
        txt = str(p.get(f"mag_{i}") or "").strip()
        try:
            ciclo = int(txt) if txt else None
        except ValueError:
            im["error"] = f"En «{nombre}», el # Mag debe ser un número (o déjalo vacío si no lleva)."
            return {"ir": im["volver"], "recargar": True}
        elegidos.append({**r, "nombre": nombre, "rental": (p.get(f"rental_{i}") or "").strip(),
                         "modelo": (p.get(f"modelo_{i}") or "").strip(), "ciclo_mag": ciclo})
    if not elegidos:
        im["error"] = "No marcaste ningún rollo. Marca al menos uno, o pulsa «Ahora no»."
        return {"ir": im["volver"], "recargar": True}
    nombre_proy = (p.get("proyecto") or "").strip()
    if not nombre_proy:
        im["error"] = "Ponle un nombre al proyecto."
        return {"ir": im["volver"], "recargar": True}
    try:
        actual = rc.listar_proyectos()[1]
        if nombre_proy != actual:
            rc.renombrar_proyecto(actual, nombre_proy)
        cfg2 = rc.cargar_config()
        agregados = rc.agregar_hallados(cfg2, elegidos)
        rc.guardar_config(cfg2)
    except ErrorRegistro as e:
        im["error"] = str(e) + (" Ponle otro nombre aquí, o cambia a ese proyecto con el selector de arriba."
                                if str(e).startswith("Ya existe un proyecto") else "")
        return {"ir": im["volver"], "recargar": True}
    volver = im["volver"]
    E.pop("importar", None)
    _cerrar_provisional()
    E.update(resumen=None, cache_firma={}, proyecto=None)
    return {"ir": volver, "recargar": True, "proyectos": True, "toast": "Agregué " + ", ".join(agregados) + ". Puedes ajustar cualquiera con «Editar»."}


# =============================================================================
# AJUSTES (del proyecto y de la app)
# =============================================================================
def _etiqueta_tipo(g):
    tipo, letra, _otro = rc.tipo_de_patrones(g["patrones"])
    return {"camara": f"Cámara (letra {letra})", "sonido": "Sonido", "drones": "Drones", "celulares": "Celulares"}.get(tipo, "BIN empieza con " + ", ".join(g["patrones"]))


def _base_de_rollo(g):
    tipo, letra, otro = rc.tipo_de_patrones(g["patrones"])
    return {"tipo": tipo, "letra": letra, "otro": otro, "nombre": g["nombre"], "rental": g["rental"], "modelo": g["modelo"],
            "ciclo_mag": g["ciclo_mag"], "color": g["color"], "avisar_si_falta": g["avisar_si_falta"], "editando": True}


def _n(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def _rollos_html(cfg):
    n = len(cfg["grupos"])
    filas = []
    for i, g in enumerate(cfg["grupos"]):
        mag = _n(g["ciclo_mag"], "tarjeta", "tarjetas") if g["ciclo_mag"] else "sin # Mag"
        grip = ('<span class="grip" role="button" aria-label="Mantén y arrastra para cambiar el orden"><svg viewBox="0 0 24 24"><circle cx="9" cy="6" r="1.7"/><circle cx="15" cy="6" r="1.7"/>'
                '<circle cx="9" cy="12" r="1.7"/><circle cx="15" cy="12" r="1.7"/><circle cx="9" cy="18" r="1.7"/><circle cx="15" cy="18" r="1.7"/></svg></span>') if n > 1 else ""
        kv = "".join(f'<div class="kv-f"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in (
            ("Tipo", _etiqueta_tipo(g)), ("Rental", g["rental"]), ("Modelo", g["modelo"]), ("Tarjetas (# Mag)", mag),
            ("Color", g["color"] or "el de la hoja"), ("Avisar si falta", "Sí" if g.get("avisar_si_falta") else "No")) if v not in ("", None))
        filas.append(f'<details class="rollo" data-i="{i}" data-k="rollo-{esc(g["id"])}"><summary><span class="punto grande" style="background:{g["color"] or "#888"}"></span>'
                     f'<span class="rollo-t"><b>{esc(g["nombre"])}</b><span class="sub">{esc(g["modelo"] or _etiqueta_tipo(g))}</span></span>{grip}</summary>'
                     f'<div class="kv">{kv}</div>'
                     f'<div class="rollo-b">{H.boton("Editar", "editar_rollo", "mini", id=g["id"])}{H.boton("Quitar", "quitar_rollo", "mini peligro", id=g["id"])}</div></details>')
    cuerpo = ('<p class="sub">Cada rollo es un tipo de material: Cámara A, Cámara B, Sonido… Toca uno para ver y editar sus datos. '
              'El orden es el de las filas en la hoja: para cambiarlo, arrastra el asa ⋮⋮.</p>')
    cuerpo += ('<div class="rollos-lista">' + "".join(filas) + "</div>") if filas else '<div class="estado aviso"><span class="ico">⚠</span><span>Aún no hay rollos. Usa «Importar rollos de mi hoja» o «Agregar rollo nuevo».</span></div>'
    hay_hoja = bool(cfg["hoja"]["enlace"])
    cuerpo += ('<div class="barra-mini llena">' + H.boton("Agregar rollo nuevo", "agregar_rollo", "acento" if (not cfg["grupos"] and not hay_hoja) else "")
               + (H.boton("Importar rollos de mi hoja", "importar_buscar", "acento" if not cfg["grupos"] else "") if hay_hoja else "") + "</div>")
    return H.tarjeta(cuerpo, f"Rollos · {n}")


def pagina_ajustes(p=None):
    """«Ajustes» (pestaña) = solo lo del PROYECTO. Lo de la app está en la rueda de arriba (pagina_app)."""
    for clave, htmlf in (("conectar", html_conectar), ("importar", html_importar)):
        if E.get(clave) and E[clave].get("volver") == "ajustes":
            return {"pagina": "ajustes", "html": htmlf()}
    if E.get("formulario") and E.get("pagina_form") == "ajustes":
        return {"pagina": "ajustes", "html": html_formulario_rollo(E["formulario"])}
    E["ajustes_tab"] = "proyecto"
    cfg = rc.cargar_config()
    proyectos, activo = rc.listar_proyectos()
    out = [f'<p class="intro">Solo del proyecto «{esc(cfg["_proyecto"])}»: sus hojas de Google y sus rollos. Se configura una sola vez; cambia lo que quieras cuando quieras. '
           'Lo de la aplicación (cuenta, apariencia, descanso) está en la rueda ⚙ de arriba.</p>',
           H.grupo("Hojas de Google"), html_hojas_conectadas(cfg, editar=True),
           H.grupo("Rollos"), _rollos_html(cfg),
           H.grupo("Proyecto")]
    cp = (f'<p class="sub">Tienes {_n(len(proyectos), "proyecto", "proyectos")}. Con la sincronización, los mismos aparecen en tu Mac.</p>'
          '<div class="barra-mini llena">' + H.boton("Renombrar", "renombrar_pedir", "") + H.boton("Nuevo proyecto…", "nuevo_pedir", "") + "</div>"
          + ('<div class="barra-mini llena">' + H.boton("Eliminar este proyecto", "eliminar_proyecto", "peligro") + "</div>" if len(proyectos) > 1 else ""))
    out.append(H.tarjeta(cp))
    return {"pagina": "ajustes", "html": "".join(out)}


def pagina_app(p=None):
    """Ajustes de la APP (la rueda ⚙): valen para todos los proyectos."""
    E["ajustes_tab"] = "app"
    out = ['<p class="intro">Estos ajustes son de la aplicación y valen para todos tus proyectos. Las hojas y los rollos de cada proyecto están en la pestaña «Ajustes».</p>',
           H.grupo("Cuenta de Google"), html_cuenta(), html_sync(),
           H.grupo("Apariencia"),
           H.tarjeta('<p class="sub">«Automático» sigue la apariencia de tu iPhone y cambia sola.</p><div class="segmentado">'
                     + "".join(f'<button class="seg" data-js="tema" data-v="{v}">{t}</button>' for v, t in (("auto", "Automático"), ("claro", "Claro"), ("oscuro", "Oscuro")))
                     + '</div>'),
           H.grupo("Descanso"), '<div id="js-descanso"></div>',
           H.grupo("Actualizaciones"), '<div id="js-version"></div>',
           '<p class="nota pie">Estadístico FilmFlow · versión para iPhone. La apariencia, el descanso y la sesión son solo de este teléfono; '
           'tus proyectos se comparten con el Mac a través de tu cuenta de Google.</p>']
    return {"pagina": "app", "html": "".join(out)}


def agregar_rollo(p):
    cfg = rc.cargar_config()
    idx_cam = [i for i, g in enumerate(cfg["grupos"]) if rc.letra_de_camara(g["patrones"])]
    E["formulario"] = {"accion": "guardar_rollo", "titulo": "Agregar rollo nuevo", "base": {"tipo": "camara"}, "nombres_posicion": [g["nombre"] for g in cfg["grupos"]],
                       "pos_camara": (idx_cam[-1] + 1) if idx_cam else 0, "usados": [g["color"] for g in cfg["grupos"]],
                       "patrones_usados": [pp for g in cfg["grupos"] for pp in g["patrones"]], "datos": {}}
    E["pagina_form"] = "ajustes"
    return {"ir": "ajustes", "recargar": True}


def editar_rollo(p):
    cfg = rc.cargar_config()
    i = next((j for j, g in enumerate(cfg["grupos"]) if g["id"] == p["id"]), None)
    if i is None:
        return pagina_ajustes()
    E["formulario"] = {"accion": "guardar_rollo", "titulo": "Editar «" + cfg["grupos"][i]["nombre"] + "»", "base": _base_de_rollo(cfg["grupos"][i]),
                       "usados": [g["color"] for j, g in enumerate(cfg["grupos"]) if j != i],
                       "patrones_usados": [pp for j, g in enumerate(cfg["grupos"]) if j != i for pp in g["patrones"]], "datos": {"id": p["id"]}}
    E["pagina_form"] = "ajustes"
    return {"ir": "ajustes", "recargar": True}


def guardar_rollo(p):
    f = E["formulario"]
    valor, error = leer_formulario_rollo(p, f)
    if error:
        f["error"] = error
        f["base"] = {**f["base"], **{k: p.get(k, "") for k in ("tipo", "letra", "otro", "nombre", "rental", "modelo")}}
        return {"ir": "ajustes", "recargar": True}
    cfg = rc.cargar_config()
    try:
        if f["datos"].get("id"):
            i = next(j for j, g in enumerate(cfg["grupos"]) if g["id"] == f["datos"]["id"])
            valor.pop("posicion", None)
            cfg["grupos"][i].update(valor)
        else:
            lugar = valor.pop("posicion", len(cfg["grupos"]))
            g = rc.agregar_grupo(cfg, **valor)
            cfg["grupos"].remove(g)
            cfg["grupos"].insert(lugar, g)
        rc.guardar_config(cfg)
    except ErrorRegistro as e:
        f["error"] = str(e)
        return {"ir": "ajustes", "recargar": True}
    E["formulario"] = None
    E.update(resumen=None, cache_firma={})
    return {"ir": "ajustes", "recargar": True}


def cancelar_formulario(p):          # (reemplaza la versión de arriba: sirve para Registrar y para Ajustes)
    volver = E.get("pagina_form", "registrar")
    E["formulario"] = None
    E["nuevos_tmp"] = []
    return {"ir": volver, "recargar": True}


def quitar_rollo(p):
    cfg = rc.cargar_config()
    g = next((g for g in cfg["grupos"] if g["id"] == p["id"]), None)
    if not g:
        return pagina_ajustes()
    resp = pagina_ajustes()
    resp["confirmar"] = {"titulo": "Quitar", "texto": f"¿Quitar «{g['nombre']}»?\nLas filas que ya están en tu hoja no se tocan.",
                         "accion": "quitar_rollo_ok", "boton": "Quitar", "p": {"id": p["id"]}}
    return resp


def quitar_rollo_ok(p):
    cfg = rc.cargar_config()
    cfg["grupos"] = [g for g in cfg["grupos"] if g["id"] != p["id"]]
    rc.guardar_config(cfg)
    E.update(resumen=None, cache_firma={})
    return pagina_ajustes()


def mover_rollo(p):
    cfg = rc.cargar_config()
    i = p["i"]
    j = p["a"] if "a" in p else i + p.get("d", 0)
    if 0 <= i < len(cfg["grupos"]) and 0 <= j < len(cfg["grupos"]) and i != j:
        cfg["grupos"].insert(j, cfg["grupos"].pop(i))
        rc.guardar_config(cfg)
    return pagina_ajustes()


# ---- proyectos ----
def _reiniciar_vista():
    E.update(titulo=None, plan=None, pdf=None, pdf_texto=None, correcciones=set(), decision={"06": "dejar", "07": "dejar"}, vistas={},
             n_hall={}, corr_res=set(), msg_corr=[], msg_err=[], resumen=None, proyecto=None, formulario=None, correo=None)


def elegir_proyecto(p):
    try:
        rc.cambiar_proyecto(p["nombre"])
    except ErrorRegistro as e:
        return _con_mensaje(pagina_ajustes(), str(e), "error")
    _reiniciar_vista()
    return {"ir": "resumen", "recargar": True, "proyectos": True}


def renombrar_pedir(p):
    resp = pagina_ajustes()
    resp["pedir"] = {"titulo": "Nombre del proyecto", "texto": "Escribe el nombre que quieras para este proyecto:", "valor": rc.listar_proyectos()[1],
                     "accion": "renombrar_ok"}
    return resp


def renombrar_ok(p):
    actual = rc.listar_proyectos()[1]
    nuevo = (p.get("valor") or "").strip()
    if not nuevo or nuevo == actual:
        return pagina_ajustes()
    try:
        rc.renombrar_proyecto(actual, nuevo)
    except ErrorRegistro as e:
        return _con_mensaje(pagina_ajustes(), str(e), "aviso")
    E["proyecto"] = None
    r = pagina_ajustes()
    r["proyectos"] = True
    return r


def nuevo_pedir(p):
    resp = pagina_ajustes()
    resp["pedir"] = {"titulo": "Nuevo proyecto", "texto": "Escribe el nombre del proyecto. Cada proyecto tiene su propia hoja de Google, sus rollos y sus colores.",
                     "valor": "", "accion": "nuevo_ok", "boton": "Crear"}
    return resp


def nuevo_ok(p):
    nombre = (p.get("valor") or "").strip()
    anterior = rc.listar_proyectos()[1]
    try:
        rc.crear_proyecto(nombre)
    except ErrorRegistro as e:
        return _con_mensaje(pagina_ajustes(), str(e), "aviso")
    _reiniciar_vista()
    r = pagina_ajustes()
    r["proyectos"] = True
    r["confirmar"] = {"titulo": "Proyecto creado", "texto": f"Listo, creé «{nombre}». ¿Quieres conectar ahora su hoja de Google? (También puedes hacerlo luego en Ajustes.)",
                      "accion": "nuevo_conectar", "boton": "Conectar hoja"}
    return r


def nuevo_conectar(p):
    return conectar_abrir({"tipo": "06", "indice": 0, "volver": "ajustes", "importar": True})


def eliminar_proyecto(p):
    proyecto = rc.cargar_config()["_proyecto"]
    resp = pagina_ajustes()
    resp["confirmar"] = {"titulo": "Eliminar proyecto", "texto": f"¿Eliminar el proyecto «{proyecto}» de este programa?\nTu hoja de Google y sus datos no se tocan.",
                         "accion": "eliminar_ok", "boton": "Eliminar"}
    return resp


def eliminar_ok(p):
    proyecto = rc.cargar_config()["_proyecto"]
    try:
        rc.eliminar_proyecto(proyecto)
    except ErrorRegistro as e:
        return _con_mensaje(pagina_ajustes(), str(e), "error")
    _reiniciar_vista()
    return {"ir": "ajustes", "recargar": True, "proyectos": True}


# =============================================================================
# CORREO
# =============================================================================
def _correo():
    return E.setdefault("correo", None)


def correo_pdf(p):
    nombre, texto = p["nombre"], rd_traducir(p["texto"])
    E["correo_pdf"] = nombre
    try:
        cfg = rc.cargar_config()
        if not cfg["grupos"]:
            raise ErrorRegistro("Este proyecto todavía no tiene rollos. Agrégalos en «Ajustes» y vuelve a intentarlo.")
        reporte = rc.leer_reporte(nombre, texto)
        datos = correo_core.datos_del_correo(reporte, cfg)
        E["correo"] = {"pdf": nombre, "datos": datos, "cfg": cfg, "proyecto": rc.listar_proyectos()[1], "reporte": reporte,
                       "prefijo": (cfg.get("correo") or {}).get("prefijo"), "error": None}
    except Exception as e:
        E["correo"] = {"pdf": nombre, "datos": None, "error": texto_error(e, "no pude leer el PDF.")}
    return pagina_correo()


def correo_usar_registro(p):
    if E.get("pdf_texto") and E.get("pdf"):
        return correo_pdf({"nombre": E["pdf"], "texto": E["pdf_texto_crudo"] if E.get("pdf_texto_crudo") else E["pdf_texto"]})
    return pagina_correo()


def correo_prefijo(p):
    c = E.get("correo")
    if not c or c.get("datos") is None:
        return {"nada": True}
    pref = correo_core.prefijo_de_asunto(p.get("asunto", ""))
    if pref and pref != c.get("prefijo"):
        c["prefijo"] = pref
        try:
            cfg = rc.cargar_config()
            cfg["correo"] = {"prefijo": pref}
            rc.guardar_config(cfg)
        except Exception:
            pass
    return {"nada": True}


def pagina_correo(p=None):
    c = E.get("correo")
    if c and c.get("proyecto") not in (None, rc.listar_proyectos()[1]):
        E["correo"] = c = None
    nombre = (c or {}).get("pdf")
    cuerpo = (f'<div class="pdf-zona{" listo" if nombre else ""}"><div class="ico-pdf">{ICO_PDF}</div>'
              f'<div class="nombre" id="correo-pdf">{esc(nombre) if nombre else "Elige el PDF del día"}</div>'
              '<p class="nota">Elige el PDF de Silverstack del día (el mismo de «Registrar día») y aquí sale el correo armado, listo para copiar. '
              'No escribe nada en tus hojas.</p>'
              f'<button class="btn {"mini" if nombre else "acento"}" data-js="elegir_pdf_correo">{"Cambiar PDF…" if nombre else "Elegir PDF…"}</button>'
              + (H.boton("Usar el de «Registrar día»", "correo_usar_registro", "mini") if E.get("pdf") else "")
              + '</div>')
    if c and c.get("error"):
        cuerpo += H.aviso("error", c["error"])
    if c and c.get("datos"):
        datos = c["datos"]
        reporte = c["reporte"]
        nota = f"Día {datos['dia']:03d} · {datos['fecha']:%d/%m/%Y} · unidad {datos['unidad']}. No escribe nada en tus hojas."
        if reporte.get("fecha_dudosa"):
            nota += f"  Ojo: la fecha del reporte no es confiable; usé el día de descarga ({reporte['fecha']:%d/%m/%Y})."
        cuerpo += H.aviso("aviso" if reporte.get("fecha_dudosa") else "info", nota)
        o = correo_core.opciones_automaticas(c["proyecto"], datos, {"prefijo": c.get("prefijo")})
        r = correo_core.armar(datos, o)
        lineas = ""
        for k, linea in enumerate(r["lineas"]):
            if not linea:
                lineas += '<div class="l v"><br></div>'
            else:
                lineas += '<div class="l">' + "".join(f"<b>{esc(t)}</b>" if b else esc(t) for t, b in linea if t) + "</div>"
        avisos = []
        if datos["sin_reconocer"]:
            avisos.append("No reconozco estos rollos: " + ", ".join(datos["sin_reconocer"]) +
                          ". Cuentan en los totales, pero no salen en las líneas de cámara. Agrégalos en «Ajustes».")
        if not datos["camaras"]:
            avisos.append("No encontré cámaras con material en este reporte. Revisa tus rollos en «Ajustes».")
        if not datos["hay_audio"]:
            avisos.append("Este reporte no trae audio: el correo sale sin la parte de sonido.")
        cuerpo += ('<section class="tarjeta"><h3>Correo</h3><div class="papel"><input id="correo-asunto" class="asunto" value="' + esc(r["asunto"]) + '">'
                   f'<hr><div id="correo-texto" class="texto-correo" contenteditable="true" spellcheck="false">{lineas}</div></div>'
                   + "".join(f'<p class="nota aviso-txt">{esc(x)}</p>' for x in avisos)
                   + '<div class="barra-mini llena"><button class="btn acento" data-js="copiar_correo">Copiar texto</button>'
                     '<button class="btn" data-js="copiar_asunto">Copiar asunto</button></div>'
                     '<div class="barra-mini llena"><button class="btn" data-js="compartir_correo">Compartir…</button></div><p class="sub" id="correo-copiado"></p>'
                     '<p class="nota">Puedes corregir el texto o el asunto aquí antes de copiarlo. Si cambias el prefijo del asunto, la app lo recuerda para este proyecto.</p></section>')
    return {"pagina": "correo", "html": cuerpo}


# =============================================================================
# ENTRADA ÚNICA (la llama el worker)
# =============================================================================

# =============================================================================
# SINCRONIZACIÓN con la app del Mac (por una hoja de tu propio Drive)
# =============================================================================
def _estado_sync():
    return sc.describir()


def html_sync():
    e = rg.estado_cuenta()
    s = _estado_sync()
    if not e["conectado"]:
        cuerpo = ('<p class="sub">Conecta tu cuenta de Google y tus proyectos aparecen aquí solos: los mismos que tienes en la app del Mac, '
                  'sin volver a escribir enlaces.</p>')
        return H.tarjeta(cuerpo, "Sincronizar con el Mac", clase="sync")
    cuerpo = ""
    if s["activa"]:
        hora = datetime.fromtimestamp(s["ultima"]).strftime("%d/%m %H:%M") if s.get("ultima") else "—"
        cuerpo += (f'<div class="estado ok"><span class="ico">✔</span><span>Sincronizado con tu cuenta {esc(s["correo"] or "")}. '
                   f'Última vez: {esc(hora)}. Lo que cambies aquí o en el Mac aparece en el otro.</span></div>')
    else:
        cuerpo += ('<p class="sub">Todavía no se ha sincronizado. Pulsa el botón para traer tus proyectos del Mac '
                   '(o subir los de este teléfono).</p>')
    if s.get("error"):
        cuerpo += f'<div class="estado aviso"><span class="ico">⚠</span><span>{esc(s["error"])}</span></div>'
    if "Drive API" in (s.get("error") or ""):
        cuerpo += ('<ol class="pasos"><li>Entra a <a href="https://console.cloud.google.com/apis/library/drive.googleapis.com" target="_blank" rel="noopener">'
                   'Google Drive API en Google Cloud</a> (con la cuenta dueña del proyecto).</li>'
                   '<li>Pulsa <b>Habilitar</b>.</li><li>Vuelve aquí y pulsa «Sincronizar ahora».</li></ol>')
    cuerpo += '<div class="barra-mini llena">' + H.boton("Sincronizar ahora", "sincronizar", "acento", manual=True) + "</div>"
    return H.tarjeta(cuerpo, "Sincronizar con el Mac", clase="sync")


def _sincronizar(manual=False, sid_manual=None):
    """Devuelve un diccionario listo para la respuesta (nunca lanza)."""
    if not web_shim.ESTADO["token"]:
        return {"sync": {"estado": "sin_sesion"}}
    try:
        r = sc.sincronizar(web_shim.http_directo, web_shim.ESTADO["correo"], "teléfono", crear=True, gana_local_al_inicio=False,
                           sid_manual=sid_manual)
    except sc.ErrorSync as e:
        sc.anotar_error(str(e))
        return {"sync": {"estado": "error", "texto": str(e), "falta_permiso": e.falta_permiso, "falta_api": e.falta_api, "codigo": e.codigo},
                **({"toast": str(e), "recargar": True} if manual else {})}
    except Exception as e:
        sc.anotar_error(texto_error(e, "no pude sincronizar."))
        return {"sync": {"estado": "error", "texto": texto_error(e, "no pude sincronizar.")}}
    sc.anotar_error("")
    out = {"sync": r, "proyectos": info_shell()}
    if r["bajados"] or r["borrados"]:
        activo = rc.listar_proyectos()[1]
        if activo in r["bajados"] or activo in r["borrados"] or E.get("proyecto") not in (None, activo):
            # cambió el proyecto que estás usando: se vuelve a leer todo (lo que estabas revisando ya no vale)
            en_curso = bool(E.get("plan") and not E["plan"].get("escrito"))
            _reiniciar_vista()
            out["recargar"] = True
            out["toast"] = (f"Tu proyecto «{activo}» cambió en el otro equipo" +
                            (": vuelve a revisar el PDF antes de escribir." if en_curso else ". Ya está actualizado."))
        else:
            # cambiaron OTROS proyectos: lo que estás haciendo en este sigue igual (antes se borraba el PDF revisado)
            out["toast"] = ("Se actualizaron tus proyectos: " + ", ".join(r["bajados"] + [f"{n} (borrado)" for n in r["borrados"]]))
    elif manual:
        out["toast"] = "Todo está sincronizado."
        out["recargar"] = True
    return out


def sincronizar(p):
    return _sincronizar(bool(p.get("manual")))


def sync_enlace(p):
    try:
        sid = sc.id_de_enlace(p.get("enlace", ""))
    except ErrorRegistro as e:
        return {"toast": str(e)}
    return _sincronizar(True, sid)


def _pagina(nombre, p=None):
    return {"resumen": pagina_resumen, "registrar": pagina_registrar, "hojas": pagina_hojas, "correo": pagina_correo, "ajustes": pagina_ajustes, "app": pagina_app}[nombre](p)


def pagina(p):
    r = _pagina(p["nombre"], p)
    r["proyectos"] = info_shell()
    return r


def cuenta(p):
    return {"conectado": web_shim.ESTADO["conectado"], "proyectos": info_shell()}


ACCIONES = {k: v for k, v in globals().items() if callable(v) and not k.startswith("_") and k in {
    "pagina", "unidad", "marcar", "marcar_seg", "alternar_vista", "mas_hallazgos", "decision", "casilla", "actualizar", "corregir_cruce",
    "corregir_cruce_ok", "corregir_errores", "corregir_errores_ok", "ir", "pdf_elegido", "revisar", "escribir", "escribir_ok", "guardar_rollo_nuevo",
    "cancelar_formulario", "conectar_abrir", "conectar_buscar", "conectar_cancelar", "conectar_usar", "quitar_estadistico", "quitar_estadistico_ok", "quitar_estatus", "quitar_estatus_ok", "estatus_principal",
    "importar_buscar", "importar_cancelar", "importar_aceptar", "agregar_rollo", "editar_rollo", "guardar_rollo", "quitar_rollo", "quitar_rollo_ok",
    "mover_rollo", "elegir_proyecto", "renombrar_pedir", "renombrar_ok", "nuevo_pedir", "nuevo_ok", "nuevo_conectar", "eliminar_proyecto", "eliminar_ok",
    "correo_pdf", "correo_usar_registro", "correo_prefijo", "cuenta", "sincronizar", "sync_enlace", "nuevo_dia",
    "reporte_abrir", "reporte_cerrar", "reporte_tipo", "reporte_tocar", "reporte_mes", "reporte_rango", "reporte_unidad", "reporte_modo", "reporte_contenido",
    "reporte_crear"}}


def _firma_config():
    try:
        st = rc.RUTA_CONFIG.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


class _Codificador(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (set, tuple)):
            return list(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)


def llamar(nombre, p_json="{}", token=None, correo=None):
    """Punto de entrada: ejecuta una acción y devuelve JSON. `token`/`correo`: la sesión de Google que tiene el navegador."""
    web_shim.ESTADO["token"] = token or None
    web_shim.ESTADO["conectado"] = bool(token)
    web_shim.ESTADO["correo"] = correo
    p = json.loads(p_json or "{}")
    antes = _firma_config()
    try:
        if nombre not in ACCIONES:
            raise ErrorRegistro(f"Acción desconocida: {nombre}")
        r = ACCIONES[nombre](p)
        if "proyectos" in r and r["proyectos"] is True:
            r["proyectos"] = info_shell()
        if nombre not in ("sincronizar", "sync_enlace") and _firma_config() != antes:
            r["sync_pendiente"] = True              # el navegador sincroniza en segundo plano en cuanto pueda
    except Exception as e:
        import traceback
        r = {"error": texto_error(e), "traza": traceback.format_exc()}
    return json.dumps(r, cls=_Codificador, ensure_ascii=False)
