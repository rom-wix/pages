# Concept 4: Invite-and-Fill

## One-line description
The payer reserves seats and enters only name + email for each attendee — then each attendee receives a personalized link to fill in their own details (health info, consent, preferences) before the session.

## Why this approach
Eventbrite, Luma, and Meetup all use a variation of this pattern for large-group events: the organizer buys N tickets, then each ticketholder fills in their own attendee form via email link. It's the dominant pattern for conferences and ticketed events.

The **clinical / wellness** use case (surfaced strongly in user-voice research) makes this pattern especially valuable:
- Medical intake forms require the **patient's own signature/consent** — not the payer's
- HIPAA/GDPR concerns mean a parent can't legally "attest" for an adult child's health history
- Consent forms need per-person entry

Rather than forcing the payer to impersonate each attendee in the booking form (Concept 1/2/3), this concept splits the responsibility cleanly: **payer pays, attendees fill themselves.**

Inspired by: **Eventbrite per-attendee form links**, **Luma RSVP flow**, **Calendly collective events**, **Typeform / JotForm public intake links**.

## User flow

```
Payer arrives at booking widget
        ↓
Step 1 — RESERVE SEATS
  ├─ Picks number of seats (1-6)
  ├─ Confirms payer identity (pre-filled from account)
  ├─ Optional: "I'm one of the attendees" checkbox
  └─ Enters name + email for each other attendee only    ← CONCEPT 4 NEW
        ↓
Step 2 — PAY
  └─ Standard Stripe/payment flow — seats are reserved immediately
        ↓
Step 3 — INVITES SENT AUTOMATICALLY
  ├─ Each attendee gets: "You're booked for [session]. Fill your details here →"
  ├─ Link opens a personalized intake form (name, health, consent, preferences)
  └─ Payer sees live status in their account: filled / pending / reminder sent
        ↓
Session start
  └─ Merchant sees full details for all attendees who completed intake
```

## Screens in this concept
- **Booking Widget (Step 1)** — a 3-step progress bar at the top (Reserve · Pay · Invite), a seat-count picker (numbered tiles), a payer card pre-filled from account, an "I'm one of the attendees" checkbox (so the payer isn't listed twice), and an invite list where each row has numbered seat + name + email fields. A dashed "How this works" card explains the intake-link mechanic.

## Requirement coverage

| Req | How this concept addresses it |
|-----|-------------------------------|
| **R1** — "For someone else" toggle | Uncheck "I'm one of the attendees" → all seats are invites = pure proxy booking |
| **R2** — Participant details separate from client | Each attendee fills their own full record via their own link — strongest data separation of any concept |
| **R3** — Multi-participant checkout | Seat count + invite list → single payment, multiple bookings |
| **R4** — Separate booking records | Each invite link generates its own record when filled; records stay linked to the payer's master booking |
| **R5** — Separate confirmations | Confirmations go to each attendee's email naturally (they filled it themselves); payer gets a roll-up receipt |

## Trade-offs

### Pros
- **Solves the medical/legal problem** — per-person consent and intake without the payer impersonating attendees
- **Lowest friction at checkout** — payer only types name + email for each attendee
- **Asynchronous data capture** — attendees fill forms at their convenience (before the session)
- **Best for unknown-details scenarios** — booking a friend whose allergies you don't know
- **Scales elegantly for large groups** (team of 6 at a spa, youth group of 12 at a lesson)

### Cons
- **Two-stage completion introduces risk** — what if an attendee never fills their form? Cancel? Proceed without data?
- **More complex merchant UX** — must show "3 of 5 filled" status, send reminder logic
- **Overkill for self-booking** — 80% of bookings are just one person; the 3-step progress is heavy
- **Email deliverability dependency** — if an invite email goes to spam, the attendee never completes intake
- **Requires intake form builder** — merchant needs a new settings area to define what each attendee fills in

## Design considerations
- **Smart defaults:** when `seats = 1` AND "I'm attending" is checked, hide the invite block entirely (becomes the classic self-booking flow)
- **Form status badges** in the payer's account: ◉ Filled / ◉ Pending / ◉ Reminder sent / ◉ Expired
- **Automatic reminders** at 48h and 24h before the session for unfilled invites
- **Fallback option:** payer can "fill on behalf of" any pending invite from their account (used for kids, elderly parents)
- **Merchant settings:** per-service toggle for "requires per-attendee intake?" — if off, the invite step is skipped
- **Grace window:** allow attendees to fill intake up to session-start; late fills generate a merchant notification
- **Link security:** intake links should be single-use tokens that expire after submission (or session-start)
- **Mobile:** the step bar collapses to a horizontal dot indicator; the invite list stacks fully
