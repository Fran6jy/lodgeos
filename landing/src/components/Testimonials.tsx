import { Reveal } from "./ui/Reveal";

export function Testimonials() {
  return (
    <section className="border-t border-slate-200 bg-slate-50 py-20 dark:border-white/10 dark:bg-ink-900/40">
      <div className="container-page">
        <div className="mx-auto grid max-w-3xl gap-5 sm:grid-cols-2">
          <Reveal>
            <div className="card h-full text-center">
              <div className="text-3xl">🚀</div>
              <p className="mt-3 text-lg font-semibold text-ink-900 dark:text-white">Currently onboarding pilot users</p>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                We’re bringing on a small first group across personal and small-business use.
              </p>
            </div>
          </Reveal>
          <Reveal delay={0.1}>
            <div className="card h-full text-center">
              <div className="text-3xl">🤝</div>
              <p className="mt-3 text-lg font-semibold text-ink-900 dark:text-white">Looking for design partners</p>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                Run your finances through messages? Help shape the next domains with us.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
