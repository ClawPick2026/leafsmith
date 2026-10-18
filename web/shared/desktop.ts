// Immutable public assets independently downloaded and SHA-256 verified.
export const desktopPreview = {
 version: '0.1.0-rc.3',
 releaseUrl: 'https://github.com/ClawPick2026/leafsmith/releases/tag/v0.1.0-rc.3',
 packages: [
  {
   platform: 'Windows',
   icon: 'windows',
   label: 'Download Windows preview',
   url: 'https://github.com/ClawPick2026/leafsmith/releases/download/v0.1.0-rc.3/Leafsmith_0.1.0_x64-setup.exe',
   sha256: '5a43304e1d16811b64c331254869dd034635e931606cd5671d98ad3db6f30810',
   bytes: 34078103,
  },
  {
   platform: 'Linux',
   icon: 'linux',
   label: 'Download Linux preview',
   url: 'https://github.com/ClawPick2026/leafsmith/releases/download/v0.1.0-rc.3/Leafsmith_0.1.0_amd64.AppImage',
   sha256: '726ff00e552c8e2666c92d82b155d5b4b91211ff8aa1bc841742cbb1a67c6e97',
   bytes: 139913720,
  },
 ],
} as const;
