# Concept 5 (Experimental): Conversational Booking Concierge

## One-line description
Natural-language AI concierge lets customers book by typing or speaking — "book a massage for me and my daughter Saturday morning" — handling identity, count, scheduling, and per-person details through dialogue.

## Why this approach (experimental rationale)
Every other concept (1–4) presents a **structured form** — toggles, steppers, chips, invite lists. Concept 5 inverts the model: **there is no form**. The customer says what they want, and an AI concierge:

1. **Parses intent** — "me and my daughter" → two attendees, one is the payer
2. **Resolves entities** — links "my daughter" to the saved "Maya" profile
3. **Fills gaps** — asks only the questions needed ("Leo has no allergies on file — any notes?")
4. **Updates a draft** — visible in the side panel, editable any time
5. **Confirms and books** — single tap when the draft looks right

This is the **ambitious version** because it solves every pain point the other concepts only partially address:
- **Proxy + group ambiguity** → resolved by natural language ("for me", "for my mom", "for 4 friends")
- **Re-typing details** → resolved by saved profiles + memory across sessions
- **Schedule complexity** → AI suggests times based on history ("your usual slot is 9:30am")
- **Intake forms** → AI asks only what's missing

Expanded scope (beyond requirements):
- AI-suggested attendees based on past bookings
- Family-discount surfacing ("because you booked 3 people, you save $24")
- Voice input support (mobile)
- Memory-based offers ("same as last month?")

All expansions respect the core requirements (R1–R5) — the concierge is a *layer on top of* the booking primitives, not a replacement.

Inspired by: **Claude/ChatGPT chat UIs**, **Klarna AI shopping assistant**, **Booking.com AI trip planner**, **Google Duplex voice booking**, **Intercom/Airbnb chatbot concierges**.

## User flow

```
Customer lands → ConcierSe greets with suggested prompts
        ↓
Customer types OR picks a prompt chip:
  "Book the group session for me, Maya and Leo Saturday morning"
        ↓
Concierge parses:
  ├─ service: group session
  ├─ when: next Saturday 9:30
  ├─ attendees: Carlos (payer), Maya (daughter), Leo (son)
  └─ suggests draft booking inline (attendees checklist + price)
        ↓
Customer can:
  ├─ Tap "Looks good, book it" → done
  ├─ Type refinement: "add my wife Dana too"
  ├─ Tap suggested chip: "Change time"
  └─ Type "actually I can't make it, just the kids"
        ↓
Concierge reconciles proxy booking automatically:
  ├─ Removes Carlos from attendees
  ├─ Keeps Carlos as payer
  └─ Routes confirmations to Maya/Leo's emails
        ↓
Concierge asks only for missing info:
  "Leo has no allergies on file — anything to note?"
        ↓
Customer confirms → booking created
        ↓
All confirmations sent with correct routing (payer receipt + per-attendee notes)
```

## Screens in this concept
- **Booking Widget (Chat)** — A chat interface replacing the form. The concierge greets the customer with chip-prompts, parses natural-language booking requests, and shows a live booking draft in the side panel. Inline cards show suggested attendees as checkboxes + price previews. Quick-prompt bar at the bottom surfaces common patterns. An "escape hatch" link in the side panel ("Prefer the classic form?") lets users switch to Concept 1/2/3-style forms at any time.

## Requirement coverage

| Req | How this concept addresses it |
|-----|-------------------------------|
| **R1** — "For someone else" toggle | Natural language handles all variants: "for me", "for my mom", "for Maya", "for a friend". No UI toggle; intent is parsed from text. |
| **R2** — Participant details separate from client | Concierge links each attendee to their saved profile (or prompts for details); each attendee's data stays separate from payer. |
| **R3** — Multi-participant checkout | "Book for me and Maya and Leo" → single payment, three bookings. Phrasing handles 1 to N attendees naturally. |
| **R4** — Separate booking records | Concierge creates one record per resolved attendee; draft panel shows each record before confirmation. |
| **R5** — Separate confirmations | Concierge confirms routing explicitly in dialogue: "Confirmations will go to Maya's and Leo's emails on file." |

## Experimental / Expanded features

| Feature | Rationale (tied to original problem) |
|---------|--------------------------------------|
| **Memory across sessions** | Reduces repeat-booking friction — "same as last time?" cuts time to ~5 seconds |
| **Voice input** | Accessibility + mobile one-handed booking |
| **AI-suggested attendees** | Addresses the "who should I book for?" question parents face with recurring kids' services |
| **Proactive gap-filling** | Flags missing intake info (allergies, consent) without a mandatory form — only asks what matters |
| **Discount surfacing** | Makes the merchant's family/group pricing visible in context, increasing conversion |
| **Classic-form escape hatch** | Respects users who distrust AI or prefer structured input |

## Trade-offs

### Pros
- **Solves the entire problem in one flow** — identity, count, scheduling, per-person data, confirmations
- **Lowest cognitive load for experienced users** — one sentence books a complex multi-attendee session
- **Accessibility** — voice input removes friction for motor-impairment and mobile users
- **Learns over time** — becomes faster with every booking (memory-based)
- **Differentiator for Wix** — no booking platform competitor currently ships a booking concierge at this depth; SOTA opportunity

### Cons
- **Requires LLM infrastructure** — latency, cost, hallucination risk, prompt-injection vectors
- **Privacy sensitivity** — conversational systems invite over-sharing; need strict PII handling
- **Trust barrier** — first-time users may distrust AI with payment; mitigated by draft-preview-before-confirm
- **Failure modes are harder to debug** — when the AI misunderstands, recovery UX matters more than in forms
- **Localization cost** — natural-language parsing multiplies complexity across languages
- **Regulatory risk** — health-intake-via-chat may not satisfy HIPAA / medical-device rules; may need to fall back to forms for medical flows
- **Overkill for simple self-booking** — a user who just wants "massage, tomorrow, 3pm" may find the chat heavier than a form

## Design considerations
- **Draft-always-visible panel:** the side panel must mirror what the AI thinks is being booked, at every turn — the user should never be surprised at checkout
- **Confirmation gate:** booking never completes silently from chat; always a final "Book it?" confirmation with full summary
- **Escape hatch:** every screen has a "switch to classic form" link — users can bail out at any point and their partial intent should pre-fill the form
- **Suggested chips after every message:** reduces the "blank text box" problem; guides users toward productive inputs
- **Transcript persistence:** chat history is visible to the user and the merchant (for dispute resolution)
- **Medical / consent flows:** when detected (keyword match), concierge should automatically route to the classic intake-form flow (Concept 4-style) to satisfy compliance
- **Mobile-first:** chat UI is already optimized for mobile; side panel collapses into a sticky top bar on small screens
- **Latency expectations:** AI responses should stream character-by-character; loading states must be visible within 300ms
- **Fallback:** if the AI backend is unreachable, the classic form (Concept 1/2/3 style) loads in its place — no dead-end

## Scope honesty (required for experimental concepts)
- **Tech stack:** requires an LLM integration (OpenAI / Anthropic / self-hosted). Existing Wix Bookings does not include this.
- **Budget:** API costs scale with usage; needs cost modeling for free-tier vs. paid-plan Bookings.
- **Timeline:** not a Phase-1 deliverable; realistic shipping as a premium feature in a later phase.
- **Constraints respected:** confirmation is always human-gated (no silent auto-booking); regulated flows fall back to structured forms; classic form remains available at all times.
