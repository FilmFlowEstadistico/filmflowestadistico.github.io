// Lee un PDF de Silverstack en el teléfono y devuelve su texto línea por línea (como pdftotext -layout), sin enviar nada a internet.
import * as pdfjs from "./vendor/pdfjs/pdf.mjs";
pdfjs.GlobalWorkerOptions.workerSrc = new URL("./vendor/pdfjs/pdf.worker.mjs", import.meta.url).href;

export async function textoDelPdf(buffer) {
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(buffer), isEvalSupported: false }).promise;
  const paginas = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const pagina = await pdf.getPage(n);
    const contenido = await pagina.getTextContent();
    const items = contenido.items.filter(i => i.str !== undefined && i.str.trim() !== "")
      .map(i => ({ s: i.str, x: i.transform[4], y: i.transform[5], w: i.width, h: Math.abs(i.height) || 8 }));
    items.sort((a, b) => b.y - a.y || a.x - b.x);
    const lineas = [];
    for (const it of items) {
      const l = lineas.find(l => Math.abs(l.y - it.y) <= Math.max(2, it.h * 0.45));
      if (l) l.items.push(it); else lineas.push({ y: it.y, items: [it] });
    }
    lineas.sort((a, b) => b.y - a.y);
    const salida = [];
    for (const l of lineas) {
      l.items.sort((a, b) => a.x - b.x);
      let txt = "", fin = null;
      for (const it of l.items) {
        if (fin === null) txt = it.s;
        else {
          const hueco = it.x - fin;
          txt += (hueco > 1.2 ? " ".repeat(Math.max(1, Math.round(hueco / 4))) : "") + it.s;
        }
        fin = it.x + it.w;
      }
      salida.push(txt);
    }
    paginas.push(salida.join("\n"));
  }
  return paginas.join("\n");
}

// Miniatura de la primera página de un PDF (para ver los adjuntos del correo). Devuelve una imagen (data URL) o null.
export async function miniaturaPdf(buffer, ancho = 240) {
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(buffer), isEvalSupported: false }).promise;
  try {
    const pag = await pdf.getPage(1);
    const v0 = pag.getViewport({ scale: 1 });
    const esc = (ancho * 2) / v0.width;
    const v = pag.getViewport({ scale: esc });
    const c = document.createElement("canvas"); c.width = Math.round(v.width); c.height = Math.min(Math.round(v.height), Math.round(v.width * 1.6));
    const ctx = c.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
    await pag.render({ canvasContext: ctx, viewport: v }).promise;
    return c.toDataURL("image/jpeg", 0.8);
  } finally { try { pdf.destroy(); } catch (e) {} }
}
