/** Shared processing operations; platform adapters own all library loading. */
import { viewMarginsToPdf } from '../shared/crop.ts';
import type { Margins, Rect } from '../shared/crop.ts';
export type EngineDependencies = {
  loadPdfLib: () => Promise<any>;
  loadPdfJs: () => Promise<any>;
  loadQr: () => Promise<any>;
};
export type PdfField = { name: string; type: string; value: string | boolean; options?: string[] };
/** Crop margins are measured on each page as displayed, after its existing /Rotate value. */
export type TransformOptions = { pages: number[]; rotate?: number; crop?: Margins };
export type PageSize = { width: number; height: number; rotation: number; box: Rect };
export type Overlay = { page: number; kind: 'text' | 'rectangle' | 'highlight' | 'image' | 'signature'; x: number; y: number; width: number; height: number; text?: string; fontSize?: number; fontFamily?: 'Helvetica' | 'TimesRoman' | 'Courier'; color?: string; imageBytes?: Uint8Array; imageMime?: string };
export type ImageOptions = { format: 'image/jpeg' | 'image/png' | 'image/webp'; quality: number; maxWidth: number; brightness: number; contrast: number; crop?: Margins };

const MAX_BYTES = 25 * 1024 * 1024;

export function createEngine({ loadPdfLib, loadPdfJs, loadQr }: EngineDependencies) {
// One PDF.js worker serves every document of this engine; otherwise each document starts and terminates a worker.
let pdfWorker: { lib: any; worker: any } | null = null;
function openPdfJs(lib: any, bytes: Uint8Array): any {
  if (lib.PDFWorker && (!pdfWorker || pdfWorker.lib !== lib || pdfWorker.worker.destroyed)) pdfWorker = { lib, worker: new lib.PDFWorker() };
  return lib.getDocument({ data: bytes.slice(), isEvalSupported: false, useSystemFonts: true, ...(lib.PDFWorker ? { worker: pdfWorker!.worker } : {}) });
}
async function openPdf(bytes: Uint8Array): Promise<any> {
  validateFileSize(bytes.byteLength);
  const lib = await loadPdfLib();
  let doc: any;
  try { doc = await lib.PDFDocument.load(bytes, { ignoreEncryption: false, updateMetadata: false }); }
  catch (error) {
    if (/encrypt|password/i.test(String(error))) throw new Error('Encrypted or password-protected PDFs are not supported. Choose an unencrypted PDF.');
    throw new Error('This file could not be read as a valid PDF. It may be damaged or unsupported.');
  }
  if (doc.isEncrypted) throw new Error('Encrypted PDFs are not supported.');
  const count = doc.getPageCount();
  if (count < 1 || count > 200) throw new Error('PDF must contain 1–200 pages.');
  return doc;
}

/** The crop box clipped to the media box: the area PDF viewers display. */
function visibleBox(page: any): Rect {
  const media = page.getMediaBox();
  const crop = page.getCropBox();
  const x = Math.max(media.x, crop.x);
  const y = Math.max(media.y, crop.y);
  const width = Math.min(media.x + media.width, crop.x + crop.width) - x;
  const height = Math.min(media.y + media.height, crop.y + crop.height) - y;
  return width > 0 && height > 0 ? { x, y, width, height } : media;
}

async function pdfInfo(bytes: Uint8Array): Promise<{ pageCount: number; sizes: PageSize[]; fields: PdfField[] }> {
  const doc = await openPdf(bytes);
  const lib = await loadPdfLib();
  const fields: PdfField[] = doc.getForm().getFields().map((field: any) => {
    const name = field.getName();
    if (field instanceof lib.PDFTextField) return { name, type: 'text', value: field.getText() || '' };
    if (field instanceof lib.PDFCheckBox) return { name, type: 'checkbox', value: field.isChecked() };
    if (field instanceof lib.PDFDropdown) return { name, type: 'dropdown', value: field.getSelected().join(', '), options: field.getOptions() };
    if (field instanceof lib.PDFOptionList) return { name, type: 'optionlist', value: field.getSelected().join(', '), options: field.getOptions() };
    return { name, type: 'unsupported', value: '' };
  });
  return { pageCount: doc.getPageCount(), sizes: doc.getPages().map((page: any) => ({ ...page.getSize(), rotation: page.getRotation().angle, box: visibleBox(page) })), fields };
}

async function makeDemoPdf(): Promise<Uint8Array> {
  const lib = await loadPdfLib();
  const doc = await lib.PDFDocument.create();
  const font = await doc.embedFont(lib.StandardFonts.Helvetica);
  for (let i = 1; i <= 3; i++) {
    const page = doc.addPage([595.28, 841.89]);
    page.drawText('Paperwork sample - your browser, your files.', { x: 54, y: 760, size: 20, font });
    page.drawText(`Page ${i}`, { x: 54, y: 722, size: 14, font });
    page.drawText('A local sample for splitting, rotating, annotating and filling.', { x: 54, y: 680, size: 12, font });
  }
  const page = doc.getPage(0);
  const form = doc.getForm();
  page.drawText('Name', { x: 54, y: 600, size: 12, font });
  form.createTextField('name').addToPage(page, { x: 54, y: 560, width: 250, height: 26 });
  form.createCheckBox('approved').addToPage(page, { x: 54, y: 510, width: 18, height: 18 });
  page.drawText('Approved', { x: 82, y: 514, size: 12, font });
  return doc.save();
}

function pageSelection(pages: number[], count: number): number[] {
  if (!Array.isArray(pages) || !pages.length || pages.length > 200 || pages.some(p => !Number.isInteger(p) || p < 1 || p > count)) {
    throw new Error(`Select 1–200 page numbers between 1 and ${count}.`);
  }
  return pages.map(p => p - 1);
}
function finite(value: number, label: string, min = 0): void {
  if (!Number.isFinite(value) || value < min) throw new Error(`${label} must be a finite number of at least ${min}.`);
}
function cropMargins(crop: Margins, whole = false): Margins {
  for (const key of ['left', 'bottom', 'right', 'top'] as const) {
    finite(crop[key], `Crop ${key}`);
    if (whole && !Number.isInteger(crop[key])) throw new Error(`Crop ${key} must be a whole number of pixels.`);
  }
  return crop;
}
async function transformPdf(bytes: Uint8Array, options: TransformOptions): Promise<Uint8Array> {
  const source = await openPdf(bytes);
  const indices = pageSelection(options.pages, source.getPageCount());
  const rotation = options.rotate ?? 0;
  if (!Number.isInteger(rotation) || rotation % 90 !== 0) throw new Error('Rotation must be an integer multiple of 90 degrees.');
  if (options.crop) cropMargins(options.crop);
  const lib = await loadPdfLib();
  const out = await lib.PDFDocument.create();
  const pages = await out.copyPages(source, indices);
  for (const page of pages) {
    const sourceRotation = page.getRotation().angle;
    page.setRotation(lib.degrees(((sourceRotation + rotation) % 360 + 360) % 360));
    if (options.crop) {
      const box = visibleBox(page);
      const { left, bottom, right, top } = viewMarginsToPdf(options.crop, sourceRotation);
      const width = box.width - left - right;
      const height = box.height - bottom - top;
      if (width <= 0 || height <= 0) throw new Error('Crop margins must leave a positive page width and height.');
      page.setCropBox(box.x + left, box.y + bottom, width, height);
    }
    out.addPage(page);
  }
  return out.save();
}

async function mergePdfs(inputs: Uint8Array[]): Promise<Uint8Array> {
  if (!Array.isArray(inputs) || !inputs.length || inputs.length > 200) throw new Error('Choose 1–200 PDFs to merge.');
  const lib = await loadPdfLib();
  const out = await lib.PDFDocument.create();
  for (const bytes of inputs) {
    const doc = await openPdf(bytes);
    if (out.getPageCount() + doc.getPageCount() > 200) throw new Error('Merged PDFs cannot exceed 200 pages.');
    for (const page of await out.copyPages(doc, doc.getPageIndices())) out.addPage(page);
  }
  return out.save();
}

async function overlayPdf(bytes: Uint8Array, overlay: Overlay): Promise<Uint8Array> {
  const doc = await openPdf(bytes);
  const lib = await loadPdfLib();
  const index = pageSelection([overlay.page], doc.getPageCount())[0];
  for (const key of ['x', 'y', 'width', 'height'] as const) if (!Number.isFinite(overlay[key])) throw new Error(`Overlay ${key} must be a finite number.`);
  if (overlay.width <= 0 || overlay.height <= 0) throw new Error('Overlay width and height must be positive.');
  const page = doc.getPage(index);
  // Check against the area viewers display; 0.01 pt absorbs rounding of placements drawn on the preview.
  const box = visibleBox(page);
  const slack = 0.01;
  const span = (start: number, length: number) => `${Math.round(start * 100) / 100}–${Math.round((start + length) * 100) / 100}`;
  if (overlay.x < box.x - slack || overlay.y < box.y - slack || overlay.x + overlay.width > box.x + box.width + slack || overlay.y + overlay.height > box.y + box.height + slack) {
    throw new Error(`Overlay must fit inside the visible page: x ${span(box.x, box.width)}, y ${span(box.y, box.height)} in PDF points.`);
  }
  if (!['text', 'rectangle', 'highlight', 'image', 'signature'].includes(overlay.kind)) throw new Error('Unsupported overlay type.');
  const hex = overlay.color ?? (overlay.kind === 'highlight' ? '#ffdf33' : '#222222');
  if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error('Use a six-digit hex color, such as #336699.');
  const color = lib.rgb(parseInt(hex.slice(1, 3), 16) / 255, parseInt(hex.slice(3, 5), 16) / 255, parseInt(hex.slice(5, 7), 16) / 255);
  const geometry = { x: overlay.x, y: overlay.y, width: overlay.width, height: overlay.height };
  if (overlay.kind === 'text') {
    const family = overlay.fontFamily ?? 'Helvetica';
    if (!['Helvetica', 'TimesRoman', 'Courier'].includes(family)) throw new Error('Choose Helvetica, TimesRoman or Courier.');
    const fontSize = overlay.fontSize ?? 16;
    finite(fontSize, 'Font size', 1);
    if (fontSize > 500) throw new Error('Font size must be 500 points or smaller.');
    if (typeof overlay.text !== 'string' || !overlay.text.trim()) throw new Error('Enter text for the overlay.');
    const font = await doc.embedFont(lib.StandardFonts[family]);
    try {
      // WinAnsi standard fonts intentionally reject unsupported characters instead of silently corrupting them.
      font.encodeText(overlay.text);
      // The first line starts at the top of the box and later lines wrap downwards, matching the placement box.
      const baseline = overlay.y + overlay.height - font.heightAtSize(fontSize, { descender: false });
      page.drawText(overlay.text, { x: overlay.x, y: baseline, size: fontSize, font, color, maxWidth: overlay.width, lineHeight: fontSize * 1.2 });
    } catch { throw new Error('This text cannot be drawn with a standard PDF font. Use supported Latin characters.'); }
  } else if (overlay.kind === 'image') {
    if (!overlay.imageBytes) throw new Error('Choose a PNG or JPEG image.');
    const image = await embedImage(doc, overlay.imageBytes, overlay.imageMime ?? '');
    page.drawImage(image, geometry);
  } else if (overlay.kind === 'signature') {
    if (!overlay.imageBytes) throw new Error('Draw a signature or choose a PNG or JPEG image.');
    const image = await embedImage(doc, overlay.imageBytes, overlay.imageMime ?? '');
    // Viewers paint page content first and then annotations in /Annots order, so a stamp appended
    // last stays above form fields, comments and earlier signatures instead of being covered by them.
    const appearance = doc.context.formXObject(
      [lib.pushGraphicsState(), lib.scale(overlay.width, overlay.height), lib.drawObject('Signature'), lib.popGraphicsState()],
      { BBox: [0, 0, overlay.width, overlay.height], Resources: { XObject: { Signature: image.ref } } },
    );
    const printable = 4, locked = 128;
    page.node.addAnnot(doc.context.register(doc.context.obj({
      Type: 'Annot', Subtype: 'Stamp', P: page.ref, F: printable | locked, Contents: lib.PDFString.of('Signature'),
      Rect: [overlay.x, overlay.y, overlay.x + overlay.width, overlay.y + overlay.height], AP: { N: doc.context.register(appearance) },
    })));
  } else if (overlay.kind === 'highlight') {
    page.drawRectangle({ ...geometry, color, opacity: 0.3 });
  } else {
    page.drawRectangle({ ...geometry, borderColor: color, borderWidth: 1.5, opacity: 0, borderOpacity: 1 });
  }
  return doc.save();
}

async function embedImage(doc: any, bytes: Uint8Array, mime: string): Promise<any> {
  validateFileSize(bytes.byteLength);
  if (mime !== 'image/png' && mime !== 'image/jpeg') throw new Error('Only PNG and JPEG images are supported for PDFs.');
  try { return await (mime === 'image/png' ? doc.embedPng(bytes) : doc.embedJpg(bytes)); }
  catch { throw new Error('This image is not a valid PNG or JPEG matching its file type.'); }
}

async function fillPdf(bytes: Uint8Array, values: Record<string, string | boolean>, flatten: boolean): Promise<Uint8Array> {
  const doc = await openPdf(bytes);
  const lib = await loadPdfLib();
  const form = doc.getForm();
  for (const [name, value] of Object.entries(values)) {
    const field = form.getFieldMaybe(name);
    if (!field) throw new Error(`Unknown form field: ${name}`);
    if (field instanceof lib.PDFCheckBox) {
      if (typeof value !== 'boolean') throw new Error(`Checkbox ${name} requires a boolean value.`);
      value ? field.check() : field.uncheck();
    } else if (field instanceof lib.PDFTextField) {
      if (typeof value !== 'string') throw new Error(`Text field ${name} requires text.`);
      field.setText(value);
    } else if (field instanceof lib.PDFDropdown || field instanceof lib.PDFOptionList) {
      if (typeof value !== 'string') throw new Error(`Choice field ${name} requires text.`);
      if (!value) field.clear();
      else {
        if (!field.getOptions().includes(value)) throw new Error(`Choose an available option for ${name}.`);
        field.select(value);
      }
    } else throw new Error(`Form field ${name} is not a supported text, checkbox or choice field.`);
  }
  try {
    const font = await doc.embedFont(lib.StandardFonts.Helvetica);
    form.updateFieldAppearances(font);
    if (flatten) form.flatten();
    return await doc.save();
  } catch (error) {
    if (/WinAnsi|encode/i.test(String(error))) throw new Error('These form values require characters unavailable in the standard PDF font. Use supported Latin characters.');
    throw error;
  }
}

async function imagesToPdf(images: { bytes: Uint8Array; mime: string }[]): Promise<Uint8Array> {
  if (!Array.isArray(images) || !images.length || images.length > 200) throw new Error('Choose 1–200 PNG or JPEG images.');
  const lib = await loadPdfLib();
  const doc = await lib.PDFDocument.create();
  for (const input of images) {
    const image = await embedImage(doc, input.bytes, input.mime);
    finite(image.width, 'Image width', 1); finite(image.height, 'Image height', 1);
    const scale = Math.min(1, 595.28 / image.width, 841.89 / image.height);
    const width = image.width * scale;
    const height = image.height * scale;
    doc.addPage([width, height]).drawImage(image, { x: 0, y: 0, width, height });
  }
  return doc.save();
}

async function optimizePdf(bytes: Uint8Array): Promise<Uint8Array> {
  const doc = await openPdf(bytes);
  const optimized: Uint8Array = await doc.save({ useObjectStreams: true });
  return optimized.byteLength < bytes.byteLength ? optimized : bytes;
}

async function qrSvg(text: string): Promise<string> {
  if (typeof text !== 'string' || !text.trim()) throw new Error('Enter non-empty text or a URL for the QR code.');
  if (new TextEncoder().encode(text).byteLength > 1000) throw new Error('QR payload must be at most 1000 UTF-8 bytes.');
  const qrFactory = await loadQr();
  const previous = qrFactory.stringToBytes;
  try {
    qrFactory.stringToBytes = (value: string) => Array.from(new TextEncoder().encode(value));
    const qr = qrFactory(0, 'M');
    qr.addData(text, 'Byte');
    qr.make();
    // No user input is put into SVG attributes or text, only encoded module geometry.
    return qr.createSvgTag({ cellSize: 4, margin: 16, scalable: true });
  } finally { qrFactory.stringToBytes = previous; }
}

const MAX_PIXELS = 16_000_000;
function pixelBudget(width: number, height: number): void {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 1 || height < 1 || Math.ceil(width) * Math.ceil(height) > MAX_PIXELS) {
    throw new Error('Image canvas exceeds the 16 million pixel limit. Reduce the size or scale.');
  }
}
/** Renders pages as displayed. Optional crop margins are PDF points on the displayed page. */
async function renderPdfPages(bytes: Uint8Array, pages: number[], scale = 1, crop?: Margins): Promise<HTMLCanvasElement[]> {
  finite(scale, 'Render scale', Number.MIN_VALUE);
  if (crop) cropMargins(crop);
  const doc = await openPdf(bytes);
  pageSelection(pages, doc.getPageCount());
  const lib = await loadPdfJs();
  const task = openPdfJs(lib, bytes);
  const canvases: HTMLCanvasElement[] = [];
  try {
    const pdf = await task.promise;
    for (const page of pages) {
      const pdfPage = await pdf.getPage(page);
      const viewport = pdfPage.getViewport({ scale });
      const [left, top, right, bottom] = crop ? [crop.left, crop.top, crop.right, crop.bottom].map(value => value * scale) : [0, 0, 0, 0];
      const width = viewport.width - left - right;
      const height = viewport.height - top - bottom;
      if (width < 1 || height < 1) throw new Error('Crop margins must leave at least one pixel of the page.');
      pixelBudget(width, height);
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(width);
      canvas.height = Math.ceil(height);
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Your browser could not create a canvas. Try a current browser.');
      await pdfPage.render({ canvasContext: context, viewport, background: 'white', ...(crop ? { transform: [1, 0, 0, 1, -left, -top] } : {}) }).promise;
      pdfPage.cleanup();
      canvases.push(canvas);
    }
    return canvases;
  } catch (error) {
    for (const canvas of canvases) { canvas.width = 0; canvas.height = 0; }
    throw error;
  } finally { await task.destroy(); }
}
async function renderPdfPage(bytes: Uint8Array, page: number, scale = 1, crop?: Margins): Promise<HTMLCanvasElement> {
  return (await renderPdfPages(bytes, [page], scale, crop))[0];
}

async function extractPdfText(bytes: Uint8Array, pages: number[]): Promise<string> {
  const doc = await openPdf(bytes);
  pageSelection(pages, doc.getPageCount());
  const lib = await loadPdfJs();
  const task = openPdfJs(lib, bytes);
  try {
    const pdf = await task.promise;
    const output: string[] = [];
    for (const number of pages) {
      const page = await pdf.getPage(number);
      const content = await page.getTextContent();
      const text = content.items.map((item: any) => typeof item.str === 'string' ? item.str + (item.hasEOL ? '\n' : ' ') : '').join('').trim();
      output.push(`Page ${number}\n${text || '[No extractable text on this page. Scanned pages require OCR, which is not available.]'}`);
      page.cleanup();
    }
    return output.join('\n\n');
  } finally { await task.destroy(); }
}

function checkImageBytes(bytes: Uint8Array, mime: string): void {
  validateFileSize(bytes.byteLength);
  const png = bytes.length >= 8 && [137,80,78,71,13,10,26,10].every((v,i) => bytes[i] === v);
  const jpeg = bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  const webp = bytes.length >= 12 && String.fromCharCode(...bytes.slice(0,4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8,12)) === 'WEBP';
  if (!(mime === 'image/png' && png || mime === 'image/jpeg' && jpeg || mime === 'image/webp' && webp)) {
    throw new Error('Choose a valid PNG, JPEG or WebP image matching its file type.');
  }
}
async function decodeImage(bytes: Uint8Array, mime: string): Promise<any> {
  checkImageBytes(bytes, mime);
  const blob = new Blob([bytes.slice().buffer as ArrayBuffer], { type: mime });
  let image: any;
  try {
    if (typeof createImageBitmap === 'function') image = await createImageBitmap(blob);
    else {
      const url = URL.createObjectURL(blob);
      try {
        image = await new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          const timer = setTimeout(() => { img.src = ''; reject(new Error('Image decode timed out.')); }, 20_000);
          img.onload = () => { clearTimeout(timer); resolve(img); };
          img.onerror = () => { clearTimeout(timer); reject(new Error('Image decode failed.')); };
          img.src = url;
        });
      } finally { URL.revokeObjectURL(url); }
    }
    finite(image.width, 'Decoded image width', 1); finite(image.height, 'Decoded image height', 1);
    return image;
  } catch { image?.close?.(); throw new Error('This image could not be decoded. Choose a valid PNG, JPEG or WebP image.'); }
}
function canvas2d(width: number, height: number): { canvas: HTMLCanvasElement; context: CanvasRenderingContext2D } {
  pixelBudget(width, height);
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Your browser could not create an image canvas.');
  return { canvas, context };
}
async function encodeCanvas(canvas: HTMLCanvasElement, mime: string, quality = 0.9): Promise<{ bytes: Uint8Array; mime: string }> {
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(value => value ? resolve(value) : reject(new Error('Image encoding failed. Try a smaller image.')), mime, quality);
  });
  return { bytes: new Uint8Array(await blob.arrayBuffer()), mime: blob.type };
}
function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) throw new Error('Image settings must be finite numbers.');
  return Math.max(min, Math.min(max, value));
}
async function processImage(bytes: Uint8Array, mime: string, options: ImageOptions): Promise<{ bytes: Uint8Array; width: number; height: number; mime: string }> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(options.format)) throw new Error('Choose JPEG, PNG or WebP output.');
  const quality = clamp(options.quality, 0.1, 1);
  const maxWidth = Math.floor(clamp(options.maxWidth, 1, 4096));
  const brightness = clamp(options.brightness, 0.5, 1.5);
  const contrast = clamp(options.contrast, 0.5, 1.5);
  const crop = cropMargins(options.crop ?? { left: 0, bottom: 0, right: 0, top: 0 }, true);
  const image = await decodeImage(bytes, mime);
  try {
    const sourceWidth = image.width - crop.left - crop.right;
    const sourceHeight = image.height - crop.top - crop.bottom;
    if (sourceWidth < 1 || sourceHeight < 1) throw new Error(`Crop margins must leave at least one pixel of the ${image.width} × ${image.height} image.`);
    const scale = Math.min(1, maxWidth / sourceWidth, 4096 / sourceHeight, Math.sqrt(MAX_PIXELS / (sourceWidth * sourceHeight)));
    const width = Math.max(1, Math.floor(sourceWidth * scale));
    const height = Math.max(1, Math.floor(sourceHeight * scale));
    const { canvas, context } = canvas2d(width, height);
    if (options.format === 'image/jpeg') { context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height); }
    context.filter = `brightness(${brightness}) contrast(${contrast})`;
    context.drawImage(image, crop.left, crop.top, sourceWidth, sourceHeight, 0, 0, width, height);
    return { ...await encodeCanvas(canvas, options.format, quality), width, height };
  } finally { image.close?.(); }
}

async function mergeImages(images: { bytes: Uint8Array; mime: string }[], direction: 'vertical' | 'horizontal'): Promise<Uint8Array> {
  if (!Array.isArray(images) || !images.length || images.length > 200) throw new Error('Choose 1–200 images to merge.');
  if (direction !== 'vertical' && direction !== 'horizontal') throw new Error('Choose vertical or horizontal image merging.');
  const decoded: any[] = [];
  let width = 0; let height = 0;
  try {
    for (const input of images) {
      const image = await decodeImage(input.bytes, input.mime);
      decoded.push(image);
      width = direction === 'vertical' ? Math.max(width, image.width) : width + image.width;
      height = direction === 'vertical' ? height + image.height : Math.max(height, image.height);
      pixelBudget(width, height);
    }
    const { canvas, context } = canvas2d(width, height);
    let x = 0; let y = 0;
    for (const image of decoded) {
      context.drawImage(image, x, y);
      if (direction === 'vertical') y += image.height; else x += image.width;
    }
    return (await encodeCanvas(canvas, 'image/png')).bytes;
  } finally { for (const image of decoded) image.close?.(); }
}

function validateFileSize(bytes: number): void {
  if (!Number.isInteger(bytes) || bytes < 1) throw new Error('Choose a non-empty file.');
  if (bytes > MAX_BYTES) throw new Error('Files must be 25 MiB or smaller.');
}


  return { loadPdfLib, loadPdfJs, openPdf, pdfInfo, makeDemoPdf, transformPdf, mergePdfs, overlayPdf, fillPdf, imagesToPdf, optimizePdf, qrSvg, renderPdfPage, renderPdfPages, extractPdfText, processImage, mergeImages, validateFileSize };
}

export type Engine = ReturnType<typeof createEngine>;
