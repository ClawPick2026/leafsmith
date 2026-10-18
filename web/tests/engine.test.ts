import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInThisContext } from 'node:vm';

// Test-only CDN loading; application code never uses Node APIs or eval.
async function realLibrary(name: 'pdf-lib' | 'qrcode-generator') {
  const url = name === 'pdf-lib'
    ? 'https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js'
    : 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
  const path = join(tmpdir(), `paperwork-${name}.js`);
  let source: string;
  try { source = await readFile(path, 'utf8'); }
  catch { const response = await fetch(url); assert.equal(response.status, 200); source = await response.text(); await writeFile(path, source); }
  runInThisContext(source, { filename: url });
}

test('browser library loading fails actionably offline, retries failures, and deduplicates concurrent loads', async () => {
  const e = await engine();
  await assert.rejects(e.loadPdfLib(), /library.*(internet|connection|online)|browser/i);
  const g = globalThis as any;
  let added = 0;
  const urls: string[] = [];
  g.document = { createElement: () => ({ remove() {} }), head: { appendChild(script: any) {
    added++; urls.push(script.src);
    queueMicrotask(() => { if (added === 1) script.onerror(); else { g.PDFLib = { available: true }; script.onload(); } });
  } } };
  try {
    await assert.rejects(e.loadPdfLib(), /library.*(internet|connection|online)/i);
    const [a, b] = await Promise.all([e.loadPdfLib(), e.loadPdfLib()]);
    assert.equal(a, b); assert.equal(added, 2);
    assert.equal(urls[0], 'https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js');
  } finally { delete g.document; delete g.PDFLib; }
});

const engine = () => import('../client/engine.ts');
let sample: Uint8Array;

test('demo PDF round-trips three pages, labeled content and editable name/approved fields', async () => {
  const e = await engine();
  assert.equal(typeof e.makeDemoPdf, 'function');
  await realLibrary('pdf-lib');
  sample = await e.makeDemoPdf();
  const info = await e.pdfInfo(sample);
  assert.equal(info.pageCount, 3);
  assert.equal(info.sizes.length, 3);
  assert.deepEqual(info.fields.map(f => [f.name, f.type, f.value]), [['name', 'text', ''], ['approved', 'checkbox', false]]);
  const doc = await e.openPdf(sample);
  assert.equal(doc.getPageCount(), 3);
  await assert.rejects(e.openPdf(new Uint8Array()), /non-empty/i);
  await assert.rejects(e.openPdf(new Uint8Array([1, 2, 3])), /valid PDF/i);
  const lib = await e.loadPdfLib();
  const big = await lib.PDFDocument.create();
  for (let i = 0; i < 201; i++) big.addPage();
  await assert.rejects(e.openPdf(await big.save()), /200/);
  const encrypted = await lib.PDFDocument.create(); encrypted.addPage();
  encrypted.context.trailerInfo.Encrypt = encrypted.context.obj({ Filter: 'Standard', V: 1 });
  await assert.rejects(e.openPdf(await encrypted.save()), /encrypt|password/i);
});

test('page transforms preserve requested page order, add rotations, crop by margins, and reject invalid geometry', async () => {
  const e = await engine();
  assert.equal(typeof e.transformPdf, 'function');
  const output = await e.transformPdf(sample, { pages: [3, 1], rotate: 90, crop: { left: 10, bottom: 20, right: 30, top: 40 } });
  const doc = await e.openPdf(output);
  assert.equal(doc.getPageCount(), 2);
  assert.equal(doc.getPage(0).getRotation().angle, 90);
  assert.deepEqual(doc.getPage(0).getCropBox(), { x: 10, y: 20, width: 555.28, height: 781.89 });
  for (const options of [{pages: []}, {pages: [0]}, {pages: [4]}, {pages: [1.5]}, {pages: [1], rotate: 45}, {pages: [1], rotate: NaN}, {pages: [1], crop: {left: -1,bottom:0,right:0,top:0}}, {pages: [1], crop: {left: 600,bottom:0,right:0,top:0}}]) {
    await assert.rejects(e.transformPdf(sample, options));
  }
});

test('PDF info reports each visible page box, clipped to the media box', async () => {
  const e = await engine();
  const info = await e.pdfInfo(sample);
  assert.deepEqual(info.sizes[0].box, { x: 0, y: 0, width: 595.28, height: 841.89 });
  const cropped = await e.pdfInfo(await e.transformPdf(sample, { pages: [1], crop: { left: 10, bottom: 20, right: 30, top: 40 } }));
  assert.deepEqual(cropped.sizes[0].box, { x: 10, y: 20, width: 555.28, height: 781.89 });
  const lib = await e.loadPdfLib();
  const doc = await lib.PDFDocument.create();
  doc.addPage([200, 100]).setCropBox(-50, 10, 400, 400);
  assert.deepEqual((await e.pdfInfo(await doc.save())).sizes[0].box, { x: 0, y: 10, width: 200, height: 90 });
});

test('crop margins follow the page as displayed, including pages with a /Rotate value', async () => {
  const e = await engine();
  const lib = await e.loadPdfLib();
  const doc = await lib.PDFDocument.create();
  doc.addPage([600, 800]).setRotation(lib.degrees(90));
  const output = await e.openPdf(await e.transformPdf(await doc.save(), { pages: [1], crop: { left: 10, bottom: 20, right: 30, top: 40 } }));
  // Displayed left/top/right/bottom are the PDF bottom/left/top/right edges at 90 degrees.
  assert.deepEqual(output.getPage(0).getCropBox(), { x: 40, y: 10, width: 540, height: 760 });
  assert.equal(output.getPage(0).getRotation().angle, 90);
});

test('merge concatenates PDF pages and enforces the combined 200-page limit', async () => {
  const e = await engine();
  assert.equal(typeof e.mergePdfs, 'function');
  assert.equal((await e.pdfInfo(await e.mergePdfs([sample, sample]))).pageCount, 6);
  await assert.rejects(e.mergePdfs([]), /select|choose|one/i);
  await assert.rejects(e.mergePdfs(Array(67).fill(sample)), /200/);
});

test('overlays draw text, rectangles and flattened highlights without discarding interactive fields', async () => {
  const e = await engine();
  assert.equal(typeof e.overlayPdf, 'function');
  let bytes = sample;
  for (const kind of ['text', 'rectangle', 'highlight'] as const) bytes = await e.overlayPdf(bytes, {page:1,kind,x:40,y:40,width:100,height:30,text:'Added',fontFamily:'Courier',color:'#336699'});
  assert.equal((await e.pdfInfo(bytes)).fields.length, 2);
  for (const extra of [{x: NaN}, {y:-1}, {width:0}, {height:Infinity}, {page:0}, {x:600}, {color:'red'}, {fontSize:0}, {fontFamily:'Bad'}, {kind:'bad'}]) {
    await assert.rejects(e.overlayPdf(sample, {page:1,kind:'text',x:40,y:40,width:100,height:30,text:'Added',...extra} as any));
  }
});

test('overlays must fit inside the visible page box, including offset media boxes and cropped pages', async () => {
  const e = await engine();
  const lib = await e.loadPdfLib();
  async function make(crop?: [number, number, number, number]) {
    const doc = await lib.PDFDocument.create();
    const page = doc.addPage([612, 792]);
    page.setMediaBox(100, 100, 612, 792);
    if (crop) page.setCropBox(...crop);
    return doc.save();
  }
  const rect = { page: 1, kind: 'rectangle' as const, width: 50, height: 50 };
  const offset = await make();
  await assert.doesNotReject(e.overlayPdf(offset, { ...rect, x: 650, y: 800 }));
  await assert.rejects(e.overlayPdf(offset, { ...rect, x: 10, y: 10 }), /visible page.*x 100–712, y 100–892/);
  const cropped = await make([300, 300, 200, 200]);
  await assert.doesNotReject(e.overlayPdf(cropped, { ...rect, x: 350, y: 350 }));
  await assert.rejects(e.overlayPdf(cropped, { ...rect, x: 150, y: 150 }), /visible page/);
  await assert.rejects(e.overlayPdf(cropped, { ...rect, x: 480, y: 350 }), /visible page/);
});

test('overlay text starts at the top of its box so it matches the placement shown on the preview', async () => {
  const e = await engine();
  const lib = await e.loadPdfLib();
  const bytes = await e.overlayPdf(sample, {page:2,kind:'text',x:100,y:300,width:200,height:80,text:'Placed',fontFamily:'Helvetica',fontSize:20});
  const page = (await lib.PDFDocument.load(bytes)).getPage(1);
  const contents = page.node.Contents();
  const streams = contents instanceof lib.PDFArray ? contents.asArray().map((ref: any) => page.doc.context.lookup(ref)) : [contents];
  const source = streams.map((stream: any) => new TextDecoder().decode(lib.decodePDFRawStream(stream).decode())).join('\n');
  // The overlay is appended after the page's existing content, so its text matrix is the last one.
  const match = [...source.matchAll(/1 0 0 1 ([\d.]+) ([\d.]+) Tm/g)].at(-1);
  assert.ok(match, 'text matrix is written');
  assert.equal(Number(match[1]), 100);
  const ascent = (await (await lib.PDFDocument.create()).embedFont(lib.StandardFonts.Helvetica)).heightAtSize(20, { descender: false });
  assert.ok(Math.abs(Number(match[2]) - (380 - ascent)) < 0.01, `first baseline ${match[2]} sits one ascent below the box top`);
});

test('signatures are painted above every existing page element, including form fields and earlier annotations', async () => {
  const e = await engine();
  const lib = await e.loadPdfLib();
  const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMs0AAAAASUVORK5CYII=', 'base64'));
  // The sample's name field has an opaque white widget at x 54, y 560, 250 × 26.
  const place = { page: 1, kind: 'signature' as const, x: 60, y: 555, width: 180, height: 40, imageBytes: png, imageMime: 'image/png' };
  const once = await e.overlayPdf(await e.overlayPdf(sample, { ...place, kind: 'highlight', x: 50, y: 550 }), place);
  const twice = await e.overlayPdf(once, { ...place, x: 70 });
  assert.deepEqual((await e.pdfInfo(twice)).fields.map(f => f.name), ['name', 'approved']);
  const doc = await lib.PDFDocument.load(twice);
  const page = doc.getPage(0);
  const annots = page.node.Annots().asArray().map((ref: any) => doc.context.lookup(ref));
  const name = (value: any) => value?.toString();
  const widget = doc.getForm().getTextField('name').acroField.getWidgets()[0].dict;
  // Viewers paint page content first, then annotations in /Annots order, so each new signature must be the last annotation.
  const [first, second] = annots.slice(-2);
  assert.ok(annots.indexOf(widget) < annots.indexOf(first), 'the form field is painted before the first signature');
  for (const [annot, x] of [[first, 60], [second, 70]] as const) {
    assert.equal(name(annot.get(lib.PDFName.of('Subtype'))), '/Stamp');
    assert.deepEqual(annot.get(lib.PDFName.of('Rect')).asArray().map((n: any) => n.asNumber()), [x, 555, x + 180, 595]);
    assert.equal(annot.get(lib.PDFName.of('F')).asNumber() & 4, 4, 'printable');
    const appearance = doc.context.lookup(annot.get(lib.PDFName.of('AP')).get(lib.PDFName.of('N')));
    assert.deepEqual(appearance.dict.get(lib.PDFName.of('BBox')).asArray().map((n: any) => n.asNumber()), [0, 0, 180, 40]);
    const images = appearance.dict.get(lib.PDFName.of('Resources')).get(lib.PDFName.of('XObject'));
    const [[key, ref]] = images.entries();
    assert.equal(name(doc.context.lookup(ref).dict.get(lib.PDFName.of('Subtype'))), '/Image');
    const ops = new TextDecoder().decode(lib.decodePDFRawStream(appearance).decode());
    assert.match(ops, new RegExp(`180 0 0 40 0 0 cm[\\s\\S]*${key.toString()} Do`), 'the image fills the signature box');
  }
  await assert.rejects(e.overlayPdf(sample, { ...place, imageBytes: undefined }), /PNG|JPEG/);
});

test('form filling updates text, checkboxes and choices, preserves fields unless flattened, and rejects unknown fields', async () => {
  const e = await engine();
  assert.equal(typeof e.fillPdf, 'function');
  const doc = await e.openPdf(sample);
  doc.getForm().createDropdown('choice').addOptions(['One', 'Two']);
  doc.getForm().getDropdown('choice').addToPage(doc.getPage(0), {x:40,y:200,width:100,height:20});
  doc.getForm().createOptionList('list').addOptions(['A', 'B']);
  doc.getForm().getOptionList('list').addToPage(doc.getPage(0), {x:40,y:160,width:100,height:20});
  const bytes = await doc.save();
  const filled = await e.fillPdf(bytes, {name:'Ada',approved:true,choice:'Two',list:'B'}, false);
  const info = await e.pdfInfo(filled);
  assert.deepEqual(info.fields.map(f => f.value), ['Ada',true,'Two','B']);
  assert.equal((await e.pdfInfo(await e.fillPdf(filled, {}, true))).fields.length, 0);
  await assert.rejects(e.fillPdf(sample, {missing:'No'}, false), /field/i);
  await assert.rejects(e.fillPdf(sample, {approved:'yes'}, false), /boolean/i);
  await assert.rejects(e.fillPdf(bytes, {choice:'Missing'}, false), /option/i);
});

test('images become natural-sized PDF pages and image overlays validate decoded PNG data', async () => {
  const e = await engine();
  assert.equal(typeof e.imagesToPdf, 'function');
  const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMs0AAAAASUVORK5CYII=', 'base64'));
  const result = await e.imagesToPdf([{bytes:png,mime:'image/png'}]);
  assert.deepEqual((await e.pdfInfo(result)).sizes[0], {width:1,height:1,rotation:0,box:{x:0,y:0,width:1,height:1}});
  assert.equal((await e.pdfInfo(await e.overlayPdf(sample,{page:1,kind:'image',x:10,y:10,width:10,height:10,imageBytes:png,imageMime:'image/png'}))).fields.length, 2);
  await assert.rejects(e.imagesToPdf([]));
  await assert.rejects(e.imagesToPdf([{bytes:png,mime:'image/webp'}]), /PNG|JPEG/);
  await assert.rejects(e.imagesToPdf([{bytes:new Uint8Array([1,2]),mime:'image/png'}]), /valid|image/i);
});

test('optimization returns a valid PDF with fields and never increases file size', async () => {
  const e = await engine();
  assert.equal(typeof e.optimizePdf, 'function');
  const out = await e.optimizePdf(sample);
  assert.ok(out.byteLength <= sample.byteLength);
  assert.equal((await e.pdfInfo(out)).fields.length, 2);
});

test('QR output is safe SVG, UTF-8 encodes non-Latin text and limits payload to 1000 bytes', async () => {
  const e = await engine();
  assert.equal(typeof e.qrSvg, 'function');
  await assert.rejects(e.qrSvg(''), /enter|empty/i);
  await assert.rejects(e.qrSvg('🙂'.repeat(251)), /1000/);
  await realLibrary('qrcode-generator');
  const svg = await e.qrSvg('<script>alert("x")</script> 🌍');
  assert.match(svg, /^<svg\b/);
  assert.doesNotMatch(svg, /<script|alert|onload|javascript:/i);
  assert.match(await e.qrSvg('a'.repeat(1000)), /^<svg\b/);
});

test('PDF.js rendering uses pinned worker, copies bytes, limits canvas pixels and destroys documents', async () => {
  const e = await engine();
  assert.equal(typeof e.renderPdfPage, 'function');
  const g = globalThis as any;
  let destroyed = 0;
  let rendered = 0;
  g.pdfjsLib = {GlobalWorkerOptions:{}, getDocument({data}: any) {
    assert.notEqual(data, sample);
    structuredClone(data, {transfer:[data.buffer]});
    return {promise:Promise.resolve({numPages:3, getPage:async () => ({getViewport:({scale}: any) => ({width:600*scale,height:800*scale}), render:() => {rendered++; return {promise:Promise.resolve()};}, cleanup(){}})}), destroy:async () => {destroyed++;}};
  }};
  g.document = {createElement:() => ({width:0,height:0,getContext:() => ({})})};
  try {
    const canvas = await e.renderPdfPage(sample, 1, 2);
    assert.equal(canvas.width, 1200); assert.equal(canvas.height, 1600);
    assert.equal(sample.byteLength > 0, true);
    assert.match(g.pdfjsLib.GlobalWorkerOptions.workerSrc, /pdfjs-dist@3\.11\.174\/build\/pdf.worker.min.js$/);
    for (const scale of [0, -1, NaN, Infinity, 10]) await assert.rejects(e.renderPdfPage(sample, 1, scale));
    await assert.rejects(e.renderPdfPage(sample, 0));
    assert.equal(rendered, 1); assert.ok(destroyed >= 2);
  } finally {delete g.pdfjsLib; delete g.document;}
});

test('page rendering opens a document once, crops the displayed page and budgets only the cropped pixels', async () => {
  const e = await engine();
  assert.equal(typeof e.renderPdfPages, 'function');
  const g = globalThis as any;
  let opened = 0; let destroyed = 0;
  const renders: any[] = [];
  g.pdfjsLib = {GlobalWorkerOptions:{}, getDocument() {
    opened++;
    return {promise:Promise.resolve({getPage:async (n: number) => ({getViewport:({scale}: any) => ({width:600*scale,height:800*scale}), render:(params: any) => {renders.push({n, ...params}); return {promise:Promise.resolve()};}, cleanup(){}})}), destroy:async () => {destroyed++;}};
  }};
  g.document = {createElement:() => ({width:0,height:0,getContext:() => ({})})};
  try {
    const canvases = await e.renderPdfPages(sample, [3, 1], 2, { left: 10, top: 20, right: 30, bottom: 40 });
    assert.equal(opened, 1); assert.equal(destroyed, 1);
    assert.deepEqual(canvases.map(c => [c.width, c.height]), [[1120, 1480], [1120, 1480]]);
    assert.deepEqual(renders.map(r => r.n), [3, 1]);
    assert.deepEqual(renders[0].transform, [1, 0, 0, 1, -20, -40]);
    assert.equal(renders[0].background, 'white');
    const whole = await e.renderPdfPage(sample, 2, 1);
    assert.equal(whole.width, 600); assert.equal(renders.at(-1).transform, undefined);
    await assert.rejects(e.renderPdfPages(sample, [1], 1, { left: 300, top: 0, right: 300, bottom: 0 }), /crop/i);
    await assert.rejects(e.renderPdfPages(sample, [1], 1, { left: -1, top: 0, right: 0, bottom: 0 }), /crop/i);
    // A small crop of a large page stays within the canvas limit at a scale the whole page would exceed.
    assert.equal((await e.renderPdfPages(sample, [1], 8, { left: 0, top: 0, right: 500, bottom: 700 }))[0].width, 800);
    await assert.rejects(e.renderPdfPages(sample, [1], 8), /pixel/i);
    await assert.rejects(e.renderPdfPages(sample, [4], 1));
    assert.equal(opened, destroyed);
  } finally {delete g.pdfjsLib; delete g.document;}
});

test('PDF.js documents share one worker per engine instead of starting a worker per document', async () => {
  const e = await engine();
  const g = globalThis as any;
  let workers = 0;
  const used: any[] = [];
  class PDFWorker { destroyed = false; constructor() { workers++; } destroy() { this.destroyed = true; } }
  g.pdfjsLib = {GlobalWorkerOptions:{}, PDFWorker, getDocument({worker}: any) {
    used.push(worker);
    return {promise:Promise.resolve({getPage:async () => ({getViewport:({scale}: any) => ({width:600*scale,height:800*scale}), render:() => ({promise:Promise.resolve()}), getTextContent:async () => ({items:[]}), cleanup(){}})}), destroy:async () => {}};
  }};
  g.document = {createElement:() => ({width:0,height:0,getContext:() => ({})})};
  try {
    await e.renderPdfPage(sample, 1, 1);
    await e.renderPdfPages(sample, [2, 3], 1);
    await e.extractPdfText(sample, [1]);
    assert.equal(workers, 1);
    assert.ok(used.length === 3 && used.every(worker => worker instanceof PDFWorker && worker === used[0]));
    used[0].destroy();
    await e.renderPdfPage(sample, 1, 1);
    assert.equal(workers, 2, 'A destroyed worker is replaced');
  } finally {delete g.pdfjsLib; delete g.document;}
});

test('text extraction preserves selected page order, line breaks, original bytes and releases PDF.js resources', async () => {
  const e = await engine();
  assert.equal(typeof e.extractPdfText, 'function');
  const g = globalThis as any;
  let destroyed = 0;
  g.pdfjsLib = {GlobalWorkerOptions:{}, getDocument({data}: any) {
    assert.notEqual(data, sample);
    return {promise:Promise.resolve({getPage:async (n: number) => ({getTextContent:async () => ({items:[{str:`Content ${n}`,hasEOL:true},{str:'Next line'}]}),cleanup(){}})}), destroy:async () => {destroyed++;}};
  }};
  try {
    const text = await e.extractPdfText(sample, [3,1]);
    assert.ok(text.indexOf('Content 3') < text.indexOf('Content 1'));
    assert.match(text, /Content 3\nNext line/);
    assert.equal(destroyed, 1);
    await assert.rejects(e.extractPdfText(sample, [4]));
  } finally {delete g.pdfjsLib;}
});

test('image processing decodes input, clamps resize/filter/quality settings, and returns actual canvas MIME', async () => {
  const e = await engine();
  assert.equal(typeof e.processImage, 'function');
  const g = globalThis as any;
  const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMs0AAAAASUVORK5CYII=', 'base64'));
  let closed = 0;
  const context: any = {drawImage(){},fillRect(){}};
  let quality = 0;
  g.createImageBitmap = async () => ({width:10000,height:5000,close(){closed++;}});
  g.document = {createElement:() => ({width:0,height:0,getContext:() => context,toBlob(cb:any,mime:string,q:number){quality=q;cb(new Blob([png],{type:mime}));}})};
  try {
    const out = await e.processImage(png,'image/png',{format:'image/webp',quality:9,maxWidth:99999,brightness:9,contrast:-5});
    assert.equal(out.width,4096); assert.equal(out.height,2048); assert.equal(out.mime,'image/webp');
    assert.equal(quality,1); assert.equal(context.filter,'brightness(1.5) contrast(0.5)'); assert.equal(closed,1);
    await assert.rejects(e.processImage(new Uint8Array([1,2]),'image/png',{format:'image/png',quality:1,maxWidth:100,brightness:1,contrast:1}), /valid|image/i);
    g.createImageBitmap = async () => {throw new Error('decode failure');};
    await assert.rejects(e.processImage(png,'image/png',{format:'image/png',quality:1,maxWidth:100,brightness:1,contrast:1}), /decod|image/i);
  } finally {delete g.createImageBitmap;delete g.document;}
});

test('image crop removes pixels outside the margins before resizing', async () => {
  const e = await engine();
  const g = globalThis as any;
  const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMs0AAAAASUVORK5CYII=', 'base64'));
  const draws: any[][] = [];
  g.createImageBitmap = async () => ({width:400,height:300,close(){}});
  g.document = {createElement:() => ({width:0,height:0,getContext:() => ({drawImage(...args: any[]){draws.push(args);},fillRect(){}}),toBlob(cb:any,mime:string){cb(new Blob([png],{type:mime}));}})};
  const options = {format:'image/png' as const,quality:1,maxWidth:4096,brightness:1,contrast:1};
  try {
    const out = await e.processImage(png,'image/png',{...options,crop:{left:50,top:20,right:150,bottom:80}});
    assert.equal(out.width,200); assert.equal(out.height,200);
    assert.deepEqual(draws.at(-1)!.slice(1),[50,20,200,200,0,0,200,200]);
    const resized = await e.processImage(png,'image/png',{...options,maxWidth:100,crop:{left:50,top:20,right:150,bottom:80}});
    assert.equal(resized.width,100); assert.equal(resized.height,100);
    assert.deepEqual(draws.at(-1)!.slice(1),[50,20,200,200,0,0,100,100]);
    for (const crop of [{left:200,top:0,right:200,bottom:0},{left:-1,top:0,right:0,bottom:0},{left:NaN,top:0,right:0,bottom:0},{left:0.5,top:0,right:0,bottom:0}]) {
      await assert.rejects(e.processImage(png,'image/png',{...options,crop}), /crop/i);
    }
  } finally {delete g.createImageBitmap;delete g.document;}
});

test('image merging places decoded images in order, produces PNG, caps pixels and closes resources', async () => {
  const e = await engine();
  assert.equal(typeof e.mergeImages, 'function');
  const g = globalThis as any;
  const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMs0AAAAASUVORK5CYII=', 'base64'));
  let width = 120; let height = 80; let closed = 0;
  const positions: number[][] = [];
  let canvas: any;
  g.createImageBitmap = async () => ({width,height,close(){closed++;}});
  g.document = {createElement:() => canvas = {width:0,height:0,getContext:() => ({drawImage(_i:any,x:number,y:number){positions.push([x,y]);}}),toBlob(cb:any,mime:string){cb(new Blob([png],{type:mime}));}}};
  try {
    const inputs = [{bytes:png,mime:'image/png'},{bytes:png,mime:'image/png'}];
    const bytes = await e.mergeImages(inputs,'vertical');
    assert.ok(bytes.byteLength > 0); assert.equal(canvas.width,120); assert.equal(canvas.height,160);
    assert.deepEqual(positions,[[0,0],[0,80]]);
    await e.mergeImages(inputs,'horizontal');
    assert.equal(canvas.width,240); assert.equal(canvas.height,80);
    width = 5000; height = 5000;
    await assert.rejects(e.mergeImages(inputs,'vertical'), /pixel|limit/i);
    assert.ok(closed >= 5);
    await assert.rejects(e.mergeImages([], 'vertical'));
  } finally {delete g.createImageBitmap;delete g.document;}
});

test('file size validation accepts 1..25 MiB and rejects empty, fractional or oversized input', async () => {
  const { validateFileSize } = await engine();
  for (const size of [0, -1, 0.5, NaN, Infinity, 25 * 1024 * 1024 + 1]) assert.throws(() => validateFileSize(size));
  assert.doesNotThrow(() => validateFileSize(1));
  assert.doesNotThrow(() => validateFileSize(25 * 1024 * 1024));
});
