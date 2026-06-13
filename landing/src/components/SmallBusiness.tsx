import { PERSONAS } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function SmallBusiness() {
  return (
    <section id="business" className="container-page py-24">
      <SectionHeading
        eyebrow="For small business"
        title="Built for people who run their business through messages."
        subtitle="If you already track work in WhatsApp, notes and a shoebox of receipts — LodgeOS is the upgrade that needs zero new habits."
      />

      <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {PERSONAS.map((p, i) => (
          <Reveal key={p.role} delay={(i % 3) * 0.08}>
            <div className="card h-full transition hover:-translate-y-1 hover:border-brand-400/50">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{p.emoji}</span>
                <h3 className="font-semibold text-ink-900 dark:text-white">{p.role}</h3>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-400">{p.scenario}</p>
            </div>
          </Reveal>
        ))}
      </div>

      <Reveal delay={0.2}>
        <div className="mt-12 rounded-2xl border border-brand-400/30 bg-brand-500/5 p-6 text-center">
          <p className="text-lg font-medium text-ink-900 dark:text-white">
            “Did that client pay?” · “What can I claim?” · “How much did Flat 3 cost me?”
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            Separate spaces keep business, personal and each property cleanly apart.
          </p>
        </div>
      </Reveal>
    </section>
  );
}
