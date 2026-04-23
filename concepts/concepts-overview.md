# UX Concepts Overview // Book on Behalf / Group Booking

**Feature:** Book on Behalf of Someone Else + Multi-Participant Appointments
**Product:** Wix Bookings
**Date:** 2026-04-23
**Baseline:** Current Wix Bookings customer + merchant surfaces (`artifacts/ux/current-product/`)

---

## Problem Statement

Wix Bookings ties every booking to the logged-in client. Two real-world patterns are unsupported:

1. **Proxy booking** — a parent books for a child, a receptionist for a patient, a friend for a friend
2. **Group booking** — multiple participants share a single appointment slot in one transaction

Competitors (Jane App, Mindbody, Fresha, Vagaro) support both; Wix loses SMBs in health, fitness, beauty, education, and childcare verticals. This concept set explores 5 distinct UX approaches to close that gap.

---

## Requirements (from spec + strategy)

### Functional
- **R1 (FR-001):** Enable "Book for someone else" toggle in booking widget (gated by service setting `allow_proxy_booking`)
- **R2 (FR-002):** Capture and store participant details separately from client account (participant = primary contact; client = payer)
- **R3 (FR-003):** Enable multi-participant checkout for appointments (expose `max_participants` for appointment services)
- **R4 (FR-004):** Create separate booking records per participant (each counted toward capacity, each cancellable independently)
- **R5 (FR-005):** Send separate confirmations to each participant + receipt to payer

### Non-functional (highlights)
- Progressive disclosure: feature only visible when service is configured for it (NFR-UX-003)
- Proxy booking ≤ 3 min task completion; group booking N=3 ≤ 4 min (NFR-UX-001/002)
- WCAG 2.1 AA, keyboard navigation, RTL + localization (NFR-A11Y, NFR-LOC)
- Participant data isolation + GDPR consent responsibility (NFR-SEC-001, NFR-LEG-001)

---

## Key Research Insights

(From `artifacts/ux/research/ux-research.md` + discovery material)

- **Jane App is the bar:** "Who is this for?" dropdown on the final booking step + "Book More" for chained multi-family flows. No competitor has matched "Book More."
- **Binary toggle vs. dropdown:** Healthcare products (Accurx/NHS) favor a binary radio at flow start; beauty/fitness products (Jane, Vagaro) favor a dropdown at flow end. Choice depends on how dominant proxy booking is for the vertical.
- **Stepper wins for participant count 1–6:** Airbnb, Booking.com, and Uber all converge on `− / +` steppers; dropdowns feel heavy.
- **Per-attendee data collection can be deferred:** Eventbrite's two-stage flow (buyer now, attendees post-checkout) lifts completion rates.
- **Dual confirmations need different voices:** Payer gets receipt ("You booked X for Y, $Z invoice"); participant gets appointment details ("Your X at [time]"). One template serving both is worse than two.
- **The "empty dropdown" trap:** Vagaro's dropdown is empty until Family & Friends are pre-invited — users complain. First-time UX must gracefully default to "new person" entry, not require setup.

---

## The 5 Concepts

### Concept 1: Fork at the Front Door
A binary "For me / For someone else" radio as the very first step of the booking widget. Rooted in the healthcare-proxy mental model (Accurx, NHS App). **Differentiator:** The proxy intent is treated as a first-class booking path, not an afterthought — reshapes the entire flow based on who it's for.

### Concept 2: Smart Attendee Stepper
A single unified stepper on the booking widget ("How many coming? 1 / 2 / 3…") that reveals repeating participant cards below. Proxy booking is just "1 person who isn't me." Inspired by Airbnb's guest picker + Eventbrite's per-attendee blocks. **Differentiator:** Proxy and group booking merge into one control — no separate feature, no toggle.

### Concept 3: Saved People Picker
A "Who's coming today?" dropdown at the end of the booking flow with saved people profiles, quick-add inline, and "Book More" chaining for multi-person households. Direct heir to Jane App's Family Profiles. **Differentiator:** The only concept that rewards repeat customers by remembering their people — second booking is 3x faster.

### Concept 4: Acting-As Header
A persistent "Booking as: [Me ▼]" chip in the header of the booking widget. Users switch identity context once; the entire flow (form, confirmations, record) reflects that choice without ever asking "who is this for?" Inspired by Mindbody's profile switcher + NHS App's role modes. **Differentiator:** Zero added friction inside the flow — identity switching lives outside the booking funnel entirely.

### Concept 5 (Experimental): Party Builder
The ambitious version. A full "Party Builder" card on the booking widget: add people as chips, assign roles (organizer / attendee / guardian), detect shared emails, preview split-payment options, save party profiles for future bookings. Extends Concept 2's stepper with Phase-2 scope. **Differentiator:** Treats the booking as a party-management task — one interface handles proxy, group, relationships, and split-payment preview in a single ambitious surface. Stretches beyond Phase 1 to show the feature's full potential.

---

## How the Concepts Differ

| Dimension | Concept 1 Fork | Concept 2 Stepper | Concept 3 Saved People | Concept 4 Acting-As | Concept 5 Party Builder |
|-----------|----------------|-------------------|------------------------|---------------------|-------------------------|
| **Entry point for "who is this for?"** | Flow start (radio) | Inline (stepper + cards) | Flow end (dropdown) | Header chip (outside flow) | Card-level (chips + roles) |
| **Proxy + group unified?** | No (different paths) | **Yes** (one stepper) | Partially (add N people) | No (identity-based) | **Yes** (chips handle both) |
| **Rewards repeat customers** | No | No | **Yes** (saved profiles) | Yes (switch & go) | **Yes** (saved parties) |
| **Added friction for self-booking** | +1 step (radio) | None (default 1) | None | None (header only) | None (default 1) |
| **Phase-2 scope included** | No | No | No | No | **Yes** (split pay, roles) |
| **Best for vertical** | Healthcare proxy | General multi-vertical | Beauty / health repeat | Power users (multi-child parents) | Visionary / full-featured |
| **Fidelity to current UI** | Modest change | Small addition | Small addition | Minimal change | Large redesign |

---

**Next:** Each concept is delivered as a working HTML/CSS/JS prototype covering the customer-facing booking widget (schedule → who-is-this-for → form → confirmation) and — where the concept affects the merchant side — the Service Settings and Booking Details panels. Documentation for each concept covers user flow, requirement coverage, and pros/cons.
