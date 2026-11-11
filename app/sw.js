const VERSION='ff-1794356140';
const ARCHIVOS=[
  'app.js',
  'assets/fondo_bienvenida.jpg',
  'assets/icono-180.png',
  'assets/icono-192.png',
  'assets/icono-512.png',
  'assets/logo_filmflow_claro.png',
  'assets/logo_filmflow_grande.png',
  'assets/logo_filmflow_grande_claro.png',
  'assets/logo_filmflow_oscuro.png',
  'config.js',
  'index.html',
  'manifest.webmanifest',
  'paleta.css',
  'pdftexto.js',
  'py/config_inicial.json',
  'py/correo_core.py',
  'py/cruce_core.py',
  'py/estadistico_core.py',
  'py/movil_api.py',
  'py/movil_html.py',
  'py/registro_core.py',
  'py/registro_diario.py',
  'py/registro_google.py',
  'py/reporte_core.py',
  'py/resumen_core.py',
  'py/sync_core.py',
  'py/tema_web.py',
  'py/web_shim.py',
  'styles.css',
  'vendor/pdfjs/pdf.mjs',
  'vendor/pdfjs/pdf.worker.mjs',
  'vendor/pyodide/package.json',
  'vendor/pyodide/pyodide-lock.json',
  'vendor/pyodide/pyodide.asm.js',
  'vendor/pyodide/pyodide.asm.wasm',
  'vendor/pyodide/pyodide.js',
  'vendor/pyodide/pyodide.mjs',
  'vendor/pyodide/python_stdlib.zip',
  'version.js',
  'worker.js',
];
// cache:'reload' = siempre de internet (GitHub Pages deja guardar archivos 10 min: sin esto la versión nueva podía armarse con archivos viejos)
self.addEventListener('install', e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(ARCHIVOS.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin || e.request.method !== 'GET') return;     // Google y demás: siempre en vivo
  // «Reparar»/reintento: el pedido con cache «reload» va a la red y repone la copia (antes se volvía a servir la copia dañada)
  if (e.request.cache === 'reload' || e.request.cache === 'no-store') {
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const c = r.clone(); caches.open(VERSION).then(k => k.put(e.request, c)).catch(() => {}); } return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true })));
    return;
  }
  // lo que no está en la copia guardada se pide a internet PREGUNTANDO si cambió (no-cache: nunca un archivo viejo que el navegador
  // guardó por su cuenta) y se agrega a la copia para usarlo sin internet
  const red = () => fetch(e.request.mode === 'navigate' ? e.request.url : e.request, { cache: 'no-cache' }).then(r => {
    if (r.ok && !u.search) { const c = r.clone(); caches.open(VERSION).then(k => k.put(u.pathname.endsWith('/') ? u.href + 'index.html' : u.href, c)).catch(() => {}); }
    return r;
  });
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || red().catch(err => {
    // sin internet, abrir la dirección raíz «/» (o cualquier página) muestra la app guardada
    if (e.request.mode === 'navigate') return caches.match('index.html', { ignoreSearch: true }).then(x => x || Promise.reject(err));
    throw err;
  })));
});
