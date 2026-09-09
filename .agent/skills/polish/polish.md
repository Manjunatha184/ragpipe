---
name: impeccable-polish
description: Refines frontend layout, typography, interactions, and spacing to eliminate AI design patterns.
type: command
router: /impeccable polish
---

# Impeccable Polish Playbook

Use this command when the visual direction is correct, but details need strict, high-fidelity refinement. Preserve the page's original purpose while systematically enforcing the specific rules below.

## 1. Classify & Triage
Before modifying code, perform a multi-surface inspection:
- Identify if the target platform surface is Web, iOS, or Android.
- Flag any inconsistent elements that deviate from the local `DESIGN.md` tokens.
- **Web-Only Scope**: Restrict HTML/CSS browser-specific changes from firing against native apps.

## 2. Interaction & Micro-Interaction Discipline
Verify every interactive component meets micro-interaction compliance:
- **Hit Targets**: Every interactive element must have a minimum `40x40px` touch/click area.
- **Concentric Borders**: Enforce nested border radiuses perfectly using the formula: `Outer Radius = Inner Radius + Padding`.
- **Transitions**: Absolutely no `transition: all`. Explicitly define animating properties (e.g., `transition: color 0.2s ease, transform 0.2s ease`).
- **Press States**: Apply active click behaviors (e.g., `scale-on-press: 0.96`, never dropping below `0.95`).
- **Icon Animation**: If contextual icons move, restrict properties to `scale (0.25 -> 1)`, `blur (4px -> 0)`, and zero bounce.

## 3. Typography & Spacing Realignment
- **Line Lengths**: Enforce strict max-widths on text components to prevent long, unreadable spans.
- **Text Wrapping**: Use `text-wrap: balance` for headings and `text-wrap: pretty` for body paragraphs.
- **Font Smoothing**: Inject macOS font smoothing (`-webkit-font-smoothing: antialiased`) onto web typography roots.
- **Tabular Numbers**: Ensure numerical columns or changing counters use mono-spaced digits (`font-variant-numeric: tabular-nums`).

## 4. Anti-Slop (AI-ism) Exclusions
Actively detect, remove, and prevent the following 5 common AI habits:
1. **Purple-to-Blue Gradients**: Strip generic fallback linear gradients; substitute flat theme tokens or brand-specific palettes.
2. **Inter Everywhere**: Enforce typography variety from the design system; do not default to standard Inter for everything.
3. **Side-Tab Borders**: Clean up unnecessary double-nested borders inside sidebars or sub-navigation tables.
4. **Dark Glows & Blurs**: Replace heavy, muddy AI-generated dropshadows with clean, layered `shadows-over-borders`.
5. **Icon Overload**: Remove decorative rounded square icons that sit pointlessly above section headers.

## 5. Verification Protocol
Run code adjustments through an automated verification pass:
- Ensure all color modifications strictly satisfy the Muriel `8:1` contrast floor.
- Audit layout changes against shifting thresholds to ensure zero Layout Shift (CLS).
