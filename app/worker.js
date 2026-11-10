// Corre Python (Pyodide) en segundo plano con el MISMO código de la app del Mac. Habla con Google Sheets de forma directa.
let py = null, llamar = null, sheetsBase = "https://sheets.googleapis.com";
const REAL = "https://sheets.googleapis.com";
const ARCHIVOS = ["web_shim.py", "movil_html.py", "movil_api.py", "tema_web.py", "registro_core.py", "registro_diario.py", "registro_google.py",
  "estadistico_core.py", "resumen_core.py", "reporte_core.py", "cruce_core.py", "correo_core.py", "sync_core.py", "config_inicial.json"];
let hubo401 = false;

self.sheetsXHR = (metodo, url, cuerpo, token) => {
  if (sheetsBase !== REAL) url = url.replace(REAL, sheetsBase).replace("https://www.googleapis.com/drive", sheetsBase + "/drive");
  const x = new XMLHttpRequest();
  x.open(metodo, url, false);
  try { x.timeout = 45000; } catch (_) {}        // con señal débil una petición no puede dejar la app trabada para siempre
  x.setRequestHeader("Authorization", "Bearer " + token);
  if (cuerpo != null) x.setRequestHeader("Content-Type", "application/json");
  try { x.send(cuerpo); } catch (e) { return [0, String(e && e.name === "TimeoutError" ? "Google tardó más de 45 s en responder" : e)]; }
  if (x.status === 401) hubo401 = true;
  return [x.status, x.responseText];
};

const etapa = (t) => { try { postMessage({ etapa: t }); } catch (_) {} };
const conTiempo = (p, ms, que) => new Promise((ok, mal) => { const t = setTimeout(() => mal(new Error("Se quedó esperando: " + que + " (más de " + Math.round(ms / 1000) + " s)")), ms); p.then((v) => { clearTimeout(t); ok(v); }, (e) => { clearTimeout(t); mal(e); }); });
let idbMuerto = false;                          // si IndexedDB no responde, se sigue sin guardar en el teléfono (Google lo recupera)
const sincronizar = () => idbMuerto ? Promise.resolve() : new Promise(res => { const t = setTimeout(res, 8000); try { py.FS.syncfs(false, () => { clearTimeout(t); res(); }); } catch (e) { clearTimeout(t); res(); } });
const txtError = (e) => {
  try {
    if (e instanceof Error) return (e.name || "Error") + ": " + (e.message || "") + (e.stack ? "\n" + String(e.stack).split("\n").slice(0, 3).join("\n") : "");
    if (e && typeof e === "object") return (e.name ? e.name + ": " : "") + (e.message || JSON.stringify(e, Object.getOwnPropertyNames(e)));
  } catch (_) {}
  return String(e);
};

async function arrancar(base, opciones) {
  if (opciones && opciones.sheets) sheetsBase = opciones.sheets;
  importScripts(base + "vendor/pyodide/pyodide.js");
  const forzar = !!(opciones && opciones.forzar), cache = forzar ? "reload" : "default";
  // La librería base de Python se comprueba ANTES de arrancar: si llega a medias, Python se cierra con «ExitStatus exit(1)».
  etapa("Descargando la base de Python…");
  const rs = await conTiempo(fetch(base + "vendor/pyodide/python_stdlib.zip", { cache }), 60000, "la descarga de python_stdlib.zip");
  if (!rs.ok) throw new Error("python_stdlib.zip: HTTP " + rs.status);
  const std = await conTiempo(rs.blob(), 60000, "leer python_stdlib.zip");
  if (std.size < 2300000) throw new Error("python_stdlib.zip llegó incompleto (" + std.size + " bytes)");
  if (forzar) { try { await (await fetch(base + "vendor/pyodide/pyodide.asm.wasm", { cache })).arrayBuffer(); } catch (_) {} }
  const errPy = [];
  etapa("Arrancando el motor de Python…");
  // la base de Python ya está bajada y comprobada: se le pasa tal cual (antes Pyodide la volvía a bajar, 2,4 MB)
  let stdURL = null;
  try { stdURL = URL.createObjectURL(std); } catch (_) {}
  try {
    py = await conTiempo(loadPyodide(Object.assign({ indexURL: base + "vendor/pyodide/", stderr: (l) => { errPy.push(l); if (errPy.length > 30) errPy.shift(); } },
      stdURL ? { stdLibURL: stdURL } : {})), 120000, "el arranque del motor de Python");
  } catch (e) {
    throw new Error("El motor de Python no pudo iniciar: " + ((e && (e.name || "") + " " + (e.message || "")) || String(e)).trim() + " [" + (self.navigator ? self.navigator.userAgent.slice(0, 90) : "") + "]" + (errPy.length ? "\n" + errPy.join("\n").slice(-500) : ""));
  }
  py.FS.mkdir("/datos");
  if (opciones && opciones.sinDatos) { idbMuerto = true; self.avisoDatos = "Modo sin datos guardados en el teléfono."; }
  else {
    etapa("Leyendo tus datos guardados…");
    py.FS.mount(py.FS.filesystems.IDBFS, {}, "/datos");
    // Si los datos guardados en el teléfono no se pueden leer (o IndexedDB no responde), la app arranca igual y los recupera de Google al sincronizar.
    await new Promise((ok) => { const t = setTimeout(() => { idbMuerto = true; self.avisoDatos = "IndexedDB no respondió en 10 s"; ok(); }, 10000);
      try { py.FS.syncfs(true, e => { clearTimeout(t); if (e) self.avisoDatos = txtError(e); ok(); }); } catch (e) { clearTimeout(t); self.avisoDatos = txtError(e); ok(); } });
  }
  etapa("Cargando la app…");
  py.FS.mkdir("/app");
  const textos = await Promise.all(ARCHIVOS.map(async (f) => {   // los módulos se bajan a la vez (antes uno por uno)
    const r = await conTiempo(fetch(base + "py/" + f, { cache }), 30000, "la descarga de " + f);
    if (!r.ok) throw new Error("No pude cargar " + f);
    return r.text();
  }));
  ARCHIVOS.forEach((f, i) => py.FS.writeFile("/app/" + f, textos[i]));
  try { py.runPython(`
import os, sys
os.environ["FILMFLOW_DATOS"] = "/datos"
sys.path.insert(0, "/app")
import web_shim
import js
def _t(m, u, c, tok):
    r = js.sheetsXHR(m, u, c, tok)
    return int(r[0]), str(r[1])
web_shim.ESTADO["transporte"] = _t
import movil_api
movil_api.iniciar()
`); } catch (e) { throw new Error("Falló al preparar los módulos de Python: " + txtError(e) + (errPy.length ? "\n" + errPy.join("\n").slice(-500) : "")); }
  llamar = py.runPython("movil_api.llamar");
  etapa("Listo");
  await sincronizar();
}

// Los mensajes se atienden EN FILA (uno termina antes de empezar el siguiente) y la respuesta sale ANTES de guardar en el teléfono:
// antes un toque esperaba a que terminara otra llamada a Google y a guardar en IndexedDB (hasta 8 s) de la llamada anterior.
let fila = Promise.resolve();
async function atender(m) {
  try {
    if (m.tipo === "arrancar") {
      await arrancar(m.base, m.opciones);
      postMessage({ id: m.id, ok: true });
    } else if (m.tipo === "llamar") {
      hubo401 = false;
      const texto = llamar(m.nombre, JSON.stringify(m.p || {}), m.token || null, m.correo || null);
      const r = JSON.parse(texto);
      if (hubo401) r.auth401 = true;
      postMessage({ id: m.id, ok: true, r });
      await sincronizar();                       // guardar en el teléfono después de responder (el siguiente mensaje espera)
    }
  } catch (err) {
    postMessage({ id: m.id, ok: false, error: txtError(err) });
  }
}
self.onmessage = (e) => { fila = fila.then(() => atender(e.data)); };
