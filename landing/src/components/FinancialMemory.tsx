import { MEMORY_EXAMPLES } from "../lib/content";
import { Reveal } from "./ui/Reveal";
import { SectionHeading } from "./ui/SectionHeading";

export function FinancialMemory() {
  return (
    <section id="memory" className="container-page py-24">
      <SectionHeading
        eyebrow="Financial memory"
        title="Ask your finances anything."
        subtitle="Most people can’t answer “how much did I spend at Tesco this year?”. LodgeOS can — instantly, from your own records."
      />

      <div className="mx-auto mt-14 max-w-2xl space-y-4">
        {MEMORY_EXAMPLES.map((ex, i) => (
          <Reveal key={ex.q} delay={i * 0.08}>
            <div className="space-y-2">
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-emerald-500 px-4 py-2.5 text-sm text-white shadow-sm">
                  {ex.q}
                </div>
              </div>
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-ink-900 shadow-sm dark:border-white/10 dark:bg-ink-900 dark:text-white">
                  {ex.a}
                </div>
              </div>
            </div>
          </Reveal>
        ))}
      </div>

      <Reveal delay={0.2}>
        <p className="mt-10 text-center text-sm text-slate-500 dark:text-slate-400">
          Deterministic by design — the numbers come from your ledger, never a guess.
        </p>
      </Reveal>
    </section>
  );
}
