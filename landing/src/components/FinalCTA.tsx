import { LINKS } from "../lib/content";
import { Reveal } from "./ui/Reveal";

export function FinalCTA() {
  return (
    <section className="container-page py-24">
      <Reveal>
        <div className="relative overflow-hidden rounded-3xl border border-brand-400/30 bg-gradient-to-br from-ink-900 to-ink-950 px-6 py-16 text-center shadow-glow">
          <div className="pointer-events-none absolute left-1/2 top-0 h-64 w-[640px] -translate-x-1/2 rounded-full bg-brand-500/20 blur-[100px]" />
          <h2 className="relative text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Your money, in plain language.
          </h2>
          <p className="relative mx-auto mt-4 max-w-xl text-slate-300">
            No forms. No bank login. No spreadsheets. Just open Telegram and tell LodgeOS what happened.
          </p>
          <div className="relative mt-8 flex flex-wrap items-center justify-center gap-3">
            <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="btn-primary">
              Start using LodgeOS →
            </a>
            <a href={LINKS.telegram} target="_blank" rel="noreferrer" className="btn-ghost border-white/20 text-white">
              Join on Telegram
            </a>
            <a href={`mailto:hello@lodgeos.app?subject=LodgeOS%20demo`} className="btn-ghost border-white/20 text-white">
              Book a demo
            </a>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
