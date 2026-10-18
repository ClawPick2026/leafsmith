import type { ComponentChildren } from 'preact';
import { guides, guideIndex, scopeHeading, scopeParagraphs, structuredData, type Guide } from '../shared/discovery.ts';
import { Icon, ThemeToggle, primary, muted } from './workspace.tsx';
import { useTheme } from './theme.ts';
import { usePageMetadata } from './discovery.ts';

const card = 'mt-6 rounded-xl border border-(--pw-line) bg-(--pw-paper) p-5 sm:p-6';
const heading2 = 'text-xl font-semibold tracking-tight';
const link = 'text-(--pw-link) underline underline-offset-4';

function Page({ children }: { children: ComponentChildren }) {
  const [theme, toggleTheme] = useTheme();
  return <div className="min-h-screen bg-(--pw-page) text-(--pw-ink) selection:bg-(--pw-selection) [&_button:not(:disabled)]:cursor-pointer [&_a[href]]:cursor-pointer" style={{fontFamily:'Inter, ui-sans-serif, system-ui, sans-serif'}}>
    <header className="flex h-20 items-center justify-between gap-4 border-b border-(--pw-line) bg-(--pw-paper) px-5 md:px-9"><a href="/" className="flex items-center gap-2.5 text-xl font-semibold tracking-tight"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-(--pw-brand) text-(--pw-on-brand)"><Icon name="pages" size={25}/></span>paperwork<span className="ml-1 hidden rounded border border-(--pw-line-strong) px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-widest text-(--pw-faint) sm:inline">browser edition</span></a><nav aria-label="Main navigation" className="flex items-center gap-5 text-sm"><a className={link} href="/tools">Tool guides</a><ThemeToggle theme={theme} onToggle={toggleTheme}/></nav></header>
    <main className="mx-auto max-w-3xl px-5 py-8 sm:px-8 md:py-12">{children}
      <section aria-labelledby="privacy" className={card}><h2 id="privacy" className={heading2}>{scopeHeading}</h2>{scopeParagraphs.map(text=><p key={text} className={muted+' mt-3'}>{text}</p>)}</section>
    </main>
    <footer className="mx-auto max-w-3xl px-5 pb-10 text-sm text-(--pw-muted) sm:px-8"><a className={link} href="/">Open Paperwork</a> · <a className={link} href="/tools">All tool guides</a></footer>
  </div>;
}

export function GuidePage({ guide }: { guide: Guide }) {
  usePageMetadata({ path: guide.path, title: guide.title, description: guide.description, structuredData: structuredData(guide) });
  return <Page>
    <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{guide.heading}</h1>
    <p className={muted+' mt-4'}>{guide.intro}</p>
    <p className="mt-6"><a className={primary} href={`/?tool=${encodeURIComponent(guide.toolId)}`}><Icon name="arrow" size={17}/>Open this tool</a></p>
    <section aria-labelledby="steps" className={card}><h2 id="steps" className={heading2}>How to use it</h2><ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed">{guide.steps.map(step=><li key={step}>{step}</li>)}</ol></section>
    <section aria-labelledby="limits" className={card}><h2 id="limits" className={heading2}>Limitations</h2><ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed">{guide.limitations.map(limit=><li key={limit}>{limit}</li>)}</ul></section>
    <section aria-labelledby="questions" className={card}><h2 id="questions" className={heading2}>Questions and answers</h2>{guide.faq.map(faq=><div key={faq.question}><h3 className="mt-4 font-semibold">{faq.question}</h3><p className={muted+' mt-1'}>{faq.answer}</p></div>)}</section>
    <nav aria-label="Other tool guides" className="mt-8"><h2 className={heading2}>Other tool guides</h2><ul className="mt-3 flex flex-wrap gap-x-6 gap-y-3 text-sm">{guides.filter(item=>item.path!==guide.path).map(item=><li key={item.path}><a className={link} href={item.path}>{item.heading}</a></li>)}</ul></nav>
  </Page>;
}

export function GuideIndex() {
  usePageMetadata({ path: guideIndex.path, title: guideIndex.title, description: guideIndex.description, structuredData: structuredData() });
  return <Page>
    <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{guideIndex.heading}</h1>
    <p className={muted+' mt-4'}>{guideIndex.intro} You can also <a className={link} href="/">open the workspace</a>.</p>
    {guides.map(guide=><article key={guide.path} className={card}><h2 className={heading2}><a className={link} href={guide.path}>{guide.heading}</a></h2><p className={muted+' mt-2'}>{guide.description}</p></article>)}
  </Page>;
}
