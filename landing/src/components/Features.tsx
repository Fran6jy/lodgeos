import { motion } from "framer-motion";
import { FEATURES } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function Features() {
  return (
    <section id="features" className="border-y border-slate-200 bg-slate-50 py-24 dark:border-white/10 dark:bg-ink-900/40">
      <div className="container-page">
        <SectionHeading
          eyebrow="Everything included"
          title="A full finance toolkit, all in chat"
          subtitle="No upsells, no add-ons. Every feature works the moment you start talking to LodgeOS."
        />

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={(i % 4) * 0.06}>
              <motion.div
                whileHover={{ y: -6 }}
                transition={{ type: "spring", stiffness: 300, damping: 20 }}
                className="card group h-full hover:border-brand-400/50"
              >
                <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-500/10 text-2xl transition group-hover:scale-110">
                  {f.icon}
                </span>
                <h3 className="mt-4 text-base font-semibold text-ink-900 dark:text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">{f.body}</p>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
