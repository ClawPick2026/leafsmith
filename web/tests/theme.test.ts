import test from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { initialTheme, nextTheme, palettes, themeVariables } from '../shared/theme.ts';

const uiDirectories = ['../client/', '../../src/'];
const uiSources = (await Promise.all(uiDirectories.map(async dir => (await readdir(new URL(dir, import.meta.url))).filter(name => name.endsWith('.tsx')).map(name => dir + name)))).flat();
const sources = await Promise.all(uiSources.map(async path => [path, await readFile(new URL(path, import.meta.url), 'utf8')] as const));

test('a saved choice wins over the system preference; otherwise the system preference applies', () => {
  assert.equal(initialTheme(null, true), 'dark');
  assert.equal(initialTheme(null, false), 'light');
  assert.equal(initialTheme('light', true), 'light');
  assert.equal(initialTheme('dark', false), 'dark');
  assert.equal(initialTheme('sepia', true), 'dark');
  assert.equal(nextTheme('light'), 'dark');
  assert.equal(nextTheme('dark'), 'light');
});

test('both themes define the same color tokens as CSS custom properties', () => {
  assert.deepEqual(Object.keys(palettes.dark).sort(), Object.keys(palettes.light).sort());
  const variables = themeVariables('dark');
  assert.equal(variables['--pw-paper'], palettes.dark.paper);
  assert.ok(Object.keys(variables).every(name => name.startsWith('--pw-')));
});

test('the theme checks cover the shared workspace and both platform shells', () => {
  for (const path of ['../client/workspace.tsx', '../client/guides.tsx', '../client/index.tsx', '../../src/App.tsx', '../../src/NativeTools.tsx']) assert.ok(uiSources.includes(path), path);
});

test('every themed color class refers to a defined token', () => {
  for (const [path, source] of sources) {
    for (const [, token] of source.matchAll(/--pw-([a-z0-9-]+)/g)) {
      assert.ok(token in palettes.light, `${path} uses undefined token --pw-${token}`);
    }
  }
});

test('UI colors come from theme tokens, not hard-coded hex classes', () => {
  for (const [path, source] of sources) {
    assert.deepEqual(source.match(/[a-z]-\[#[0-9a-f]{3,8}\]/gi) ?? [], [], `${path} has hard-coded color classes`);
  }
});

function luminance(hex: string) {
  const channels = hex.slice(1).match(/../g)!.map(part => parseInt(part, 16) / 255);
  const [r, g, b] = channels.map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

test('dark theme text meets WCAG AA contrast on the surfaces it is used on', () => {
  const d = palettes.dark;
  const pairs: [string, string, string][] = [
    ['ink', 'page', 'body text'], ['ink', 'paper', 'card text'], ['ink', 'field', 'input text'],
    ['muted', 'paper', 'muted text'], ['muted', 'page', 'muted text on page'], ['subtle', 'paper', 'captions'],
    ['subtle', 'sunken', 'preview captions'], ['faint', 'paper', 'section labels'], ['link', 'paper', 'links'],
    ['link', 'page', 'links on page'], ['accent', 'paper', 'accent text'], ['accent', 'accent-bg', 'native badge'],
    ['on-primary', 'primary', 'primary buttons'], ['on-primary', 'primary-hover', 'hovered primary buttons'],
    ['error-text', 'error-bg', 'errors'], ['ok-text', 'ok-bg', 'notices'], ['note-text', 'note-bg', 'notes'],
    ['warn-text', 'warn-bg', 'warnings'], ['limit-text', 'limit-bg', 'limits'], ['icon', 'paper', 'tool icons'],
  ];
  for (const [text, surface, use] of pairs) {
    const ratio = contrast(d[text as keyof typeof d], d[surface as keyof typeof d]);
    assert.ok(ratio >= 4.5, `${use}: ${text} on ${surface} is ${ratio.toFixed(2)}:1`);
  }
});
