const VERSION='ff-1794614695';
const ARCHIVOS=[
  ['app.js','841865cebde7b21d'],
  ['assets/fondo_bienvenida.jpg','8a31a09a70f6b4cb'],
  ['assets/icono-180.png','1b2c2621dbd1f412'],
  ['assets/icono-192.png','cef4a782be966592'],
  ['assets/icono-512.png','11458bdedaa52b87'],
  ['assets/logo_filmflow_claro.png','67dcf9e7b9595def'],
  ['assets/logo_filmflow_grande.png','ea6d1c638e8080a7'],
  ['assets/logo_filmflow_grande_claro.png','604140d3c6f4ed83'],
  ['assets/logo_filmflow_oscuro.png','9635ce95300143b6'],
  ['config.js','2f155e4abf18efa1'],
  ['index.html','550351d3b38d5c76'],
  ['manifest.webmanifest','15a83cb83ef6ca88'],
  ['paleta.css','8c90aae993aed9e6'],
  ['pdftexto.js','c2c9f87a09288548'],
  ['py/config_inicial.json','72eeafe923ad219b'],
  ['py/correo_core.py','8b6e0e73be0f9ce2'],
  ['py/cruce_core.py','e7656cf2762053a0'],
  ['py/estadistico_core.py','2f2634279083fd7f'],
  ['py/movil_api.py','a5b9e861d71e9f53'],
  ['py/movil_html.py','ae5bc4d7260b15aa'],
  ['py/registro_core.py','d5bbff9b1ab640ce'],
  ['py/registro_diario.py','f765715d350bf62c'],
  ['py/registro_google.py','7e6889bcb5c36656'],
  ['py/reporte_core.py','0c98c62a12514fa3'],
  ['py/resumen_core.py','8e32586b92ebe0c7'],
  ['py/sync_core.py','6df487bd3f1e732e'],
  ['py/tema_web.py','35f4329010fae1d8'],
  ['py/web_shim.py','7086ff1a3ad21e28'],
  ['styles.css','23ec4e3b7ef971f3'],
  ['vendor/pdfjs/pdf.mjs','a209a2124baa35cb'],
  ['vendor/pdfjs/pdf.worker.mjs','7c237f83fa56bce6'],
  ['vendor/pyodide/package.json','bf221f60c8816262'],
  ['vendor/pyodide/pyodide-lock.json','9c45b916001a750f'],
  ['vendor/pyodide/pyodide.asm.js','6b4c90de5b717287'],
  ['vendor/pyodide/pyodide.asm.wasm','a50dd1843f805a0b'],
  ['vendor/pyodide/pyodide.js','b4cb23a53aba19c2'],
  ['vendor/pyodide/pyodide.mjs','04c052c815abb0bf'],
  ['vendor/pyodide/python_stdlib.zip','16611534726e5d8a'],
  ['version.js','26b17dc8fa564da9'],
  ['worker.js','7d0ee7ac107afa5c'],
];
// Al instalar una versión: los archivos con la MISMA huella que en la versión guardada se copian de ella (sin internet); los demás se
// piden con cache:'reload' = siempre de internet (GitHub Pages deja guardar archivos 10 min: sin esto la versión nueva podía armarse
// con archivos viejos). «__huellas__» guarda las huellas de esta versión para la próxima.
self.addEventListener('install', e => { e.waitUntil((async () => {
  const nueva = await caches.open(VERSION);
  const viejas = (await caches.keys()).filter(k => k !== VERSION);
  let previas = {};
  for (const k of viejas) { try { const r = await (await caches.open(k)).match('__huellas__'); if (r) { previas = await r.json(); break; } } catch (_) {} }
  await Promise.all(ARCHIVOS.map(async ([u, h]) => {
    if (previas[u] === h) {
      for (const k of viejas) { try { const r = await (await caches.open(k)).match(u); if (r) { await nueva.put(u, r); return; } } catch (_) {} }
    }
    const r = await fetch(new Request(u, { cache: 'reload' }));
    if (!r.ok) throw new Error('No pude bajar ' + u);
    await nueva.put(u, r);
  }));
  await nueva.put('__huellas__', new Response(JSON.stringify(Object.fromEntries(ARCHIVOS)), { headers: { 'Content-Type': 'application/json' } }));
  await self.skipWaiting();
})()); });
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
