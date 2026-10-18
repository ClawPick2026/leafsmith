import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as desktopCatalog from '../src/catalog.ts';
import * as webCatalog from '../web/shared/catalog.ts';
import * as desktopPages from '../src/pages.ts';
import * as webPages from '../web/shared/pages.ts';
import * as PDFLib from 'pdf-lib';
import { existsSync } from 'node:fs';

// Exercise the old singleton when the extraction is absent: RED must prove
// injected loaders are ignored, not just fail at a missing module import.
async function engineFactory() {
  const core = new URL('../web/client/engine-core.ts', import.meta.url);
  if (existsSync(core)) return (await import(core.href)).createEngine;
  const singleton = await import('../web/client/engine.ts');
  return (_dependencies: unknown) => singleton;
}

test('engine instances use their own injected PDF library without globals or eager unrelated loads', async () => {
  const createEngine = await engineFactory();
  let loads = 0;
  const e = createEngine({
    loadPdfLib: async () => { loads++; return PDFLib; },
    loadPdfJs: async () => { throw Error('PDF.js must stay lazy'); },
    loadQr: async () => { throw Error('QR must stay lazy'); },
  });
  const previous = (globalThis as any).PDFLib;
  (globalThis as any).PDFLib = PDFLib; // Lets the pre-refactor singleton run.
  try {
    assert.equal(loads, 0);
    const sample = await e.makeDemoPdf();
    assert.equal((await PDFLib.PDFDocument.load(sample)).getPageCount(), 3);
    assert.ok(loads > 0, 'PDF creation must call this instance’s injected loader');
    const transformed = await e.transformPdf(sample, {pages:[3,1], rotate:90});
    const result = await PDFLib.PDFDocument.load(transformed);
    assert.equal(result.getPageCount(), 2);
    assert.equal(result.getPage(0).getRotation().angle, 90);
    const blocked = createEngine({
      loadPdfLib: async () => { throw Error('isolated PDF loader'); },
      loadPdfJs: async () => { throw Error('unused'); },
      loadQr: async () => { throw Error('unused'); },
    });
    await assert.rejects(blocked.makeDemoPdf(), /isolated PDF loader/);
    assert.equal((await e.pdfInfo(sample)).pageCount, 3);
  } finally {
    if (previous === undefined) delete (globalThis as any).PDFLib;
    else (globalThis as any).PDFLib = previous;
  }
});

test('desktop and browser use the same live catalog and page-selection functions', () => {
  assert.strictEqual(desktopCatalog.tools, webCatalog.tools, 'Tool objects must have one canonical owner, not copied catalogs');
  assert.strictEqual(desktopCatalog.categories, webCatalog.categories);
  assert.strictEqual(desktopCatalog.findTools, webCatalog.findTools);
  assert.strictEqual(desktopPages.parsePageRange, webPages.parsePageRange);
  assert.deepEqual(desktopPages.parsePageRange('3,1-2,3', 3), [3,1,2]);
  assert.strictEqual(desktopCatalog.findTools('Utilities', 'QR')[0], webCatalog.tools.find(tool => tool.id === 'qr'));
});

// Architectural shell regression: processing interactions remain covered by the
// existing browser acceptance suites, not by these source wiring assertions.
import { readFileSync, readdirSync, realpathSync } from 'node:fs';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseSync, transformSync } from 'rolldown/utils';
import { registerHooks } from 'node:module';

const repository = fileURLToPath(new URL('..', import.meta.url));
const sourceAt = (path: string) => readFileSync(resolve(repository, path), 'utf8');

test('both platform shells mount one canonical workspace with injected platform behavior', async () => {
  for (const path of ['src/App.tsx', 'web/client/index.tsx']) {
    const source = sourceAt(path);
    assert.match(source, /import \{ Workspace \} from ['"][^'"]*workspace(?:\.tsx)?['"]/, `${path} must delegate to the canonical workspace`);
    assert.doesNotMatch(source, /function (?:execute|addFiles|Drawing)\(|useState\(/, `${path} must not keep a duplicate workspace implementation`);
  }
  const hooks = registerHooks({
    resolve(specifier, context, next) {
      if (specifier.startsWith('.') && !extname(specifier) && context.parentURL?.startsWith('file:')) {
        const url = new URL(specifier, context.parentURL);
        for (const extension of ['.ts', '.tsx']) if (existsSync(fileURLToPath(url) + extension)) return next(url.href + extension, context);
      }
      return next(specifier, context);
    },
    load(url, context, next) {
      if (url.endsWith('.tsx')) return {format:'module', shortCircuit:true, source:transformSync(fileURLToPath(url), readFileSync(fileURLToPath(url), 'utf8'), {lang:'tsx', jsx:{runtime:'automatic', importSource:'preact'}}).code};
      return next(url, context);
    },
  });
  try {
    const desktop = (await import('../src/App.tsx')).App();
    const browser = (await import('../web/client/index.tsx')).App();
    const { Workspace } = await import('../web/client/workspace.tsx');
    assert.equal(desktop.type, Workspace);
    assert.equal(browser.type, Workspace);
    assert.notEqual(desktop.props.engine, browser.props.engine, 'Platform adapters must stay separate');
    assert.equal(desktop.props.platform.name, 'Paperwork Desktop');
    assert.equal(browser.props.platform.name, 'paperwork');
    assert.equal(desktop.props.platform.initialQrText, 'https://example.com');
    assert.equal(browser.props.platform.initialQrText, 'https://lakebed.dev');
    assert.ok(desktop.props.platform.homeBottom, 'Desktop retains the NativeTools slot');
    assert.ok(browser.props.platform.homeAfterTools, 'Browser retains the desktop-download slot');
    assert.equal(desktop.props.platform.homeAfterTools, undefined, 'Web download marketing must not enter the desktop shell');
    assert.equal(browser.props.platform.homeBottom, undefined, 'Browser must not import NativeTools');
  } finally { hooks.deregister(); }
});

function dependencies(source: string, filename: string): string[] {
  const parsed = parseSync(filename, source, {lang:filename.endsWith('.tsx') ? 'tsx' : 'ts'});
  assert.deepEqual(parsed.errors, [], filename);
  const imports: string[] = [];
  function visit(node: any) {
    if (!node || typeof node !== 'object') return;
    if (['ImportDeclaration','ExportNamedDeclaration','ExportAllDeclaration','ImportExpression'].includes(node.type) && node.source) {
      assert.equal(typeof node.source.value, 'string', `Only literal imports are auditable: ${filename}`);
      imports.push(node.source.value);
    }
    assert.notEqual(node.type, 'TSImportEqualsDeclaration', `No CommonJS imports in capsule: ${filename}`);
    if (node.type === 'CallExpression' && node.callee?.name === 'require') assert.fail(`No Node require in capsule: ${filename}`);
    for (const child of Object.values(node)) if (Array.isArray(child)) child.forEach(visit); else if (child && typeof child === 'object') visit(child);
  }
  visit(parsed.program);
  return imports;
}

test('recursive capsule import boundary permits only internal files and documented Preact/Lakebed modules', () => {
  const capsule = realpathSync(resolve(repository, 'web'));
  const allowed = new Set(['preact','preact/hooks','preact/jsx-runtime','preact/jsx-dev-runtime','lakebed/client','lakebed/server']);
  const seen = new Set<string>();
  function inspect(file: string) {
    file = realpathSync(file);
    assert.ok(file.startsWith(capsule + sep), `Import escapes capsule: ${file}`);
    if (seen.has(file)) return;
    seen.add(file);
    for (const specifier of dependencies(readFileSync(file, 'utf8'), file)) {
      if (!specifier.startsWith('.')) {
        assert.ok(allowed.has(specifier), `Forbidden external import ${specifier} in ${file}`);
        continue;
      }
      const base = resolve(dirname(file), specifier);
      const target = [base,base+'.ts',base+'.tsx',resolve(base,'index.ts'),resolve(base,'index.tsx')].find(candidate => existsSync(candidate) && ['.ts','.tsx'].includes(extname(candidate)));
      assert.ok(target, `Unresolved capsule import ${specifier} in ${file}`);
      inspect(target);
    }
  }
  function scan(directory: string) {
    for (const item of readdirSync(directory, {withFileTypes:true})) {
      const path = resolve(directory,item.name);
      if (item.isDirectory()) scan(path);
      else if (/\.tsx?$/.test(path)) inspect(path);
    }
  }
  scan(resolve(capsule, 'client'));
  scan(resolve(capsule, 'shared'));
  assert.ok(seen.has(resolve(capsule, 'client/engine-core.ts')));
  assert.ok(seen.has(resolve(capsule, 'client/workspace.tsx')));
  // Parser characterization prevents comment/string matches hiding import leaks.
  assert.deepEqual(dependencies(`// import 'safe';\nexport * from '../escape.ts'; const lazy=import('node:fs');`, 'fixture.ts'), ['../escape.ts','node:fs']);
});

// Characterization of the extracted dependency seams, in addition to the RED
// PDF-loader regression above. Real PDF/QR artifacts; PDF.js is a task fixture.
import qrFactory from 'qrcode-generator';

test('injected QR generation is independently callable and restores UTF-8 encoder state', async () => {
  const createEngine = await engineFactory();
  let qrLoads = 0;
  const original = qrFactory.stringToBytes;
  const e = createEngine({
    loadPdfLib: async () => { throw Error('PDF must not load for QR'); },
    loadPdfJs: async () => { throw Error('PDF.js must not load for QR'); },
    loadQr: async () => { qrLoads++; return qrFactory; },
  });
  assert.equal(qrLoads, 0);
  const svg = await e.qrSvg('Injected UTF-8 — Bücher 🌍');
  assert.match(svg, /^<svg\b/);
  assert.equal(qrLoads, 1);
  assert.equal(qrFactory.stringToBytes, original);
  await assert.rejects(e.qrSvg(''), /non-empty/);
  await assert.rejects(e.qrSvg('🙂'.repeat(251)), /1000/);
  assert.equal(qrLoads, 1, 'Invalid QR payloads must be rejected before loading');
  const failure = createEngine({
    loadPdfLib: async () => { throw Error('unused'); },
    loadPdfJs: async () => { throw Error('unused'); },
    loadQr: async () => { throw Error('isolated QR loader'); },
  });
  await assert.rejects(failure.qrSvg('test'), /isolated QR loader/);
  assert.match(await e.qrSvg('Still works'), /^<svg\b/);
});

test('injected PDF.js extraction copies input, honors selected order, and destroys its own task', async () => {
  const createEngine = await engineFactory();
  const doc = await PDFLib.PDFDocument.create();
  doc.addPage([100,100]); doc.addPage([200,200]);
  const bytes = await doc.save();
  const original = bytes.slice();
  let destroyed = 0;
  let pdfJsLoads = 0;
  let fail = false;
  const cleaned: number[] = [];
  const pdfJs = { getDocument(options: any) {
    assert.equal(options.isEvalSupported, false);
    assert.equal(options.useSystemFonts, true);
    assert.notEqual(options.data, bytes);
    structuredClone(options.data, {transfer:[options.data.buffer]});
    return {
      promise: fail ? Promise.reject(Error('parser failure')) : Promise.resolve({
        getPage: async (number: number) => ({
          getTextContent: async () => ({items:[{str:`Injected ${number}`,hasEOL:true},{str:'Next'}]}),
          cleanup() { cleaned.push(number); },
        }),
      }),
      async destroy() { destroyed++; },
    };
  } };
  const e = createEngine({
    loadPdfLib: async () => PDFLib,
    loadPdfJs: async () => { pdfJsLoads++; return pdfJs; },
    loadQr: async () => { throw Error('QR must not load for text'); },
  });
  assert.equal(pdfJsLoads, 0);
  assert.equal(await e.loadPdfJs(), pdfJs, 'Dependency seam is independently callable');
  assert.equal(await e.loadPdfLib(), PDFLib);
  assert.equal(await e.extractPdfText(bytes, [2,1]), 'Page 2\nInjected 2\nNext\n\nPage 1\nInjected 1\nNext');
  assert.deepEqual(cleaned, [2,1]);
  assert.deepEqual(bytes, original);
  assert.equal(destroyed, 1);
  fail = true;
  await assert.rejects(e.extractPdfText(bytes, [1]), /parser failure/);
  assert.equal(destroyed, 2);
  const isolated = createEngine({
    loadPdfLib: async () => PDFLib,
    loadPdfJs: async () => { throw Error('isolated PDF.js loader'); },
    loadQr: async () => { throw Error('unused'); },
  });
  await assert.rejects(isolated.extractPdfText(bytes, [1]), /isolated PDF.js loader/);
});

test('platform adapters preserve the complete operation API without implementing operations twice', async () => {
  const desktop = await import('../src/engine.ts');
  const browser = await import('../web/client/engine.ts');
  const createEngine = await engineFactory();
  const e = createEngine({loadPdfLib:async()=>PDFLib,loadPdfJs:async()=>({}),loadQr:async()=>qrFactory});
  assert.deepEqual(Object.keys(desktop).sort(), Object.keys(browser).sort());
  assert.deepEqual(Object.keys(desktop).sort(), Object.keys(e).sort());
  for (const path of ['src/engine.ts','web/client/engine.ts']) {
    const source = sourceAt(path);
    assert.match(source, /createEngine\(\{ loadPdfLib, loadPdfJs, loadQr \}\)/);
    assert.doesNotMatch(source, /PDFDocument|function (?:openPdf|transformPdf|qrSvg|renderPdfPage|processImage)\(/);
  }
  assert.match(sourceAt('src/engine.ts'), /pdfjs-dist\/build\/pdf\.worker\.min\.mjs\?url/);
  assert.doesNotMatch(sourceAt('src/engine.ts'), /https?:|loadScript/);
  assert.match(sourceAt('web/client/engine.ts'), /pdfjs-dist@3\.11\.174/);
  assert.match(sourceAt('web/client/engine.ts'), /qrcode-generator@1\.4\.4/);
  assert.match(sourceAt('web/client/engine.ts'), /pdf-lib@1\.17\.1/);
});
