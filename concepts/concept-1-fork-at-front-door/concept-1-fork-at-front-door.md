# Concept 1: Fork at the Front Door

## One-line description
Make "Who is this appointment for?" the **first** question the booking widget asks — a bold binary fork that reshapes the entire flow based on who the booking is for.

## Why this approach
Healthcare-proxy products (Accurx/NHS App, Zocdoc intake) treat the proxy intent as a first-class path. They know that when a parent arrives on the site, they need the flow to recognize that fact immediately — not after they've picked a time. Putting the fork at the start:

- **Eliminates "mode confusion"** — users never second-guess "wait, is this for me or for my kid?" three steps in
- **Prevents wasted effort** — if a parent picks a time only to realize the flow doesn't support proxy booking, the time they chose might not even work for their child
- **Reshapes the rest of the flow** — labels, defaults, and confirmation language all adjust based on the fork choice

Rooted in: **Accurx (NHS) binary toggle at flow start**, **Zocdoc "myself / someone else" entry question**.

## User flow

```
Customer lands on service page
        ↓
Step 1: WHO — Fork (For me / For someone else)     ← CONCEPT 1 NEW
        ↓
   [Fork answer branches the flow]
        ├─ "For me" → Step 2: WHEN (classic date/time)
        │
        └─ "For someone else" → Show participant details form (inline)
                                     ↓
                               Step 2: WHEN (date/time, pre-fitted to participant needs)
        ↓
Step 3: DETAILS (contact info — just the payer's for "me", both for "someone else")
        ↓
Step 4: PAYMENT (receipt to payer; appointment details to participant)
        ↓
Confirmation
```

## Screens in this concept
- **Booking Widget** — Shows the new "Who is this appointment for?" binary fork at the top of the flow. Clicking "For someone else" reveals a participant details form with clear payer-note and "add another participant" affordance.
- **Service Settings** — Merchant toggles "Allow booking for someone else" (new, enables the fork) and "Group booking capacity" (new, supports multi-participant). New "Participant details to collect" section maps to FR-002.

## Requirement coverage

| Req | How this concept addresses it |
|-----|-------------------------------|
| **R1** — "For someone else" toggle in widget | Upgraded from a toggle to a full binary fork (radio-style card) as **Step 1** of the booking flow |
| **R2** — Participant details stored separately | Dedicated participant card with a clear "primary contact" tag; inline payer-note reinforces the role split |
| **R3** — Multi-participant checkout | "+ Add another participant" button appears under the first participant card — scales to N participants |
| **R4** — Separate booking records per participant | Each participant card generates one booking record (implicit — same data model as Concept 2/3) |
| **R5** — Separate confirmations | Payer-note explicitly states "you'll get the receipt, they'll get appointment confirmations" |

## Trade-offs

### Pros
- **Zero ambiguity** — users know from step 1 whose appointment this is
- **Healthcare-native** — matches the mental model of pediatric, therapy, and clinical-intake workflows
- **Cleanest flow for proxy-dominant verticals** (children's services, caregivers)
- **Supports multiple participants naturally** via "+ Add another participant" from day one
- **Fork answer drives ALL subsequent UI** — labels, defaults, email language all reflect the context

### Cons
- **Adds a step for the 80% case** (customers booking for themselves get an extra question)
- **Highest change to existing flow** — adds a new step that was never there
- **Merchants in beauty/fitness verticals may feel it's overkill** for services where proxy booking is rare
- **Requires clear default** (pre-select "For me") to avoid dead-end if user skips the question

## Design considerations
- Pre-select "For me" so returning self-bookers feel zero friction (keyboard/enter advances immediately)
- The fork card should be **visually heavy** to make the decision feel deliberate, but not intimidating
- When "For someone else" is picked, the participant form should **unfurl inline** (not navigate to a new screen) so users don't lose context
- Mobile: stack the two fork options vertically, keep labels short
- Accessibility: use proper radio input semantics; announce the fork choice + its consequence ("now showing participant fields") via ARIA live region
