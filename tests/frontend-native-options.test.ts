import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const native = await import('../src/native-model.ts');
const catalog = await import('../src/native-catalog.ts');
const defaults = (id: string) => Object.fromEntries(catalog.nativeTools.find(t => t.id === id)!.fields.map(f => [f.key, Array.isArray(f.value) ? [...f.value] : f.value]));
const options = (id: string, values: Record<string, unknown>) => native.buildNativeRequest(id, ['grant'], { ...defaults(id), ...values }).request.options;

test('existing-text edits keep the original font and size unless the user changes them', () => {
  const sent = options('edit_pdf_text', { page: 1, object_index: 3, text: 'Replacement' });
  assert.equal('font' in sent, false);
  assert.equal('font_size' in sent, false);
  assert.equal(sent.object_index, 3);
  assert.equal(options('edit_pdf_text', { object_index: 0, text: 'x', font_size: 0 }).font_size, undefined, 'a cleared size field keeps the original size');
  assert.equal(options('edit_pdf_text', { object_index: 0, text: 'x', font_size: 12 }).font_size, 12);
  assert.equal(options('edit_pdf_text', { object_index: 0, text: 'x', font: 'Helvetica-Bold' }).font, 'Helvetica-Bold');
});

test('the font choice lists every standard font the worker accepts after the keep-original default', () => {
  const font = catalog.nativeTools.find(t => t.id === 'edit_pdf_text')!.fields.find(f => f.key === 'font')!;
  assert.equal(font.value, native.KEEP_ORIGINAL_FONT);
  assert.deepEqual(font.choices, [native.KEEP_ORIGINAL_FONT, 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique', 'Times-Roman', 'Times-Bold', 'Times-Italic', 'Courier', 'Courier-Bold', 'Courier-Oblique']);
});

test('watermark removal defaults to all pages and exposes annotation types', () => {
  const sent = options('remove_watermark', { exact_text: 'DRAFT' });
  assert.equal('page' in sent, false);
  assert.equal('annotation_subtype' in sent, false);
  assert.equal(sent.exact_text, 'DRAFT');
  assert.equal(options('remove_watermark', { exact_text: 'DRAFT', page: 2 }).page, 2);
  const subtype = catalog.nativeTools.find(t => t.id === 'remove_watermark')!.fields.find(f => f.key === 'annotation_subtype')!;
  assert.deepEqual(subtype.choices, ['None', 'Watermark', 'Stamp', 'FreeText', 'Text', 'Highlight']);
  const annotationsOnly = options('remove_watermark', { annotation_subtype: 'Stamp' });
  assert.equal(annotationsOnly.annotation_subtype, 'Stamp');
  assert.equal('exact_text' in annotationsOnly, false);
  assert.throws(() => options('remove_watermark', {}), /exact watermark text or an annotation type/i);
});

test('summary language defaults to blank, which the worker treats as the document language; translation keeps a target', () => {
  assert.equal(defaults('summarize').language, '');
  assert.equal(options('summarize', { model: 'local' }).language, '');
  assert.equal(options('summarize', { model: 'local', language: 'German' }).language, 'German');
  assert.equal(options('translate_pdf', { model: 'local' }).language, 'German');
});

test('a selected translation font travels as an opaque grant for translation only', () => {
  assert.equal(options('translate_pdf', { model: 'local', font_file_id: 'font-grant' }).font_file_id, 'font-grant');
  assert.equal('font_file_id' in options('summarize', { model: 'local', font_file_id: 'font-grant' }), false);
  assert.throws(() => options('translate_pdf', { model: 'local', font_file_id: '/usr/share/fonts/a.ttf' }), /grant|ID/i);
});

test('the native panel offers a separate font-file picker for translation', async () => {
  const source = await readFile(new URL('../src/NativeTools.tsx', import.meta.url), 'utf8');
  assert.match(source, /Select font file/);
  assert.match(source, /font_file_id/);
  assert.match(source, /setFontFile/);
});
