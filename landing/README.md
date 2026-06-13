# LodgeOS — Landing Page

A modern, interactive marketing site for LodgeOS, built with **React + TypeScript + Tailwind + Framer Motion** (Vite).

The centrepiece is a **live Telegram simulator** — visitors type or tap a suggestion and watch LodgeOS record an expense / answer a question in real time.

## Run

```bash
cd landing
npm install
npm run dev      # http://localhost:5173
```

## Build

```bash
npm run build    # type-checks then bundles to dist/
npm run preview  # serve the production build locally
```

## Structure

```
landing/
├── index.html              # SEO meta, OG tags, JSON-LD, fonts
├── tailwind.config.ts      # brand palette, dark mode (class strategy)
└── src/
    ├── App.tsx             # section composition
    ├── components/
    │   ├── Navbar, Hero, HowItWorks, Comparison, FinancialMemory,
    │   ├── Features, SmallBusiness, Trust, Vision, Testimonials,
    │   ├── FinalCTA, Footer, TelegramSimulator
    │   └── ui/             # Reveal (scroll-in), SectionHeading
    ├── hooks/
    │   ├── useDarkMode.ts  # persisted theme, respects system preference
    │   └── useSimulator.ts # chat state machine for the demo
    └── lib/
        ├── simulator.ts    # deterministic NL engine (parse → classify → respond)
        └── content.ts      # all copy + structured section data
```

## Notes

- **Dark mode** by default (Linear/Vercel aesthetic), with a light toggle.
- **Mobile-first**, accessible (skip link, ARIA live region on the demo, focus states).
- **No fabricated testimonials or compliance claims** — pilot/design-partner placeholders only.
- Telegram CTA points to `t.me/LodgerOS_bot`; update links in `src/lib/content.ts`.

Deploy `dist/` to any static host (Vercel, Netlify, Cloudflare Pages, GitHub Pages).
