/** Color tokens for the website and desktop UI. Light values are the original paper/green/terracotta palette. */
export type Theme = 'light' | 'dark';

export const themeStorageKey = 'paperwork-theme';

const light = {
  page: '#f8f9f4', paper: '#fffefa', field: '#ffffff', sunken: '#eef1e7', hover: '#f3f4ee', selected: '#e9ede3',
  line: '#e0e4d8', 'line-strong': '#d9ddd5', 'line-hover': '#a9b89e',
  ink: '#283c31', 'ink-soft': '#37473c', muted: '#677169', subtle: '#7b8574', faint: '#8a9183', 'icon-faint': '#acb59e',
  link: '#294c3e', icon: '#486446', primary: '#294c3e', 'primary-hover': '#1b382d', 'on-primary': '#ffffff',
  accent: '#a74d34', 'accent-bg': '#f9ebdf', brand: '#a74d34', 'on-brand': '#fff8ed', selection: '#e8c9a1',
  'drop-bg': '#eff3e7', 'drop-line': '#a9b99c',
  'ok-bg': '#edf3e7', 'ok-line': '#d2dec9', 'ok-text': '#42633e', 'ok-dot': '#638c5c', 'result-bg': '#f0f6e9', 'result-line': '#bfd0b4',
  'error-bg': '#fcf0ea', 'error-line': '#e1bdb0', 'error-text': '#963e2e',
  'note-bg': '#f5f0e5', 'note-line': '#e4decf', 'note-text': '#7b6b4f', 'warn-bg': '#f7eee3', 'warn-text': '#8d6242',
  'limit-bg': '#efeade', 'limit-text': '#76654f',
  'art-circle': '#e9eddf', 'art-shadow': '#d9decc', 'art-page': '#fffefa', 'art-edge': '#cbd3be', 'art-lines': '#c8d1c1',
  /** Share of a tool's catalog tint in its icon background; the rest is paper. */
  'tint-mix': '100%',
};

const dark: typeof light = {
  page: '#131814', paper: '#1a201c', field: '#212823', sunken: '#0f1411', hover: '#252d27', selected: '#2b352e',
  line: '#2d3630', 'line-strong': '#3b463e', 'line-hover': '#5f7360',
  ink: '#e3e8de', 'ink-soft': '#d1d9cc', muted: '#a8b1a4', subtle: '#98a193', faint: '#8d9688', 'icon-faint': '#5d6a5c',
  link: '#9fcdb0', icon: '#a9cba0', primary: '#3a6a54', 'primary-hover': '#2f5a46', 'on-primary': '#ffffff',
  accent: '#e3907a', 'accent-bg': '#3a231b', brand: '#a74d34', 'on-brand': '#fff8ed', selection: '#6a4a2c',
  'drop-bg': '#18211b', 'drop-line': '#4b5e4a',
  'ok-bg': '#18261c', 'ok-line': '#2f4733', 'ok-text': '#b2d6a8', 'ok-dot': '#7fb276', 'result-bg': '#17251b', 'result-line': '#3a5640',
  'error-bg': '#2d1a15', 'error-line': '#6a3527', 'error-text': '#f2b3a0',
  'note-bg': '#252117', 'note-line': '#4a4231', 'note-text': '#dcc9a2', 'warn-bg': '#2a2016', 'warn-text': '#e4b48c',
  'limit-bg': '#24201a', 'limit-text': '#d6c4a3',
  'art-circle': '#1d2620', 'art-shadow': '#151b17', 'art-page': '#27302a', 'art-edge': '#3b473e', 'art-lines': '#4a584e',
  'tint-mix': '16%',
};

export const palettes: Record<Theme, typeof light> = { light, dark };

/** A saved choice wins; without one, follow the system preference. */
export function initialTheme(saved: string | null, prefersDark: boolean): Theme {
  return saved === 'light' || saved === 'dark' ? saved : prefersDark ? 'dark' : 'light';
}

export function nextTheme(theme: Theme): Theme {
  return theme === 'dark' ? 'light' : 'dark';
}

/** Custom properties referenced by classes such as `bg-(--pw-paper)`. */
export function themeVariables(theme: Theme): Record<string, string> {
  return Object.fromEntries(Object.entries(palettes[theme]).map(([token, value]) => [`--pw-${token}`, value]));
}
