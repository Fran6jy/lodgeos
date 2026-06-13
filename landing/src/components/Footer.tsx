import { LINKS, NAV_ITEMS } from "../lib/content";

export function Footer() {
  return (
    <footer className="border-t border-slate-200 py-12 dark:border-white/10">
      <div className="container-page flex flex-col items-center justify-between gap-6 sm:flex-row">
        <div className="flex items-center gap-2 font-bold">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-brand-400 to-emerald-600 text-white">
            L
          </span>
          <span className="text-ink-900 dark:text-white">LodgeOS</span>
          <span className="ml-2 text-sm font-normal text-slate-500">Your money, in plain language.</span>
        </div>

        <nav className="flex flex-wrap items-center justify-center gap-5 text-sm text-slate-500" aria-label="Footer">
          {NAV_ITEMS.map((i) => (
            <a key={i.href} href={i.href} className="transition hover:text-brand-600 dark:hover:text-brand-300">
              {i.label}
            </a>
          ))}
          <a href={LINKS.github} target="_blank" rel="noreferrer" className="transition hover:text-brand-600 dark:hover:text-brand-300">
            GitHub
          </a>
          <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="transition hover:text-brand-600 dark:hover:text-brand-300">
            Telegram
          </a>
        </nav>
      </div>
      <p className="container-page mt-8 text-center text-xs text-slate-400">
        © {new Date().getFullYear()} LodgeOS. Local-first, privacy-focused, deterministic. Early-stage — no compliance
        claims made.
      </p>
    </footer>
  );
}
