# Concept 2: Smart Attendee Stepper

## One-line description
A single `− / +` stepper ("How many are coming?") merges proxy booking and group booking into one unified control — proxy booking is just "1 attendee who isn't me," and any attendee card can be marked "not me."

## Why this approach
Most competitors treat proxy booking and group booking as **two separate features** (Jane has "Family Profiles" + "Group Appointments"; Vagaro has "Family & Friends" + separate group checkout). This creates UI clutter and forces users to learn two mental models. Airbnb, Booking.com, and Eventbrite all converge on a single stepper-based pattern: choose a count, get N forms, done.

By folding both patterns into one stepper:
- **Simpler service settings** — one `max_participants` field controls everything
- **Simpler customer UX** — one number to pick, one way to get forms
- **Natural scaling** — 1 person, 3 friends, parent+2 kids all use the same mechanism

Rooted in: **Airbnb guest picker modal**, **Eventbrite per-attendee forms**, **Fresha's online group checkout**.

## User flow

```
Customer lands on service page
        ↓
Sees single "How many coming?" stepper (defaults to 1)                ← CONCEPT 2 NEW
        ↓
Pick date + time (standard)
        ↓
Participant cards appear inline, one per stepper count                 ← CONCEPT 2 NEW
        ├─ Card 1 has "I'm attending too" checkbox (defaults CHECKED)
        │    └─ Checked: pre-filled from account (payer+attendee)
        │    └─ Unchecked: blank fields (payer only, proxy booking)
        └─ Cards 2+N: per-attendee name/email/phone
        ↓
Sidebar shows running total (N × $price)
        ↓
Continue to payment — one transaction, N booking records, dual confirmations
```

## Screens in this concept
- **Booking Widget** — A bold `− / +` stepper at the top of the flow ("How many are coming?"). As the count rises, participant cards appear inline. Attendee 1 is marked "Payer · You" by default (checkbox to opt out = proxy booking). Each additional attendee gets its own card with a "remove" link.

## Requirement coverage

| Req | How this concept addresses it |
|-----|-------------------------------|
| **R1** — "For someone else" toggle | Implicit in the stepper: leaving count = 1 + unchecking "I'm attending too" = proxy booking |
| **R2** — Participant details separate from client | Each participant card captures name/email/phone independently; payer badge on the one marked "me" |
| **R3** — Multi-participant checkout | **Core control** — the stepper IS this requirement |
| **R4** — Separate booking records | Each card generates a record; cards render with index numbers (1, 2, 3) that map to records |
| **R5** — Separate confirmations | "Appointment goes to them" tag on non-payer cards signals their confirmation routing clearly |

## Trade-offs

### Pros
- **Highest conceptual efficiency** — one control, two jobs. Less to learn, less to ship.
- **Matches proven patterns** — Airbnb/Booking.com users already understand the stepper
- **Scales naturally** — 1 to N participants with no extra UI
- **Progressive disclosure baked in** — when capacity = 1, the stepper is hidden; users see the classic flow
- **Running total in sidebar** gives instant cost feedback as count changes

### Cons
- **Proxy-only booking (count = 1, not me) may feel weird** — the stepper mental model assumes counting people, not switching identities
- **Less explicit than Concept 1** — some users may miss that they can uncheck "I'm attending too" to book for someone else entirely
- **Requires careful copy** — "How many are coming?" is friendly but doesn't hint at proxy booking; needs secondary hint text
- **Doesn't reward repeat customers** — no saved profiles (see Concept 3 for that)

## Design considerations
- Stepper should disable `−` at 1 and `+` at the service's `max_participants` limit, with clear error state when limit hit
- Participant cards should use numbered labels (Attendee 1, 2, 3) + small visual connector to the stepper above
- "Remove" button on non-first cards reduces cognitive load — users feel in control of the roster
- When count = 1 AND "I'm attending too" is checked, the sidebar should read "Just you" instead of "1 attendee"
- Mobile: stepper becomes a horizontal bar; participant cards stack full-width
- When count increases, newly-added cards should scroll into view (smooth-scroll) so users don't lose where they are
