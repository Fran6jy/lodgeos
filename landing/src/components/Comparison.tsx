import { COMPARISON } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function Comparison() {
  return (
    <section className="border-y border-slate-200 bg-slate-50 py-24 dark:border-white/10 dark:bg-ink-900/40">
      <div className="container-page">
        <SectionHeading
          eyebrow="Why people switch"
          title="The opposite of a budgeting app"
          subtitle="Budgeting apps make you do the work. LodgeOS does the work for you."
        />

        <div className="mx-auto mt-14 grid max-w-3xl gap-5 sm:grid-cols-2">
          <Reveal>
            <div className="card h-full opacity-90">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                {COMPARISON.traditional.title}
              </h3>
              <ul className="mt-5 space-y-3">
                {COMPARISON.traditional.rows.map((r) => (
                  <li key={r} className="flex items-start gap-3 text-slate-600 dark:text-slate-400">
                    <span className="mt-0.5 text-rose-400">✕</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>

          <Reveal delay={0.1}>
            <div className="card h-full border-brand-400/40 shadow-glow ring-1 ring-brand-400/20">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-300">
                {COMPARISON.lodgeos.title}
              </h3>
              <ul className="mt-5 space-y-3">
                {COMPARISON.lodgeos.rows.map((r) => (
                  <li key={r} className="flex items-start gap-3 text-ink-900 dark:text-white">
                    <span className="mt-0.5 text-emerald-500">✓</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
