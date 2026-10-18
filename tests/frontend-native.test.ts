import { test } from 'node:test';
import assert from 'node:assert/strict';

const native = await import('../src/native-model.ts');
test('builds the exact granted-ID request for inspecting a selected PDF', () => {
  assert.deepEqual(native.buildNativeRequest('inspect_pdf', ['grant-123'], {}), {
    request: { operation: 'inspect_pdf', inputIds: ['grant-123'], options: {} },
  });
});
test('rejects a cloud job without per-job consent before dispatch', () => {
  assert.throws(() => native.buildNativeRequest('summarize', ['grant-123'], {
    provider: 'openai', api_key: 'test-secret', cloud_consent: false,
  }), /consent/i);
});
test('rejects ungranted paths, unknown operations and missing input', () => {
  assert.throws(() => native.buildNativeRequest('shell', ['grant'], {}), /operation/i);
  assert.throws(() => native.buildNativeRequest('inspect_pdf', ['/etc/passwd'], {}), /grant|ID/i);
  assert.throws(() => native.buildNativeRequest('inspect_pdf', [], {}), /select|input/i);
  assert.deepEqual(native.buildNativeRequest('form_template', [], {template_id:'contact'}).request.inputIds, []);
});
test('allows genuine PDF comment annotations as native jobs', () => {
  assert.equal(native.buildNativeRequest('annotate_pdf', ['grant'], {page:1,kind:'comment',text:'Comment',rect:[50,50,250,90]}).request.operation, 'annotate_pdf');
});
const catalog = await import('../src/native-catalog.ts').catch(() => ({nativeTools: []}));
test('provides an actionable parameter schema for every native operation without claiming engines installed', () => {
  assert.deepEqual(catalog.nativeTools.map(t => t.id).sort(), [...native.nativeOperations].sort());
  const edit = catalog.nativeTools.find(t => t.id === 'edit_pdf_text');
  assert.equal(edit?.fields.find(f => f.key === 'object_index')?.value, 0);
  assert.equal(edit?.fields.find(f => f.key === 'font')?.value, 'Helvetica');
  const ai = catalog.nativeTools.find(t => t.id === 'summarize');
  assert.equal(ai?.fields.find(f => f.key === 'provider')?.value, 'ollama');
  assert.equal(ai?.fields.find(f => f.key === 'endpoint')?.value, 'http://127.0.0.1:11434');
});
test('matches current worker mode/provider/template contracts', () => {
  assert.ok(catalog.nativeTools.find(t=>t.id==='summarize')?.fields.find(f=>f.key==='provider')?.choices?.includes('openai-compatible'));
  assert.ok(catalog.nativeTools.find(t=>t.id==='summarize')?.fields.find(f=>f.key==='provider')?.choices?.includes('llama.cpp'));
  assert.deepEqual(catalog.nativeTools.find(t=>t.id==='compress_pdf')?.fields.find(f=>f.key==='mode')?.choices, ['lossless','raster']);
  assert.deepEqual(catalog.nativeTools.find(t=>t.id==='form_template')?.fields.find(f=>f.key==='template_id')?.choices, ['contact','approval','invoice']);
});
test('opaque file IDs containing x and zero are not mistaken for filesystem paths', () => {
  assert.equal(native.buildNativeRequest('inspect_pdf',['grant-x0'],{}).request.inputIds[0], 'grant-x0');
});
test('local llama jobs use a separate opaque model grant without cloud consent', () => {
  const job=native.buildNativeRequest('summarize',['document-id'],{provider:'llama.cpp',model:'selected-local-model',model_file_id:'model-id',cloud_consent:false});
  assert.deepEqual(job.request.inputIds,['document-id']);
  assert.equal(job.request.options.model_file_id,'model-id');
});
test('transcription uses the actual whisper.cpp worker provider', () => {
  assert.equal(catalog.nativeTools.find(t=>t.id==='transcribe')?.fields.find(f=>f.key==='provider')?.value,'whisper.cpp');
  assert.equal(native.buildNativeRequest('transcribe',['media-id'],{provider:'whisper.cpp',model_file_id:'model-id',cloud_consent:false}).request.options.provider,'whisper.cpp');
});
