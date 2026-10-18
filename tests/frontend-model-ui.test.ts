import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../src/NativeTools.tsx',import.meta.url),'utf8');
test('native model selection has its own file-picker flow and opaque model grant',()=>{
 assert.match(source,/Select local model file/);
 assert.match(source,/model_file_id/);
 assert.match(source,/setModelFile/);
 assert.doesNotMatch(source,/__PAPERWORK_TEST_NATIVE__|localStorage|sessionStorage/);
});
