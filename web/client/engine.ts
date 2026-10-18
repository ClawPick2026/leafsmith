import { createEngine } from './engine-core.ts';
export type { PdfField, TransformOptions, Overlay, ImageOptions } from './engine-core.ts';
const globals = globalThis as typeof globalThis & { PDFLib?: any; pdfjsLib?: any; qrcode?: any };
const scripts = new Map<string, Promise<any>>();
const PDF_LIB_URL = 'https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js';
const PDF_JS_URL = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js';

function loadScript(url: string, name: 'PDFLib' | 'pdfjsLib' | 'qrcode'): Promise<any> {
  if (globals[name]) return Promise.resolve(globals[name]);
  if (scripts.has(url)) return scripts.get(url)!;
  const promise = new Promise<any>((resolve, reject) => {
    const fail = () => reject(new Error('Unable to load the PDF/image library. Check your internet connection, allow cdn.jsdelivr.net, then retry. Your files have not been uploaded.'));
    if (typeof document === 'undefined') { fail(); return; }
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    const timer = setTimeout(() => { script.remove(); fail(); }, 20_000);
    script.onerror = () => { clearTimeout(timer); script.remove(); fail(); };
    script.onload = () => { clearTimeout(timer); if (globals[name]) resolve(globals[name]); else { script.remove(); fail(); } };
    document.head.appendChild(script);
  });
  scripts.set(url, promise);
  // Remove both successes and failures: a failed load is retryable, a loaded global is reused.
  void promise.then(() => scripts.delete(url), () => scripts.delete(url));
  return promise;
}

export function loadPdfLib(): Promise<any> { return loadScript(PDF_LIB_URL, 'PDFLib'); }


export async function loadPdfJs(): Promise<any> {
  const lib = await loadScript(PDF_JS_URL, 'pdfjsLib');
  lib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
  return lib;
}
function loadQr(): Promise<any> { return loadScript('https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js', 'qrcode'); }

export const { openPdf, pdfInfo, makeDemoPdf, transformPdf, mergePdfs, overlayPdf, fillPdf, imagesToPdf, optimizePdf, qrSvg, renderPdfPage, extractPdfText, processImage, mergeImages, validateFileSize } = createEngine({ loadPdfLib, loadPdfJs, loadQr });
