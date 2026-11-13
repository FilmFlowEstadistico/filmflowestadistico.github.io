// Estadístico FilmFlow · teléfono. Esta parte solo dibuja y reparte toques; TODA la lógica es Python (la misma de la app del Mac).
// El lector de PDF (650 KB) se carga solo cuando eliges un PDF: así la app abre más rápido.
const textoDelPdf = async (datos) => (await import("./pdftexto.js")).textoDelPdf(datos);

const CFG = window.FILMFLOW_CONFIG || {};
const PRUEBA = window.FILMFLOW_PRUEBA || null;       // solo lo pone el entorno de pruebas
const base = new URL("./", location.href).href;
const $ = (s) => document.querySelector(s);
const vista = $("#vista");
const PAGINAS_GOOGLE = new Set(["resumen", "registrar", "hojas", "correo"]);
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
  const out = await mensaje({ tipo: "llamar", nombre, p, token: tokenVigente(), correo: sesion.correo });
  return out.r;
}
// «Silenciosas»: no ponen nada en pantalla mientras trabajan. «Bloqueantes»: tapan la pantalla (escriben o tardan). El resto: barra de progreso arriba.
const SILENCIOSAS = new Set(["marcar", "marcar_seg", "alternar_vista", "mas_hallazgos", "decision", "casilla", "unidad", "correo_prefijo", "cancelar_formulario",
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
async function pedirToken(interactivo) {
  if (PRUEBA) return PRUEBA.token;
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
  if (/redirect_uri/i.test(e)) return "Google no reconoce la dirección de la app para volver. Avísale a quien administra la app (Google Cloud → URI de redireccionamiento).";
  return "No se conectó la cuenta de Google" + (e && e !== "sin_respuesta" ? " (" + e + ")" : "") + ". Vuelve a intentarlo.";
}
async function conectar() {
  if (ES_APP_INSTALADA && !PRUEBA && CFG.clientId) { irAGoogle(PERMISOS); return; }
  const t = await pedirToken(true);
  if (t) {
    toast("Cuenta conectada" + (sesion.correo ? ": " + sesion.correo : ""));
    const _p = actual; document.body.classList.remove("sin-sesion"); ocultarPortada();
    await ir(PAGINAS_GOOGLE.has(_p) ? _p : "resumen", false);
    if (leer("ff-unirse") && leer("ff-unirse") !== "null") await procesarInvitacion(); else sincronizar(false);
  } else if (CFG.clientId) {
    if (errorConexion === "toca_otra_vez") toast(textoErrorConexion());
    else await modal({ titulo: "No se pudo conectar", texto: textoErrorConexion(), si: "Entendido", no: "" });
  }
}
async function desconectar() {
  const ok = await modal({ titulo: "Desconectar", texto: "¿Desconecto tu cuenta de Google de este teléfono? Tus hojas y tus proyectos no se tocan.", si: "Desconectar" });
  if (!ok) return;
  try { google.accounts.oauth2.revoke(sesion.token, () => {}); } catch (e) {}
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
  proyectos = { lista: info.proyectos, activo: info.activo };
  $("#proyecto-nombre").textContent = info.activo || "—";
  if (!PRUEBA) guardar("ff-proy", JSON.stringify(proyectos));
}
function abiertos() { return [...vista.querySelectorAll("details[data-k][open]")].map((d) => d.dataset.k); }
function restaurarAbiertos(claves) { vista.querySelectorAll("details[data-k]").forEach((d) => { if (claves.includes(d.dataset.k)) d.open = true; }); }
function posprocesar() {
  vista.querySelectorAll("form").forEach(alternarTipo);
  $("#btn-actualizar").style.display = actual === "resumen" ? "" : "none";
  if (actual === "app") { pintarDescanso(); pintarVersion(); }
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
  const t = { resumen: "Resumen", registrar: "Registrar día", hojas: "Hojas conectadas", correo: "Correo", ajustes: "Ajustes del proyecto", app: "Ajustes de la app" }[nombre];
  const atras = nombre === "app" ? `<button class="atras" data-ir="${ultimaTab}">‹ Volver</button>` : "";
  return `<header class="cab-pagina">${atras}<h1>${t}</h1></header>`;
}
const claveCache = () => "ff-res-" + (proyectos.activo || "");
async function ir(nombre, mantener) {
  actual = nombre; if (nombre !== "app") ultimaTab = nombre; resaltarTab();
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
    vista.innerHTML = cabeza(actual) + r.html; posprocesar(); restaurarAbiertos(abiertas);
    if (r.subtitulo) { const h = vista.querySelector(".cab-pagina"); if (h) h.insertAdjacentHTML("beforeend", `<p>${r.subtitulo}</p>`); }
    if (!nuevaPagina) scrollTo(0, y);
    ponerBarra(r.barra || null);
    if (r.scroll) setTimeout(() => vista.querySelector(r.scroll)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    if (actual === "resumen" && !PRUEBA && !r.html.includes("Un momento") && !r.html.includes('id="reporte-panel"')) guardar(claveCache(), JSON.stringify({ html: r.html, t: Date.now() }));
  }
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
  descanso_min(el) { guardar("ff-descanso", el.dataset.v); pintarDescanso(); toast(el.dataset.v === "0" ? "Descanso: nunca" : "Descanso tras " + el.textContent); },
  descansar() { mostrarPortada("descanso"); },
  buscar_version() { revisarVersion(true); },
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
async function abrirReporte(rep) {
  const html = rep.html.replace("LOGO_CLARO", await logoComoDato("assets/logo_filmflow_claro.png"))
                       .replace("LOGO_OSCURO", await logoComoDato("assets/logo_filmflow_oscuro.png"));
  const capa = document.createElement("div");
  capa.className = "reporte-capa";
  capa.innerHTML = `<div class="reporte-barra"><button class="btn mini" data-r="cerrar">Cerrar</button><span class="espacio"></span>
    <button class="btn mini" data-r="pdf">PDF / Imprimir</button><button class="btn mini acento" data-r="compartir">Compartir</button></div>
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
  mostrar(await api(t.dataset.a, p));
});
document.addEventListener("change", async (e) => {
  const t = e.target;
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
    const card = g.closest(".rollo"); card.parentElement.querySelectorAll("details.rollo[open]").forEach((x) => { x.open = false; });
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
if ("serviceWorker" in navigator && !PRUEBA) escucharVersionNueva();
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
async function revisarVersion(aMano) {
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
  const nueva = versionNube && numVersion(versionNube.id) > numVersion(MI_VERSION.id);
  const estado = revisandoVersion ? "Buscando si hay una versión nueva…"
    : nueva ? `Hay una versión nueva (${versionNube.app || versionNube.id}): se está instalando sola.`
    : ultimaRevision ? `Tienes la última versión. Revisado a las ${new Date(ultimaRevision).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}.`
    : "Se revisa sola al abrir la app.";
  cont.innerHTML = `<section class="tarjeta"><p>Versión instalada: <b>${MI_VERSION.app || "—"}</b>${MI_VERSION.fecha ? ` <span class="sub">· publicada el ${MI_VERSION.fecha}</span>` : ""}</p>
    <p class="sub">${estado}</p>
    <p class="sub">La app se actualiza sola: al abrirla y cada rato revisa si hay una versión nueva y la instala sin borrar tus proyectos ni tu sesión.</p>
    <div class="barra-mini llena"><button class="btn" data-js="buscar_version" title="Preguntar ahora mismo si hay una versión nueva de la app.">Buscar actualizaciones</button>
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
  const regreso = PRUEBA ? null : await regresoDeGoogle();          // volviendo de iniciar sesión (app instalada)
  if (regreso === "redirige") return;
  if (!PRUEBA && CFG.clientId) cargarGIS().catch(() => {});
  const sinSesion = !tokenVigente() && !PRUEBA && !leer("ff-correo");
  let conCache = false;
  if (sinSesion) {                                   // primera pantalla: solo conectar con Google; el motor carga detrás
    document.body.classList.add("sin-sesion"); actual = "resumen"; mostrarPortada("inicio");
    motorListo.catch(() => {});
  } else {
    if (!PRUEBA) {                                   // se ve al instante lo último guardado, sin esperar al motor
      try { const c = JSON.parse(leer("ff-proy") || "null"); if (c && c.activo) { proyectos = c; $("#proyecto-nombre").textContent = c.activo; } } catch (e) {}
      const ini = new URLSearchParams(location.search).get("p") || "resumen";
      if (ini === "resumen") { const c = leer(claveCache()); if (c) { try { const o = JSON.parse(c); if (o.html) { vista.innerHTML = cabeza("resumen") + o.html; vista.classList.add("carga"); conCache = true; resaltarTab(); } } catch (e) {} } }
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
  if ("serviceWorker" in navigator && !PRUEBA) activarActualizaciones();
  const inicial = new URLSearchParams(location.search).get("p") || "resumen";
  window.__ff = { api, ir, listo: true, get sesion() { return sesion; }, sincronizar };
  try { const c = await llamar("cuenta", {}); if (c && c.proyectos) actualizarProyectos(c.proyectos); } catch (e) {}
  if (sinSesion && !leer("ff-correo")) return;       // sigue en la pantalla de inicio hasta que conecte
  if (tokenVigente() && !conCache) await sincronizar(false);   // sin nada guardado: primero traer los proyectos y leer una sola vez
  await ir(pendiente ? "ajustes" : inicial, conCache && !pendiente);
  if (pendiente && pendiente.accion) mostrar(await api(pendiente.accion, pendiente.p || {}));
  await procesarInvitacion();
  if (tokenVigente() && conCache) sincronizar(false);
})();
