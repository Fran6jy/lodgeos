import { TRUST } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function Trust() {
  return (
    <section id="trust" className="border-y border-slate-200 bg-slate-50 py-24 dark:border-white/10 dark:bg-ink-900/40">
      <div className="container-page">
        <SectionHeading
          eyebrow="Built to be trusted"
          title="It’s your money — so it’s engineered like it."
          subtitle="Financial data deserves more than a chatbot. LodgeOS is deterministic, auditable and private by design."
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {TRUST.map((t, i) => (
            <Reveal key={t.title} delay={(i % 3) * 0.07}>
              <div className="card h-full">
                <span className="text-2xl">{t.icon}</span>
                <h3 className="mt-3 font-semibold text-ink-900 dark:text-white">{t.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-400">{t.body}</p>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.2}>
          <p className="mt-10 text-center text-xs text-slate-400">
            We make no regulatory or compliance claims. LodgeOS is an early-stage product — your data, your control.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
