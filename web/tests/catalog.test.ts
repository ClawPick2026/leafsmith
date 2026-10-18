import { test } from 'node:test';
import assert from 'node:assert/strict';

test('tool discovery filters active browser tools by category and search', async () => {
  const catalog = await import('../shared/catalog.ts').catch(() => ({} as any));
  assert.equal(typeof catalog.findTools, 'function', 'browser tool discovery is implemented');
  const tools = catalog.findTools('Pages', 'rotate');
  assert.equal(tools.length, 1);
  assert.equal(tools[0].id, 'organize');
  assert.equal(catalog.findTools('All tools', 'images').some((t:any)=>t.id==='images-pdf'), true);
});

test('tool descriptions state supported operations without promotional language', async () => {
  const { tools } = await import('../shared/catalog.ts');
  const expected: Record<string,string> = {
    organize:'Reorder, rotate, crop, extract or delete pages.',
    merge:'Combine multiple PDFs in the selected file order.',
    split:'Extract selected pages or save each page as a separate PDF.',
    annotate:'Add text, images, shapes and translucent highlights.',
    sign:'Draw your signature and place it on a document.',
    forms:'Fill existing text fields, checkboxes and supported dropdowns.',
    'images-pdf':'Convert PNG and JPEG images into one PDF.',
    'pdf-images':'Export selected PDF pages as PNG images.',
    text:'Save text already embedded in a PDF as a .txt file.',
    optimize:'Optimize PDF structure without changing image quality.',
    'image-tools':'Resize, compress, adjust brightness and contrast, or combine images.',
    qr:'Generate a QR code from a link or text.'
  };
  assert.deepEqual(Object.fromEntries(tools.map(t=>[t.id,t.description])),expected);
});
