import { Workspace } from '../web/client/workspace.tsx';
import type { WorkspacePlatform } from '../web/client/workspace.tsx';
import { NativeTools } from './NativeTools';
import * as engine from './engine';

const platform: WorkspacePlatform = {
 name: "Paperwork Desktop",
 homeLabel: "Paperwork Desktop home",
 edition: "desktop",
 status: "Local by default",
 initialQrText: "https://example.com",
 sidebarPrivacy: "Local processing by default. Cloud AI requires consent for each job. Close the app to clear the in-memory workspace.",
 privacyParagraphs: ["Browser tools process files in app memory using bundled libraries, offline. Native tools read only files chosen in their separate system picker. Local jobs do not upload documents. Optional cloud AI sends selected content to your configured provider only with explicit per-job consent. Save results before closing the app. Source files are never overwritten by processing.", "Browser processing libraries and their PDF worker are bundled with the app; no runtime CDN scripts are loaded. Optional processing engines and models may need a separate installation with your consent. Component availability is checked on this device. Local Ollama connections happen only when you run a job. Cloud credentials remain in memory, are sent only for the requested job, and are not stored in app settings. Native jobs and outputs are cached on disk in a private app-cache directory. On normal exit and startup, Paperwork attempts to remove cached job files. Files can remain after a crash or forced termination, or if cleanup fails. This is ordinary deletion, not secure erasure."],
 scopeTitle: "Native processing and limitations",
 limitsNote: "These limits apply to browser tools, not native-file selection. This app is not a backup service and has not received an independent security audit.",
 noTextError: "No embedded text found. Use Image/PDF OCR in Native tools for scanned documents.",
 textHelp: "Existing embedded text is exported as plain UTF-8. This is not optical character recognition. Use Searchable PDF (OCR) in Native tools for image-only scans.",
 scopeItems: [["Native tools","Existing-text editing, Office conversion, OCR, templates, encryption, text watermark removal, model-based tools and media processing are available in the separate Native tools section below. Some require optional engines; unavailable engines block processing with an actionable error."],["Review generated files","Font substitutions, reconstructed layouts, OCR, translation and model output require review. Electronic signatures are not certificate signatures. Watermark removal is limited to supported exact-match text objects."]],
 sidebarFooter: <a href="#about" className="mt-5 px-2 text-xs underline">About &amp; licenses</a>,
 homeBottom: <NativeTools/>,
 footer: <section id="about" className="mt-12 border-t border-[#e1e5db] pt-5 text-xs leading-6 text-[#677169]"><h2 className="font-semibold">About Paperwork Desktop</h2><p>Independent, local-first desktop app. Application source is MIT licensed; third-party packages, processing engines and models keep their own licenses.</p><details><summary className="cursor-pointer underline">Third-party notices</summary><p>Preact: MIT. pdf-lib: MIT. PDF.js: Apache-2.0. qrcode-generator: MIT. Tauri: MIT / Apache-2.0. Engine and model licenses depend on the installed component. Full notices accompany the application distribution.</p></details></section>,
};

export function App(){ return <Workspace engine={engine} platform={platform}/>; }
