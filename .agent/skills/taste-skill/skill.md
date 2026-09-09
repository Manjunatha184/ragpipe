---
name: impeccable-taste
description: Overrides generic AI layout fallbacks with opinionated, premium UI and typography principles.
type: framework
router: /impeccable taste
---

# Impeccable Taste Workflow Instructions

Apply this framework during the initial layout ideation and component architecture phases. Do not design for "average" layouts; enforce high-density, beautifully restrained user interfaces by default.

## 1. Aesthetic Archetype Selection
Before writing code, select one explicit visual archetype based on the product context:
- **Productivity/Utility (e.g., Linear, Cron)**: High density, monospaced accents, razor-thin borders, subtle shortcuts, extreme keyboard-navigable focus.
- **Developer/Technical (e.g., Vercel, Supabase)**: Dark mode optimization, high-contrast syntax highlighting, neon terminal glow accents, tabular numeric columns.
- **Editorial/Brand (e.g., Apple, Stripe)**: Large fluid typography, deep asymmetric negative space, high-fidelity imagery masks, premium scroll-driven transitions.

## 2. Layout & Proportional Restraint
- **The 60-30-10 Rule**: Enforce spatial hierarchy. Use 60% negative space/background canvas, 30% structural components/cards, and only 10% focal point highlights.
- **Asymmetry**: Avoid rigid, perfectly symmetrical grids for marketing copy. Shift content blocks slightly off-center to create visual interest.
- **Borders over Shadows**: In light mode, separate containers using soft, translucent borders (`rgba(0,0,0,0.06)`) instead of heavy box-shadows. 
- **High-Density Data**: For data surfaces, opt for compact tables with crisp borders and minimal padding rather than card grids that waste screen real estate.

## 3. Typography & Type Hierarchy
- **System Fonts over Clichés**: Never fall back to Inter by default. Use premium system font stacks:
  - *macOS*: San Francisco (`-apple-system`)
  - *Windows*: Segoe UI
  - *Technical*: SF Mono, JetBrains Mono, or Geist Mono
- **Visual Weight**: Drive contrast through extreme weights rather than size inflation. Pair a massive `font-weight: 800` heading with a small, crisp `font-weight: 500` subtext.
- **Tracking (Letter Spacing)**: Apply a slight negative letter-spacing (`letter-spacing: -0.02em`) to headers above 24px to lock the characters together cleanly.

## 4. Color & Contrast Sophistication
- **Sophisticated Grays**: Ban pure `#000000` backgrounds and pure `#111111` cards. Use zinc, slate, or custom-tinted grays (e.g., adding 2% blue or amber into the gray mix to give it temperature).
- **Monochrome Defaults**: Keep interactive states (buttons, tabs) strictly monochrome (black, white, or deep gray). Reservce primary accent colors exclusively for crucial user actions or status indicators.
- **Subtle Gradients**: If gradients are requested, they must span across highly narrow hues (e.g., deep charcoal to midnight blue), mimicking real-world lighting rather than vibrant rainbows.

## 5. Composition Execution Check
Before outputting code, verify against the "Taste Audit":
1. Are there decorative items present that serve no functional or structural layout purpose? (If yes, delete them).
2. Is the hierarchy flat, or does one dominant element immediately capture attention?
3. Does the interface breathe? If padding feels tight, increase it by exactly 1.5x.
