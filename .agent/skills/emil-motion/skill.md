---
name: emil-kowalski-motion
description: Enforces premium micro-interactions, responsive physics, and intentional easing curves.
type: animation-framework
router: /impeccable motion
---

# Emil Kowalski Motion Skill Playbook

Apply these parameters to any component requiring translation, scale changes, page transitions, or layout mutations. Animation must never feel slow or purely decorative; it must feel responsive, physically anchored, and highly intentional.

## 1. Core Easing Emitters & Tokens
Ban generic `ease-in-out` or linear interpolations. Utilize these explicit cubic-bezier parameters based on interaction intent:

- **The Standard Easing (`ease-premium`)**: For general UI movements (drawers, menus, tabs).
  * *CSS*: `cubic-bezier(0.16, 1, 0.3, 1)`
  * *Duration*: `300ms` to `400ms`
- **The Snappy Pop (`ease-pop`)**: For tooltips, dropdowns, and button clicks.
  * *CSS*: `cubic-bezier(0.34, 1.56, 0.64, 1)` (Subtle, controlled overshoot)
  * *Duration*: `150ms` to `200ms`
- **The Out-of-View Exit (`ease-exit`)**: For elements dismissing off-screen.
  * *CSS*: `cubic-bezier(0.7, 0, 0.84, 0)`
  * *Duration*: `150ms`

## 2. Spring Physics Blueprint (Framer Motion / Radix)
When utilizing physics-based engines instead of time-based durations, enforce these strict stiffness/damping constraints:

- **Highly Responsive (Default UI Transitions)**:
  * `stiffness: 400`
  * `damping: 30`
  * `mass: 0.8`
- **Soft Accent (Dialogs / Modals)**:
  * `stiffness: 300`
  * `damping: 28`
- **Micro-Feedback (Button scaling on press)**:
  * `stiffness: 500`
  * `damping: 25`

## 3. Scale & Shift Proportional Constraints
Animations must remain proportional to the container volume. Never scale or translate past these comfort thresholds:

- **Press Down Scaling**: `whileTap={{ scale: 0.97 }}` for large buttons, `scale: 0.95` for small icons. Never dip below `0.95`.
- **Hover Transitions**: Restrict hover scaling to `1.02` max. Rely primarily on subtle background shifting or color transitions rather than massive size morphing.
- **Directional Entrance**: Elements entering the viewport should translate vertically by a maximum of `8px` to `12px` (`translateY`), paired with an opacity fade (`0 -> 1`). Avoid sweeping structural movements.

## 4. Layout Layout-Id (Shared Layouts)
When morphing an active state between two separate elements (e.g., a background bubble shifting across navbar links):
- Enforce `layoutId` matching across target elements.
- Apply a duration threshold scaling rule: layout shifts extending over `400px` screen distance must adaptively slow their time profile to `450ms` to prevent jarring visual jumps.
- Inject a subtle blur filter (`blur(2px) -> blur(0px)`) to mask sub-pixel text rendering artifacts during structural layout mutations.

## 5. Implementation Config Blocks

### Tailwind CSS Extension
```json
{
  "theme": {
    "extend": {
      "transitionTimingFunction": {
        "premium": "cubic-bezier(0.16, 1, 0.3, 1)",
        "pop": "cubic-bezier(0.34, 1.56, 0.64, 1)",
        "exit": "cubic-bezier(0.7, 0, 0.84, 0)"
      },
      "animation": {
        "drawer-in": "slideUp 350ms cubic-bezier(0.16, 1, 0.3, 1)"
      }
    }
  }
}
```

### Framer Motion Presets
```typescript
export const PREMIUM_TRANSITION = {
  type: "spring",
  stiffness: 400,
  damping: 30,
  mass: 0.8
};

export const FADE_IN_UP = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: PREMIUM_TRANSITION
};
```
