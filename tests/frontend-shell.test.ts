import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8').catch(() => '');
test('desktop shell keeps the original workspace and mounts separate native tools with factual privacy', () => {
  assert.match(source, /Paperwork Desktop/);
  assert.match(source, /<NativeTools/);
  assert.match(source, /data-testid="file-input"/);
  assert.match(source, /data-testid="run-tool"/);
  assert.match(source, /data-testid="download-result"/);
  assert.match(source, /explicit per-job consent/);
  assert.doesNotMatch(source, /BUILT WITH LAKEBED|public alpha|jsDelivr|internet connection is needed/i);
  assert.match(source, /button:not\(:disabled\).*cursor-pointer/);
});
