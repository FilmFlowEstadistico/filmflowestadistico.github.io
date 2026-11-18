// Estadístico FilmFlow · teléfono. Esta parte solo dibuja y reparte toques; TODA la lógica es Python (la misma de la app del Mac).
// El lector de PDF (650 KB) se carga solo cuando eliges un PDF: así la app abre más rápido.
const textoDelPdf = async (datos) => (await import("./pdftexto.js")).textoDelPdf(datos);

const CFG = window.FILMFLOW_CONFIG || {};
const PRUEBA = window.FILMFLOW_PRUEBA || null;       // solo lo pone el entorno de pruebas
// App del Mac: la MISMA interfaz, servida por la app del Mac (ventana_web.py). El Python corre en el Mac (no en el navegador) y la
// sesión de Google es la del Mac. La clave viene en la dirección (?mac=…) y va en cada pedido al Mac.
const CLAVE_MAC = new URLSearchParams(location.search).get("mac") || "";
const MAC = !!CLAVE_MAC && !PRUEBA;
async function mac(metodo, p = {}) {
  const r = await fetch("/mac/" + metodo, { method: "POST", headers: { "Content-Type": "application/json", "X-FF-Clave": CLAVE_MAC }, body: JSON.stringify(p) });
  if (!r.ok) throw new Error("La app del Mac no respondió (" + r.status + "). Ciérrala y ábrela otra vez.");
  return r.json();
}
// En la ventana propia del Mac (WebKit) el PDF lo hace la ventana con el motor de Safari
const PDF_WEBKIT = MAC && !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.filmflow);
let idPdf = 0; const pdfsPendientes = {};
window.__ffPdfListo = (id, ok) => { const f = pdfsPendientes[id]; if (f) { delete pdfsPendientes[id]; f(!!ok); } };
function pdfConWebKit(html, pdf) {
  return new Promise((ok) => {
    const id = ++idPdf; pdfsPendientes[id] = ok;
    setTimeout(() => window.__ffPdfListo(id, false), 90000);
    try { window.webkit.messageHandlers.filmflow.postMessage({ accion: "pdf", html, pdf, id }); } catch (e) { window.__ffPdfListo(id, false); }
  });
}
if (MAC) {
  document.documentElement.classList.add("en-mac");
  setInterval(() => { mac("latido").catch(() => {}); }, 5000);            // así el Mac sabe que la ventana sigue abierta
}
const base = new URL("./", location.href).href;
const $ = (s) => document.querySelector(s);
const vista = $("#vista");
const PAGINAS_GOOGLE = new Set(["resumen", "registrar", "hojas", "reporte", "correo"]);
const PERMISOS = "https://www.googleapis.com/auth/spreadsheets openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/drive.file";
let actual = "resumen";
let sesion = { token: null, exp: 0, correo: null };
let cliente = null;
let proyectos = { lista: [], activo: "" };

// ---------- almacenamiento ligero ----------
// Si el navegador no deja guardar (pestaña privada de Safari, "bloquear todas las cookies"…), se guarda en memoria mientras la pestaña siga abierta.
const memoria = {};
let almacenFalla = false;
const guardar = (k, v) => { memoria[k] = String(v); try { localStorage.setItem(k, v); } catch (e) { almacenFalla = true; try { sessionStorage.setItem(k, v); } catch (_) {} } };
const leer = (k) => { try { const v = localStorage.getItem(k); if (v !== null) return v; } catch (e) { almacenFalla = true; try { const w = sessionStorage.getItem(k); if (w !== null) return w; } catch (_) {} } return k in memoria ? memoria[k] : null; };
try { localStorage.setItem("ff-prueba", "1"); localStorage.removeItem("ff-prueba"); } catch (e) { almacenFalla = true; }
// ¿Puede esta pestaña guardar archivos en el teléfono (IndexedDB)? En una pestaña privada a veces no: la app sigue, sin guardar nada.
function probarIDB() {
  return new Promise((res) => {
    const t = setTimeout(() => res(false), 2500);
    try {
      const q = indexedDB.open("ff-prueba-idb", 1);
      q.onupgradeneeded = () => { try { q.result.createObjectStore("x"); } catch (e) {} };
      q.onsuccess = () => { clearTimeout(t); try { q.result.close(); indexedDB.deleteDatabase("ff-prueba-idb"); } catch (e) {} res(true); };
      q.onerror = q.onblocked = () => { clearTimeout(t); res(false); };
    } catch (e) { clearTimeout(t); res(false); }
  });
}
let sinGuardar = false;
function avisoPrivado() {
  if (document.getElementById("aviso-privado")) return;
  const d = document.createElement("div"); d.id = "aviso-privado"; d.className = "aviso-privado";
  d.innerHTML = '<span>Estás en una pestaña privada o sin almacenamiento: la app funciona, pero al cerrar la pestaña tendrás que volver a conectar Google.</span><button type="button" aria-label="Cerrar aviso">✕</button>';
  d.querySelector("button").onclick = () => d.remove();
  document.body.prepend(d);
}

// ---------- tema ----------
function aplicarTema() {
  const t = leer("ff-tema") || "auto";
  if (t === "auto") document.documentElement.removeAttribute("data-tema"); else document.documentElement.dataset.tema = t;
  const oscuro = t === "oscuro" || (t === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#logo").src = "assets/" + (oscuro ? "logo_filmflow_oscuro.png" : "logo_filmflow_claro.png");
}
aplicarTema();
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", aplicarTema);


// ---------- portada: pantalla de inicio y de descanso (igual que en el Mac) ----------
const G_SVG = '<svg viewBox="0 0 48 48" width="22" height="22"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.2 5.5-4.7 7.2l7.6 5.9c4.4-4.1 6.9-10.1 6.9-17.6z"/><path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.8 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/></svg>';
const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
let portadaModo = null, fotoUrl = null, fotoTimer = null, relojTimer = null, fotoIdx = 0;
const portada = $("#portada");
function bd(op) { // IndexedDB de las fotos de descanso
  return new Promise((res, rej) => { try { const q = indexedDB.open("ff-fotos", 1); q.onupgradeneeded = () => q.result.createObjectStore("f", { keyPath: "id", autoIncrement: true });
    q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); } catch (e) { rej(e); } }).then((db) => new Promise((res, rej) => { const r = op(db.transaction("f", "readwrite").objectStore("f")); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }));
}
const fotosLeer = () => bd((s) => s.getAll()).catch(() => []);
const fotosContar = () => bd((s) => s.count()).catch(() => 0);
const fotosBorrar = () => bd((s) => s.clear()).catch(() => {});
async function fotosAgregar(files) {
  let n = 0;
  for (const f of files) {
    try {
      const bmp = await createImageBitmap(f), k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas"); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
      await bd((s) => s.add({ blob })); n++;
    } catch (e) {}
  }
  return n;
}
const minutosDescanso = () => { const v = parseInt(leer("ff-descanso")); return [0, 5, 15, 30, 60].includes(v) ? v : 15; };
const segFoto = () => { const v = parseInt(leer("ff-foto-seg")); return [10, 30, 60, 300].includes(v) ? v : 30; };
function ocultarPortada() {
  portada.hidden = true; portadaModo = null; portada.style.backgroundImage = ""; portada.classList.remove("con-foto");
  clearInterval(relojTimer); clearTimeout(fotoTimer); if (fotoUrl) { URL.revokeObjectURL(fotoUrl); fotoUrl = null; }
  ultimoUso = Date.now();
}
function mostrarPortada(modo) {
  if (portadaModo === modo) return;
  portadaModo = modo; portada.hidden = false;
  if (modo === "inicio") {
    portada.onclick = null; portada.classList.remove("descanso");
    portada.innerHTML = `<div class="p-in"><img class="p-logo" src="assets/logo_filmflow_grande.png" alt="FilmFlow">
      <h1>Tus estadísticos,<br><span>en un solo lugar.</span></h1>
      <p class="p-txt">Registra cada día de rodaje y mira el resumen completo de tu proyecto, leído siempre de tus hojas de Google.</p>
      <button class="p-google" data-js="conectar">${G_SVG}<span>Iniciar sesión con Google</span></button>
      <p class="p-nota">Tus proyectos se sincronizan con la app del Mac.</p></div>`;
  } else {
    portada.classList.add("descanso"); portada.onclick = () => ocultarPortada();
    const pintar = () => {
      const d = new Date();
      portada.innerHTML = `<div class="p-in"><img class="p-logo" src="assets/logo_filmflow_grande.png" alt="FilmFlow">
        <div class="p-hora">${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}</div>
        <div class="p-fecha">${DIAS[d.getDay()][0].toUpperCase() + DIAS[d.getDay()].slice(1)}, ${d.getDate()} de ${MESES[d.getMonth()]}</div>
        <p class="p-nota">En descanso · toca la pantalla para volver</p></div>`;
    };
    pintar(); relojTimer = setInterval(pintar, 15000);
    fotosLeer().then((fs) => {
      if (!fs.length || portadaModo !== "descanso") return;
      const orden = leer("ff-foto-azar") === "1" ? fs.sort(() => Math.random() - 0.5) : fs;
      const poner = () => {
        if (portadaModo !== "descanso") return;
        if (fotoUrl) URL.revokeObjectURL(fotoUrl);
        fotoUrl = URL.createObjectURL(orden[fotoIdx % orden.length].blob); fotoIdx++;
        portada.style.backgroundImage = `url(${fotoUrl})`; portada.classList.add("con-foto");
        if (orden.length > 1) fotoTimer = setTimeout(poner, segFoto() * 1000);
      };
      poner();
    });
  }
}
let ultimoUso = Date.now();
["pointerdown", "touchstart", "keydown", "scroll"].forEach((e) => addEventListener(e, () => { if (portadaModo !== "descanso") ultimoUso = Date.now(); }, { passive: true, capture: true }));
setInterval(() => {
  const m = minutosDescanso();
  if (!m || portadaModo || document.hidden || nOcupado || $("#modal.on") || document.body.classList.contains("sin-sesion") || PRUEBA) return;
  if (Date.now() - ultimoUso > m * 60000) mostrarPortada("descanso");
}, 15000);
async function pintarDescanso() {
  const cont = $("#js-descanso"); if (!cont) return;
  const n = await fotosContar(), m = minutosDescanso();
  const seg = (v, t, js, act) => `<button class="seg ${v === act ? "on" : ""}" data-js="${js}" data-v="${v}">${t}</button>`;
  cont.innerHTML = `<section class="tarjeta"><p class="sub">Se cubre con la pantalla de inicio y la hora si no usas la app. Un toque y vuelves donde estabas.</p>
    <div class="segmentado">${[[0, "Nunca"], [5, "5 min"], [15, "15 min"], [30, "30 min"], [60, "1 h"]].map(([v, t]) => seg(v, t, "descanso_min", m)).join("")}</div>
    <div class="barra-mini llena"><button class="btn" data-js="descansar">Descansar ahora</button></div></section>
    <section class="tarjeta"><h3>Fotos de la pantalla de descanso</h3>
    <p class="sub">${n ? `${n} foto${n === 1 ? "" : "s"} elegida${n === 1 ? "" : "s"}.${n > 1 ? " Se van pasando solas." : ""}` : "Ahora se ve la imagen de FilmFlow. Elige una o varias fotos de tu iPhone y se irán pasando solas."}</p>
    <div class="barra-mini llena"><button class="btn" data-js="elegir_fotos">Elegir fotos…</button>${n ? '<button class="btn" data-js="quitar_fotos">Volver a la de FilmFlow</button>' : ""}</div>
    ${n > 1 ? `<p class="sub" style="margin-top:14px">Cambiar cada</p><div class="segmentado">${[[10, "10 s"], [30, "30 s"], [60, "1 min"], [300, "5 min"]].map(([v, t]) => seg(v, t, "foto_seg", segFoto())).join("")}</div>
    <div class="segmentado" style="margin-top:10px">${seg("0", "En orden", "foto_azar", leer("ff-foto-azar") === "1" ? "1" : "0")}${seg("1", "Al azar", "foto_azar", leer("ff-foto-azar") === "1" ? "1" : "0")}</div>` : ""}</section>`;
}

// ---------- avisos en pantalla ----------
let nOcupado = 0, nProgreso = 0;
function ocupado(on, txt) {
  nOcupado = Math.max(0, nOcupado + (on ? 1 : -1));
  if (on && txt) $("#ocupado-txt").textContent = txt;
  $("#ocupado").classList.toggle("on", nOcupado > 0);
}
function progreso(on) {
  nProgreso = Math.max(0, nProgreso + (on ? 1 : -1));
  $("#progreso").classList.toggle("on", nProgreso > 0);
  $("#btn-actualizar").classList.toggle("gira", nProgreso > 0);
}
let tToast;
function toast(txt) {
  const t = $("#toast"); t.textContent = txt; t.classList.add("on");
  clearTimeout(tToast); tToast = setTimeout(() => t.classList.remove("on"), 4500);
}
// Hoja inferior estilo iPhone. Con `lista` devuelve el valor del renglón tocado; con `input`, el texto; si no, true/null.
function modal({ titulo, texto, input, valor, si = "Aceptar", no = "Cancelar", lista }) {
  return new Promise((res) => {
    const m = $("#modal"), inp = $("#m-input"), l = $("#m-lista");
    $("#m-titulo").textContent = titulo || ""; $("#m-texto").textContent = texto || "";
    inp.style.display = input ? "" : "none"; inp.value = valor || "";
    $("#m-si").textContent = si; $("#m-no").textContent = no;
    $("#m-si").style.display = si ? "" : "none";
    $("#m-no").style.display = no ? "" : "none";
    const fin = (v) => { m.classList.remove("on"); res(v); };
    l.innerHTML = "";
    (lista || []).forEach((it) => {
      const b = document.createElement("button");
      b.className = "fila-sheet" + (it.on ? " on" : "") + (it.accion ? " accion" : "");
      b.innerHTML = `<span></span>${it.on ? '<span class="ok">✓</span>' : ""}`; b.firstChild.textContent = it.txt;
      b.onclick = () => fin(it.valor); l.appendChild(b);
    });
    $("#m-si").onclick = () => fin(input ? inp.value : true);
    $("#m-no").onclick = () => fin(null);
    m.onclick = (e) => { if (e.target === m) fin(null); };
    m.classList.add("on");
    if (input) setTimeout(() => inp.focus(), 80);
  });
}

// ---------- Python en segundo plano ----------
let worker, idMsg = 0, etapaMotor = ""; const pendientes = new Map();
function nuevoWorker() {
  if (MAC) return;                                 // en el Mac el Python corre en el propio Mac
  worker = new Worker("worker.js");
  worker.onerror = (ev) => {                       // el worker no cargó o se cayó (memoria): se avisa a todo lo que esperaba
    const err = new Error("El motor de Python no pudo iniciar: " + ((ev && ev.message) || "el proceso de fondo se detuvo"));
    for (const [, p] of pendientes) p.rej(err);
    pendientes.clear();
  };
  worker.onmessage = (e) => { if (e.data.etapa) { etapaMotor = e.data.etapa; document.querySelectorAll(".etapa-motor").forEach((n) => { n.textContent = etapaMotor; }); const o = $("#ocupado-txt"); if (o && $("#ocupado").classList.contains("on")) o.textContent = etapaMotor; return; } const p = pendientes.get(e.data.id); if (p) { pendientes.delete(e.data.id); e.data.ok ? p.res(e.data) : p.rej(new Error(e.data.error)); } };
}
nuevoWorker();
const mensaje = (m) => new Promise((res, rej) => {
  const id = ++idMsg;
  const limite = m.tipo === "arrancar" ? 200000 : 180000;   // ninguna llamada espera para siempre (cada pedido a Google ya corta a los 45 s)
  const t = setTimeout(() => { if (pendientes.has(id)) { pendientes.delete(id); rej(new Error("La app tardó demasiado en responder (más de " + Math.round(limite / 60000) + " min). Revisa tu conexión e inténtalo otra vez.")); } }, limite);
  pendientes.set(id, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } });
  worker.postMessage({ ...m, id });
});
// Si el motor falla al arrancar (en iPhone a veces una descarga llega a medias), se reintenta solo, bajando los archivos de nuevo.
async function arrancarMotor() {
  if (MAC) { await mac("latido"); return {}; }
  const opc = PRUEBA ? { sheets: PRUEBA.sheets } : {};
  let ultimo;
  sinGuardar = !(await probarIDB());
  for (let i = 0; i < 3; i++) {
    try { return await mensaje({ tipo: "arrancar", base, opciones: { ...opc, forzar: i > 0, sinDatos: i > 1 || sinGuardar } }); }
    catch (e) { ultimo = e; try { worker.terminate(); } catch (_) {} pendientes.clear(); nuevoWorker(); await new Promise((r) => setTimeout(r, 700)); }
  }
  throw ultimo;
}
let motorListo = arrancarMotor();
let motorFallo = false;
motorListo.catch(() => { motorFallo = true; });
let ofreciendoReparar = false;
async function ofrecerReparar(e) {
  if (ofreciendoReparar) return; ofreciendoReparar = true;
  ocupado(false); progreso(false);
  const rep = await modal({ titulo: "No pude arrancar la app", si: "Reparar y reintentar", no: "Cerrar",
    texto: "Pasa a veces cuando los archivos guardados en el teléfono quedaron a medias. «Reparar» los borra de este teléfono y vuelve a abrir la app; tus proyectos se recuperan solos desde tu cuenta de Google (no se pierde nada de tus hojas).\n\nDetalle técnico:\n" + String(e.message).slice(0, 500) });
  ofreciendoReparar = false;
  if (rep) await repararDatos();
}

async function llamar(nombre, p = {}) {
  await motorListo;
  if (MAC) return await mac("llamar", { nombre, p });
  const out = await mensaje({ tipo: "llamar", nombre, p, token: tokenVigente(), correo: sesion.correo });
  return out.r;
}
// «Silenciosas»: no ponen nada en pantalla mientras trabajan. «Bloqueantes»: tapan la pantalla (escriben o tardan). El resto: barra de progreso arriba.
const SILENCIOSAS = new Set(["correo_destinos", "correo_elegir_firma", "firma_agregar", "firma_quitar", "correo_armar", "correo_resultado", "correo_enviar", "resumen_muestra", "resumen_panel", "reporte_seccion", "reporte_orden", "reporte_modo_rapido", "reporte_nombre", "marcar", "marcar_seg", "alternar_vista", "mas_hallazgos", "decision", "casilla", "unidad", "correo_prefijo", "cancelar_formulario",
  "conectar_cancelar", "importar_cancelar", "mover_rollo", "quitar_rollo", "editar_rollo", "agregar_rollo", "renombrar_pedir", "nuevo_pedir", "eliminar_proyecto",
  "quitar_estadistico", "quitar_estatus", "estatus_principal", "ir", "corregir_cruce", "corregir_errores", "escribir", "conectar_abrir"]);
const TEXTO_OCUPADO = { revisar: "Leyendo el PDF y tus hojas de Google…", escribir_ok: "Escribiendo en tus hojas y comprobándolas…",
  conectar_buscar: "Buscando la hoja…", conectar_usar: "Comprobando que entiendo la hoja…",
  importar_buscar: "Leyendo tu hoja para encontrar los rollos…", corregir_cruce_ok: "Corrigiendo el estadístico…",
  corregir_errores_ok: "Corrigiendo el estatus de tarjetas…", correo_pdf: "Leyendo el PDF…", sincronizar: "Sincronizando…" };

async function api(nombre, p = {}) {
  const silenciosa = SILENCIOSAS.has(nombre);
  const bloquea = nombre in TEXTO_OCUPADO && nombre !== "sincronizar";
  if (bloquea) ocupado(true, TEXTO_OCUPADO[nombre]); else if (!silenciosa) progreso(true);
  try {
    let r = await llamar(nombre, p);
    if (r.auth401 && !PRUEBA) {
      if (navigator.userActivation?.isActive) {
        const t = await pedirToken(false);
        if (t) r = await llamar(nombre, p);
      } else { revisarRed(); r = { toast: "La sesión de Google venció. Toca «Reconectar» arriba." }; }
    }
    return r;
  } catch (e) {
    if (motorFallo || /motor de Python|módulos de Python|ExitStatus|python_stdlib|No pude cargar|Falló al preparar/.test(String(e.message))) { ofrecerReparar(e); return null; }
    return { error: "Algo salió mal en la app del teléfono.\n\n" + e.message };
  } finally {
    if (bloquea) ocupado(false); else if (!silenciosa) progreso(false);
  }
}

// ---------- cuenta de Google ----------
function tokenVigente() {
  if (PRUEBA) return PRUEBA.token;
  if (MAC) return sesion.token;
  return sesion.token && Date.now() < sesion.exp - 60000 ? sesion.token : null;
}
function cargarSesion() {
  if (PRUEBA) { sesion = { token: PRUEBA.token, exp: Date.now() + 36e5, correo: PRUEBA.correo }; return; }
  try { const s = JSON.parse(leer("ff-sesion") || "null"); if (s && Date.now() < s.exp - 60000) sesion = s; } catch (e) {}
}
function cargarGIS() {
  return new Promise((res, rej) => {
    if (window.google?.accounts?.oauth2) return res();
    const s = document.createElement("script"); s.src = "https://accounts.google.com/gsi/client"; s.async = true;
    s.onload = () => res(); s.onerror = () => rej(new Error("No pude cargar el inicio de sesión de Google (¿sin internet?)."));
    document.head.appendChild(s);
  });
}
let errorConexion = "";
const PERMISO_DRIVE = "https://www.googleapis.com/auth/drive.file";
// include_granted_scopes en false: Google NO junta los permisos que esa cuenta dio antes a otro uso del mismo proyecto de Google Cloud
// (p. ej. youtube.upload para subir el video de la verificación): «drive.file» y «youtube.upload» no se pueden pedir juntos y Google
// bloqueaba la entrada (Error 400: invalid_request). Se pide siempre la lista completa (PERMISOS, + drive al compartir).
function crearCliente(scope) {
  return google.accounts.oauth2.initTokenClient({ client_id: CFG.clientId, scope, include_granted_scopes: false, callback: () => {}, error_callback: () => {} });
}
// Importante: en el iPhone la ventana de Google solo se abre si se pide en el MISMO toque del dedo.
// Por eso GIS se carga desde que arranca la app y aquí no hay ningún «await» antes de pedir el permiso.
function pedirTokenYa(interactivo, scope) {
  return new Promise((res0) => {
    let hecho = false;
    const res = (v) => { if (!hecho) { hecho = true; clearTimeout(tLim); res0(v); } };
    const tLim = setTimeout(() => { errorConexion = errorConexion || "sin_respuesta"; res(null); }, 90000);
    cliente = crearCliente(scope);
    cliente.callback = async (r) => {
      if (!r || r.error || !r.access_token) { errorConexion = (r && (r.error_description || r.error)) || "sin_respuesta"; return res(null); }
      sesion = { token: r.access_token, exp: Date.now() + (r.expires_in || 3600) * 1000, correo: sesion.correo, permisos: r.scope || "" };
      try {
        const u = await (await fetch("https://www.googleapis.com/oauth2/v3/userinfo", { headers: { Authorization: "Bearer " + r.access_token } })).json();
        sesion.correo = u.email || sesion.correo || null;
      } catch (e) {}
      guardar("ff-sesion", JSON.stringify(sesion));
      if (sesion.correo) guardar("ff-correo", sesion.correo);
      res(sesion.token);
    };
    // En Safari del iPhone la ventana de Google es otra pestaña y Google avisa «popup_closed» aunque el inicio de sesión siga: se espera
    // un poco la respuesta de verdad antes de dar el error (si llega, `res` ya resolvió con el token y esto no hace nada).
    cliente.error_callback = (e) => {
      errorConexion = (e && e.type) || "popup";
      if (errorConexion === "popup_closed") setTimeout(() => res(null), 15000); else res(null);
    };
    try { cliente.requestAccessToken({ prompt: interactivo ? "select_account" : "" }); }
    catch (e) { errorConexion = "popup_failed_to_open"; res(null); }
  });
}
// ---- App instalada en la pantalla de inicio (iPhone/iPad): la ventanita de Google pierde el camino de vuelta cuando se entra con un
// correo NUEVO (hay que escribir correo y contraseña), así que solo funcionaba con la cuenta que ya tenía la sesión abierta. Ahí se usa
// el inicio de sesión «por redirección»: la misma pantalla va a Google y Google la devuelve a la app con el permiso (#access_token=…).
// La dirección de regreso (…/app/) debe estar en Google Cloud → Clientes → «Cliente web 1» → URI de redireccionamiento autorizados.
const ES_APP_INSTALADA = navigator.standalone === true || !!(window.matchMedia && matchMedia("(display-mode: standalone)").matches);
function urlDeRegreso() { return location.origin + location.pathname.replace(/index\.html$/, ""); }
function irAGoogle(scope) {
  const estado = Math.random().toString(36).slice(2) + Date.now().toString(36);
  guardar("ff-oauth", JSON.stringify({ e: estado, scope, p: actual }));
  const q = new URLSearchParams({ client_id: CFG.clientId, redirect_uri: urlDeRegreso(), response_type: "token", scope,
    include_granted_scopes: "false", prompt: "select_account", state: estado });
  location.href = "https://accounts.google.com/o/oauth2/v2/auth?" + q.toString();
}
async function regresoDeGoogle() {
  if (!/(^#|&)(access_token|error)=/.test(location.hash)) return null;
  const h = new URLSearchParams(location.hash.slice(1));
  history.replaceState(null, "", location.pathname + location.search);          // el permiso no se queda en la dirección
  let g = null; try { g = JSON.parse(leer("ff-oauth") || "null"); } catch (e) {}
  guardar("ff-oauth", "null");
  if (g && h.get("state") !== g.e) { errorConexion = "estado"; return "error"; }
  if (h.get("error")) {
    if (/scope/i.test(h.get("error")) && g && g.scope.includes("drive")) {      // Google no aceptó el permiso de Drive: se entra sin él
      irAGoogle(g.scope.split(" ").filter((x) => !x.includes("drive")).join(" ")); return "redirige";
    }
    errorConexion = h.get("error"); return "error";
  }
  const tok = h.get("access_token");
  sesion = { token: tok, exp: Date.now() + (parseInt(h.get("expires_in"), 10) || 3600) * 1000, correo: null, permisos: h.get("scope") || "" };
  try {
    const u = await (await fetch("https://www.googleapis.com/oauth2/v3/userinfo", { headers: { Authorization: "Bearer " + tok } })).json();
    sesion.correo = u.email || null;
  } catch (e) {}
  guardar("ff-sesion", JSON.stringify(sesion));
  if (sesion.correo) guardar("ff-correo", sesion.correo);
  return "ok";
}
async function sesionMac() {          // la sesión de Google del Mac (token.json)
  try { const s = await mac("sesion"); sesion = s.correo ? { token: "mac", exp: Date.now() + 1e12, correo: s.correo, permisos: s.permisos || "" } : { token: null, exp: 0, correo: null }; }
  catch (e) { sesion = { token: null, exp: 0, correo: null }; }
  if (sesion.correo) guardar("ff-correo", sesion.correo);
  return sesion.token;
}
async function pedirToken(interactivo) {
  if (PRUEBA) return PRUEBA.token;
  if (MAC) {                           // se abre el navegador del Mac para elegir la cuenta (como siempre en la app del Mac)
    if (!interactivo) return await sesionMac();
    ocupado(true, "Elige tu cuenta de Google en el navegador que se abrió…");
    try { const r = await mac("entrar", {}); if (r.error) { errorConexion = r.error; return null; } }
    finally { ocupado(false); }
    return await sesionMac();
  }
  errorConexion = "";
  if (!CFG.clientId) {
    await modal({ titulo: "Falta un paso de instalación", si: "Entendido", no: "",
      texto: "Esta app todavía no tiene el «ID de cliente» de Google.\n\nQuien instaló la app debe pegarlo en el archivo config.js (está explicado en el LEEME). Sin ese dato Google no deja iniciar sesión." });
    return null;
  }
  if (!window.google?.accounts?.oauth2) {            // aún no cargó: se carga y se pide al siguiente toque
    try { await cargarGIS(); } catch (e) { errorConexion = "red"; return null; }
    errorConexion = "toca_otra_vez"; return null;
  }
  const DRIVE_TODO = "https://www.googleapis.com/auth/drive";                   // si ya dio el permiso de compartir, se sigue pidiendo
  const conCompartir = (sesion && (sesion.permisos || "").split(" ").includes(DRIVE_TODO)) ? " " + DRIVE_TODO : "";
  let t = await pedirTokenYa(interactivo, PERMISOS + conCompartir);
  if (!t && interactivo && /invalid_scope|scope/i.test(errorConexion)) {          // Google no aceptó el permiso de Drive: se entra sin él
    t = await pedirTokenYa(interactivo, PERMISOS.split(" ").filter((x) => !x.includes("drive")).join(" "));
  }
  return t;
}
function textoErrorConexion() {
  const e = errorConexion || "";
  if (e === "red") return "No pude cargar el inicio de sesión de Google. Revisa tu internet y vuelve a tocar el botón.";
  if (e === "toca_otra_vez") return "Ya está lista la conexión con Google. Toca el botón otra vez.";
  if (e === "popup_failed_to_open") return "Safari no abrió la ventana de Google. Toca el botón otra vez. Si sigue igual, en Ajustes → Safari desactiva «Bloquear ventanas emergentes».";
  if (e === "popup_closed") return "Cerraste la ventana de Google antes de terminar. Toca el botón para intentarlo otra vez.";
  if (/access_denied/i.test(e)) return "No se dio el permiso: en la pantalla de Google hay que tocar «Continuar» y marcar TODAS las casillas (si sale «Google no verificó esta app», toca «Configuración avanzada» → «Ir a …»).";
  if (e === "estado") return "El inicio de sesión no terminó bien (la respuesta de Google no coincide). Vuelve a tocar el botón.";
  if (MAC && e) return e;
  if (/redirect_uri/i.test(e)) return "Google no reconoce la dirección de la app para volver. Avísale a quien administra la app (Google Cloud → URI de redireccionamiento).";
  return "No se conectó la cuenta de Google" + (e && e !== "sin_respuesta" ? " (" + e + ")" : "") + ". Vuelve a intentarlo.";
}
async function conectar() {
  if (ES_APP_INSTALADA && !PRUEBA && !MAC && CFG.clientId) { irAGoogle(PERMISOS); return; }
  const t = await pedirToken(true);
  if (t) {
    toast("Cuenta conectada" + (sesion.correo ? ": " + sesion.correo : ""));
    const _p = actual; document.body.classList.remove("sin-sesion"); ocultarPortada();
    await ir(PAGINAS_GOOGLE.has(_p) ? _p : "resumen", false);
    if (leer("ff-unirse") && leer("ff-unirse") !== "null") await procesarInvitacion(); else sincronizar(false);
  } else if (CFG.clientId || MAC) {
    if (errorConexion === "toca_otra_vez") toast(textoErrorConexion());
    else await modal({ titulo: "No se pudo conectar", texto: textoErrorConexion(), si: "Entendido", no: "" });
  }
}
async function desconectar() {
  const ok = await modal({ titulo: "Desconectar", texto: "¿Desconecto tu cuenta de Google de este teléfono? Tus hojas y tus proyectos no se tocan.", si: "Desconectar" });
  if (!ok) return;
  if (MAC) { try { await mac("salir"); } catch (e) {} }
  else try { google.accounts.oauth2.revoke(sesion.token, () => {}); } catch (e) {}
  sesion = { token: null, exp: 0, correo: null }; guardar("ff-sesion", "null");
  delete memoria["ff-correo"]; try { localStorage.removeItem("ff-correo"); sessionStorage.removeItem("ff-correo"); } catch (e) {}
  await ir(actual, true);
}

// ---------- sincronización con el Mac ----------
let sincronizando = false, tSync = null;
async function sincronizar(manual) {
  if (sincronizando || !tokenVigente()) return;
  sincronizando = true; $("#btn-actualizar").classList.add("gira");
  try { await mostrar(await llamar("sincronizar", { manual: !!manual })); }
  catch (e) { /* sincronizar nunca molesta */ }
  finally { sincronizando = false; if (!nProgreso) $("#btn-actualizar").classList.remove("gira"); }
}
const modalAbierto = () => { const m = document.getElementById("modal"); return !!(m && m.classList.contains("on")); };
setInterval(async () => { if (!navigator.onLine && !document.hidden) await probarRed(); if (!document.hidden && enLinea && tokenVigente() && !nOcupado && !nProgreso && !modalAbierto()) sincronizar(false); }, 60000);
function programarSync() { clearTimeout(tSync); tSync = setTimeout(() => sincronizar(false), 3500); }

// ---------- pantallas ----------
let ultimaTab = "resumen";
function resaltarTab() { document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.ir === actual)); $("#btn-app").classList.toggle("on", actual === "app"); }
function actualizarProyectos(info) {
  if (!info || !info.proyectos) return;
  proyectos = { lista: info.proyectos, activo: info.activo, abrev: info.abrev || {} };
  $("#proyecto-nombre").textContent = info.activo || "—";
  if (!PRUEBA) guardar("ff-proy", JSON.stringify(proyectos));
}
function abiertos() { return [...vista.querySelectorAll("details[data-k][open]")].map((d) => d.dataset.k); }
// Lo que abriste o plegaste se respeta al volver a dibujar la pantalla (y los paneles del reporte, también al volver a abrir la app).
let plegEstado = {}; try { plegEstado = JSON.parse(leer("ff-pleg") || "{}") || {}; } catch (e) {}
document.addEventListener("toggle", (e) => {
  const d = e.target; if (!d || !d.matches || !d.matches("details[data-k]") || d.dataset.restaurando) return;
  plegEstado[d.dataset.k] = d.open;
  guardar("ff-pleg", JSON.stringify(Object.fromEntries(Object.entries(plegEstado).filter(([k]) => k.startsWith("rep-") || k.startsWith("app-")))));
}, true);
function restaurarAbiertos(claves) {
  vista.querySelectorAll("details[data-k]").forEach((d) => {
    const k = d.dataset.k, quiere = k in plegEstado ? plegEstado[k] : (claves.includes(k) || d.open);
    if (d.open !== quiere) { d.dataset.restaurando = "1"; d.open = quiere; setTimeout(() => { delete d.dataset.restaurando; }, 0); }
  });
}
// Gráfica «Volumen por día» dibujada al ancho real (1 unidad = 1 píxel): letras de 11–12 px en el celular y en el computador,
// barras de 64 px como mucho y rótulos de días que no se amontonan. Se vuelve a dibujar si cambia el ancho (girar, ventana).
const vigiaGrafico = window.ResizeObserver ? new ResizeObserver((es) => requestAnimationFrame(() => es.forEach((e) => dibujarGrafico(e.target)))) : null;
function dibujarGrafico(g) {
  let d; try { d = JSON.parse(g.dataset.g); } catch (e) { return; }
  const W = Math.round(g.clientWidth); if (!W || W === +g.dataset.w) return; g.dataset.w = W;
  const ancha = W >= 560, Hh = ancha ? 240 : 200, izq = 40, der = 6, arr = 30, aba = 24, base = Hh - aba, n = d.v.length;
  const techo = Math.max(...d.v, 1) * 1.08, paso = (W - izq - der) / n, ancho = Math.max(2, Math.min(paso * 0.62, 64));
  const yDe = (gb) => base - (base - arr) * gb / techo, x = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const o = [];
  [[0, "0"], [0.5, d.e[0]], [1, d.e[1]]].forEach(([fr, t]) => {
    const y = base - (base - arr) * fr;
    o.push(`<line x1="${izq}" x2="${W - der}" y1="${y}" y2="${y}" class="rej"/><text x="${izq - 6}" y="${y + 4}" text-anchor="end" class="eje" font-size="11">${x(t)}</text>`);
  });
  d.v.forEach((gb, i) => {
    const h = (base - arr) * gb / techo, xx = izq + paso * i + (paso - ancho) / 2;
    if (h > 0.5) o.push(`<rect x="${xx.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${ancho.toFixed(1)}" height="${h.toFixed(1)}" rx="${Math.min(ancho / 2, 6).toFixed(1)}" class="col${i === n - 1 ? " ult" : ""}" data-i="${i}"/>`);
  });
  if (d.p) {
    const y = yDe(d.p);
    const txt = "promedio" + (d.pt ? " " + d.pt : ""), tw = Math.ceil(txt.length * 6.4) + 14, ty = Math.max(arr - 4, y - 22);
    o.push(`<line x1="${izq}" x2="${W - der}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" class="prom"/>`
      + `<rect x="${W - der - tw}" y="${ty.toFixed(1)}" width="${tw}" height="18" rx="9" class="prom-fondo"/>`
      + `<text x="${W - der - tw / 2}" y="${(ty + 13).toFixed(1)}" text-anchor="middle" class="prom-t" font-size="11">${x(txt)}</text>`);
  }
  const cada = Math.max(1, Math.ceil(n / Math.max(1, Math.floor((W - izq - der) / 34))));
  for (let i = 0; i < n; i += cada) o.push(`<text x="${(izq + paso * i + paso / 2).toFixed(1)}" y="${base + 16}" text-anchor="middle" class="eje" font-size="11">${x(d.d[i])}</text>`);
  o.push(`<rect class="hit" x="${izq}" y="0" width="${W - izq - der}" height="${base + 4}" fill="transparent"/>`);
  o.push('<g class="tip" pointer-events="none" visibility="hidden"><rect rx="11" height="24"/><text y="16" font-size="12" font-weight="700"></text></g>');
  const svg = g.querySelector("svg"); svg.setAttribute("viewBox", `0 0 ${W} ${Hh}`); svg.innerHTML = o.join("");
}
function prepararGraficos(raiz) {
  (raiz || document).querySelectorAll(".grafico[data-g]").forEach((g) => { dibujarGrafico(g); if (vigiaGrafico) vigiaGrafico.observe(g); });
}
// ---- Rueda de semanas (como la del reloj del iPhone): cada .ri-lista se desliza con «scroll-snap»; al soltar, la semana que quedó
// en la franja del centro se manda a Python (acción «reporte_semanas»). Mientras gira, cada renglón se inclina y se apaga según lo
// lejos que esté del centro (efecto de tambor). Tocar un renglón lo trae al centro.
const ALTO_RUEDA = 40;
function pintarTambor(lista) {
  const centro = lista.scrollTop + lista.clientHeight / 2;
  const its = lista.querySelectorAll(".ri-it");
  let cerca = null, mejor = 1e9;
  its.forEach((it) => {
    const d = (it.offsetTop + it.offsetHeight / 2 - centro) / ALTO_RUEDA, a = Math.min(Math.abs(d), 3);
    it.style.transform = `perspective(400px) rotateX(${Math.max(-60, Math.min(60, -d * 18))}deg) scale(${1 - a * 0.07})`;
    it.style.opacity = String(Math.max(0.15, 1 - a * 0.3));
    if (Math.abs(d) < mejor) { mejor = Math.abs(d); cerca = it; }
  });
  its.forEach((it) => it.classList.toggle("centro", it === cerca));
  return cerca;
}
function prepararRuedas(raiz) {
  (raiz || document).querySelectorAll(".ri-lista").forEach((lista) => {
    const sel = lista.querySelector(".ri-it.sel");
    if (sel) lista.scrollTop = sel.offsetTop + sel.offsetHeight / 2 - lista.clientHeight / 2;
    pintarTambor(lista);
    if (lista.dataset.listo) return;
    lista.dataset.listo = "1";
    let quieto = null, pintando = false;
    const soltar = async () => {
      const it = pintarTambor(lista);
      if (!it || it.classList.contains("sel")) return;
      lista.querySelectorAll(".ri-it.sel").forEach((x) => x.classList.remove("sel")); it.classList.add("sel");
      if (navigator.vibrate) { try { navigator.vibrate(8); } catch (e) {} }
      mostrar(await api("reporte_semanas", { columna: lista.dataset.rueda, id: it.dataset.id }));
    };
    lista.addEventListener("scroll", () => {
      if (!pintando) { pintando = true; requestAnimationFrame(() => { pintando = false; pintarTambor(lista); }); }
      clearTimeout(quieto); quieto = setTimeout(soltar, 160);
    }, { passive: true });
    lista.addEventListener("click", (e) => {
      const it = e.target.closest(".ri-it"); if (!it) return;
      lista.scrollTo({ top: it.offsetTop + it.offsetHeight / 2 - lista.clientHeight / 2, behavior: "smooth" });
    });
    lista.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault(); lista.scrollBy({ top: e.key === "ArrowDown" ? ALTO_RUEDA : -ALTO_RUEDA, behavior: "smooth" });
    });
  });
}
function ponerPasoReporte() {        // pestaña «Reporte» en el teléfono: Días / Contenido / Vista previa (uno a la vez)
  const g = vista.querySelector(".rep-grid"); if (!g) return;
  const paso = leer("ff-rep-paso") || "dias";
  g.dataset.paso = paso;
  vista.querySelectorAll('.rep-pasos .seg').forEach((b) => { b.classList.toggle("on", b.dataset.v === paso); b.setAttribute("aria-selected", b.dataset.v === paso); });
  prepararRuedas(g);
  if (innerWidth >= 1000) vista.querySelectorAll("details.sec-grupo").forEach((d) => { d.open = true; });
}
function posprocesar() {
  prepararGraficos(vista); prepararRuedas(vista); ponerPasoReporte();
  vista.querySelectorAll("form").forEach(alternarTipo);
  $("#btn-actualizar").style.display = actual === "resumen" ? "" : "none";
  if (actual === "app") { pintarDescanso(); pintarVersion(); }
  if (actual === "correo") {
    const pr = ($("#proyecto-nombre") || {}).textContent || "";
    if (pr !== proyectoDelCorreo) { fueraEstaVez.clear(); proyectoDelCorreo = pr; }
    pintarAdjuntos(); aplicarFuera();
    if (enviando) modoEnviando(true);
  }
  vista.querySelectorAll('.seg[data-js="tema"]').forEach((b) => b.classList.toggle("on", b.dataset.v === (leer("ff-tema") || "auto")));
}
function alternarTipo(form) {
  const sel = form.querySelector('[data-form="tipo"]:checked');
  if (!sel) return;
  form.querySelectorAll("[data-solo]").forEach((el) => { el.style.display = el.dataset.solo === sel.value ? "" : "none"; });
}
function ponerBarra(html) {
  const b = $("#accion-fija");
  if (html) { b.innerHTML = '<div class="in">' + html + "</div>"; b.hidden = false; document.documentElement.style.setProperty("--fijo", (b.offsetHeight || 80) + "px"); }
  else { b.hidden = true; b.innerHTML = ""; document.documentElement.style.setProperty("--fijo", "0px"); }
}
function bienvenida() {
  const correo = leer("ff-correo");
  const oscuro = ($("#logo").src || "").includes("oscuro");
  return `<section class="bienvenida"><img class="logo-grande" src="assets/${oscuro ? "logo_filmflow_grande.png" : "logo_filmflow_grande_claro.png"}" alt="FilmFlow">
    <h2>${correo ? "Te damos la bienvenida otra vez" : "Estadístico FilmFlow"}</h2>
    <p>${correo ? "Tu sesión de Google venció (dura una hora). Tócala para seguir como " + esc(correo) + "." : "Registra tus días de rodaje y revisa tus estadísticos desde el teléfono."}</p>
    <div class="beneficios">
      <div class="beneficio"><span class="ico">🔄</span><div><b>Igual que en tu Mac</b><span class="t">Tus proyectos y hojas aparecen solos al entrar con tu cuenta de Google.</span></div></div>
      <div class="beneficio"><span class="ico">📄</span><div><b>El PDF no sale del teléfono</b><span class="t">Se lee aquí; solo se escribe en tus hojas cuando tú confirmas.</span></div></div>
      <div class="beneficio"><span class="ico">📊</span><div><b>Resumen y revisión</b><span class="t">TB por cámara, rollo actual y errores entre tus dos hojas.</span></div></div>
    </div>
    <button class="btn acento grande-btn" data-js="conectar">${correo ? "Continuar con Google" : "Conectar con Google"}</button>
    <p class="nota" style="margin-top:14px">Tip: en Safari toca Compartir → «Agregar a pantalla de inicio» para usarla como una app.</p></section>`;
}
function cabeza(nombre) {
  const t = { resumen: "Resumen", registrar: "Registrar día", hojas: "Hojas conectadas", reporte: "Reporte", correo: "Correo", ajustes: "Ajustes del proyecto", app: "Ajustes de la app" }[nombre];
  const atras = nombre === "app" ? `<button class="atras" data-ir="${ultimaTab}">‹ Volver</button>` : "";
  return `<header class="cab-pagina">${atras}<h1>${t}</h1></header>`;
}
const claveCache = () => "ff-res-" + (proyectos.activo || "");
async function ir(nombre, mantener) {
  actual = nombre; if (nombre !== "app") ultimaTab = nombre; resaltarTab();
  document.body.classList.remove("vista-grande");
  const sinSesion = !tokenVigente() && !PRUEBA && !leer("ff-correo");        // nunca ha conectado: solo la pantalla de inicio
  document.body.classList.toggle("sin-sesion", sinSesion);
  revisarRed();
  if (sinSesion) { ponerBarra(null); mostrarPortada("inicio"); return; }
  if (portadaModo === "inicio") ocultarPortada();
  if (!tokenVigente() && !PRUEBA && (nombre === "resumen" || nombre === "registrar")) {      // sesión vencida o sin internet: se ve lo último guardado
    ponerBarra(null);
    let cuerpo = "";
    const c = nombre === "resumen" ? leer(claveCache()) : null;
    if (c) { try { const o = JSON.parse(c); if (o.html) cuerpo = `<div class="estado aviso"><span class="ico">⏱</span><span>Mostrando lo último guardado (${haceCuanto(o.t)}). ${enLinea ? "Reconecta con Google para actualizar." : "Cuando vuelva el internet se actualiza."}</span></div>` + o.html; } catch (e) {} }
    if (!cuerpo) cuerpo = `<section class="tarjeta vacia"><div class="grande">🔒</div><h3>${enLinea ? "Reconecta con Google" : "Sin conexión"}</h3><p class="nota">${nombre === "registrar" ? "Para registrar un día necesito leer y escribir en tus hojas." : "Todavía no hay datos guardados de este proyecto en el teléfono."}</p>${enLinea ? '<button class="btn acento" data-js="conectar">Reconectar con Google</button>' : ""}</section>`;
    vista.innerHTML = cabeza(nombre) + cuerpo; posprocesar(); scrollTo(0, 0); return;
  }
  let conCache = false;
  if (nombre === "resumen" && !PRUEBA) {          // se ve al instante lo último guardado y se actualiza detrás
    const c = leer(claveCache());
    if (c) { try { const o = JSON.parse(c); if (o.html) { vista.innerHTML = cabeza("resumen") + o.html; vista.classList.add("carga"); conCache = true; posprocesar(); } } catch (e) {} }
  }
  if (!conCache && !mantener) vista.innerHTML = cabeza(nombre) + '<section class="tarjeta vacia"><div class="grande carga">↻</div><h3>Un momento…</h3><p class="nota etapa-motor">' + esc(etapaMotor) + '</p></section>';
  const r = await api("pagina", { nombre });
  vista.classList.remove("carga");
  await mostrar(r, true);
  if (!mantener) scrollTo(0, 0);
}
async function mostrar(r, nuevaPagina) {
  if (!r) return;
  if (r.error) { await modal({ titulo: "Algo salió mal", texto: r.error, si: "Cerrar", no: "" }); return; }
  if (r.proyectos && typeof r.proyectos === "object") actualizarProyectos(r.proyectos);
  if (r.ir) { if (r.toast) toast(r.toast); return ir(r.ir); }
  if (r.html !== undefined && r.pagina === actual) {
    const y = scrollY, abiertas = abiertos();
    vista.dataset.pagina = actual;
    document.documentElement.classList.toggle("en-reporte", actual === "reporte");
    vista.innerHTML = cabeza(actual) + r.html; posprocesar(); restaurarAbiertos(abiertas);
    if (r.subtitulo) { const h = vista.querySelector(".cab-pagina"); if (h) h.insertAdjacentHTML("beforeend", `<p>${r.subtitulo}</p>`); }
    if (!nuevaPagina) scrollTo(0, y);
    ponerBarra(r.barra || null);
    if (r.scroll) setTimeout(() => vista.querySelector(r.scroll)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    if (actual === "resumen" && !PRUEBA && !r.html.includes("Un momento") && !r.html.includes('id="reporte-panel"')) guardar(claveCache(), JSON.stringify({ html: r.html, t: Date.now() }));
  }
  if (r.preview !== undefined && r.pagina === actual) pintarVista(r.preview);
  if (r.toast) toast(r.toast);
  if (r.reporte) await abrirReporte(r.reporte);
  if (r.sync_pendiente && tokenVigente()) programarSync();
  if (r.recargar) await ir(actual, true);
  if (r.confirmar) {
    const c = r.confirmar;
    if (await modal({ titulo: c.titulo, texto: c.texto, si: c.boton || "Aceptar" })) mostrar(await api(c.accion, c.p || {}));
  }
  if (r.pedir_permiso) {             // «Equipo del proyecto»: compartir hojas pide a Google un permiso más (se va a Google y se vuelve solo)
    const c = r.pedir_permiso;
    if (await modal({ titulo: "Falta un permiso de Google", texto: c.texto, si: "Dar permiso" })) {
      if (MAC) {                        // en el Mac: se abre el navegador, das el permiso y se sigue aquí mismo
        ocupado(true, "Da el permiso en el navegador que se abrió…");
        let r; try { r = await mac("entrar", { extra: [c.scope] }); } finally { ocupado(false); }
        if (r && r.error) await modal({ titulo: "No se dio el permiso", texto: r.error, si: "Entendido", no: "" });
        else { await sesionMac(); if (c.luego && c.luego.accion) mostrar(await api(c.luego.accion, c.luego.p || {})); }
        return;
      }
      guardar("ff-pendiente", JSON.stringify(c.luego || null));
      irAGoogle(PERMISOS + " " + c.scope);
    }
  }
  if (r.pedir) {
    const c = r.pedir, v = await modal({ titulo: c.titulo, texto: c.texto, input: true, valor: c.valor, si: c.boton || "Guardar" });
    if (v !== null) mostrar(await api(c.accion, { valor: v }));
  }
}

// ---------- selector de proyecto ----------
async function elegirProyecto() {
  const lista = proyectos.lista.map((n) => ({ txt: n, valor: "p:" + n, on: n === proyectos.activo }));
  lista.push({ txt: "＋ Nuevo proyecto…", valor: "nuevo", accion: true }, { txt: "Renombrar este proyecto…", valor: "renombrar", accion: true });
  const v = await modal({ titulo: "Proyecto", texto: "", lista, si: "", no: "Cerrar" });
  if (!v) return;
  if (v === "nuevo") return mostrar(await api("nuevo_pedir"));
  if (v === "renombrar") return mostrar(await api("renombrar_pedir"));
  const n = v.slice(2);
  if (n !== proyectos.activo) mostrar(await api("elegir_proyecto", { nombre: n }));
}

// ---------- PDF ----------
function elegirPdf() {
  return new Promise((res) => {
    const inp = $("#selector-pdf"); inp.value = "";
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return res(null);
      ocupado(true, "Leyendo el PDF…");
      try { res({ nombre: f.name, texto: await textoDelPdf(await f.arrayBuffer()) }); }
      catch (e) { toast("No pude leer ese PDF."); res(null); }
      finally { ocupado(false); }
    };
    inp.click();
  });
}

// ---------- correo ----------
function lineasDelCorreo() {
  return [...document.querySelectorAll("#correo-texto .l")].map((l) =>
    l.classList.contains("v") ? [] : [...l.childNodes].map((n) => [n.textContent, n.nodeName === "B"]).filter((x) => x[0]));
}
const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function aHtml(ls) {
  const f = ls.map((l) => !l.length ? '<div style="font-size:7px;line-height:9px"><br></div>'
    : '<div style="margin:0;line-height:1.3">' + l.map(([t, b]) => b ? `<b>${esc(t)}</b>` : esc(t)).join("") + "</div>");
  return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.3">' + f.join("") + "</div>";
}
async function copiar(texto, html) {
  try {
    if (html && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([texto], { type: "text/plain" }) })]);
      return true;
    }
    await navigator.clipboard.writeText(texto); return true;
  } catch (e) { return false; }
}

const JS = {
  conectar, desconectar,
  ver_seccion(el) { verSeccion(el.dataset.sec, true); },
  async muestra_panel(el) {                  // Ajustes de la app: muestra aquí mismo cómo se ve esa parte del Resumen (burbuja)
    const ya = document.querySelector(".burbuja");
    if (ya && ya.dataset.panel === el.dataset.panel) { cerrarBurbuja(); return; }
    cerrarBurbuja();
    const b = document.createElement("div"); b.className = "burbuja cargando"; b.dataset.panel = el.dataset.panel;
    b.innerHTML = '<div class="burbuja-in"><p class="sub">Preparando la muestra…</p></div>';
    document.body.appendChild(b); ponerBurbuja(b, el);
    const r = await api("resumen_muestra", { id: el.dataset.panel });
    if (!document.body.contains(b) || !r || !r.muestra) return;
    b.classList.remove("cargando");
    b.innerHTML = `<div class="burbuja-cab"><b>${r.muestra.titulo}</b><button type="button" class="burbuja-x" aria-label="Cerrar muestra" title="Cerrar">✕</button></div>
      <div class="burbuja-in"><div class="burbuja-escala">${r.muestra.html}</div></div>`;
    b.querySelectorAll("details").forEach((d) => { d.open = true; });
    b.querySelectorAll("button:not(.burbuja-x), a, input").forEach((x) => { x.tabIndex = -1; });
    prepararGraficos(b);
    ponerBurbuja(b, el);
  },
  ampliar_vista(el) {                       // la vista previa en grande, en toda la ventana (se sigue pudiendo ordenar)
    const on = document.body.classList.toggle("vista-grande");
    document.querySelectorAll('[data-js="ampliar_vista"]').forEach((b) => { b.textContent = on ? "Cerrar" : "Ampliar"; b.classList.toggle("acento", on); });
    requestAnimationFrame(() => { ajustarVista(); setTimeout(ajustarVista, 260); });
  },
  rep_paso(el) { guardar("ff-rep-paso", el.dataset.v); ponerPasoReporte(); scrollTo({ top: 0, behavior: "smooth" }); },
  descanso_min(el) { guardar("ff-descanso", el.dataset.v); pintarDescanso(); toast(el.dataset.v === "0" ? "Descanso: nunca" : "Descanso tras " + el.textContent); },
  descansar() { mostrarPortada("descanso"); },
  buscar_version() { revisarVersion(true); },
  abrir_descargas() { if (MAC) mac("abrir", { url: URL_DESCARGAS }).catch(() => {}); else window.open(URL_DESCARGAS, "_blank", "noopener"); },
  async compartir_descarga() {
    try { if (navigator.share) { await navigator.share({ title: "Estadístico FilmFlow", text: "Instala la app Estadístico FilmFlow (Mac y celular):", url: URL_DESCARGAS }); return; } } catch (e) { if (e && e.name === "AbortError") return; }
    try { await navigator.clipboard.writeText(URL_DESCARGAS); toast("Copié el enlace de descarga"); } catch (e) { toast(URL_DESCARGAS); }
  },
  foto_seg(el) { guardar("ff-foto-seg", el.dataset.v); pintarDescanso(); },
  foto_azar(el) { guardar("ff-foto-azar", el.dataset.v); pintarDescanso(); },
  async quitar_fotos() { await fotosBorrar(); fotoIdx = 0; pintarDescanso(); toast("Listo: vuelve la imagen de FilmFlow"); },
  elegir_fotos() {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*"; inp.multiple = true;
    inp.onchange = async () => { ocupado(true, "Guardando fotos…"); const n = await fotosAgregar([...inp.files]); ocupado(false); pintarDescanso();
      toast(n === inp.files.length ? `${n} foto${n === 1 ? "" : "s"} agregada${n === 1 ? "" : "s"}` : `Pude agregar ${n} de ${inp.files.length} fotos`); };
    inp.click();
  },
  async elegir_pdf() { const d = await elegirPdf(); if (d) mostrar(await api("pdf_elegido", d)); },
  adj_elegir() { elegirAdjuntos(false); },
  adj_carpeta() { elegirAdjuntos(true); },
  adj_quitar_todo() { if (enviando) return; quitarAdjuntos(); pintarAdjuntos(); },
  async correo_enviar() { await enviarCorreo(false); },
  correo_detener() { if (envioXhr) envioXhr.abort(); },
  ver_cadena(el) { const c = el.closest(".chips-correo"); const k = c.dataset.campo; cadenasAbiertas.has(k) ? cadenasAbiertas.delete(k) : cadenasAbiertas.add(k); aplicarFuera(); },
  dest_mostrar_agregar() { const a = $(".agregar-correo"); if (a) { a.hidden = !a.hidden; if (!a.hidden) $("#nuevo-correo")?.focus(); } },
  firma_cambiar() { $("#tarjeta-firma")?.classList.toggle("cambiando"); },
  async abreviatura_guardar() {            // Ajustes del proyecto › Abreviatura
    const r = await api("abreviatura_guardar", { valor: ($("#abrev-in") || {}).value || "" });
    if (r) mostrar(r);
  },
  dest_agregar_para() { agregarDestinos("para"); },
  dest_agregar_cc() { agregarDestinos("cc"); },
  async dest_deshacer() { if (ultimoQuitado) { const d = ultimoQuitado; ultimoQuitado = null; const av = $("#destinos-aviso"); if (av) delete av.dataset.fijo; await opDestinos({ op: "volver", deshacer: d }); toast("Listo, volvió a la cadena"); } },
  firma_nueva() { editorFirma(); },
  async firma_borrar(el) {
    if (!(await modal({ titulo: "¿Quitar esta firma?", texto: `La firma de ${el.dataset.firma} se quita de la lista de este equipo (en Gmail sigue igual).`, si: "Quitar" }))) return;
    const r = await api("firma_quitar", { nombre: el.dataset.firma });
    const tj = $("#tarjeta-firma"); if (r && tj && r.firma) tj.outerHTML = r.firma;
    const v = $("#correo-firma"); if (r && v) v.innerHTML = r.vista || "";
    if (r && r.toast) toast(r.toast);
  },
  async elegir_pdf_correo() { const d = await elegirPdf(); if (d) mostrar(await api("correo_pdf", d)); },
  async copiar_correo() {
    const ls = lineasDelCorreo(), texto = ls.map((l) => l.map((x) => x[0]).join("")).join("\n");
    const ok = await copiar(texto, aHtml(ls));
    $("#correo-copiado").textContent = ok ? "✔ Texto copiado. Pégalo en el correo." : "No pude copiar: mantén el dedo sobre el texto, selecciónalo y copia.";
    if (ok) toast("Texto copiado");
  },
  async copiar_asunto() {
    const ok = await copiar($("#correo-asunto").value);
    $("#correo-copiado").textContent = ok ? "✔ Asunto copiado." : "No pude copiar el asunto.";
    if (ok) toast("Asunto copiado");
  },
  async compartir_correo() {
    const ls = lineasDelCorreo(), texto = ls.map((l) => l.map((x) => x[0]).join("")).join("\n");
    try { await navigator.share({ title: $("#correo-asunto").value, text: texto }); } catch (e) {}
  },
  tema(el) { guardar("ff-tema", el.dataset.v); aplicarTema(); posprocesar(); toast("Apariencia: " + el.textContent); },
  async invitar(el) {                // «Equipo del proyecto»: mandar el enlace de invitación (WhatsApp, correo…) o copiarlo
    const texto = `Te agregué al proyecto «${el.dataset.proyecto}» en Estadístico FilmFlow. Abre este enlace y entra con ${el.dataset.correo}: ${el.dataset.enlace}`;
    try { if (navigator.share) { await navigator.share({ title: "Estadístico FilmFlow", text: texto }); return; } } catch (e) { if (e.name === "AbortError") return; }
    toast((await copiar(texto)) ? "Invitación copiada: pégala en WhatsApp o en un correo." : el.dataset.enlace);
  },
  proyecto: elegirProyecto,
};

// ---------- reporte para enviar (lo arma Python; aquí se muestra, se comparte o se guarda en PDF) ----------
const logoComoDato = async (ruta) => {
  try {
    const b = await (await fetch(ruta)).blob();
    return await new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = () => ok(ruta); f.readAsDataURL(b); });
  } catch (e) { return ruta; }
};
// ---- Vista previa del PDF en la pestaña «Reporte»: el mismo HTML del reporte, dibujado al ancho de una hoja (860 px, como el PDF) y
// achicado para que quepa en la tarjeta; la altura sigue a la del documento. Se guarda dónde ibas para no saltar al cambiar algo.
let vistaHtml = "";
const ANCHO_HOJA = 860;
const docVista = () => { const f = vista.querySelector(".rep-vista iframe"); try { return f && f.contentDocument; } catch (e) { return null; } };
function ajustarVista() {                // la altura de la tarjeta sigue a la del documento (achicado al ancho de la tarjeta)
  const caja = vista.querySelector(".rep-vista"), lienzo = caja && caja.querySelector(".rep-lienzo"), fr = caja && caja.querySelector("iframe"), d = docVista();
  if (!fr || !d || !d.documentElement) return;
  // el alto es donde TERMINA la hoja (no el del documento: ese nunca baja del alto del marco, y al quitar partes quedaba una franja negra)
  const hoja = d.querySelector(".hoja");
  const s = Math.min(document.body.classList.contains("vista-grande") ? 1.35 : 1, caja.clientWidth / ANCHO_HOJA);
  const alto = hoja ? Math.ceil(hoja.getBoundingClientRect().bottom + (parseFloat(d.defaultView.getComputedStyle(hoja).marginBottom) || 0))
                    : Math.max(d.documentElement.scrollHeight, d.body ? d.body.scrollHeight : 0);
  fr.style.width = ANCHO_HOJA + "px"; fr.style.height = alto + "px"; fr.style.transform = `scale(${s})`;
  fr.style.left = Math.max(0, Math.floor((caja.clientWidth - ANCHO_HOJA * s) / 2)) + "px";        // centrada si sobra ancho
  lienzo.style.height = Math.ceil(alto * s) + "px";     // la caja tiene alto máximo y se desliza por dentro (el resto de la app no se mueve)
}
async function pintarVista(html) {
  const caja = vista.querySelector(".rep-vista"), fr = caja && caja.querySelector("iframe");
  if (!fr) return;
  const conLogos = html.replace("LOGO_CLARO", await logoComoDato("assets/logo_filmflow_claro.png"))
                       .replace("LOGO_OSCURO", await logoComoDato("assets/logo_filmflow_oscuro.png"));
  if (conLogos === vistaHtml && fr.dataset.lista) { ajustarVista(); return; }
  vistaHtml = conLogos;
  fr.onload = () => {
    fr.dataset.lista = "1"; sincronizarVista(); prepararAsasVista(); prepararNombreVista(); ajustarVista(); setTimeout(ajustarVista, 300);
    try {                                           // cualquier cambio de tamaño de la hoja (partes, letras, imágenes) ajusta el alto
      const d = fr.contentDocument, h = d.querySelector(".hoja");
      if (h && d.defaultView.ResizeObserver) new d.defaultView.ResizeObserver(() => requestAnimationFrame(ajustarVista)).observe(h);
    } catch (e) {}
  };
  fr.srcdoc = conLogos;
  if (!caja.dataset.vigia && window.ResizeObserver) { caja.dataset.vigia = "1"; new ResizeObserver(() => requestAnimationFrame(ajustarVista)).observe(caja); }
}
// Si tocaste interruptores u ordenaste mientras la vista previa todavía cargaba, al terminar de cargar se pone igual a la pantalla.
function sincronizarVista() {
  const d = docVista(); if (!d || !d.querySelector(".hoja")) return;
  vista.querySelectorAll("input.sw[data-sec]:not(:disabled)").forEach((sw) => {
    const el = d.querySelector(`[data-sec="${sw.dataset.sec}"]`); if (el) el.hidden = !sw.checked;
  });
  d.querySelectorAll("[data-sec-grupo]").forEach((g) => { g.hidden = ![...g.querySelectorAll("[data-sec]")].some((x) => !x.hidden); });
}
// El nombre del reporte se escribe EN la vista previa: el nombre del proyecto y el título de la portada se tocan y se cambian ahí
// mismo (vacío = el sugerido). Se guarda solo, sin volver a dibujar la pantalla.
const nombreEspera = {};
function prepararNombreVista() {
  const d = docVista(), caja = vista.querySelector(".rep-vista"); if (!d || !caja) return;
  const campos = { proyecto: d.querySelector(".p-proyecto"), titulo: d.querySelector(".p-titulo") };
  const sug = { proyecto: caja.dataset.sugProy || "", titulo: caja.dataset.sugTit || "" };
  if (!d.getElementById("ff-nombre")) {
    const st = d.createElement("style"); st.id = "ff-nombre";
    st.textContent = `.ff-editable{border-radius:8px;outline:1.5px dashed transparent;outline-offset:4px;cursor:text;transition:outline-color .15s,background .15s}
.ff-editable:hover{outline-color:rgba(142,142,147,.7)}
.ff-editable:focus{outline:2px solid #1fbf6a;background:rgba(31,191,106,.08)}
@media print{.ff-editable{outline:0!important;background:none!important}}`;
    d.head.appendChild(st);
  }
  const pie = () => d.querySelector(".hoja > footer span:last-child");
  Object.entries(campos).forEach(([clave, el]) => {
    if (!el || el.dataset.ffListo) return;
    el.dataset.ffListo = "1";
    try { el.contentEditable = "plaintext-only"; } catch (e) { el.contentEditable = "true"; }
    if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
    el.spellcheck = false; el.classList.add("ff-editable");
    el.title = clave === "titulo" ? "Toca para cambiar el título del reporte (si lo borras, vuelve el sugerido)" : "Toca para cambiar el nombre del proyecto en el reporte (si lo borras, vuelve el sugerido)";
    const guardarYa = () => { const v = el.textContent.trim(); api("reporte_nombre", { [clave]: v === sug[clave] ? "" : v }); };
    el.addEventListener("input", () => {
      if (clave === "proyecto" && pie()) pie().textContent = el.textContent.trim() || sug.proyecto;
      clearTimeout(nombreEspera[clave]); nombreEspera[clave] = setTimeout(guardarYa, 400);
    });
    el.addEventListener("focus", () => {            // al tocarlo queda todo seleccionado: lo que escribas lo reemplaza (como al renombrar un archivo)
      setTimeout(() => { try { const r = d.createRange(); r.selectNodeContents(el); const sel = d.defaultView.getSelection(); sel.removeAllRanges(); sel.addRange(r); } catch (e) {} }, 0);
    });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
    el.addEventListener("blur", () => {
      if (!el.textContent.trim()) { el.textContent = sug[clave]; if (clave === "proyecto" && pie()) pie().textContent = sug.proyecto; }
      clearTimeout(nombreEspera[clave]); guardarYa();
    });
  });
}
// ---- Mover las partes del PDF en la misma vista previa: cada parte lleva al lado sus puntitos ⋮⋮; se arrastran y las demás se
// corren con animación (como los rollos en Ajustes). Al soltar se guarda el orden (sin volver a dibujar la pantalla).
const ASA_SVG = '<svg viewBox="0 0 12 20" width="16" height="26" aria-hidden="true">' +
  [3, 9].map((x) => [3, 10, 17].map((y) => `<circle cx="${x}" cy="${y}" r="1.9"/>`).join("")).join("") + "</svg>";
function prepararAsasVista() {
  const d = docVista(); if (!d || !d.querySelector(".hoja") || d.getElementById("ff-asas")) return;
  const st = d.createElement("style"); st.id = "ff-asas";
  st.textContent = `.ff-mov{position:relative}
.ff-asa{position:absolute;left:-43px;top:0;width:40px;height:60px;display:grid;place-items:center;border-radius:10px;cursor:grab;
  color:#8e8e93;fill:currentColor;opacity:.75;touch-action:none;user-select:none;-webkit-user-select:none;z-index:3}
.ff-asa:hover,.ff-arrastrando>.ff-asa{opacity:1;background:rgba(142,142,147,.18);color:#1fbf6a}
.ff-arrastrando{z-index:20;cursor:grabbing;box-shadow:0 18px 40px rgba(0,0,0,.28);border-radius:16px}
.ff-ordenando>.ff-mov:not(.ff-arrastrando){transition:transform .24s cubic-bezier(.2,.8,.2,1)}
.ff-quitar{position:absolute;right:-40px;top:6px;width:30px;height:30px;border-radius:50%;border:0;display:grid;place-items:center;cursor:pointer;
  background:rgba(229,72,77,.12);color:#e5484d;font:700 18px/1 -apple-system,system-ui,sans-serif;opacity:.7;z-index:3;padding:0}
.ff-quitar:hover{opacity:1;background:#e5484d;color:#fff}
.kpi.ff-mov-k{position:relative}.kpi>.ff-quitar{right:6px;top:6px;width:24px;height:24px;font-size:15px;opacity:0}
.kpi:hover>.ff-quitar{opacity:.8}
.ff-visto{animation:ffvisto 1.6s ease-out!important;border-radius:14px}
@keyframes ffvisto{0%,35%{box-shadow:0 0 0 3px #1fbf6a,0 0 0 9px rgba(31,191,106,.25)}100%{box-shadow:0 0 0 0 rgba(31,191,106,0)}}
@media print{.ff-asa,.ff-quitar{display:none!important}}`;
  d.head.appendChild(st);
  d.querySelectorAll(".hoja > [data-sec], .hoja > [data-sec-grupo]").forEach((b) => {
    b.classList.add("ff-mov");
    const a = d.createElement("span"); a.className = "ff-asa"; a.title = "Arrastra para mover esta parte del PDF"; a.innerHTML = ASA_SVG;
    b.appendChild(a);
    const quitar = (sid, donde, nombre) => {          // la ✕ roja: quita esa parte del PDF (solo existe en la vista previa, nunca en el PDF)
      const x = d.createElement("button"); x.type = "button"; x.className = "ff-quitar"; x.textContent = "✕"; x.dataset.quitar = sid;
      x.title = "Quitar esta parte del PDF" + (nombre ? " («" + nombre + "»)" : ""); donde.appendChild(x);
    };
    const nombreDe = (sid) => { const sw = vista.querySelector(`input.sw[data-sec="${sid}"]`); const t = sw && sw.closest("label")?.querySelector(".sec-txt b"); return t ? t.textContent : ""; };
    if (b.dataset.secGrupo) b.querySelectorAll(":scope > .kpi-g").forEach((g) => { const k = g.querySelector(".kpi"); if (k) { k.classList.add("ff-mov-k"); quitar(g.dataset.sec, k, nombreDe(g.dataset.sec)); } });
    else quitar(b.dataset.sec, b, nombreDe(b.dataset.sec));
  });
  d.addEventListener("click", (e) => {
    const x = e.target.closest && e.target.closest(".ff-quitar"); if (!x) return;
    e.preventDefault(); e.stopPropagation();
    const sid = x.dataset.quitar, sw = vista.querySelector(`input.sw[data-sec="${sid}"]`);
    if (sw && sw.checked) { sw.checked = false; prenderSeccion(sid, false); api("reporte_seccion", { id: sid, valor: false }); }
  });
  let m = null, raf = 0;
  const fr = () => vista.querySelector(".rep-vista iframe");
  const escala = () => { const f = fr(); return f ? f.getBoundingClientRect().width / ANCHO_HOJA : 1; };
  const pos = () => {
    const dy = m.y - m.y0, r0 = m.rects[m.i], centro = dy < 0 ? r0.top + dy : r0.top + dy + r0.height;   // subiendo manda el borde de arriba; bajando, el de abajo
    m.card.style.transform = `translateY(${dy}px)`;
    let a = 0;
    m.items.forEach((el, j) => { if (j !== m.i && m.rects[j].top + m.rects[j].height / 2 < centro) a++; });
    m.a = a;
    const paso = r0.height + m.sep;
    m.items.forEach((el, j) => {
      if (j === m.i) return;
      const t = (m.i < a && j > m.i && j <= a) ? -paso : (a < m.i && j >= a && j < m.i) ? paso : 0;
      el.style.transform = t ? `translateY(${t}px)` : "";
    });
  };
  const auto = () => {                    // cerca del borde de arriba o de abajo de la vista previa, se desliza sola (solo ella)
    if (!m) return;
    const caja = vista.querySelector(".rep-vista"), rc_ = caja.getBoundingClientRect();
    const cy = fr().getBoundingClientRect().top + m.y * m.s;
    const arriba = Math.max(rc_.top, 0), abajo = Math.min(rc_.bottom, innerHeight - (document.getElementById("accion-fija")?.offsetHeight || 0));
    const v = cy < arriba + 50 ? -(14 + Math.min(30, arriba + 50 - cy) / 2) : cy > abajo - 50 ? 14 + Math.min(30, cy - abajo + 50) / 2 : 0;
    if (v) { const y0 = caja.scrollTop; caja.scrollTop += v; m.y += (caja.scrollTop - y0) / m.s; pos(); }
    raf = requestAnimationFrame(auto);
  };
  d.addEventListener("pointerdown", (e) => {
    const asa = e.target.closest && e.target.closest(".ff-asa"); if (!asa) return;
    const card = asa.parentElement, hoja = card.parentElement;
    const items = [...hoja.querySelectorAll(":scope > .ff-mov:not([hidden])")];
    const rects = items.map((el) => { const q = el.getBoundingClientRect(); return { top: q.top + d.defaultView.scrollY, height: q.height }; });
    const i = items.indexOf(card);
    const sep = rects[1] ? Math.max(0, rects[1].top - rects[0].top - rects[0].height) : 14;
    m = { card, hoja, items, rects, i, a: i, y0: e.clientY, y: e.clientY, s: escala(), sep, id: e.pointerId };
    try { asa.setPointerCapture(e.pointerId); } catch (x) {}
    card.classList.add("ff-arrastrando"); hoja.classList.add("ff-ordenando");
    if (navigator.vibrate) navigator.vibrate(8);
    raf = requestAnimationFrame(auto); e.preventDefault();
  });
  d.addEventListener("pointermove", (e) => { if (!m || e.pointerId !== m.id) return; m.y = e.clientY; pos(); e.preventDefault(); });
  const fin = (e, cancelar) => {
    if (!m || e.pointerId !== m.id) return;
    cancelAnimationFrame(raf);
    const { card, hoja, items, i, a } = m; m = null;
    const antes = card.getBoundingClientRect().top;
    items.forEach((el) => { el.style.transition = "none"; el.style.transform = ""; });
    hoja.classList.remove("ff-ordenando");
    if (!cancelar && a !== i) {
      const ref = items[a]; hoja.insertBefore(card, a > i ? ref.nextSibling : ref);
      const orden = [];
      hoja.querySelectorAll(":scope > .ff-mov").forEach((b) => {
        if (b.dataset.secGrupo) b.querySelectorAll("[data-sec]").forEach((k) => orden.push(k.dataset.sec)); else orden.push(b.dataset.sec);
      });
      api("reporte_orden", { orden });
    }
    const dy = antes - card.getBoundingClientRect().top;          // la parte soltada llega suave a su lugar
    card.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" })
      .onfinish = () => card.classList.remove("ff-arrastrando");
    requestAnimationFrame(() => items.forEach((el) => { el.style.transition = ""; }));
    vistaHtml = "";
  };
  d.addEventListener("pointerup", (e) => fin(e, false));
  d.addEventListener("pointercancel", (e) => fin(e, true));
}
// Prender / apagar una sección: en la vista previa se muestra o se esconde al instante (ya viene armada), con una entrada suave;
// la lista del orden y la cuenta de cada grupo también cambian. Python solo lo guarda (sin volver a dibujar la pantalla).
// Dónde está una parte del reporte en la vista previa (las cifras no tienen caja propia: se usa su primera tarjeta)
function bloqueDe(d, sid) {
  const el = d && d.querySelector(`[data-sec="${sid}"]`); if (!el) return null;
  if (el.classList.contains("kpi-g")) return el.querySelector(".kpi") || el;
  const hijo = [...el.children].find((c) => !c.classList.contains("ff-asa") && !c.classList.contains("ff-quitar") && c.getBoundingClientRect().height > 0);
  return hijo || el;                                  // la tarjeta que se ve (así el reborde verde sigue sus esquinas)
}
// El ojito: desliza la vista previa hasta esa parte y la resalta un momento. En el teléfono, si se pide, abre el paso «Vista previa».
function verSeccion(sid, abrirPaso) {
  const d = docVista(), caja = vista.querySelector(".rep-vista"), fr = caja && caja.querySelector("iframe");
  const el = bloqueDe(d, sid); if (!el || !fr) return;
  let espera = 0;
  if (abrirPaso && getComputedStyle(vista.querySelector('[data-paso-de="vista"]') || document.body).display === "none") {
    guardar("ff-rep-paso", "vista"); ponerPasoReporte(); espera = 120;       // primero se muestra el paso y se acomoda la vista previa
  }
  setTimeout(() => {
    const s = fr.getBoundingClientRect().width / ANCHO_HOJA, y = (el.getBoundingClientRect().top + d.defaultView.scrollY) * s;
    caja.scrollTo({ top: Math.max(0, y - 16), behavior: "smooth" });
    el.classList.remove("ff-visto", "entra"); el.closest(".entra")?.classList.remove("entra"); void el.offsetWidth; el.classList.add("ff-visto");
    setTimeout(() => el.classList.remove("ff-visto"), 1700);
  }, espera);
}
function prenderSeccion(sid, on) {
  const ojo = vista.querySelector(`button.ojo[data-sec="${sid}"]`); if (ojo) ojo.disabled = !on;
  const d = docVista();
  if (d) {
    const el = d.querySelector(`[data-sec="${sid}"]`);
    if (el) { el.hidden = !on; el.classList.remove("entra"); if (on) { void el.offsetWidth; el.classList.add("entra"); } }
    const g = el && el.closest("[data-sec-grupo]");
    if (g) g.hidden = ![...g.querySelectorAll("[data-sec]")].some((x) => !x.hidden);
    ajustarVista();
  }
  vista.querySelectorAll("details.sec-grupo").forEach((det) => {
    const sw = [...det.querySelectorAll("input.sw:not(:disabled)")];
    const c = det.querySelector(".sec-cuenta"); if (c) c.textContent = `${sw.filter((x) => x.checked).length} de ${sw.length}`;
  });
  vista.querySelectorAll('.segmentado .seg[data-a="reporte_preset"]').forEach((b) => b.classList.remove("on"));
  const nuevo = d && d.documentElement ? "<!doctype html>" + d.documentElement.outerHTML : "";
  if (nuevo) vistaHtml = nuevo;
  if (on) setTimeout(() => verSeccion(sid, false), 60);       // al prenderla, la vista previa muestra dónde quedó
}
async function abrirReporte(rep) {
  const html = rep.html.replace("LOGO_CLARO", await logoComoDato("assets/logo_filmflow_claro.png"))
                       .replace("LOGO_OSCURO", await logoComoDato("assets/logo_filmflow_oscuro.png"));
  const capa = document.createElement("div");
  capa.className = "reporte-capa";
  capa.innerHTML = `<div class="reporte-barra"><button class="btn mini" data-r="cerrar">Cerrar</button><span class="espacio"></span>
    <button class="btn mini" data-r="pdf" title="${MAC ? "Guarda el PDF en Documentos › Reportes FilmFlow y lo abre." : "Imprimir o guardar como PDF."}">${MAC ? "Guardar PDF" : "PDF / Imprimir"}</button><button class="btn mini acento" data-r="compartir">Compartir</button></div>
    <iframe title="Reporte"></iframe>`;
  document.body.appendChild(capa);
  document.body.classList.add("con-reporte");
  const marco = capa.querySelector("iframe");
  marco.srcdoc = html;
  const archivo = () => new File([html], rep.nombre, { type: "text/html" });
  const descargar = () => {
    const u = URL.createObjectURL(archivo()), enl = document.createElement("a");
    enl.href = u; enl.download = rep.nombre; document.body.appendChild(enl); enl.click(); enl.remove();
    setTimeout(() => URL.revokeObjectURL(u), 30000);
  };
  capa.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-r]"); if (!b) return;
    if (b.dataset.r === "cerrar") { capa.remove(); document.body.classList.remove("con-reporte"); return; }
    if (b.dataset.r === "pdf" && MAC) {           // Mac: PDF y página web en Documentos › Reportes FilmFlow, y se abre el PDF
      ocupado(true, "Guardando el PDF…");
      let r;
      try {
        if (PDF_WEBKIT) {                         // el PDF con el motor de Safari de la ventana del Mac (no hace falta Chrome)
          r = await mac("guardar_reporte", { html, nombre: rep.nombre, sin_pdf: true });
          if (!r.error) {
            let hecho = await pdfConWebKit(r.html, r.pdf_ruta);
            if (!hecho) hecho = (await mac("pdf_chrome", { html: r.html, pdf: r.pdf_ruta })).ok;      // plan B: Chrome, si lo hay
            const abierto = await mac("abrir_ruta", { ruta: hecho ? r.pdf_ruta : r.html });
            r = { pdf: hecho ? r.pdf_ruta : null, nombre: abierto.nombre };
          }
        } else r = await mac("guardar_reporte", { html, nombre: rep.nombre });
      } catch (x) { r = { error: x.message }; } finally { ocupado(false); }
      if (r.error) await modal({ titulo: "No pude guardar el reporte", texto: r.error, si: "Entendido", no: "" });
      else toast((r.pdf ? "Listo: guardé «" : "Guardé la página «") + r.nombre + "» en Documentos › Reportes FilmFlow"
                 + (r.pdf ? "" : " (no pude hacer el PDF: ábrela y usa Archivo › Exportar como PDF)"));
      return;
    }
    if (b.dataset.r === "pdf") {
      // Imprimir el marco: en el iPhone sale la hoja de impresión, y desde ahí «Compartir» lo guarda como PDF.
      try { marco.contentWindow.focus(); marco.contentWindow.print(); } catch (x) { descargar(); }
      return;
    }
    const f = archivo();
    if (navigator.canShare && navigator.canShare({ files: [f] })) {
      try { await navigator.share({ files: [f], title: rep.titulo }); } catch (x) {}
    } else descargar();
  });
}

// ---------- toques ----------
document.addEventListener("click", async (e) => {
  if (e.target.closest("#btn-proyecto")) return elegirProyecto();
  const t = e.target.closest("[data-a],[data-js],[data-ir]");
  if (!t || t.tagName === "FORM") return;
  if (vista.classList.contains("carga") && vista.contains(t)) return;
  if (t.dataset.ir) { if (t.dataset.ir === actual) scrollTo({ top: 0, behavior: "smooth" }); else ir(t.dataset.ir); return; }
  if (t.matches('input[type="checkbox"]')) return;
  if (t.dataset.js) { const f = JS[t.dataset.js]; if (f) f(t); return; }
  const p = JSON.parse(t.dataset.p || "{}");
  if (t.dataset.a === "ir") return ir(p.pagina);
  if (t.disabled) return;
  if (t.dataset.a === "reporte_modo_rapido") {          // claro / oscuro: la vista previa cambia al instante; Python solo lo guarda
    t.parentElement.querySelectorAll(".seg").forEach((b) => b.classList.toggle("on", b === t));
    const d = docVista(); if (d) d.documentElement.dataset.tema = p.valor;
    vistaHtml = vistaHtml.replace(/data-tema="(claro|oscuro)"/, `data-tema="${p.valor}"`);
    api("reporte_modo_rapido", p); return;
  }
  mostrar(await api(t.dataset.a, p));
});
document.addEventListener("change", async (e) => {
  const t = e.target;
  if (t.matches('input.sw[data-panel]')) {
    api("resumen_panel", { id: t.dataset.panel, valor: t.checked });
    const sws = [...vista.querySelectorAll("input.sw[data-panel]")], c = $("#cuenta-paneles");
    if (c) c.textContent = `${sws.filter((x) => x.checked).length} de ${sws.length}`;
    return;
  }
  if (t.matches('input.sw[data-sec]')) { prenderSeccion(t.dataset.sec, t.checked); api("reporte_seccion", { id: t.dataset.sec, valor: t.checked }); return; }
  if (t.matches('input[type="checkbox"][data-a]')) { mostrar(await api(t.dataset.a, { ...JSON.parse(t.dataset.p || "{}"), valor: t.checked })); return; }
  if (t.matches('[data-form="tipo"]')) alternarTipo(t.closest("form"));
  if (t.id === "correo-asunto") api("correo_prefijo", { asunto: t.value });
});
document.addEventListener("submit", async (e) => {
  const f = e.target.closest("form[data-a]"); if (!f) return;
  e.preventDefault();
  const datos = {};
  for (const [k, v] of new FormData(f)) datos[k] = v === "on" ? true : v;
  mostrar(await api(f.dataset.a, { ...JSON.parse(f.dataset.p || "{}"), ...datos }));
});

// ---------- arrastrar rollos para cambiar su orden ----------
(() => {
  let d = null, raf = 0;
  const pos = () => {
    const y = d.cy + scrollY, dy = y - d.y0, r = d.rects[d.i];
    d.card.style.transform = `translateY(${dy}px)`;
    const centro = r.top + r.height / 2 + dy;
    let a = d.i;
    d.rects.forEach((q, k) => { if (k < d.i && centro < q.top + q.height / 2) a = Math.min(a, k); if (k > d.i && centro > q.top + q.height / 2) a = Math.max(a === d.i ? k : a, k); });
    d.a = a;
    d.items.forEach((el, k) => {
      if (k === d.i) return;
      const mueve = a > d.i ? (k > d.i && k <= a ? -1 : 0) : (k < d.i && k >= a ? 1 : 0);
      el.style.transform = mueve ? `translateY(${mueve * (r.height + d.sep)}px)` : "";
    });
  };
  const auto = () => {
    if (!d) return;
    const borde = 90, v = d.cy < borde + 60 ? -10 : d.cy > innerHeight - borde - 70 ? 10 : 0;
    if (v) { scrollBy(0, v); pos(); }
    raf = requestAnimationFrame(auto);
  };
  document.addEventListener("click", (e) => { if (e.target.closest(".grip")) { e.preventDefault(); e.stopPropagation(); } }, true);
  document.addEventListener("pointerdown", (e) => {
    const g = e.target.closest(".grip"); if (!g) return;
    const card = g.closest(".rollo"); if (!card) return;
    card.parentElement.querySelectorAll("details.rollo[open]").forEach((x) => { x.open = false; });
    const items = [...card.parentElement.querySelectorAll(":scope > .rollo")];
    const rects = items.map((el) => { const q = el.getBoundingClientRect(); return { top: q.top + scrollY, height: q.height }; });
    d = { card, items, rects, i: items.indexOf(card), a: items.indexOf(card), y0: e.clientY + scrollY, cy: e.clientY, sep: rects[1] ? Math.max(0, rects[1].top - rects[0].top - rects[0].height) : 0, id: e.pointerId };
    try { g.setPointerCapture(e.pointerId); } catch (x) {}
    card.classList.add("arrastrando"); card.parentElement.classList.add("ordenando");
    if (navigator.vibrate) navigator.vibrate(8);
    raf = requestAnimationFrame(auto); e.preventDefault();
  });
  document.addEventListener("pointermove", (e) => { if (!d || e.pointerId !== d.id) return; d.cy = e.clientY; pos(); e.preventDefault(); });
  const fin = async (e, cancelar) => {
    if (!d || e.pointerId !== d.id) return;
    cancelAnimationFrame(raf);
    const { i, a, items, card } = d; d = null;
    card.classList.remove("arrastrando"); card.parentElement.classList.remove("ordenando");
    items.forEach((el) => { el.style.transform = ""; });
    if (!cancelar && a !== i) mostrar(await api("mover_rollo", { i, a }));
  };
  document.addEventListener("pointerup", (e) => fin(e, false));
  document.addEventListener("pointercancel", (e) => fin(e, true));
})();

// ---------- gráfico de volumen: tocar o deslizar para ver el día ----------
(() => {
  let g = null;
  const mostrar = (cx) => {
    const svg = g.querySelector("svg"), r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    const x = (cx - r.left) / r.width * vb.width, cols = [...svg.querySelectorAll(".col")];
    const todas = g.dataset.ayudas.split("|"), n = todas.length, izq = 40, der = 6;
    let i = Math.floor((x - izq) / ((vb.width - izq - der) / n)); i = Math.max(0, Math.min(n - 1, i));
    svg.querySelectorAll(".col.sel").forEach((e) => e.classList.remove("sel"));
    const col = svg.querySelector(`.col[data-i="${i}"]`); if (col) col.classList.add("sel");
    const tip = svg.querySelector(".tip"), t = tip.querySelector("text"), rc = tip.querySelector("rect");
    t.textContent = todas[i]; tip.setAttribute("visibility", "visible");
    const w = t.getComputedTextLength() + 18; rc.setAttribute("width", w); t.setAttribute("x", 9);
    const centro = izq + (vb.width - izq - der) / n * (i + 0.5);
    const xx = Math.max(2, Math.min(vb.width - w - 2, centro - w / 2));
    tip.setAttribute("transform", `translate(${xx},0)`);
  };
  document.addEventListener("pointerdown", (e) => { const s = e.target.closest(".grafico svg"); if (!s) { document.querySelectorAll(".grafico .tip").forEach((t) => t.setAttribute("visibility", "hidden")); document.querySelectorAll(".grafico .col.sel").forEach((c) => c.classList.remove("sel")); return; } g = s.closest(".grafico"); mostrar(e.clientX); });
  document.addEventListener("pointermove", (e) => { if (g && (e.buttons || e.pointerType === "touch")) mostrar(e.clientX); else if (e.pointerType === "mouse") { const s = e.target.closest(".grafico svg"); if (s) { g = s.closest(".grafico"); mostrar(e.clientX); } } });
  document.addEventListener("pointerup", () => { g = null; });
  document.addEventListener("pointercancel", () => { g = null; });
})();

// ---------- jalar para actualizar (solo en Resumen) ----------
(() => {
  let y0 = null, dy = 0;
  const ind = document.createElement("div");
  ind.style.cssText = "position:fixed;left:50%;top:0;transform:translate(-50%,-80px);opacity:0;z-index:40;background:var(--superficie);border:1px solid var(--separador);border-radius:20px;padding:7px 14px;font-size:13px;font-weight:600;color:var(--texto2);transition:transform .15s;pointer-events:none";
  ind.textContent = "Suelta para actualizar"; document.body.appendChild(ind);
  document.addEventListener("touchstart", (e) => { y0 = (actual === "resumen" && scrollY <= 0 && e.touches.length === 1) ? e.touches[0].clientY : null; dy = 0; }, { passive: true });
  document.addEventListener("touchmove", (e) => {
    if (y0 === null) return; dy = e.touches[0].clientY - y0;
    if (dy > 0) ind.style.opacity = 1, ind.style.transform = `translate(-50%,${Math.min(70, dy / 2) + $("#barra").offsetHeight}px)`;
  }, { passive: true });
  document.addEventListener("touchend", async () => {
    ind.style.transform = "translate(-50%,-80px)"; ind.style.opacity = 0;
    if (y0 !== null && dy > 110) mostrar(await api("actualizar", { forzar: true }));
    y0 = null; dy = 0;
  });
})();

// ---------- sin internet, y al volver a la app ----------
// ¿Hay internet? Safari a veces dice «sin conexión» teniendo red (VPN, ciertas redes Wi-Fi, el simulador): si lo dice, se comprueba de
// verdad tocando a Google (fuera del sitio, así el service worker no responde con lo guardado).
let enLinea = navigator.onLine;
async function probarRed() {
  if (navigator.onLine) { enLinea = true; revisarRed(); return true; }
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), 5000);
    await fetch("https://www.googleapis.com/generate_204?ff=" + Date.now(), { mode: "no-cors", cache: "no-store", signal: c.signal });
    clearTimeout(t); enLinea = true;
  } catch (e) { enLinea = false; }
  revisarRed();
  return enLinea;
}
function revisarRed() {
  const f = $("#franja"), off = !enLinea;
  const vencida = !off && !PRUEBA && !tokenVigente() && !!leer("ff-correo") && !document.body.classList.contains("sin-sesion");
  f.hidden = !(off || vencida); f.classList.toggle("vencida", vencida);
  if (off) f.textContent = "Sin internet. Verás lo último guardado; para registrar o actualizar necesitas conexión.";
  else if (vencida) f.innerHTML = 'La sesión de Google venció. Lo que ves es lo último guardado. <button class="enlace" data-js="conectar">Reconectar</button>';
  else f.textContent = "";
}
function haceCuanto(t) {
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 1) return "hace un momento"; if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60); if (h < 24) return `hace ${h} h`; return `hace ${Math.round(h / 24)} d`;
}
addEventListener("online", () => { enLinea = true; revisarRed(); if (tokenVigente()) sincronizar(false); else if (actual === "resumen") ir("resumen", true); });
addEventListener("offline", () => { probarRed(); });
let ocultoDesde = 0;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { ocultoDesde = Date.now(); return; }
  const fuera = Date.now() - ocultoDesde;
  if (!ocultoDesde || nOcupado || nProgreso || modalAbierto()) return;
  (async () => {                                   // primero sincronizar (1 consulta) y DESPUÉS leer la página (antes las dos a la vez)
    if (fuera > 20 * 1000 && tokenVigente()) await sincronizar(false);
    if (fuera > 5 * 60 * 1000 && actual === "resumen") ir("resumen", true);
  })();
});

async function repararDatos() {
  if (MAC) { location.reload(); return; }
  ocupado(true, "Reparando…");
  try { if (navigator.serviceWorker) for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister(); } catch (e) {}
  try { for (const k of await caches.keys()) await caches.delete(k); } catch (e) {}
  try { worker.terminate(); } catch (e) {}
  await new Promise((res) => { try { const q = indexedDB.deleteDatabase("/datos"); q.onsuccess = q.onerror = q.onblocked = () => res(); setTimeout(res, 3000); } catch (e) { res(); } });
  location.reload();
}
// ---------- versiones nuevas ----------
// La app se guarda en el teléfono para funcionar sin internet. Cuando se publica una versión nueva, el teléfono la descarga
// detrás; aquí se pide revisar al abrir y al volver a la app, y en cuanto la nueva queda lista se recarga sola (si no está trabajando).
let recargaPendiente = false;
const HABIA_VERSION = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
function escucharVersionNueva() {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!HABIA_VERSION || recargaPendiente) return;          // la primera instalación no necesita recargar
    recargaPendiente = true;
    const aplicar = () => {
      if (nOcupado || nProgreso || document.querySelector(".reporte-capa")) { setTimeout(aplicar, 2000); return; }
      toast("Hay una versión nueva de la app: actualizando…");
      setTimeout(() => location.reload(), 900);
    };
    aplicar();
  });
}
if ("serviceWorker" in navigator && !PRUEBA && !MAC) escucharVersionNueva();
function activarActualizaciones() {
  navigator.serviceWorker.register("sw.js", { updateViaCache: "none" }).then((reg) => {
    const revisar = async () => { if (navigator.onLine || await probarRed()) { reg.update().catch(() => {}); revisarVersion(false); } };
    revisar();
    document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - ultimaRevision > 5 * 60000) revisar(); });
    setInterval(() => { if (!document.hidden) revisar(); }, 30 * 60000);
  }).catch(() => {});
}
// Comprobación extra: la versión publicada (version.json, siempre de internet) contra la que tiene el teléfono (version.js,
// guardada). Si el teléfono quedó en una vieja (Safari a veces no cambia sola), primero se le pide cambiar y, si en 25 s no lo
// hizo, se borra SOLO la copia de la app (no tus datos ni tu sesión) y se recarga: queda en la versión publicada.
const MI_VERSION = self.FF_VERSION || { id: "", app: "", fecha: "" };
const URL_DESCARGAS = "https://filmflowestadistico.github.io/";
let versionNube = null, ultimaRevision = 0, revisandoVersion = false, forzandoVersion = false;
const numVersion = (v) => parseInt(String(v || "").replace(/\D/g, ""), 10) || 0;
// ---- Mac: las actualizaciones de la app instalada (descarga, cambia la app y la vuelve a abrir: actualizar.py) ----
let macVersion = null, macRevisada = 0, macBuscando = false, macPospuesta = "";
async function revisarVersionMac(aMano) {
  if (macBuscando) return;
  macBuscando = true; if (actual === "app") pintarVersion();
  let r; try { r = await mac("buscar_actualizacion"); } catch (e) { r = { error: e.message }; }
  macBuscando = false; macRevisada = Date.now();
  if (!r.error) macVersion = r;
  if (actual === "app") pintarVersion();
  if (r.error) { if (aMano) toast(r.error); return; }
  if (!r.nueva) { if (aMano) toast("Tienes la última versión (" + r.actual + ")"); return; }
  if (!aMano && macPospuesta === r.version) return;
  const nov = (r.novedades || []).map((x) => "•  " + x).join("\n");
  const si = await modal({ titulo: "Hay una versión nueva: " + r.version, texto: (nov ? "Novedades:\n" + nov + "\n\n" : "") + "Tienes la " + r.actual + ". Se descarga, la app se cierra y se abre sola con la nueva (no se pierde nada).", si: "Actualizar ahora", no: "Más tarde" });
  if (!si) { macPospuesta = r.version; return; }
  const ini = await mac("instalar_actualizacion"); if (ini.error) { await modal({ titulo: "No pude actualizar", texto: ini.error, si: "Entendido", no: "" }); return; }
  ocupado(true, "Descargando la versión nueva… 0 %");
  for (;;) {
    await new Promise((ok) => setTimeout(ok, 400));
    const pr = await mac("progreso");
    const o = $("#ocupado-txt"); if (o) o.textContent = pr.estado === "descargando" ? `Descargando la versión nueva… ${Math.round(pr.v * 100)} % · no cierres la app` : "Preparando la versión nueva…";
    if (pr.estado === "error") { ocupado(false); await modal({ titulo: "No pude actualizar", texto: pr.error + "\n\nTu app sigue igual.", si: "Entendido", no: "" }); return; }
    if (pr.estado === "descargas") { ocupado(false); await modal({ titulo: "La versión nueva quedó en Descargas", texto: "No puedo cambiar la app donde está. Abre el archivo que dejé en Descargas y arrastra «Estadistico FilmFlow» a Aplicaciones (reemplazando la anterior).", si: "Entendido", no: "" }); return; }
    if (pr.estado === "listo") break;
  }
  ocupado(false);
  await modal({ titulo: "Lista la versión " + r.version, texto: "La app se va a cerrar y se abrirá sola en unos segundos con la versión nueva.", si: "Entendido", no: "" });
  await mac("reiniciar_actualizado");
}
async function revisarVersion(aMano) {
  if (MAC) return revisarVersionMac(aMano);
  if (PRUEBA || !MI_VERSION.id || revisandoVersion) return null;
  revisandoVersion = true; if (aMano && actual === "app") pintarVersion();
  try {
    const r = await fetch("version.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    versionNube = await r.json(); ultimaRevision = Date.now();
  } catch (e) {
    revisandoVersion = false; if (actual === "app") pintarVersion();
    if (aMano) toast("No pude revisar: ¿tienes internet?");
    return null;
  }
  revisandoVersion = false;
  const nueva = numVersion(versionNube.id) > numVersion(MI_VERSION.id);
  if (actual === "app") pintarVersion();
  if (nueva) forzarVersionNueva();
  else if (aMano) toast("Tienes la última versión (" + (MI_VERSION.app || MI_VERSION.id) + ")");
  return nueva;
}
async function forzarVersionNueva() {
  if (forzandoVersion || recargaPendiente) return;
  forzandoVersion = true;
  toast("Hay una versión nueva de la app: descargándola…");
  try { const reg = await navigator.serviceWorker.getRegistration(); if (reg) await reg.update(); } catch (e) {}
  setTimeout(async function forzar() {
    if (recargaPendiente) return;                   // ya cambió sola (controllerchange recarga)
    if (nOcupado || nProgreso || modalAbierto() || document.querySelector(".reporte-capa")) { setTimeout(forzar, 3000); return; }
    toast("Actualizando a la versión nueva…");
    // se borra la copia guardada: al recargar, el service worker pide cada archivo a internet preguntando si cambió (nunca uno viejo)
    try { const reg = await navigator.serviceWorker.getRegistration(); if (reg) await reg.update(); } catch (e) {}
    try { for (const k of await caches.keys()) await caches.delete(k); } catch (e) {}
    setTimeout(() => location.reload(), 900);
  }, 25000);
}
function pintarVersion() {
  const cont = $("#js-version"); if (!cont) return;
  if (MAC) {
    const estadoMac = macBuscando ? "Buscando si hay una versión nueva…" : macVersion && macVersion.nueva ? `Hay una versión nueva (${macVersion.version}).`
      : macRevisada && macVersion ? `Tienes la última versión. Revisado a las ${new Date(macRevisada).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}.` : "Se revisa sola al abrir la app y cada 6 horas.";
    cont.innerHTML = `<section class="tarjeta"><p>Versión instalada: <b>${(macVersion && macVersion.actual) || MI_VERSION.app || "—"}</b> <span class="sub">· app del Mac</span></p>
      <p class="sub">${estadoMac}</p>
      <div class="barra-mini llena"><button class="btn" data-js="buscar_version" title="Preguntar ahora mismo si hay una versión nueva de la app del Mac.">Buscar actualizaciones</button>
      <button class="btn" data-js="abrir_descargas" title="Abre la página de descargas de la app (instaladores del Mac y app del celular).">Abrir la página de descargas</button>
      <button class="btn" data-js="compartir_descarga" title="Mandar a otro data manager el enlace para instalar la app (Mac y celular).">Compartir enlace de descarga</button></div></section>`;
    return;
  }
  const nueva = versionNube && numVersion(versionNube.id) > numVersion(MI_VERSION.id);
  const estado = revisandoVersion ? "Buscando si hay una versión nueva…"
    : nueva ? `Hay una versión nueva (${versionNube.app || versionNube.id}): se está instalando sola.`
    : ultimaRevision ? `Tienes la última versión. Revisado a las ${new Date(ultimaRevision).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}.`
    : "Se revisa sola al abrir la app.";
  cont.innerHTML = `<section class="tarjeta"><p>Versión instalada: <b>${MI_VERSION.app || "—"}</b>${MI_VERSION.fecha ? ` <span class="sub">· publicada el ${MI_VERSION.fecha}</span>` : ""}</p>
    <p class="sub">${estado}</p>
    <p class="sub">La app se actualiza sola: al abrirla y cada rato revisa si hay una versión nueva y la instala sin borrar tus proyectos ni tu sesión.</p>
    <div class="barra-mini llena"><button class="btn" data-js="buscar_version" title="Preguntar ahora mismo si hay una versión nueva de la app.">Buscar actualizaciones</button>
    <button class="btn" data-js="abrir_descargas" title="Abre la página de descargas de la app (instaladores del Mac y app del celular).">Abrir la página de descargas</button>
      <button class="btn" data-js="compartir_descarga" title="Mandar a otro data manager el enlace para instalar la app (Mac y celular).">Compartir enlace de descarga</button></div></section>`;
}
// ---------- arranque ----------
async function procesarInvitacion() {
  const f = leer("ff-unirse");
  if (!f || f === "null" || !tokenVigente() || PRUEBA) return;
  guardar("ff-unirse", "null");
  mostrar(await api("unirse", { ficha: f }));
}
(async () => {
  const inv = new URLSearchParams(location.search).get("unirse");       // enlace de invitación a un proyecto
  if (inv) { guardar("ff-unirse", inv); history.replaceState(null, "", location.pathname + location.hash); }
  cargarSesion(); revisarRed(); if (!navigator.onLine) probarRed();
  if (MAC) { try { await motorListo; } catch (e) {} await sesionMac(); if (!sesion.correo) { delete memoria["ff-correo"]; try { localStorage.removeItem("ff-correo"); } catch (e) {} } }
  const regreso = PRUEBA || MAC ? null : await regresoDeGoogle();          // volviendo de iniciar sesión (app instalada)
  if (regreso === "redirige") return;
  if (!PRUEBA && !MAC && CFG.clientId) cargarGIS().catch(() => {});
  const sinSesion = !tokenVigente() && !PRUEBA && !leer("ff-correo");
  let conCache = false;
  if (sinSesion) {                                   // primera pantalla: solo conectar con Google; el motor carga detrás
    document.body.classList.add("sin-sesion"); actual = "resumen"; mostrarPortada("inicio");
    motorListo.catch(() => {});
  } else {
    if (!PRUEBA) {                                   // se ve al instante lo último guardado, sin esperar al motor
      try { const c = JSON.parse(leer("ff-proy") || "null"); if (c && c.activo) { proyectos = c; $("#proyecto-nombre").textContent = c.activo; } } catch (e) {}
      const ini = new URLSearchParams(location.search).get("p") || "resumen";
      if (ini === "resumen") { const c = leer(claveCache()); if (c) { try { const o = JSON.parse(c); if (o.html) { vista.innerHTML = cabeza("resumen") + o.html; vista.classList.add("carga"); conCache = true; resaltarTab(); prepararGraficos(vista); } } catch (e) {} } }
    }
    if (conCache) progreso(true); else ocupado(true, "Preparando la app… (la primera vez tarda un poco más)");
  }
  try { await motorListo; } catch (e) { await ofrecerReparar(e); return; }
  ocupado(false); if (conCache) progreso(false);
  if (regreso === "ok") toast("Cuenta conectada" + (sesion.correo ? ": " + sesion.correo : ""));
  let pendiente = null;                                             // lo que se iba a hacer antes de ir a Google por el permiso
  try { pendiente = JSON.parse(leer("ff-pendiente") || "null"); } catch (e) {}
  if (pendiente) guardar("ff-pendiente", "null");
  if (regreso !== "ok") pendiente = null;
  if (regreso === "error") await modal({ titulo: "No se pudo conectar", texto: textoErrorConexion(), si: "Entendido", no: "" });
  if (almacenFalla || sinGuardar) avisoPrivado();
  if ("serviceWorker" in navigator && !PRUEBA && !MAC) activarActualizaciones();
  if (MAC) setTimeout(() => revisarVersionMac(false), 6000);
  const inicial = new URLSearchParams(location.search).get("p") || "resumen";
  window.__ff = { api, ir, listo: true, get sesion() { return sesion; }, sincronizar, MAC, adjuntar: (l) => agregarAdjuntos(l) };
  if (MAC) setInterval(() => { if (!document.hidden) revisarVersionMac(false); }, 6 * 3600 * 1000);
  try { const c = await llamar("cuenta", {}); if (c && c.proyectos) actualizarProyectos(c.proyectos); } catch (e) {}
  if (sinSesion && !leer("ff-correo")) return;       // sigue en la pantalla de inicio hasta que conecte
  if (tokenVigente() && !conCache) await sincronizar(false);   // sin nada guardado: primero traer los proyectos y leer una sola vez
  await ir(pendiente ? "ajustes" : inicial, conCache && !pendiente);
  if (pendiente && pendiente.accion) mostrar(await api(pendiente.accion, pendiente.p || {}));
  await procesarInvitacion();
  if (tokenVigente() && conCache) sincronizar(false);
})();

// Mac: atajos de teclado como en la app de siempre (⌘1 Resumen … ⌘6 Ajustes, ⌘, Ajustes de la app)
if (MAC) document.addEventListener("keydown", (e) => {
  if (!e.metaKey || e.altKey || e.ctrlKey) return;
  const pags = { "1": "resumen", "2": "registrar", "3": "hojas", "4": "reporte", "5": "correo", "6": "ajustes", ",": "app" };
  if (pags[e.key]) { e.preventDefault(); ir(pags[e.key]); }
});

// Esc cierra la vista previa ampliada; al cambiar de pestaña también se cierra
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("vista-grande")) JS.ampliar_vista(); });

// Reporte en pantalla ancha: la cuadrícula ocupa lo que queda de ventana (cada columna se desliza por dentro: nada «salta» al desplazar)
function medirReporte() {
  const g = vista.querySelector(".rep-grid"); if (!g) return;
  document.documentElement.style.setProperty("--rep-top", Math.round(g.getBoundingClientRect().top + scrollY) + "px");
}
new MutationObserver(() => { if (actual === "reporte") { medirReporte(); ajustarVista(); } }).observe(vista, { childList: true });
addEventListener("resize", () => { if (actual === "reporte") { medirReporte(); ajustarVista(); } });

// ---- burbuja de muestra (Ajustes de la app → Resumen): junto al ojito; se cierra al tocar fuera, con Esc o al desplazar ----
function ponerBurbuja(b, ancla) {
  const r = ancla.getBoundingClientRect(), W = innerWidth, ancho = Math.min(360, W - 24);
  b.style.width = ancho + "px";
  const izq = Math.max(12, Math.min(r.right - ancho, W - ancho - 12));
  const alto = b.offsetHeight, abajo = r.bottom + 10 + alto < innerHeight - 12;
  b.style.left = izq + "px";
  b.style.top = (abajo ? r.bottom + 10 : Math.max(12, r.top - 10 - alto)) + "px";
  b.classList.toggle("arriba", !abajo);
  b.style.setProperty("--flecha", Math.max(16, Math.min(ancho - 16, r.left + r.width / 2 - izq)) + "px");
}
function cerrarBurbuja() { document.querySelectorAll(".burbuja").forEach((x) => x.remove()); }
document.addEventListener("click", (e) => {
  const b = document.querySelector(".burbuja"); if (!b) return;
  if (e.target.closest(".burbuja-x")) { cerrarBurbuja(); return; }
  if (!e.target.closest(".burbuja") && !e.target.closest('[data-js="muestra_panel"]')) cerrarBurbuja();
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarBurbuja(); });
addEventListener("scroll", () => cerrarBurbuja(), { passive: true });

// ---------- Correo: cadena del proyecto, firma, adjuntos (con vista previa y estado de cada uno) y envío desde la app ----------
// Los archivos se quedan en la pantalla (no se guardan en ninguna parte) hasta que se envía el correo.
let adjuntos = [], nAdj = 0, envioXhr = null, enviando = false, ultimoQuitado = null;
const fueraEstaVez = new Set();
let proyectoDelCorreo = "";
const cadenasAbiertas = new Set();     // «+N más» abierto (Para / CC)                    // correos de la cadena a los que NO se envía solo esta vez
const LIMITE_ADJ = 25 * 1000 * 1000;
const mb = (b) => (b / 1e6).toFixed(b < 1e7 ? 1 : 0) + " MB";
const extDe = (n) => ((n || "").includes(".") ? n.split(".").pop() : "").toLowerCase();
const escH = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const TIPOS_EXT = { pdf: "application/pdf", csv: "text/csv", txt: "text/plain", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  xls: "application/vnd.ms-excel", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", png: "image/png", jpg: "image/jpeg",
  jpeg: "image/jpeg", gif: "image/gif", zip: "application/zip", mov: "video/quicktime", mp4: "video/mp4", ale: "text/plain", xml: "text/xml", json: "application/json" };
const TEXTO_ESTADO = { leyendo: "Preparando", listo: "Listo", error: "No se pudo leer", espera: "En espera", enviando: "Enviando", enviado: "Enviado ✓" };

function agregarAdjuntos(lista) {
  if (enviando) { toast("Espera a que termine el envío"); return; }
  if (adjuntos.length && adjuntos.every((a) => a.estado === "enviado")) quitarAdjuntos();     // el correo anterior ya salió: se empieza otro
  let nuevos = 0, repetidos = 0;
  for (const f of lista) {
    if (!f || !f.size || f.name.startsWith(".")) continue;                 // (archivos ocultos de las carpetas, p. ej. .DS_Store)
    if (adjuntos.some((a) => a.nombre === f.name && a.size === f.size)) { repetidos++; continue; }
    const a = { id: ++nAdj, file: f, nombre: f.name, size: f.size, tipo: f.type || TIPOS_EXT[extDe(f.name)] || "application/octet-stream", estado: "leyendo", pct: 0 };
    adjuntos.push(a); nuevos++;
    leerAdjunto(a); miniatura(a);
  }
  ordenarAdjuntos();
  pintarAdjuntos();
  if (nuevos) toast(nuevos === 1 ? "1 archivo adjuntado" : nuevos + " archivos adjuntados");
  else if (repetidos) toast(repetidos === 1 ? "Ese archivo ya estaba adjunto" : "Esos archivos ya estaban adjuntos");
}
// orden fijo: por tipo (PDF, CSV, hojas de cálculo, texto, imágenes, lo demás) y dentro de cada tipo por nombre (A2 antes que A10)
const ORDEN_TIPO = ["pdf", "csv", "xlsx", "xls", "numbers", "txt", "ale", "xml", "json", "png", "jpg", "jpeg", "gif", "zip"];
function ordenarAdjuntos() {
  const rango = (a) => { const k = ORDEN_TIPO.indexOf(extDe(a.nombre)); return k < 0 ? 99 : k; };
  adjuntos.sort((x, y) => rango(x) - rango(y) || extDe(x.nombre).localeCompare(extDe(y.nombre)) || x.nombre.localeCompare(y.nombre, "es", { numeric: true, sensitivity: "base" }));
}
function quitarAdjuntos() {
  for (const a of adjuntos) { try { if (a.url) URL.revokeObjectURL(a.url); } catch (e) {} }
  if (MAC && adjuntos.length) mac("adjunto_quitar", { ids: adjuntos.map((a) => a.id) }).catch(() => {});
  adjuntos = [];
}
function leerAdjunto(a) {
  if (MAC) return guardarEnMac(a);
  leerBase64(a);
}
// En el Mac el archivo se le pasa al Mac apenas se agrega, tal cual (sin convertir): al enviar ya está allá y sale de inmediato
function guardarEnMac(a) {
  const x = new XMLHttpRequest();
  x.open("POST", "/mac/adjunto_guardar");
  x.setRequestHeader("X-FF-Clave", CLAVE_MAC); x.setRequestHeader("X-FF-Id", String(a.id));
  x.setRequestHeader("X-FF-Nombre", encodeURIComponent(a.nombre)); x.setRequestHeader("X-FF-Tipo", a.tipo);
  x.upload.onprogress = (e) => { if (e.lengthComputable) { a.pct = e.loaded / e.total; actualizarAdjunto(a); } };
  x.onload = () => { if (x.status === 200) { a.ref = a.id; a.estado = "listo"; a.pct = 1; } else { a.estado = "error"; a.error = "el Mac no lo recibió (" + x.status + ")"; } actualizarAdjunto(a); };
  x.onerror = () => { a.estado = "error"; a.error = "el Mac no lo recibió"; actualizarAdjunto(a); };
  x.send(a.file);
}
function leerBase64(a) {
  const r = new FileReader();
  r.onprogress = (e) => { if (e.lengthComputable) { a.pct = e.loaded / e.total; actualizarAdjunto(a); } };
  r.onload = () => { a.datos = String(r.result).split(",")[1] || ""; a.estado = "listo"; a.pct = 1; actualizarAdjunto(a); };
  r.onerror = () => { a.estado = "error"; a.error = String(r.error && r.error.message || r.error || "no se pudo leer"); actualizarAdjunto(a); };
  r.readAsDataURL(a.file);
}
async function miniatura(a) {
  const e = extDe(a.nombre);
  try {
    if (a.tipo.startsWith("image/")) { a.url = URL.createObjectURL(a.file); a.mini = `<img src="${a.url}" alt="">`; }
    else if (e === "pdf" && a.size < 60e6) {
      a.url = URL.createObjectURL(a.file);
      const m = await import("./pdftexto.js");
      const dataUrl = await m.miniaturaPdf(await a.file.arrayBuffer(), 240);
      if (dataUrl) a.mini = `<img src="${dataUrl}" alt="">`;
    } else if (["csv", "txt", "ale", "xml", "json"].includes(e)) {
      a.texto = await a.file.slice(0, 20000).text();
      a.mini = `<pre>${escH(a.texto.slice(0, 400))}</pre>`;
    }
  } catch (err) {}
  if (!a.mini) a.mini = `<span class="adj-ext">${escH((e || "archivo").toUpperCase().slice(0, 5))}</span>`;
  actualizarAdjunto(a);
}
function htmlAdj(a) {
  const pct = Math.round((a.pct || 0) * 100);
  const txt = TEXTO_ESTADO[a.estado] + (a.estado === "leyendo" || a.estado === "enviando" ? ` ${pct}%` : "");
  return `<div class="adj-it e-${a.estado}" data-id="${a.id}" title="${escH(a.nombre)} · toca para ver el archivo">
    <div class="adj-mini">${a.mini || '<span class="adj-ext">…</span>'}</div>
    <div class="adj-n">${escH(a.nombre)}</div>
    <div class="adj-pie"><span class="nota">${mb(a.size)}</span><span class="adj-estado">${txt}</span></div>
    <div class="adj-carga"><div style="width:${a.estado === "listo" || a.estado === "enviado" ? 100 : pct}%"></div></div>
    <button type="button" class="adj-x" data-id="${a.id}" title="Quitar este adjunto" aria-label="Quitar"${enviando ? " disabled" : ""}>✕</button></div>`;
}
function pintarAdjuntos() {
  const cont = $("#adj-lista"); if (!cont) return;
  cont.innerHTML = adjuntos.map(htmlAdj).join("");
  pintarTotalAdjuntos();
}
function actualizarAdjunto(a) {
  const el = document.querySelector(`.adj-it[data-id="${a.id}"]`);
  if (el) el.outerHTML = htmlAdj(a);
  pintarTotalAdjuntos();
}
function pintarTotalAdjuntos() {
  const total = adjuntos.reduce((s, f) => s + f.size, 0);
  const txt = $("#adj-texto");
  if (txt) txt.classList.toggle("aviso-txt", total > LIMITE_ADJ);
  const qt = document.querySelector('.adj-total [data-js="adj_quitar_todo"]'); if (qt) qt.hidden = !adjuntos.length || enviando;
  if (!txt) return;
  const leyendo = adjuntos.filter((a) => a.estado === "leyendo").length, malos = adjuntos.filter((a) => a.estado === "error").length;
  txt.textContent = adjuntos.length ? `${adjuntos.length} ${adjuntos.length === 1 ? "adjunto" : "adjuntos"} · ${mb(total)}`
    + (total > LIMITE_ADJ ? ` · ⚠ pasa el límite de 25 MB de Gmail: quita ${mb(total - LIMITE_ADJ)} o mándalos en dos correos`
      : leyendo ? ` · preparando ${leyendo}…` : malos ? ` · ${malos} no se pudo leer` : adjuntos.every((a) => a.estado === "enviado") ? " · enviados" : " · todos listos")
    : "Ninguno todavía";
}
function elegirAdjuntos(carpeta) {
  const i = document.createElement("input"); i.type = "file"; i.multiple = true;
  if (carpeta) { i.webkitdirectory = true; i.setAttribute("webkitdirectory", ""); }
  i.onchange = () => agregarAdjuntos([...i.files]);
  i.click();
}
// vista previa grande de un adjunto (PDF, imagen, CSV/texto)
function verAdjunto(a) {
  cerrarVisor();
  const k = adjuntos.indexOf(a), n = adjuntos.length;
  const e = extDe(a.nombre);
  let cuerpo;
  if (a.tipo.startsWith("image/") && a.url) cuerpo = `<img src="${a.url}" alt="">`;
  else if (e === "pdf" && a.url) cuerpo = `<iframe src="${a.url}#view=FitH" title="${escH(a.nombre)}"></iframe>`;
  else if (a.texto != null) {
    if (e === "csv") {
      const filas = a.texto.split(/\r?\n/).filter((x) => x.trim()).slice(0, 60).map((l) => l.split(/[,;\t]/));
      cuerpo = `<div class="visor-tabla"><table>${filas.map((f, k) => `<tr>${f.map((c) => k ? `<td>${escH(c)}</td>` : `<th>${escH(c)}</th>`).join("")}</tr>`).join("")}</table></div>`;
    } else cuerpo = `<pre>${escH(a.texto)}</pre>`;
  } else cuerpo = `<div class="visor-nada"><span class="adj-ext">${escH((e || "archivo").toUpperCase())}</span><p>Este tipo de archivo no tiene vista previa aquí, pero se adjunta igual.</p></div>`;
  const v = document.createElement("div"); v.className = "adj-visor";
  v.innerHTML = `<div class="visor-caja"><div class="visor-cab">
    <button type="button" class="visor-flecha" data-paso="-1" title="Anterior (←)" aria-label="Anterior"${n < 2 ? " hidden" : ""}>‹</button>
    <div class="visor-titulo"><b>${escH(a.nombre)}</b><span class="nota">${k + 1} de ${n} · ${mb(a.size)} · ${TEXTO_ESTADO[a.estado]}</span></div>
    <button type="button" class="visor-flecha" data-paso="1" title="Siguiente (→)" aria-label="Siguiente"${n < 2 ? " hidden" : ""}>›</button>
    <button type="button" class="btn mini visor-x" title="Cerrar la vista previa (Esc)">Cerrar</button></div><div class="visor-cuerpo">${cuerpo}</div></div>`;
  v.dataset.k = k;
  v.addEventListener("click", (ev) => {
    const f = ev.target.closest(".visor-flecha"); if (f) { moverVisor(+f.dataset.paso); return; }
    if (ev.target === v || ev.target.closest(".visor-x")) cerrarVisor();
  });
  let x0 = null;                                                   // deslizar con el dedo (o el trackpad) a la izquierda / derecha
  v.addEventListener("touchstart", (ev) => { x0 = ev.touches[0].clientX; }, { passive: true });
  v.addEventListener("touchend", (ev) => { if (x0 == null) return; const dx = ev.changedTouches[0].clientX - x0; x0 = null; if (Math.abs(dx) > 50) moverVisor(dx < 0 ? 1 : -1); });
  let acum = 0, t = 0;
  v.addEventListener("wheel", (ev) => {
    if (Math.abs(ev.deltaX) <= Math.abs(ev.deltaY)) return;
    ev.preventDefault(); if (Date.now() - t < 450) return;
    acum += ev.deltaX; if (Math.abs(acum) > 60) { moverVisor(acum > 0 ? 1 : -1); acum = 0; t = Date.now(); }
  }, { passive: false });
  document.body.appendChild(v);
  v.querySelector(".visor-caja").focus?.();
}
function moverVisor(paso) {
  const v = document.querySelector(".adj-visor[data-k]"); if (!v || adjuntos.length < 2) return;
  const k = (+v.dataset.k + paso + adjuntos.length) % adjuntos.length;
  verAdjunto(adjuntos[k]);
}
function cerrarVisor() { document.querySelectorAll(".adj-visor").forEach((x) => x.remove()); }
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") cerrarVisor();
  if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && document.querySelector(".adj-visor[data-k]")) { e.preventDefault(); moverVisor(e.key === "ArrowRight" ? 1 : -1); }
});
document.addEventListener("click", (e) => {
  const x = e.target.closest && e.target.closest(".adj-x");
  if (x) { if (enviando) return; const k = adjuntos.findIndex((a) => a.id === +x.dataset.id); if (k >= 0) { const [a] = adjuntos.splice(k, 1); try { if (a.url) URL.revokeObjectURL(a.url); } catch (err) {} if (MAC) mac("adjunto_quitar", { ids: [a.id] }).catch(() => {}); } pintarAdjuntos(); return; }
  const t = e.target.closest && e.target.closest(".adj-it");
  if (t) { const a = adjuntos.find((z) => z.id === +t.dataset.id); if (a) verAdjunto(a); }
});
// arrastrar archivos a la pestaña Correo (en cualquier parte); en otras pestañas soltar un archivo no hace nada
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => {
  if (!e.dataTransfer || ![...(e.dataTransfer.types || [])].includes("Files")) return;
  e.preventDefault();
  if (actual === "correo") { e.dataTransfer.dropEffect = "copy"; $("#adj-zona")?.classList.add("encima"); }
  else e.dataTransfer.dropEffect = "none";
}));
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $("#adj-zona")?.classList.remove("encima"); });
document.addEventListener("drop", async (e) => {
  if (!e.dataTransfer || ![...(e.dataTransfer.types || [])].includes("Files")) return;
  e.preventDefault(); $("#adj-zona")?.classList.remove("encima");
  if (actual !== "correo") return;
  const archivos = [];
  const items = [...(e.dataTransfer.items || [])].map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  const leerEntrada = (en) => new Promise((ok) => {          // también carpetas soltadas: se toman sus archivos
    if (en.isFile) en.file((f) => { archivos.push(f); ok(); }, () => ok());
    else if (en.isDirectory) {
      const r = en.createReader(), todas = [];
      const lote = () => r.readEntries(async (es) => { if (!es.length) { for (const x of todas) await leerEntrada(x); ok(); } else { todas.push(...es); lote(); } }, () => ok());
      lote();
    } else ok();
  });
  if (items.length) { for (const en of items) await leerEntrada(en); } else archivos.push(...e.dataTransfer.files);
  agregarAdjuntos(archivos);
});

// ----- la cadena de correos del proyecto (fichas) -----
function aplicarFuera() {
  document.querySelectorAll(".chip-c").forEach((c) => c.classList.toggle("fuera", fueraEstaVez.has(c.dataset.correo)));
  document.querySelectorAll(".chips-correo.muchas").forEach((c) => {
    const ab = cadenasAbiertas.has(c.dataset.campo); c.classList.toggle("abierta", ab);
    const b = c.querySelector(".chip-mas"); if (b) { if (!b.dataset.txt) b.dataset.txt = b.textContent; b.textContent = ab ? "Ver menos" : b.dataset.txt; }
  });
  const n = fueraEstaVez.size, av = $("#destinos-aviso");
  if (av && !av.dataset.fijo) av.textContent = n ? `Esta vez no se envía a ${n} ${n === 1 ? "persona" : "personas"} (siguen en la cadena).` : "";
}
async function opDestinos(p) {
  const r = await api("correo_destinos", p);
  if (!r || r.error) { if (r && r.error) toast(r.error); return r; }
  const d = $("#destinos"); if (d && r.html) d.outerHTML = r.html;
  aplicarFuera();
  const av = $("#destinos-aviso");
  if (av && (r.malos?.length || r.deshacer)) {
    av.dataset.fijo = "1";
    av.innerHTML = r.malos?.length ? "No parecen correos (no los guardé): " + escH(r.malos.join(", "))
      : `Quité a ${escH(r.deshacer.direccion)}. <button type="button" class="btn mini" data-js="dest_deshacer" title="Volver a ponerlo en la cadena">Deshacer</button>`;
  }
  if (r.deshacer) ultimoQuitado = r.deshacer;
  if (r.toast && !r.deshacer) toast(r.toast);
  return r;
}
async function agregarDestinos(campo) {
  const t = $("#nuevo-correo"); if (!t || !t.value.trim()) { t?.focus(); toast("Escribe o pega primero los correos"); return; }
  const r = await opDestinos({ op: "agregar", campo, texto: t.value });
  if (r && !r.malos?.length) { const n = $("#nuevo-correo"); if (n) n.value = ""; const ag = $(".agregar-correo"); if (ag && ag.hidden) { ag.hidden = false; $("#nuevo-correo")?.focus(); } }
  else if (r) { const n = $("#nuevo-correo"); if (n) n.value = r.malos.join(", "); }
}
document.addEventListener("click", (e) => {
  const t = e.target; if (!t.closest) return;
  const x = t.closest(".chip-x"); if (x) { opDestinos({ op: "quitar", correo: x.dataset.correo }); return; }
  const m = t.closest(".chip-mover"); if (m) { opDestinos({ op: "mover", correo: m.dataset.correo }); return; }
  const c = t.closest(".chip-c");
  if (c) { const k = c.dataset.correo; fueraEstaVez.has(k) ? fueraEstaVez.delete(k) : fueraEstaVez.add(k); const av = $("#destinos-aviso"); if (av) delete av.dataset.fijo; aplicarFuera(); return; }
  const f = t.closest("#tarjeta-firma .firma-op[data-firma]:not([data-js])");
  if (f) { elegirFirma(f.dataset.firma); }
});
document.addEventListener("keydown", (e) => {
  if (e.target && e.target.id === "nuevo-correo" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); agregarDestinos("para"); }
});
// forma antigua (por si quedó alguna casilla de texto de la versión anterior)
document.addEventListener("change", async (e) => {
  const t = e.target;
  if (t.matches && t.matches("textarea.destinos")) await opDestinos({ [t.dataset.campo]: t.value });
});

// ----- firma -----
async function elegirFirma(nombre) {
  const r = await api("correo_elegir_firma", { nombre: nombre || "" });
  if (!r || r.error) { if (r && r.error) toast(r.error); return; }
  const tj = $("#tarjeta-firma"); if (tj && r.firma) tj.outerHTML = r.firma;
  const v = $("#correo-firma"); if (v) v.innerHTML = r.vista || "";
  if (r.toast) toast(r.toast);
}
function editorFirma() {
  const v = document.createElement("div"); v.className = "adj-visor";
  v.innerHTML = `<div class="visor-caja firma-editor"><div class="visor-cab"><b>Agregar firma</b>
    <button type="button" class="btn mini visor-x" title="Cerrar sin guardar">Cancelar</button></div>
    <div class="visor-cuerpo"><ol class="pasos"><li>En Gmail abre Configuración › Ver toda la configuración › Firma.</li>
    <li>Elige la firma, selecciónala toda (⌘A dentro del cuadro) y cópiala (⌘C).</li><li>Pégala aquí abajo (⌘V) y escribe de quién es.</li></ol>
    <label class="etq-campo">Nombre</label><input id="firma-nombre" class="campo" placeholder="Nombre de quien firma" title="Así aparecerá en la lista de firmas">
    <label class="etq-campo">Firma</label><div id="firma-pegar" class="firma-pegar" contenteditable="true" title="Pega aquí la firma copiada de Gmail"></div>
    <div class="barra-mini"><button type="button" class="btn acento" id="firma-guardar" title="Guardar la firma y usarla en este proyecto">Guardar firma</button></div></div></div>`;
  v.addEventListener("click", (ev) => { if (ev.target === v || ev.target.closest(".visor-x")) v.remove(); });
  v.querySelector("#firma-guardar").addEventListener("click", async () => {
    const r = await api("firma_agregar", { nombre: v.querySelector("#firma-nombre").value, html: v.querySelector("#firma-pegar").innerHTML });
    if (!r || r.error) { toast(r && r.error || "No pude guardar la firma"); return; }
    v.remove();
    const tj = $("#tarjeta-firma"); if (tj && r.firma) tj.outerHTML = r.firma;
    const vf = $("#correo-firma"); if (vf) vf.innerHTML = r.vista || "";
    toast(r.toast || "Firma guardada");
  });
  document.body.appendChild(v);
  v.querySelector("#firma-nombre").focus();
}

// ----- envío -----
function progresoEnvio(texto, pct) {
  const p = $("#envio-progreso"); if (!p) return;
  p.hidden = texto == null;
  if (texto != null) { $("#envio-texto").textContent = texto; $("#envio-barra").style.width = Math.round((pct || 0) * 100) + "%"; }
}
function modoEnviando(si) {
  enviando = si;
  const b = document.querySelector('[data-js="correo_enviar"]'), d = document.querySelector('[data-js="correo_detener"]');
  if (b) { b.disabled = si; b.textContent = si ? "Enviando…" : "Enviar correo"; }
  if (d) d.hidden = !si;
  document.querySelectorAll(".adj-x").forEach((x) => (x.disabled = si));
}
async function tokenParaGmail() {
  if (PRUEBA) return { token: PRUEBA.token, url: (u) => u.replace("https://gmail.googleapis.com", PRUEBA.sheets + "/gmail") };
  if (MAC) { const r = await mac("token_google", {}); return { token: r && r.token, url: (u) => (r && r.base ? u.replace("https://gmail.googleapis.com", r.base + "/gmail") : u) }; }
  return { token: tokenVigente(), url: (u) => u };
}
function subirAGmail(url, token, mime, alAvance) {
  return new Promise((ok) => {
    const x = new XMLHttpRequest(); envioXhr = x;
    x.open("POST", url);
    x.timeout = 20 * 60 * 1000;
    x.setRequestHeader("Authorization", "Bearer " + token);
    x.setRequestHeader("Content-Type", "message/rfc822");
    x.upload.onprogress = (e) => { if (e.lengthComputable) alAvance(e.loaded, e.total); };
    x.onload = () => ok({ codigo: x.status, texto: x.responseText });
    x.onerror = () => ok({ codigo: 0, texto: "red" });
    x.ontimeout = () => ok({ codigo: 0, texto: "Gmail tardó demasiado en recibir el correo" });
    x.onabort = () => ok({ cancelado: true });
    x.send(mime);
  });
}
async function permisoGmail(c) {
  if (!(await modal({ titulo: "Falta un permiso de Google", texto: c.texto, si: "Dar permiso" }))) return false;
  if (MAC) {
    ocupado(true, "Da el permiso en el navegador que se abrió…");
    try { const x = await mac("entrar", { extra: [c.scope] }); if (x.error) { await modal({ titulo: "No se dio el permiso", texto: x.error, si: "Entendido", no: "" }); return false; } }
    finally { ocupado(false); }
    await sesionMac(); return true;
  }
  if (ES_APP_INSTALADA) { toast("Vuelve a adjuntar los archivos y pulsa «Enviar correo» al regresar"); irAGoogle(PERMISOS + " " + c.scope); return false; }
  return !!(await pedirTokenYa(true, PERMISOS + " " + c.scope));
}
function marcarAvance(r, enviados) {
  const cortes = r.cortes || [];
  adjuntos.forEach((a, i) => {
    const ini = cortes[i] ?? r.mime.length, fin = cortes[i + 1] ?? r.mime.length;
    const antes = a.estado + Math.round((a.pct || 0) * 20);
    if (enviados >= fin) { a.estado = "enviando"; a.pct = 1; }
    else if (enviados > ini) { a.estado = "enviando"; a.pct = (enviados - ini) / Math.max(1, fin - ini); }
    else { a.estado = "espera"; a.pct = 0; }
    if (antes !== a.estado + Math.round(a.pct * 20)) actualizarAdjunto(a);
  });
}
async function enviarCorreo(forzar, sinPreguntar) {
  if (enviando) return;
  if (!$("#correo-asunto")) { await modal({ titulo: "Falta el correo", texto: "Primero elige el PDF del día: con él se arma el asunto y el texto.", si: "Entendido", no: "" }); return; }
  const malos = adjuntos.filter((a) => a.estado === "error");
  if (malos.length) { await modal({ titulo: "Hay un adjunto que no se pudo leer", texto: `«${malos[0].nombre}»: ${malos[0].error || ""}\n\nQuítalo con ✕ y vuelve a adjuntarlo.`, si: "Entendido", no: "" }); return; }
  if (adjuntos.length && adjuntos.every((a) => a.estado === "enviado") && !forzar) {
    if (!(await modal({ titulo: "Esos adjuntos ya se enviaron", texto: "¿Envío el mismo correo otra vez con los mismos archivos?", si: "Enviar otra vez" }))) return;
    adjuntos.forEach((a) => { if (MAC) { a.estado = "leyendo"; a.pct = 0; guardarEnMac(a); } else { a.estado = "listo"; a.pct = 1; } }); pintarAdjuntos(); forzar = true; sinPreguntar = true;
  }
  const total = adjuntos.reduce((s, f) => s + f.size, 0);
  if (total > LIMITE_ADJ) { await modal({ titulo: "Los adjuntos pesan demasiado", texto: `Pesan ${mb(total)} y Gmail deja hasta 25 MB por correo. Quita algunos o mándalos en dos correos.`, si: "Entendido", no: "" }); return; }
  const asunto = $("#correo-asunto").value.trim();
  const para = document.querySelectorAll('.chips-correo[data-campo="para"] .chip-c:not(.fuera)').length;
  const cc = document.querySelectorAll('.chips-correo[data-campo="cc"] .chip-c:not(.fuera)').length;
  if (!para) { await modal({ titulo: "Falta a quién enviarlo", texto: "Agrega al menos un correo en «Para» (Destinatarios de este proyecto).", si: "Entendido", no: "" }); return; }
  const fop = $("#tarjeta-firma .firma-op.on"), firma = fop ? (fop.dataset.firma || "sin firma") : "sin elegir (sale sin firma)";
  if (!sinPreguntar && !(await modal({ titulo: "¿Envío el correo?", si: "Enviar",
      texto: `«${asunto}»\n\nPara: ${para} · CC: ${cc}${fueraEstaVez.size ? ` (esta vez sin ${fueraEstaVez.size})` : ""}\nFirma: ${firma}\nAdjuntos: ${adjuntos.length} (${mb(total)})\n\nSe envía desde tu cuenta de Gmail; queda en tus «Enviados».` }))) return;
  modoEnviando(true);
  try {
    if (adjuntos.some((a) => a.estado === "leyendo")) {
      progresoEnvio("Terminando de leer los adjuntos…", 0);
      while (adjuntos.some((a) => a.estado === "leyendo")) await new Promise((r) => setTimeout(r, 200));
      if (adjuntos.some((a) => a.estado === "error")) { modoEnviando(false); progresoEnvio(null); return enviarCorreo(forzar, true); }
    }
    progresoEnvio("Armando el correo…", 0);
    const ls = lineasDelCorreo(), texto = ls.map((l) => l.map((x) => x[0]).join("")).join("\n");
    const carga = { asunto, texto, html: aHtml(ls), adjuntos: adjuntos.map((a) => (MAC ? { ref: a.ref, nombre: a.nombre } : { nombre: a.nombre, tipo: a.tipo, datos: a.datos })), forzar: !!forzar, fuera: [...fueraEstaVez],
      envio_id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7) };
    if (MAC) { await enviarDesdeMac(carga, total, forzar); return; }
    if (!PRUEBA && !(sesion.permisos || "").includes("gmail.send")) {     // el permiso se pide ANTES de subir nada
      modoEnviando(false); progresoEnvio(null);
      const c = { scope: "https://www.googleapis.com/auth/gmail.send", texto: "Para enviar el correo desde la app, Google pide un permiso más: «Enviar correo electrónico en tu nombre». La app solo podrá ENVIAR (no puede leer tu correo).\n\nToca «Dar permiso» y deja MARCADA esa casilla." };
      if (await permisoGmail(c)) await enviarCorreo(true, true);
      return;
    }
    const r = await api("correo_armar", carga);
    if (!r) return;
    if (r.confirmar_envio) { modoEnviando(false); progresoEnvio(null); if (await modal({ titulo: "Ya se envió", texto: r.confirmar_envio, si: "Enviar otra vez" })) await enviarCorreo(true, true); return; }
    if (r.error) { await modal({ titulo: "No se envió el correo", texto: r.error, si: "Entendido", no: "" }); return; }
    let g = await tokenParaGmail(), res;
    for (let intento = 0; intento < 2; intento++) {
      const largo = r.mime.length;
      res = await subirAGmail(g.url(r.url), g.token, r.mime, (env, tot) => {
        const pct = env / tot;
        const k = adjuntos.findIndex((a) => a.estado !== "enviando" || a.pct < 1);
        progresoEnvio(pct >= 0.999 ? "Gmail está recibiendo el correo…" : `Enviando ${mb(total * pct)} de ${mb(total)}` + (adjuntos.length ? ` · archivo ${Math.min(adjuntos.length, Math.max(1, k + 1 || adjuntos.length))} de ${adjuntos.length}` : ""), pct);
        marcarAvance(r, env / tot * largo);
      });
      if (res.codigo === 401 && intento === 0 && !PRUEBA) { g = MAC ? await tokenParaGmail() : { ...g, token: await pedirToken(false) }; if (g.token) continue; }
      break;
    }
    if (res.cancelado) { adjuntos.forEach((a) => { a.estado = "listo"; a.pct = 1; }); pintarAdjuntos(); toast("Envío detenido: no se mandó nada"); return; }
    let fin;
    if (res.codigo === 0) {                   // sin respuesta de Gmail: NUNCA se reintenta solo (pudo haber salido: no se duplica)
      fin = { error: "No tuve respuesta de Gmail (¿internet?). Revisa tus «Enviados» en Gmail antes de volver a enviarlo, para no mandarlo dos veces." };
    } else fin = await api("correo_resultado", { codigo: res.codigo, texto: res.texto, asunto: r.asunto, para: r.para, cc: r.cc, adjuntos: adjuntos.length, total: r.total });
    await terminarEnvio(fin);
  } finally {
    envioXhr = null; modoEnviando(false);
    if (!adjuntos.length || !adjuntos.every((a) => a.estado === "enviado")) progresoEnvio(null);
  }
}
// Lo que pasa al terminar (igual en el Mac y en la web)
async function terminarEnvio(fin) {
    if (!fin) return;
    if (fin.pedir_permiso) {
      adjuntos.forEach((a) => { a.estado = "listo"; a.pct = 1; }); pintarAdjuntos();
      modoEnviando(false); progresoEnvio(null);
      if (await permisoGmail(fin.pedir_permiso)) await enviarCorreo(true, true);
      return;
    }
    if (fin.error) { adjuntos.forEach((a) => { a.estado = "listo"; a.pct = 1; }); pintarAdjuntos(); await modal({ titulo: "No se envió el correo", texto: fin.error, si: "Entendido", no: "" }); return; }
    if (fin.enviado) {
      adjuntos.forEach((a) => { a.estado = "enviado"; a.pct = 1; }); pintarAdjuntos();
      progresoEnvio(`✔ Enviado a ${fin.enviado.para + fin.enviado.cc} personas`, 1);
      const e = $("#correo-enviado"); if (e) e.textContent = `✔ Enviado el ${fin.enviado.fecha} a ${fin.enviado.para + fin.enviado.cc} personas con ${fin.enviado.adjuntos} adjuntos${fin.enviado.firma ? " · firma " + fin.enviado.firma : ""}.`;
      fueraEstaVez.clear(); aplicarFuera();
      toast(fin.toast || "Correo enviado");
    }
}
// En el Mac: el Mac lo envía en segundo plano (un solo camino); la página solo pregunta cómo va. Se puede seguir usando la app.
async function enviarDesdeMac(carga, total, forzar) {
  const r = await mac("correo_enviar_fondo", carga);
  if (!r) return;
  if (r.pedir_permiso) {
    modoEnviando(false); progresoEnvio(null);
    if (await permisoGmail(r.pedir_permiso)) await enviarCorreo(true, true);
    return;
  }
  if (r.confirmar_envio) { modoEnviando(false); progresoEnvio(null); if (await modal({ titulo: "Ya se envió", texto: r.confirmar_envio, si: "Enviar otra vez" })) await enviarCorreo(true, true); return; }
  if (r.error) { await modal({ titulo: "No se envió el correo", texto: r.error, si: "Entendido", no: "" }); return; }
  toast("Enviando en segundo plano: puedes seguir usando la app");
  const base = { cortes: r.cortes, mime: { length: r.largo } };
  for (;;) {
    await new Promise((ok) => setTimeout(ok, 300));
    const e = await mac("correo_estado", { id: r.id });
    if (!e || e.error) { await terminarEnvio({ error: (e && e.error) || "Perdí el envío." }); return; }
    const pct = e.total ? e.enviados / e.total : 0;
    progresoEnvio(e.estado === "listo" ? "Terminando…" : pct >= 0.999 ? "Gmail está recibiendo el correo…" : `Enviando ${mb(total * pct)} de ${mb(total)}`, pct);
    marcarAvance(base, pct * r.largo);
    if (e.estado === "listo") { await terminarEnvio(e.resultado); return; }
  }
}
