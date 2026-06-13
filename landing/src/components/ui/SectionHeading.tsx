import { ReactNode } from "react";
import { Reveal } from "./Reveal";

type Props = {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  center?: boolean;
};

export function SectionHeading({ eyebrow, title, subtitle, center = true }: Props) {
  return (
    <Reveal className={center ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      {eyebrow && <span className="eyebrow mb-4">{eyebrow}</span>}
      <h2 className="mt-3 text-3xl font-bold tracking-tight text-ink-900 dark:text-white sm:text-4xl">
        {title}
      </h2>
      {subtitle && <p className="mt-4 text-lg leading-relaxed text-slate-600 dark:text-slate-400">{subtitle}</p>}
    </Reveal>
  );
}
