# Concept 3: Saved People Picker

## One-line description
Once logged in, customers see their family/friends as a grid of avatar chips — tap to select who's coming. Details are saved once and reused forever.

## Why this approach
Jane App's **Family Profiles** are beloved by users precisely because they eliminate re-typing. Research surfaced a common pain point: parents booking recurring kids' appointments re-entered child details every single booking. Mindbody and Vagaro have similar patterns ("Family & Friends" / "Linked Accounts"), though with friction (buried in account settings).

This concept elevates saved people to a **first-class picker at the top of the booking flow** — not a sub-menu, not a dropdown option. The visual metaphor is iOS "tagged contacts" or Messenger's recipient chips: you see faces (or initials), you tap who you mean, you continue.

Inspired by: **Jane App family profiles**, **Apple Family Sharing picker**, **Splitwise group selector**, **iOS message recipients**.

## User flow

```
Customer logs in (or already logged in)
        ↓
Sees service + "Who's coming today?" question
        ↓
Grid of person chips appears: themselves + saved family/friends + "Add someone new"
        ↓
Tap to toggle (multi-select); chips show selected state
        ↓
Below the picker: attendee pills confirm the roster
        ↓
Any attendee missing required details gets a mini inline form    ← CONCEPT 3 NEW
        ↓
Sidebar total updates live (N × price)
        ↓
Continue to payment — dual confirmations to each attendee's saved email
```

## Screens in this concept
- **Booking Widget** — "Who's coming today?" with a 3-column grid of person chips. Each chip shows avatar (initials), name, and relationship tag ("Daughter · age 8"). Selected chips have thick black borders. An "Add someone new" dashed chip sits in the grid and saves the new person for future bookings.

## Requirement coverage

| Req | How this concept addresses it |
|-----|-------------------------------|
| **R1** — "For someone else" toggle | Simply deselect yourself + select another person = proxy booking. No dedicated toggle needed. |
| **R2** — Participant details separate from client | Each saved person carries their own profile (name, email, relationship) separate from the payer's account |
| **R3** — Multi-participant checkout | Multi-select on the chip grid; system creates N bookings in one transaction |
| **R4** — Separate booking records | Each selected chip = one record; records linked to the saved person profile, not the payer |
| **R5** — Separate confirmations | Each saved person has their own email on file → confirmations route automatically |

## Trade-offs

### Pros
- **Fastest repeat-booking experience** in the entire concept set — one tap per attendee, zero typing
- **Visual recognition beats recall** — avatars/names are easier than dropdowns
- **Naturally supports large groups** (team / family) without UI bloat
- **Data reuse** benefits merchant too: richer CRM, fewer duplicate client records
- **Mobile-perfect** — chips stack nicely as 2-column grid on small screens

### Cons
- **First-booking-ever experience is the worst** — empty state ("no saved people yet") requires falling back to a form-based flow
- **Requires account** — guests can't benefit; needs login flow to shine
- **Privacy concern for shared devices** — a logged-in parent's device exposes all linked profile names
- **Unknown people pattern** — booking for a friend-of-a-friend whose details you don't have feels awkward ("Add someone new" works but isn't ideal)

## Design considerations
- **Empty state matters:** the picker becomes a "add your first person" prompt when no one is saved; can optionally default to self-only
- **Chip selection should animate state change** (no motion per B&W rules, but border thickness changes work as hierarchy)
- **Relationship labels help disambiguate** people with similar names (two "Alex"es)
- **Quick-add form** should be a 3-field inline expansion, not a separate modal — keeps users in the flow
- **Smart defaults:** the logged-in user is pre-selected by default; they can deselect to do proxy-only booking
- **Different-times-per-attendee link** appears when count > 1 — opens a split flow (each attendee picks their own slot)
- **Privacy:** relationship labels can be toggled off in account settings for users who find them uncomfortable
