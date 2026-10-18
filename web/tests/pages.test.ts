import test from 'node:test';
import assert from 'node:assert/strict';
import { parsePageRange } from '../shared/pages.ts';

test('comma ranges preserve requested order and deduplicate', () => {
  assert.deepEqual(parsePageRange('3, 1-2, 3, 5-5', 5), [3, 1, 2, 5]);
});

test('range validation rejects malformed, reversed, out-of-bounds ranges and invalid counts', () => {
  for (const input of ['0', '4', '2-1', '1,', ',1', '1,,2', 'a', '1.5', '-1', '1-2-3', '1e2', '1-', 'Infinity']) {
    assert.throws(() => parsePageRange(input, 3), undefined, input);
  }
  for (const count of [0, -1, 1.5, 201, Infinity, NaN]) assert.throws(() => parsePageRange('', count));
  assert.deepEqual(parsePageRange('200', 200), [200]);
});

test('blank page range selects every 1-based page', async () => {
  const { parsePageRange } = await import('../shared/pages.ts');
  assert.deepEqual(parsePageRange('  ', 3), [1, 2, 3]);
});
