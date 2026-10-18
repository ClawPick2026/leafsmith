import test from 'node:test';
import assert from 'node:assert/strict';

const crop = () => import('../shared/crop.ts');

test('display-relative margins map to unrotated PDF margins for each page rotation', async () => {
  const { viewMarginsToPdf } = await crop();
  const view = { left: 1, bottom: 2, right: 3, top: 4 };
  assert.deepEqual(viewMarginsToPdf(view, 0), { left: 1, bottom: 2, right: 3, top: 4 });
  // Rotate 90 clockwise: displayed left is the PDF bottom, displayed top is the PDF left.
  assert.deepEqual(viewMarginsToPdf(view, 90), { left: 4, bottom: 1, right: 2, top: 3 });
  assert.deepEqual(viewMarginsToPdf(view, 180), { left: 3, bottom: 4, right: 1, top: 2 });
  assert.deepEqual(viewMarginsToPdf(view, 270), { left: 2, bottom: 3, right: 4, top: 1 });
  assert.deepEqual(viewMarginsToPdf(view, -90), viewMarginsToPdf(view, 270));
  assert.deepEqual(viewMarginsToPdf(view, 450), viewMarginsToPdf(view, 90));
  assert.throws(() => viewMarginsToPdf(view, 45), /90/);
});

test('displayed page size swaps width and height for quarter turns', async () => {
  const { viewSize } = await crop();
  assert.deepEqual(viewSize({ width: 600, height: 800 }, 0), { width: 600, height: 800 });
  assert.deepEqual(viewSize({ width: 600, height: 800 }, 90), { width: 800, height: 600 });
  assert.deepEqual(viewSize({ width: 600, height: 800 }, 180), { width: 600, height: 800 });
  assert.deepEqual(viewSize({ width: 600, height: 800 }, 270), { width: 800, height: 600 });
});

test('a fractional selection converts to rounded margins and back', async () => {
  const { selectionToMargins, marginsToSelection } = await crop();
  const size = { width: 600, height: 800 };
  assert.deepEqual(selectionToMargins({ x: 0.1, y: 0.25, width: 0.5, height: 0.5 }, size), { left: 60, top: 200, right: 240, bottom: 200 });
  assert.deepEqual(selectionToMargins({ x: 0, y: 0, width: 1, height: 1 }, size), { left: 0, top: 0, right: 0, bottom: 0 });
  // Rounds to whole units and never produces negative margins from float noise.
  assert.deepEqual(selectionToMargins({ x: 0.10004, y: 0, width: 0.89996, height: 1.0000001 }, size), { left: 60, top: 0, right: 0, bottom: 0 });
  assert.deepEqual(marginsToSelection({ left: 60, top: 200, right: 240, bottom: 200 }, size), { x: 0.1, y: 0.25, width: 0.5, height: 0.5 });
  assert.equal(marginsToSelection({ left: 600, top: 0, right: 0, bottom: 0 }, size), null, 'Margins that leave no area have no selection');
  assert.equal(marginsToSelection({ left: NaN, top: 0, right: 0, bottom: 0 }, size), null);
});

test('placement selections convert to PDF rectangles relative to the visible page box', async () => {
  const { selectionToPdfRect, pdfRectToSelection } = await crop();
  const box = { x: 0, y: 0, width: 600, height: 800 };
  // Top-left quarter of an unrotated page: PDF y counts up from the bottom.
  assert.deepEqual(selectionToPdfRect({ x: 0, y: 0, width: 0.5, height: 0.25 }, box, 0), { x: 0, y: 600, width: 300, height: 200 });
  assert.deepEqual(pdfRectToSelection({ x: 0, y: 600, width: 300, height: 200 }, box, 0), { x: 0, y: 0, width: 0.5, height: 0.25 });
  // A page already cropped to an offset box keeps PDF user-space coordinates.
  const offset = { x: 10, y: 20, width: 580, height: 760 };
  assert.deepEqual(selectionToPdfRect({ x: 0, y: 0, width: 1, height: 1 }, offset, 0), offset);
  // On a page displayed at 90 degrees, the displayed top-left corner is the PDF bottom-left corner.
  assert.deepEqual(selectionToPdfRect({ x: 0, y: 0, width: 0.25, height: 0.5 }, box, 90), { x: 0, y: 0, width: 300, height: 200 });
  assert.deepEqual(pdfRectToSelection({ x: 0, y: 0, width: 300, height: 200 }, box, 90), { x: 0, y: 0, width: 0.25, height: 0.5 });
  assert.equal(pdfRectToSelection({ x: 0, y: 0, width: 0, height: 10 }, box, 0), null);
});

test('selection clamping keeps rectangles inside the page with a minimum size', async () => {
  const { clampSelection } = await crop();
  assert.deepEqual(clampSelection({ x: -0.2, y: 0.9, width: 0.5, height: 0.5 }, 0.05), { x: 0, y: 0.5, width: 0.5, height: 0.5 });
  assert.deepEqual(clampSelection({ x: 0.5, y: 0.5, width: 0.001, height: 2 }, 0.05), { x: 0.5, y: 0, width: 0.05, height: 1 });
  assert.deepEqual(clampSelection({ x: 0.99, y: 0, width: 0.001, height: 1 }, 0.05), { x: 0.95, y: 0, width: 0.05, height: 1 });
});
