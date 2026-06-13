import { useEffect, useState } from "react";
import { LINKS, NAV_ITEMS } from "../lib/content";
import { useDarkMode } from "../hooks/useDarkMode";

export function Navbar() {
  const { isDark, toggle } = useDarkMode();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all ${
        scrolled
          ? "border-b border-slate-200/70 bg-white/80 backdrop-blur-md dark:border-white/10 dark:bg-ink-950/80"
          : "border-b border-transparent"
      }`}
    >
      <nav className="container-page flex h-16 items-center justify-between" aria-label="Primary">
        <a href="#top" className="flex items-center gap-2 font-bold tracking-tight">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-400 to-emerald-600 text-white">
            L
          </span>
          <span className="text-ink-900 dark:text-white">LodgeOS</span>
        </a>

        <div className="hidden items-center gap-7 md:flex">
          {NAV_ITEMS.map((i) => (
            <a
              key={i.href}
              href={i.href}
              className="text-sm font-medium text-slate-600 transition hover:text-brand-600 dark:text-slate-400 dark:hover:text-brand-300"
            >
              {i.label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggle}
            aria-label="Toggle dark mode"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:text-brand-600 dark:border-white/10 dark:text-slate-400"
          >
            {isDark ? "☀️" : "🌙"}
          </button>
          <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="btn-primary hidden sm:inline-flex">
            Try on Telegram
          </a>
          <button
            className="md:hidden flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10"
            aria-label="Menu"
            onClick={() => setOpen((o) => !o)}
          >
            ☰
          </button>
        </div>
      </nav>

      {open && (
        <div className="border-t border-slate-200 bg-white px-5 py-4 md:hidden dark:border-white/10 dark:bg-ink-950">
          {NAV_ITEMS.map((i) => (
            <a
              key={i.href}
              href={i.href}
              onClick={() => setOpen(false)}
              className="block py-2 text-sm font-medium text-slate-600 dark:text-slate-300"
            >
              {i.label}
            </a>
          ))}
          <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="btn-primary mt-3 w-full">
            Try on Telegram
          </a>
        </div>
      )}
    </header>
  );
}
