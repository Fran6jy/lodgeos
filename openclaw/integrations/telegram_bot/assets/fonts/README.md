# Recap poster fonts

Vendored for `charts.monthly_wrapped`:

- **Inter.ttf** — body/labels. SIL Open Font License 1.1 (rsms / Google Fonts).
- **SpaceGrotesk.ttf** — display/hero numerals. SIL Open Font License 1.1
  (Florian Karsten / Google Fonts). Used as a reliably-licensed stand-in for
  Clash Display.

Both are variable fonts; `_wfont` selects weights via named instances
(Regular/Medium/Bold). To use Clash Display instead, drop `ClashDisplay-Bold.ttf`
here — the loader prefers it for display text automatically.
