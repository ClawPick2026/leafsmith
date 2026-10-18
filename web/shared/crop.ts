/** Crop and placement geometry shared by PDF pages and images. Pure functions, no DOM. */
export type Margins = { left: number; bottom: number; right: number; top: number };
export type Rect = { x: number; y: number; width: number; height: number };
/** Fractions of the displayed page or image, measured from its top-left corner. */
export type Selection = Rect;
export type Size = { width: number; height: number };

function quarterTurns(rotation: number): number {
  if (!Number.isInteger(rotation) || rotation % 90 !== 0) throw new Error('Rotation must be a multiple of 90 degrees.');
  return ((rotation / 90) % 4 + 4) % 4;
}

/** Size of a page box as displayed after its /Rotate value. */
export function viewSize(size: Size, rotation: number): Size {
  return quarterTurns(rotation) % 2 ? { width: size.height, height: size.width } : { width: size.width, height: size.height };
}

/** Margins measured on the displayed page, as unrotated PDF box margins. PDF rotation is clockwise. */
export function viewMarginsToPdf(view: Margins, rotation: number): Margins {
  const { left, bottom, right, top } = view;
  return [
    { left, bottom, right, top },
    { left: top, bottom: left, right: bottom, top: right },
    { left: right, bottom: top, right: left, top: bottom },
    { left: bottom, bottom: right, right: top, top: left },
  ][quarterTurns(rotation)];
}

export function pdfMarginsToView(pdf: Margins, rotation: number): Margins {
  return viewMarginsToPdf(pdf, -rotation);
}

/** Whole-unit margins (points or pixels) around a selection. */
export function selectionToMargins(selection: Selection, size: Size): Margins {
  const edge = (fraction: number, length: number) => Math.max(0, Math.round(fraction * length));
  return {
    left: edge(selection.x, size.width),
    top: edge(selection.y, size.height),
    right: edge(1 - selection.x - selection.width, size.width),
    bottom: edge(1 - selection.y - selection.height, size.height),
  };
}

/** The selection left by margins, or null when they are invalid or leave no area. */
export function marginsToSelection(margins: Margins, size: Size): Selection | null {
  const { left, top, right, bottom } = margins;
  if (![left, top, right, bottom, size.width, size.height].every(Number.isFinite) || Math.min(left, top, right, bottom) < 0) return null;
  const width = size.width - left - right;
  const height = size.height - top - bottom;
  if (width <= 0 || height <= 0) return null;
  return { x: left / size.width, y: top / size.height, width: width / size.width, height: height / size.height };
}

const hundredths = (value: number) => Math.round(value * 100) / 100;

/** A displayed selection as a PDF rectangle in user space, from the bottom-left of the unrotated page. */
export function selectionToPdfRect(selection: Selection, box: Rect, rotation: number): Rect {
  const m = viewMarginsToPdf(selectionToMargins(selection, viewSize(box, rotation)), rotation);
  return { x: hundredths(box.x + m.left), y: hundredths(box.y + m.bottom), width: hundredths(box.width - m.left - m.right), height: hundredths(box.height - m.bottom - m.top) };
}

export function pdfRectToSelection(rect: Rect, box: Rect, rotation: number): Selection | null {
  if (![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) || rect.width <= 0 || rect.height <= 0) return null;
  const pdf = { left: rect.x - box.x, bottom: rect.y - box.y, right: box.x + box.width - rect.x - rect.width, top: box.y + box.height - rect.y - rect.height };
  return marginsToSelection(pdfMarginsToView(pdf, rotation), viewSize(box, rotation));
}

/** Keeps a selection inside the unit square with at least `min` width and height. */
export function clampSelection(selection: Selection, min: number): Selection {
  const width = Math.min(1, Math.max(min, selection.width));
  const height = Math.min(1, Math.max(min, selection.height));
  return { x: Math.min(1 - width, Math.max(0, selection.x)), y: Math.min(1 - height, Math.max(0, selection.y)), width, height };
}
