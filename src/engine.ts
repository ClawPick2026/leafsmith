import * as PDFLib from 'pdf-lib';
import qrFactory from 'qrcode-generator';
import { createEngine } from '../web/client/engine-core.ts';
export type { PdfField, PageSize, TransformOptions, Overlay, ImageOptions } from '../web/client/engine-core.ts';

export function loadPdfLib(): Promise<any> { return Promise.resolve(PDFLib); }
export async function loadPdfJs(): Promise<any> {
  const [lib, worker] = await Promise.all([
    import('pdfjs-dist/build/pdf.mjs'),
    import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
  ]);
  lib.GlobalWorkerOptions.workerSrc = worker.default;
  return lib;
}
function loadQr(): Promise<any> { return Promise.resolve(qrFactory); }

export const { openPdf, pdfInfo, makeDemoPdf, transformPdf, mergePdfs, overlayPdf, fillPdf, imagesToPdf, optimizePdf, qrSvg, renderPdfPage, renderPdfPages, extractPdfText, processImage, mergeImages, validateFileSize } = createEngine({ loadPdfLib, loadPdfJs, loadQr });
