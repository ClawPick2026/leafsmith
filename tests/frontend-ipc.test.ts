import { test } from 'node:test';
import assert from 'node:assert/strict';
const clientModule = await import('../src/native-client.ts');
test('browser preview blocks native access instead of returning a successful empty selection', async () => {
  const client = clientModule.createNativeClient(async () => [], () => false);
  await assert.rejects(() => client.selectInputs(), /installed.*app|desktop app/i);
});
test('dispatches exact IPC wrappers and preserves cancelled saves as false', async () => {
  const calls: unknown[] = [];
  const client = clientModule.createNativeClient(async (command, args) => { calls.push([command,args]); return (command === 'save_output' ? false : []) as never; }, () => true);
  await client.selectInputs();
  await client.run('inspect_pdf', ['grant-123'], {});
  assert.equal(await client.save('output-123'), false);
  await client.status();
  await client.install('tesseract');
  assert.deepEqual(calls, [
    ['select_inputs',undefined],
    ['run_native_job',{request:{operation:'inspect_pdf',inputIds:['grant-123'],options:{}}}],
    ['save_output',{outputId:'output-123'}],
    ['component_status',undefined],
    ['install_component',{componentId:'tesseract'}],
  ]);
});
