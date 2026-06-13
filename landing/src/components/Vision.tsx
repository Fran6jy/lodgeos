import { ARCHITECTURE, ROADMAP } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function Vision() {
  return (
    <section className="container-page py-24">
      <SectionHeading
        eyebrow="The vision"
        title={
          <>
            One engine.{" "}
            <span className="bg-gradient-to-r from-brand-500 to-emerald-400 bg-clip-text text-transparent">
              Many domains.
            </span>
          </>
        }
        subtitle="Finance is the first domain. The same natural-language engine extends — by adding plugins, not rewriting."
      />

      {/* architecture pipeline */}
      <Reveal>
        <div className="mt-12 flex flex-wrap items-center justify-center gap-2 text-sm">
          {ARCHITECTURE.map((step, i) => (
            <span key={step} className="flex items-center gap-2">
              <span className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-medium text-ink-900 dark:border-white/10 dark:bg-ink-900 dark:text-slate-200">
                {step}
              </span>
              {i < ARCHITECTURE.length - 1 && <span className="text-brand-500">→</span>}
            </span>
          ))}
        </div>
      </Reveal>

      {/* roadmap */}
      <div className="mx-auto mt-14 grid max-w-3xl gap-5 sm:grid-cols-2">
        <Reveal>
          <div className="card h-full">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-300">
              Today
            </h3>
            <div className="mt-4 flex flex-wrap gap-2">
              {ROADMAP.today.map((d) => (
                <span key={d} className="rounded-full bg-brand-500/15 px-3 py-1 text-sm font-medium text-brand-700 dark:text-brand-200">
                  {d}
                </span>
              ))}
            </div>
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <div className="card h-full">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Tomorrow</h3>
            <div className="mt-4 flex flex-wrap gap-2">
              {ROADMAP.tomorrow.map((d) => (
                <span key={d} className="rounded-full border border-slate-200 px-3 py-1 text-sm text-slate-600 dark:border-white/10 dark:text-slate-400">
                  {d}
                </span>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
