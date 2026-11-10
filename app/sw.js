const VERSION='ff-1794343252';
const ARCHIVOS=[
  'LEEME_CELULAR.txt',
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
self.addEventListener('install', e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting())); });
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
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request).catch(err => {
    // sin internet, abrir la dirección raíz «/» (o cualquier página) muestra la app guardada
    if (e.request.mode === 'navigate') return caches.match('index.html', { ignoreSearch: true }).then(x => x || Promise.reject(err));
    throw err;
  })));
});
