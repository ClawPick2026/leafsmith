import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PDFDocument } from 'pdf-lib';

const engine = await import('../src/engine.ts');
test('creates a real three-page PDF offline with a fillable name field', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('Network prohibited in offline test'); };
  try {
    const bytes = await engine.makeDemoPdf();
    assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), '%PDF');
    const pdf = await PDFDocument.load(bytes);
    assert.equal(pdf.getPageCount(), 3);
    assert.equal(pdf.getForm().getTextField('name').getText(), undefined);
  } finally { globalThis.fetch = originalFetch; }
});
// Characterization coverage for preserved website processing behavior.
test('preserved page tools write real reordered, rotated, cropped and merged PDFs', async()=>{
 const sample=await engine.makeDemoPdf();
 const output=await engine.transformPdf(sample,{pages:[3,1],rotate:90,crop:{left:10,bottom:10,right:20,top:20}});
 const doc=await PDFDocument.load(output);
 assert.equal(doc.getPageCount(),2);
 assert.equal(doc.getPage(0).getRotation().angle,90);
 assert.equal(Math.round(doc.getPage(0).getCropBox().width),565);
 const merged=await PDFDocument.load(await engine.mergePdfs([output,output]));
 assert.equal(merged.getPageCount(),4);
 assert.equal((await PDFDocument.load(sample)).getPageCount(),3);
});
test('preserved filling, flattening, annotations and structural optimization produce valid artifacts',async()=>{
 const sample=await engine.makeDemoPdf();
 const filled=await engine.fillPdf(sample,{name:'Ada',approved:true},false);
 const doc=await PDFDocument.load(filled);
 assert.equal(doc.getForm().getTextField('name').getText(),'Ada');
 assert.equal(doc.getForm().getCheckBox('approved').isChecked(),true);
 const flat=await PDFDocument.load(await engine.fillPdf(sample,{name:'Grace'},true));
 assert.equal(flat.getForm().getFields().length,0);
 const annotated=await engine.overlayPdf(sample,{page:1,kind:'text',text:'Local note',x:50,y:50,width:150,height:30,fontSize:12});
 assert.equal((await PDFDocument.load(annotated)).getPageCount(),3);
 assert.ok(annotated.length>0);
 const optimized=await engine.optimizePdf(sample);
 assert.ok(optimized.length<=sample.length);
 assert.equal((await PDFDocument.load(optimized)).getPageCount(),3);
});
test('preserved image-to-PDF and bundled UTF-8 QR work without a CDN',async()=>{
 const png=new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64'));
 const pdf=await PDFDocument.load(await engine.imagesToPdf([{bytes:png,mime:'image/png'}]));
 assert.equal(pdf.getPageCount(),1);
 const svg=await engine.qrSvg('Offline — Bücher');
 assert.match(svg,/<svg/);
 assert.doesNotMatch(svg,/<script|(?:src|href)=["']https?:/);
 await assert.rejects(()=>engine.qrSvg(''),/non-empty/);
 await assert.rejects(()=>engine.qrSvg('a'.repeat(1001)),/1000/);
});
test('preserved file and document guards reject malformed input rather than successful fake outputs',async()=>{
 assert.throws(()=>engine.validateFileSize(0),/non-empty/);
 assert.throws(()=>engine.validateFileSize(26*1024*1024),/25 MiB/);
 await assert.rejects(()=>engine.pdfInfo(new TextEncoder().encode('not a pdf')),/valid PDF/);
 const sample=await engine.makeDemoPdf();
 await assert.rejects(()=>engine.transformPdf(sample,{pages:[4]}),/between/);
 await assert.rejects(()=>engine.overlayPdf(sample,{page:1,kind:'text',text:'x',x:900,y:0,width:100,height:20}),/fit/);
});
