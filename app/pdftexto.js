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
