import { useEffect, useLayoutEffect, useState } from 'preact/hooks';
import { initialTheme, nextTheme, themeStorageKey, themeVariables, type Theme } from '../shared/theme.ts';

// Only the theme choice is stored; documents never leave tab memory.
function savedTheme() {
  try { return localStorage.getItem(themeStorageKey); } catch { return null; }
}
const systemQuery = () => matchMedia('(prefers-color-scheme: dark)');

/** Applies the theme's color tokens to <html> so the page, body and native controls follow it. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => initialTheme(savedTheme(), systemQuery().matches));
  useLayoutEffect(() => {
    const root = document.documentElement;
    for (const [name, value] of Object.entries(themeVariables(theme))) root.style.setProperty(name, value);
    root.style.colorScheme = theme;
  }, [theme]);
  useEffect(() => {
    const query = systemQuery();
    const follow = () => { if (!savedTheme()) setTheme(query.matches ? 'dark' : 'light'); };
    query.addEventListener('change', follow);
    return () => query.removeEventListener('change', follow);
  }, []);
  function toggle() {
    const next = nextTheme(theme);
    setTheme(next);
    try { localStorage.setItem(themeStorageKey, next); } catch { /* Storage blocked: the choice lasts until reload. */ }
  }
  return [theme, toggle];
}
