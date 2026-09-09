---
target: Ragpipe dashboard
total_score: 19
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
timestamp: 2026-09-09T07-20-54Z
slug: frontend-src-app-tsx
---
Method: dual-agent (A: /root/design_review · B: /root/evidence)

The dark visual direction fits Ragpipe. The biggest weakness is that the dashboard looks more operationally complete than its workflows are. Prioritize trust, accessibility and investigation before visual polish.

Heuristic assessment: 19/40 (Poor; source-informed, all ten applicable).
| Heuristic | Score / 4 | Main gap |
|---|---:|---|
| System status | 1 | Unknown data appears connected or zero |
| Real-world language | 2 | JSON and configuration jargon |
| User control | 2 | No filter reset or shareable views |
| Consistency | 3 | Shared patterns; inconsistent labels |
| Error prevention | 2 | Minimal source validation |
| Recognition | 2 | Metadata fields must be recalled |
| Efficiency | 1 | No sorting or run expansion |
| Minimalist design | 2 | Equal metric emphasis, tiny text |
| Error recovery | 2 | Generic failures and empty results |
| Help | 2 | Developer help substitutes for operator guidance |

What works: four task areas match the product; graphite surfaces, low radii and restrained motion fit an operations console; reusable components and real API data provide a good base. Domain content is specific, but equal metric cards, colored icon boxes and the hardcoded M avatar make the composition feel interchangeable.

1. [P1] Make operational status trustworthy. App.tsx renders API connected before the first response, absent metrics as zero, and loading history as empty. api.ts couples four requests through Promise.all, so one failure becomes a blanket API failure. Separate checking, loaded, empty, stale and unavailable states. Make latest outcome, running/failed counts and freshness the overview's primary signal. Command: $impeccable harden.

2. [P1] Repair accessibility and reading comfort. Below 480px, App.css hides navigation text while icons are aria-hidden, leaving unnamed buttons. Selection lacks programmatic state and asynchronous results lack live announcements. Faint text #596677 against #0f141c measures about 3.16:1, insufficient for the small text used. Preserve navigation labels/names, expose selection, announce results, and increase text contrast and size. Commands: $impeccable audit, $impeccable adapt.

3. [P1] Make metadata filtering usable without JSON. Search requires users to remember keys and syntax. Provide field/value rows mapped to supported metadata matching, optional advanced JSON and reset. Replace nested chunk scrolling with expansion; give zero-result recovery actions. Do not claim filters caused zero results without evidence, invent thresholds, or display server query time absent from the API. Command: $impeccable clarify.

4. [P1] Make failed runs investigable. RunsTable presents static summaries despite the API supplying detailed metrics. Add keyboard-operable expansion, safe failure guidance, sorting and accessible full-source disclosure. Do not expose arbitrary raw errors or internal paths. Command: $impeccable harden.

5. [P2] Finish the synchronization workflow. Changing source type overwrites entered text; validation only checks nonempty input; helper text names an environment variable; completion omits embedding batches. Preserve per-source values, validate source shape, explain approved folders and incremental embedding behavior, and distinguish busy/schema/validation/failure outcomes. Commands: $impeccable clarify, $impeccable harden.

Cognitive load comes from interpretation and recall rather than too many choices. First-time users must know metadata syntax; power operators cannot investigate failed runs; mobile screen-reader users lose navigation names. The reassuring sync-success ending is stronger than the dead-end search and failure states.

Minor fixes: remove the hardcoded avatar; relabel completion rate as success rate; expand Content/Metadata labels; keep freshness visible on mobile; use an opaque header to match the no-glass brief. Finish with $impeccable polish.

Automated evidence: one overused-font warning at frontend/src/index.css:2 for Inter. This is a contextual style signal, not a reason to replace a legible existing font.

Browser evidence: all four screens captured at 1440 and 390 pixels with the real API unavailable (502); outage presentation and hidden mobile labels confirmed. Successful populated states remain source-reviewed, not browser-verified.
