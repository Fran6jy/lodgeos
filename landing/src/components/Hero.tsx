import { motion } from "framer-motion";
import { LINKS } from "../lib/content";
import { TelegramSimulator } from "./TelegramSimulator";

const INPUT_MODES = ["💬 Text", "🎤 Voice", "🧾 Receipt"];

export function Hero() {
  return (
    <section id="hero-demo" className="relative overflow-hidden pt-28 sm:pt-32">
      <div className="bg-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,_black_30%,_transparent_75%)]" />
      <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-brand-500/15 blur-[120px]" />

      <div className="container-page relative grid items-center gap-14 pb-20 lg:grid-cols-2 lg:gap-8">
        <div>
          <motion.span
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="eyebrow"
          >
            ✨ Natural-language record OS · in Telegram
          </motion.span>

          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.05 }}
            className="mt-5 text-4xl font-extrabold leading-[1.08] tracking-tight text-ink-900 dark:text-white sm:text-5xl lg:text-[3.4rem]"
          >
            Stop filling forms.
            <br />
            Just tell LodgeOS{" "}
            <span className="bg-gradient-to-r from-brand-500 to-emerald-400 bg-clip-text text-transparent">
              what happened.
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.12 }}
            className="mt-5 max-w-xl text-lg leading-relaxed text-slate-600 dark:text-slate-400"
          >
            Text it. Say it. Snap it. LodgeOS turns messages, voice notes and receipts into organised financial
            records, budgets, insights and reports — without a single form.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.18 }}
            className="mt-8 flex flex-wrap items-center gap-3"
          >
            <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="btn-primary">
              Try the Telegram bot
              <span aria-hidden>→</span>
            </a>
            <a href="#how" className="btn-ghost">
              ▶ Watch demo
            </a>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="mt-8 flex flex-wrap items-center gap-2 text-sm text-slate-500 dark:text-slate-400"
          >
            <span>No bank login.</span>
            {INPUT_MODES.map((m) => (
              <span key={m} className="rounded-full border border-slate-200 px-2.5 py-1 dark:border-white/10">
                {m}
              </span>
            ))}
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15 }}
        >
          <p className="mb-3 text-center text-xs font-medium uppercase tracking-wider text-slate-400">
            👇 Live demo — type or tap a suggestion
          </p>
          <TelegramSimulator />
        </motion.div>
      </div>
    </section>
  );
}
