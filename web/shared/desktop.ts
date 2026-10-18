// Immutable public assets independently downloaded and SHA-256 verified.
export const desktopPreview = {
 version: '0.1.0-rc.2',
 releaseUrl: 'https://github.com/ClawPick2026/leafsmith/releases/tag/v0.1.0-rc.2',
 packages: [
  {
   platform: 'Windows',
   icon: 'windows',
   label: 'Download Windows preview',
   url: 'https://github.com/ClawPick2026/leafsmith/releases/download/v0.1.0-rc.2/Paperwork_0.1.0_x64-setup.exe',
   sha256: 'fbcaa8473a2d7d51848edc3623aad45999eff12891eaac67fcba4deb5ec3e502',
   bytes: 34073800,
  },
  {
   platform: 'Linux',
   icon: 'linux',
   label: 'Download Linux preview',
   url: 'https://github.com/ClawPick2026/leafsmith/releases/download/v0.1.0-rc.2/Paperwork_0.1.0_amd64.AppImage',
   sha256: '16b0ebe4484820754224d1850a847990626e4c9e7a35cb7b5ac5b31c638761ca',
   bytes: 139901432,
  },
 ],
} as const;
