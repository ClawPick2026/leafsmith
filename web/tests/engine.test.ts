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
  assert.deepEqual((await e.pdfInfo(result)).sizes[0], {width:1,height:1,rotation:0});
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
