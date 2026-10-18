/** Parse a 1-based page selection. Blank input means all pages. */
export function parsePageRange(input: string, count: number): number[] {
  if (!Number.isInteger(count) || count < 1 || count > 200) throw new Error('PDF must contain 1–200 pages.');
  if (typeof input !== 'string') throw new Error('Enter page numbers or ranges, such as 1-3,5.');
  if (!input.trim()) return Array.from({ length: count }, (_, i) => i + 1);
  const selected = new Set<number>();
  for (const token of input.split(',')) {
    const match = /^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$/.exec(token);
    if (!match) throw new Error('Use comma-separated page numbers and ranges, such as 1-3,5.');
    const start = Number(match[1]);
    const end = match[2] === undefined ? start : Number(match[2]);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end > count || start > end) {
      throw new Error(`Page ranges must ascend and stay between 1 and ${count}.`);
    }
    for (let page = start; page <= end; page++) selected.add(page);
  }
  return [...selected];
}
