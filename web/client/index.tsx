import { Workspace } from './workspace.tsx';
import { Icon, primary, muted } from './workspace.tsx';
import type { WorkspacePlatform } from './workspace.tsx';
import * as engine from './engine.ts';
import { unsupported } from '../shared/catalog.ts';
import { windowsPreview } from '../shared/desktop.ts';
import { HomeMetadata } from './discovery.ts';
import { guides } from '../shared/discovery.ts';

const platform: WorkspacePlatform = {
 name: "paperwork",
 homeLabel: "Paperwork home",
 edition: "browser edition",
 status: "No account. No uploads.",
 initialQrText: "https://lakebed.dev",
 sidebarPrivacy: "Your files stay on your device. Close the tab to clear this workspace.",
 privacyParagraphs: ["Files are read into this tab's memory and processed in your browser. The app does not upload documents, store them in Lakebed, or send them to an AI service. Download a result before closing or refreshing this tab. Source files on your device are never overwritten.", "An internet connection is needed to load Lakebed and version-pinned processing libraries from jsDelivr. Those services receive ordinary network metadata such as your IP address; the app does not transmit document bytes to them. Third-party scripts execute in the page, so this is not a security-audited environment for highly sensitive material."],
 scopeTitle: "Not included in this release",
 limitsNote: "Lakebed is a public alpha, not production-ready. No backup, security audit, or uptime guarantee.",
 noTextError: "No embedded text found. Scanned documents need OCR, which is not included.",
 textHelp: "Existing embedded text is exported as plain UTF-8. This is not optical character recognition. Image-only scans need an OCR service, not included here.",
 scopeItems: unsupported,
 sidebarFooter: <p className="mt-5 px-2 text-[10px] tracking-wide text-[#87907e]">BUILT WITH LAKEBED · ALPHA</p>,
 footer: <><HomeMetadata/><nav aria-label="PDF guides" className="mt-8 border-t border-[#dfe4d6] pt-6"><h2 className="text-xl font-semibold">PDF guides</h2><p className={muted+' mt-2'}>Instructions and limitations for browser-only PDF tools.</p><ul className="mt-4 flex flex-wrap gap-x-6 gap-y-3 text-sm text-[#294c3e]">{guides.map(guide=><li key={guide.path}><a className="underline underline-offset-4" href={guide.path}>{guide.heading}</a></li>)}<li><a className="underline underline-offset-4" href="/tools">All PDF guides</a></li></ul></nav></>,
 homeAfterTools: <section id="desktop-downloads" aria-label="Desktop downloads" className="mt-8 rounded-xl border border-[#dfe4d6] bg-[#fffefa] p-5 sm:p-6"><h2 className="text-xl font-semibold tracking-tight">Desktop preview</h2><p className={muted+' mt-3'}>{windowsPreview.platform} · {windowsPreview.version} · Unsigned release candidate. Linux and remaining optional engine downloads are not ready.</p><div className="mt-5 flex flex-wrap items-center gap-4"><a className={primary} href={windowsPreview.installerUrl} rel="noreferrer"><Icon name="download" size={17}/>Download Windows preview</a><a className="text-sm text-[#294c3e] underline underline-offset-4" href={windowsPreview.releaseUrl} rel="noreferrer">Release notes &amp; checksums</a></div><p className="mt-4 text-xs leading-6 text-[#677169]">Silent installation and 22 packaged document-operation checks passed. Interactive Windows GUI testing is pending. Windows may show an unrecognized-publisher warning. Use copies of non-sensitive documents for this preview.</p></section>,
};

export function App(){
 const initialTool=typeof window==='undefined'?'':new URLSearchParams(window.location.search).get('tool')||'';
 return <Workspace engine={engine} platform={platform} initialTool={initialTool}/>;
}
