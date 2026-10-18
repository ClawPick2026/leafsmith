import { useEffect, useRef, useState } from 'preact/hooks';
import { clampSelection } from '../shared/crop.ts';
import type { Selection } from '../shared/crop.ts';
import type { Engine } from './engine-core.ts';

type Handle = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw';
type Drag = { mode: 'move' | 'draw' | Handle; start: [number, number]; rect: Selection };
const handles: [Handle, number, number, string][] = [
 ['nw', 0, 0, 'nwse-resize'], ['n', 50, 0, 'ns-resize'], ['ne', 100, 0, 'nesw-resize'], ['e', 100, 50, 'ew-resize'],
 ['se', 100, 100, 'nwse-resize'], ['s', 50, 100, 'ns-resize'], ['sw', 0, 100, 'nesw-resize'], ['w', 0, 50, 'ew-resize'],
];
const pct = (value: number) => `${value * 100}%`;

/**
 * Rectangle selection drawn over a preview, in fractions of the preview.
 * Crop mode shades the area outside the selection; place mode outlines a box.
 */
export function RegionSelector({ value, onChange, mode, label, min = 0.02 }: { value: Selection | null; onChange: (selection: Selection) => void; mode: 'crop' | 'place'; label: string; min?: number }) {
 const host = useRef<HTMLDivElement>(null);
 const drag = useRef<Drag | null>(null);
 function point(e: PointerEvent): [number, number] {
  const r = host.current!.getBoundingClientRect();
  return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
 }
 function start(e: PointerEvent) {
  if (e.button !== 0) return;
  const p = point(e);
  const handle = (e.target as HTMLElement).dataset?.handle as Handle | undefined;
  const r = value;
  const inside = !!r && p[0] >= r.x && p[0] <= r.x + r.width && p[1] >= r.y && p[1] <= r.y + r.height;
  // A selection covering the whole preview cannot be moved, so dragging inside it draws a new one.
  const whole = !!r && r.width > 0.995 && r.height > 0.995;
  drag.current = { mode: handle && r ? handle : inside && !whole ? 'move' : 'draw', start: p, rect: r ?? { x: p[0], y: p[1], width: 0, height: 0 } };
  host.current!.setPointerCapture(e.pointerId);
  e.preventDefault();
 }
 function move(e: PointerEvent) {
  const d = drag.current;
  if (!d) return;
  const [px, py] = point(e);
  const r = d.rect;
  if (d.mode === 'move') { onChange(clampSelection({ ...r, x: r.x + px - d.start[0], y: r.y + py - d.start[1] }, min)); return; }
  if (d.mode === 'draw') {
   const width = Math.abs(px - d.start[0]); const height = Math.abs(py - d.start[1]);
   // Ignore clicks and tiny drags instead of collapsing the selection.
   if (width < min && height < min) return;
   onChange(clampSelection({ x: Math.min(px, d.start[0]), y: Math.min(py, d.start[1]), width, height }, min));
   return;
  }
  let left = r.x, top = r.y, right = r.x + r.width, bottom = r.y + r.height;
  if (d.mode.includes('w')) left = Math.min(right - min, Math.max(0, px));
  if (d.mode.includes('e')) right = Math.max(left + min, Math.min(1, px));
  if (d.mode.includes('n')) top = Math.min(bottom - min, Math.max(0, py));
  if (d.mode.includes('s')) bottom = Math.max(top + min, Math.min(1, py));
  onChange(clampSelection({ x: left, y: top, width: right - left, height: bottom - top }, min));
 }
 function key(e: KeyboardEvent) {
  if (!value) return;
  const step = 0.01;
  const delta = ({ ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] } as Record<string, number[]>)[e.key];
  if (!delta) return;
  e.preventDefault();
  onChange(clampSelection(e.shiftKey ? { ...value, width: value.width + delta[0], height: value.height + delta[1] } : { ...value, x: value.x + delta[0], y: value.y + delta[1] }, min));
 }
 const end = () => { drag.current = null; };
 return <div ref={host} data-testid={mode === 'crop' ? 'crop-selector' : 'placement-selector'} className="absolute inset-0 touch-none select-none" style={{ cursor: 'crosshair' }} onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
  {value && mode === 'crop' && <div aria-hidden="true" className="pointer-events-none absolute inset-0">
   <div className="absolute inset-x-0 top-0 bg-black/45" style={{ height: pct(value.y) }}/>
   <div className="absolute inset-x-0 bottom-0 bg-black/45" style={{ height: pct(1 - value.y - value.height) }}/>
   <div className="absolute left-0 bg-black/45" style={{ top: pct(value.y), height: pct(value.height), width: pct(value.x) }}/>
   <div className="absolute right-0 bg-black/45" style={{ top: pct(value.y), height: pct(value.height), width: pct(1 - value.x - value.width) }}/>
  </div>}
  {value && <div tabIndex={0} role="group" aria-label={label} data-testid="selection-box" onKeyDown={key}
   className={'absolute border-2 border-(--pw-brand) shadow-[0_0_0_1px_rgba(255,255,255,0.85)] outline-none focus-visible:ring-2 focus-visible:ring-(--pw-accent) ' + (mode === 'place' ? 'bg-(--pw-brand)/15' : '')}
   style={{ left: pct(value.x), top: pct(value.y), width: pct(value.width), height: pct(value.height), cursor: 'move' }}>
   {handles.map(([handle, left, top, cursor]) => <span key={handle} data-handle={handle} aria-hidden="true" className="absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-sm border-2 border-(--pw-brand) bg-white" style={{ left: `${left}%`, top: `${top}%`, cursor }}/>)}
  </div>}
 </div>;
}

type Previewable = { name: string; bytes: Uint8Array; mime: string; url: string; page?: number };
const TEXT_LIMIT = 20_000;
const caption = 'mt-2 text-center text-[11px] text-(--pw-subtle)';

/** Collapsible preview rendered from the generated file itself. */
export function ResultPreview({ engine, result, defaultOpen }: { engine: Engine; result: Previewable; defaultOpen: boolean }) {
 const [open, setOpen] = useState(defaultOpen);
 const kind = result.mime === 'application/pdf' ? 'pdf' : result.mime.startsWith('image/') ? 'image' : result.mime.startsWith('text/') ? 'text' : '';
 if (!kind) return null;
 return <div className="w-full">
  <button type="button" className="text-xs underline underline-offset-4" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide preview' : 'Show preview'}</button>
  {open && <div className="mt-3 rounded-lg border border-(--pw-line) bg-(--pw-sunken) p-3" data-testid="result-preview">
   {kind === 'pdf' ? <PdfPreview engine={engine} result={result}/> : kind === 'image' ? <ImagePreview result={result}/> : <TextPreview bytes={result.bytes}/>}
  </div>}
 </div>;
}

function PdfPreview({ engine, result }: { engine: Engine; result: Previewable }) {
 const host = useRef<HTMLDivElement>(null);
 const [info, setInfo] = useState<Awaited<ReturnType<Engine['pdfInfo']>> | null>(null);
 const [page, setPage] = useState(result.page ?? 1);
 const [error, setError] = useState('');
 useEffect(() => {
  let alive = true;
  engine.pdfInfo(result.bytes).then(value => { if (alive) { setInfo(value); setPage(p => Math.min(Math.max(1, p), value.pageCount)); } }).catch(e => { if (alive) setError(e.message); });
  return () => { alive = false; };
 }, [result.bytes]);
 useEffect(() => {
  const size = info?.sizes[page - 1];
  if (!size) return;
  let alive = true;
  setError('');
  // Sharp enough to read, without exceeding the canvas budget on very large pages.
  const scale = Math.min(1.5, 1600 / Math.max(size.box.width, size.box.height));
  engine.renderPdfPage(result.bytes, page, scale).then(canvas => {
   if (!alive) { canvas.width = 0; canvas.height = 0; return; }
   canvas.setAttribute('role', 'img');
   canvas.setAttribute('aria-label', `Result preview page ${page}`);
   canvas.className = 'mx-auto block h-auto max-h-[36rem] w-auto max-w-full bg-white shadow-sm';
   host.current?.replaceChildren(canvas);
  }).catch(e => { if (alive) setError(e.message); });
  return () => { alive = false; };
 }, [info, page]);
 const count = info?.pageCount ?? 0;
 return <>
  {count > 1 && <div className="mb-3 flex items-center justify-center gap-3 text-xs">
   <button type="button" className="rounded border border-(--pw-line-strong) bg-(--pw-paper) px-2 py-1 disabled:opacity-40" aria-label="Previous result page" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
   <span>Page {page} of {count}</span>
   <button type="button" className="rounded border border-(--pw-line-strong) bg-(--pw-paper) px-2 py-1 disabled:opacity-40" aria-label="Next result page" disabled={page >= count} onClick={() => setPage(page + 1)}>›</button>
  </div>}
  <div ref={host} className="min-h-24"/>
  {error ? <p className="mt-2 text-xs text-(--pw-accent)">Preview unavailable: {error}</p> : <p className={caption}>Rendered from {result.name}</p>}
 </>;
}

function ImagePreview({ result }: { result: Previewable }) {
 const [size, setSize] = useState('');
 return <>
  <img src={result.url} alt={result.name === 'qr-code.svg' ? 'Generated QR code' : `Preview of ${result.name}`} className="mx-auto block max-h-[36rem] max-w-full bg-white object-contain shadow-sm" onLoad={e => { const img = e.currentTarget; setSize(`${img.naturalWidth} × ${img.naturalHeight} px · `); }}/>
  <p className={caption}>{size}Rendered from {result.name}</p>
 </>;
}

function TextPreview({ bytes }: { bytes: Uint8Array }) {
 const text = new TextDecoder().decode(bytes);
 return <>
  <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-(--pw-paper) p-3 text-xs leading-5" data-testid="text-preview">{text.slice(0, TEXT_LIMIT)}</pre>
  {text.length > TEXT_LIMIT && <p className={caption}>Showing the first {TEXT_LIMIT.toLocaleString('en')} of {text.length.toLocaleString('en')} characters. The download contains all of the text.</p>}
 </>;
}
