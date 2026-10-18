import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {buildNativeRequest, nativeOperations} from '../src/native-model.ts';
import {nativeTools} from '../src/native-catalog.ts';

const tool = (id: string) => {
  const found = nativeTools.find(t => t.id === id);
  assert.ok(found, `Missing native tool: ${id}`);
  return found;
};
const defaults = (id: string) => Object.fromEntries(tool(id).fields.map(f => [f.key, f.value]));

test('video controls dispatch worker CRF and height defaults and boundary values', () => {
  const video = tool('compress_video');
  assert.deepEqual(video.fields.map(({key, value, min, max, step}) => ({key, value, min, max, step})), [
    {key:'crf', value:36, min:10, max:63, step:1},
    {key:'max_height', value:1080, min:64, max:2160, step:1},
  ]);
  assert.match(video.description, /height/i);
  assert.match(video.fields[0].label, /CRF/);
  assert.match(video.fields[1].label, /height/i);
  for (const options of [defaults('compress_video'), {crf:10, max_height:64}, {crf:63, max_height:2160}]) {
    assert.deepEqual(buildNativeRequest('compress_video', ['media-grant'], options).request.options, options);
  }
});

test('image multiplier controls accept only the worker range zero through four', () => {
  assert.deepEqual(tool('enhance_image').fields.map(({key, value, min, max, step}) => ({key, value, min, max, step})),
    ['brightness','contrast','sharpness'].map(key => ({key, value:1, min:0, max:4, step:0.1})));
  for (const value of [0, 1, 4]) {
    const options = {brightness:value, contrast:value, sharpness:value};
    assert.deepEqual(buildNativeRequest('enhance_image', ['image-grant'], options).request.options, options);
  }
});

test('local executable providers omit stale HTTP configuration but retain opaque model grants', () => {
  for (const [operation, provider] of [['transcribe','whisper.cpp'], ['summarize','llama.cpp'], ['translate_pdf','llama.cpp'], ['transcribe','local']]) {
    const options = Object.freeze({...defaults(operation), provider, endpoint:'https://api.openai.com/v1', api_key:'stale-test-secret', model_file_id:'model-grant-x0', cloud_consent:false});
    const {endpoint: _endpoint, api_key: _apiKey, ...expected} = options;
    const request = buildNativeRequest(operation, ['document-grant-x0'], options).request;
    assert.deepEqual(request.options, expected, `${operation}/${provider} must not send HTTP settings to Rust`);
    assert.deepEqual(request.inputIds, ['document-grant-x0']);
    assert.equal(request.options.model_file_id, 'model-grant-x0');
    assert.equal(options.endpoint, 'https://api.openai.com/v1', 'caller options are not mutated');
    assert.equal(options.api_key, 'stale-test-secret');
  }
});

test('PDF requests omit per-job cloud metadata rejected by the strict PDF worker', () => {
  const media = new Set(['summarize','translate_pdf','transcribe','compress_video','enhance_image']);
  // Blank/"keep original"/"None" defaults are UI placeholders for worker defaults and are omitted.
  const placeholders: Record<string, string[]> = {edit_pdf_text:['font','font_size'], remove_watermark:['page','annotation_subtype']};
  const required: Record<string, Record<string, unknown>> = {remove_watermark:{exact_text:'DRAFT'}};
  for (const operation of nativeOperations.filter(id => !media.has(id))) {
    const options = {...defaults(operation), ...required[operation]};
    const expected = Object.fromEntries(Object.entries(options).filter(([key]) => !placeholders[operation]?.includes(key)));
    const inputIds = operation === 'form_template' ? [] : ['pdf-grant'];
    for (const cloud_consent of [false, true]) {
      assert.deepEqual(buildNativeRequest(operation, inputIds, {...options, cloud_consent}).request.options, expected, operation);
    }
  }
});

test('existing cloud policy preserves explicit provider settings and requires fresh boolean consent on each request', () => {
  for (const operation of ['summarize','translate_pdf','transcribe']) {
    const settings = {...defaults(operation), provider:'openai-compatible', endpoint:'https://provider.example/v1', model:'chosen-model', api_key:'test-only-key'};
    const approved = {...settings, cloud_consent:true};
    assert.deepEqual(buildNativeRequest(operation, ['input-grant'], approved).request.options, approved);
    for (const consent of [undefined, false, 'true', 1]) {
      assert.throws(() => buildNativeRequest(operation, ['input-grant'], {...settings, cloud_consent:consent}), /consent/i);
    }
  }
  const ollama = {...defaults('summarize'), model:'installed-model'};
  assert.deepEqual(buildNativeRequest('summarize', ['input-grant'], ollama).request.options, ollama);
});

test('transcription catalog lists both local engines and discloses FFmpeg for cloud audio extraction', () => {
  assert.deepEqual(tool('transcribe').components, ['whisper','ffmpeg']);
  assert.match(tool('transcribe').note, /FFmpeg/);
  assert.match(tool('transcribe').note, /cloud/i);
  assert.deepEqual(tool('compress_video').components, ['ffmpeg']);
});

// Source assertions cover UI wiring/copy only, not an interactive Tauri end-to-end run.
const source = await readFile(new URL('../src/NativeTools.tsx', import.meta.url), 'utf8');
test('UI shell checks all required engines, treats absent/failed status as unavailable, and blocks submission', () => {
  assert.match(source, /const requiredComponents=/);
  assert.match(source, /requiredComponents\.filter/);
  assert.match(source, /!components\.some\(c=>c\.id===id&&c\.installed\)/);
  assert.match(source, /missing\.map/);
  assert.match(source, /status is unavailable/);
  assert.match(source, /disabled=\{[^}]*missing\.length/);
  assert.match(source, /async function refresh\(\)\{setComponents\(\[\]\)/);
  assert.match(source, /selected\.id==='transcribe'&&cloud&&id==='whisper'/);
});

test('UI shell clears only existing credential keys after every job and resets cloud consent in finally', () => {
  const run = source.slice(source.indexOf('async function run()'), source.indexOf('async function save('));
  assert.ok(!run.includes("setOptions(old=>({...old,password:''"), 'cleanup must not inject password/owner_password/api_key into unrelated jobs');
  assert.ok(run.includes('Object.entries(old).map'), 'cleanup visits existing options only');
  assert.match(run, /finally\{setBusy\(false\);setCloudConsent\(false\)/);
  assert.ok(run.includes('...(cloud?{cloud_consent:cloudConsent}:{})'), 'only cloud jobs attach cloud metadata');
});

test('UI shell exposes endpoints only for HTTP providers and does not assign cloud endpoints to local modes', () => {
  assert.ok(source.includes("f.key!=='endpoint'||options.provider==='ollama'||cloud"), 'whisper.cpp and llama.cpp do not show unused endpoint controls');
  assert.ok(source.includes("v==='openai-compatible'?'https://api.openai.com/v1':''"), 'provider switches clear the endpoint for executable providers');
});
