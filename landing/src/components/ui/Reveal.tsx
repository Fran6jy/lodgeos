import { motion } from "framer-motion";
import { ReactNode } from "react";

type Props = {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
};

/** Fades + slides content in once it scrolls into view. Respects reduced motion. */
export function Reveal({ children, delay = 0, y = 24, className }: Props) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.55, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}
