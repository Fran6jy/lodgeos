import { motion } from "framer-motion";
import { HOW_IT_WORKS } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function HowItWorks() {
  return (
    <section id="how" className="container-page py-24">
      <SectionHeading
        eyebrow="How it works"
        title="Three ways in. One organised ledger out."
        subtitle="However you tell LodgeOS, it extracts the amount, merchant and category — and files it instantly."
      />

      <div className="mt-14 grid gap-6 md:grid-cols-3">
        {HOW_IT_WORKS.map((step, i) => (
          <Reveal key={step.mode} delay={i * 0.1}>
            <div className="card group h-full hover:-translate-y-1 hover:border-brand-400/50 hover:shadow-glow">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500/10 text-xl">
                  {step.icon}
                </span>
                <h3 className="text-lg font-semibold text-ink-900 dark:text-white">{step.mode}</h3>
              </div>

              <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-white/10 dark:bg-ink-950/60">
                <div className="text-slate-700 dark:text-slate-300">{step.input}</div>
                <motion.div
                  initial={{ opacity: 0, x: -8 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.25 + i * 0.1, duration: 0.4 }}
                  className="mt-2 flex items-center gap-2 font-medium text-emerald-500"
                >
                  <span className="text-slate-400">→</span> {step.result}
                </motion.div>
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
