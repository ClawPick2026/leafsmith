import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
for(const file of ['App.tsx','NativeTools.tsx']) test(`${file} describes verified normal-exit cache cleanup and abnormal-exit retention`,async()=>{
  const source=await readFile(new URL(`../src/${file}`,import.meta.url),'utf8');
  assert.ok(/attempts to remove/i.test(source),'Cache cleanup is best-effort, not a guarantee of deletion');
  assert.ok(/cleanup fails/i.test(source),'Cleanup failure can retain files without a crash');
  assert.ok(/normal exit/i.test(source),'Normal-exit cleanup must be disclosed');
  assert.ok(/crash or forced termination/i.test(source),'Abnormal-exit cache retention must be disclosed');
  assert.ok(!/closing the app does not erase/i.test(source),'Remove the obsolete claim that normal exit leaves cached jobs');
});
