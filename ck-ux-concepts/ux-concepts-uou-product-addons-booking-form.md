# UX Concepts: Product Add-ons in the Booking Form (UoU / Live Site)

**Date:** 2026-03-11
**Focus:** User of User (end client) experience
**Repo context:** `wix-private/bookings-booking-checkout-viewer` — `packages/bookings-form-widget`

---

## Context

Business owners can configure product add-ons per service (admin-side, covered in prior concepts). This document explores how those linked products surface to the **end client** on the live site booking form, so clients can multi-select products and add them to their order alongside the booking.

### Current Booking Form Structure

The booking form uses a two-column layout:

| Left Column (`formWrapper`) | Right Sidebar (`floatingContainer`) |
| :--- | :--- |
| WixForm (Client Details — name, email, phone, message) | BookingDetails (service name, date, time) |
| NumberOfParticipantsDropdown | CouponCheckbox |
| PaymentSelectionContainer | PaymentSummary (Total) |
| IntakeFormSection | AddonsNotification |
| **AddonsDetails** (service add-ons — groups, checkboxes, quantities) | SmsNotification |
| | PolicyDescription |
| | **ButtonsContainer** (Add to Cart, Book Now) |

**Key reference files:**
- `Widget/index.tsx` — main layout (lines 199–299)
- `Widget/AddonsDetails/index.tsx` — current service add-ons rendering
- `Widget/BookingDetails/` — sidebar booking summary
- `Widget/PaymentSummary/` — price total
- `Widget/ButtonsContainer/` — CTA buttons

### Design Constraints

- Products must coexist with existing **service add-ons** (duration/price extras) without confusion
- Selected products must update the **PaymentSummary** total in real time
- The booking form already supports **cart mode** (Add to Cart + Book Now) — products join this flow
- Mobile-first: 60-70% of bookings happen on mobile — must work in single-column layout
- Wix eCommerce checkout already supports mixed Bookings + Stores items — the cart infrastructure exists

---

## Concepts

### Concept 1: Inline Product Cards

**Placement:** Below service add-ons in the left column, as a new section
**Mental model:** "Complete your experience" — curated products paired with the service

Products appear as visual cards with thumbnails, names, prices, and checkboxes. The section is introduced with a heading like "Recommended for your visit" that frames products as helpful suggestions rather than a hard sell. Clients check the products they want; selected items appear in the sidebar total.

**Layout:**
- Section heading: "Recommended for your visit" (or business-customizable)
- Product cards in a 2-column grid (single column on mobile)
- Each card: product image (square thumbnail), name (truncated to 2 lines), price, checkbox
- Optional: quantity selector for applicable products (shown on interaction)
- Selected state: subtle border highlight + checkbox filled

**Interaction:**
- Click anywhere on the card to toggle selection
- PaymentSummary in the sidebar updates instantly with product line items
- On mobile: section scrolls naturally below add-ons — no extra step

**Pros:**
- Visual and browsable — product images drive intent
- Familiar card-based selection pattern from e-commerce
- Clear separation from service add-ons
- Natural scroll position (after add-ons, before submitting)

**Cons:**
- Takes vertical space — 4+ products push the form down
- Cards may feel heavy for services with only 1-2 linked products
- Grid layout requires careful responsive handling

**Architecture note:**
New component `ProductAddons` placed after `AddonsDetails` in `formWrapper`. Reads from a new `productAddons` field in `SlotService` state (populated by a catalog API call keyed on the service's linked product IDs). Selection state managed in `FormState` alongside `selectedAddons`.

---

### Concept 2: Sidebar Product Recommendations

**Placement:** In the right sidebar, between BookingDetails and PaymentSummary
**Mental model:** "Add to your booking" — products are presented alongside booking details as optional extras

Products appear as a compact list inside the sidebar's floating container. Each item shows a small thumbnail, name, price, and a checkbox or add button. Selected products are reflected as line items in the PaymentSummary total below. The sidebar becomes a one-stop summary of everything the client is ordering.

**Layout:**
- Section heading: "Add products" (subtle, same style as "Payment Details")
- Compact list items: small square thumbnail (40×40), product name, price, checkbox/toggle
- Divider between products and PaymentSummary
- Selected products show as line items in PaymentSummary

**Interaction:**
- Click checkbox or the entire row to toggle
- PaymentSummary updates with product line items (name + price per item)
- Total recalculates in real time
- "More details" link on each product → lightweight tooltip or expand for description

**Pros:**
- Products and total are in the same visual zone — instant feedback
- Doesn't add length to the left column (form stays short)
- Sidebar context is natural for "order summary + extras"
- Compact — works well for 1-5 products

**Cons:**
- Sidebar is narrow — limited space for product details/images
- On mobile, sidebar content moves below the form — loses proximity advantage
- Can feel crowded if many products are linked
- Smaller thumbnails reduce visual appeal compared to cards

**Architecture note:**
New component `SidebarProductAddons` placed between `BookingDetails` and `CouponCheckbox` inside `floatingContainer`. Shares selection state with `PaymentSummary` via `FormState`.

---

### Concept 3: Expandable Accordion Section

**Placement:** Below service add-ons in the left column, as a collapsible section
**Mental model:** "Products available with this service" — opt-in discovery, doesn't add visual weight by default

Products are tucked inside a collapsible accordion. The collapsed state shows a summary line: "Products available with this service (3)" with a chevron. Expanding reveals product cards or a list with multi-select. A badge on the section header shows how many products are selected.

**Layout:**
- Collapsed state: section header with product count badge + chevron
- Expanded state: product list/cards with checkboxes
- Selected count badge updates on the header when collapsed
- Subtle animation on expand/collapse

**Interaction:**
- Click header to expand/collapse
- Inside: same card or list selection as Concept 1
- Header badge: "2 selected" when products are chosen and section is collapsed
- PaymentSummary updates regardless of expanded/collapsed state

**Pros:**
- Minimal visual footprint by default — doesn't add form length until expanded
- Progressive disclosure: only clients interested in products see the full list
- Badge provides glanceable selected state even when collapsed
- Works well for both few (1-2) and many (5+) products

**Cons:**
- Collapsed by default means lower discovery — clients may not notice it
- Extra click to see products reduces conversion vs. always-visible
- Accordion pattern is less visually engaging than cards
- Risk of clients completing booking without noticing the section

**Architecture note:**
Same as Concept 1 (`ProductAddons` after `AddonsDetails`), but wrapped in an accordion container. Collapsed/expanded state in local component state. The section can be configured to start expanded by default (business setting) to improve discovery.

---

### Concept 4: Step-based Upsell

**Placement:** Dedicated full-width step between form completion and checkout
**Mental model:** "Enhance your visit" — a focused moment to browse products before paying

The booking flow is divided into three explicit steps via a progress indicator: 1) Details (form + service add-ons), 2) Enhance (product selection), 3) Checkout. After completing the form, the client advances to a full-width product grid with larger cards and a "Skip this step" option. A running selected summary shows count and total. This mirrors the "extras" step used by airline and hotel booking platforms.

**Layout:**
- Step indicator bar at the top: Details → Enhance → Checkout
- Full-width 4-column product grid (2-column on mobile)
- Each card: large image, name, price, checkbox, quantity selector when selected
- Bottom bar: "Skip this step" link + selected summary + Continue button
- Payment sidebar visible in Step 1 and Step 3

**Interaction:**
- Click "Continue" on Step 1 to reach product step
- Click cards to select/deselect; quantity controls appear on selection
- "Skip this step" jumps straight to checkout
- Step indicators are clickable — user can navigate back

**Pros:**
- Dedicated attention to products — no competition with form fields
- Larger cards with more breathing room than inline placement
- Clear opt-in: users who don't want products can skip instantly
- Progress indicator provides a sense of structure and completion
- Full-width layout works equally well on desktop and mobile

**Cons:**
- Adds a step to the flow — increases time to book
- Users who skip may never see products
- Step-based flow feels heavier for simple bookings
- Requires managing step state and back navigation

**Architecture note:**
New step management layer wrapping the existing form. `BookingFormSteps` component manages `currentStep` state and conditionally renders form, products, and checkout. URL-based step tracking (query param or hash) for browser back support.

---

### Concept 5: Floating Bottom Drawer

**Placement:** Persistent floating button at the bottom of the page; opens a slide-up drawer
**Mental model:** "Tap to browse products" — always accessible without taking form space

A floating pill-shaped button sits at the bottom of the screen: "Add spa products". Tapping it opens a drawer that slides up from the bottom with a product list. Products can be selected, quantities adjusted, and the drawer closed. The trigger button updates to show the count of selected products. The form itself stays completely clean.

**Layout:**
- Form renders normally with no product section visible
- Floating trigger: dark pill button with icon + text + badge
- Drawer: slides up with drag handle, title, close button, product list
- Each product row: checkbox, thumbnail (56×56), name, price, quantity controls
- Semi-transparent overlay behind drawer

**Interaction:**
- Click floating button to open drawer; click overlay or close button to dismiss
- Click product row to toggle selection; quantity controls appear inline
- Trigger button text updates: "Add spa products" → "2 products added" with badge
- Sidebar payment summary updates in real time even while drawer is closed

**Pros:**
- Zero impact on form layout — form stays as short as before
- Always accessible from any scroll position
- Mobile-native pattern (bottom sheet) — intuitive on phones
- Floating button creates curiosity / affordance to explore
- Badge provides glanceable state

**Cons:**
- Products are hidden by default — requires a tap to discover
- Drawer pattern may feel disconnected from the booking flow
- Floating button could overlap with other sticky elements
- Users may not associate the button with the booking
- Less visual product presentation than cards (list view in drawer)

**Architecture note:**
New `ProductDrawer` component rendered at page level (outside form layout). Uses a portal for the overlay and drawer. Trigger button positioned fixed. Shares selection state with `PaymentSummary` via context/store.

---

### Concept 6: Horizontal Carousel

**Placement:** Below service add-ons in the left column, as a scrollable horizontal strip
**Mental model:** "Swipe to discover products" — compact and browsable

Products appear as a horizontally scrollable row of compact cards with arrow navigation. This takes minimal vertical space while still showing visual product cards with images. Selected products appear as removable pill chips below the carousel, providing a clear summary of what's been added.

**Layout:**
- Section heading: "Recommended for your visit" with left/right arrow buttons
- Horizontal scrollable track: compact product cards (~160px wide)
- Each card: square image, name (2-line clamp), price, checkbox overlay, quantity controls
- Below carousel: selected product pills with thumbnail, name, quantity, and remove (✕) button

**Interaction:**
- Click arrows or swipe to scroll through products
- Click card to toggle selection; quantity counter appears in card
- Selected products appear as pills below — click ✕ to remove
- Sidebar payment summary updates in real time

**Pros:**
- Minimal vertical footprint — barely increases form length
- Visual cards with images maintain product appeal
- Arrow navigation is familiar and accessible
- Selected pills provide clear, always-visible summary of choices
- Works well for any number of products (scrolls naturally)
- Mobile: natural swipe gesture

**Cons:**
- Only ~3 products visible at once — others require scrolling
- Smaller cards mean less room for product details
- Users may not realize there are more products to scroll to
- Carousel pattern has known discoverability issues on desktop

**Architecture note:**
New `ProductCarousel` component after `AddonsDetails`. Uses CSS `overflow-x: auto` on the track with `scroll-snap-align` for card alignment. Arrow buttons control `scrollLeft` programmatically. Selected pills rendered in a flex-wrap container below.

---

## Comparative Analysis

| Dimension | C1: Inline Cards | C2: Sidebar | C3: Product List | C4: Step Upsell | C5: Bottom Drawer | C6: Carousel |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Discovery** | High | Medium | Low | Medium (own step) | Low (hidden) | Medium |
| **Visual appeal** | High | Low | Medium | Highest (full-width) | Medium (drawer list) | Medium-High |
| **Form length impact** | High | None | None → High | None (separate step) | None | Low |
| **Mobile behavior** | Good | Weak | Good | Good | Best (native sheet) | Good (swipe) |
| **Best for** | 2-4 products | 1-3 products | 3+ products | 3+ products, premium | Any count | 4+ products |
| **Conversion potential** | Highest | Medium | Lowest | High | Medium-Low | Medium |
| **Implementation effort** | Medium | Medium | Medium-Low | Medium-High | Medium | Medium |

| Dimension | C1: Inline Cards | C2: Sidebar | C3: Accordion |
| :--- | :--- | :--- | :--- |
| **Discovery** | High — always visible with images | Medium — visible but small | Low — collapsed by default |
| **Visual appeal** | High — product images drive intent | Low — small thumbnails, compact | Medium — good when expanded |
| **Form length impact** | High — adds vertical space | None — uses sidebar | None when collapsed, High when expanded |
| **Mobile behavior** | Good — cards stack naturally | Weak — sidebar moves to bottom | Good — collapsed saves space |
| **Best for** | 2-4 products, image-driven items | 1-3 products, subtle upsell | 3+ products, opt-in exploration |
| **Conversion potential** | Highest | Medium | Lowest |
| **Implementation effort** | Medium | Medium | Medium-Low |

---

## Recommendation

**Concept 1 (Inline Product Cards)** is the strongest default for V1 — it maximizes discovery and conversion through visual product presentation. The "extras step after service selection" pattern is used by 83% of booking platforms studied (see prior research). Paired with real-time sidebar total updates, it creates a natural "see products → select → see updated total → book" flow.

**Concept 4 (Step-based Upsell)** is the best option for businesses with premium products or 3+ linked items — the dedicated step gives products a focused moment without cluttering the form. Good for spa/salon/wellness where the "enhance your visit" framing resonates.

**Concept 6 (Horizontal Carousel)** strikes the best balance between discovery and form length — products are visible and visual but take minimal vertical space. The selected pills below provide a clear summary. Good default for businesses that want products visible but not dominant.

**Concept 2 (Sidebar)** is a strong alternative for businesses with 1-2 products or where minimizing form length is critical. Could be offered as a layout setting.

**Concept 5 (Bottom Drawer)** is the most mobile-native option and keeps the form entirely clean. Best suited for mobile-first businesses or when products are truly optional. The floating trigger ensures discoverability without form disruption.

**Concept 3 (Product List)** is the safest option for not disrupting the existing flow, but risks low product discovery. Recommended only if the list defaults to visible.

### Mobile Considerations

On mobile, the form collapses to a single column with the sidebar content stacking below the form. For all concepts:
- Product section should appear **before** the Book Now button (not after)
- Cards should stack to single column
- Thumbnails should be sized appropriately (not too small to tap)
- Selected products count badge should be visible near the CTA

---

## Edge Cases to Consider

1. **No products linked** — Section doesn't render (same as AddonsDetails when no add-ons)
2. **All products out of stock** — Section hidden, or shows with "Currently unavailable" state
3. **Product goes out of stock mid-form** — Disable the product card, show tooltip on hover
4. **Product with variants** (size/color) — Card shows "Select options" → opens variant picker modal
5. **Many products (10+)** — Show first 4-6, "Show all products" expand link
6. **Products + service add-ons both present** — Clear visual separation between sections
7. **Pricing plan selected** — Products should still be available (paid separately from plan credits)
8. **Cart mode** — Selected products added to cart alongside the booking
9. **Product image missing** — Show placeholder icon (shopping bag)
10. **Long product names** — Truncate to 2 lines with ellipsis, full name in tooltip

---

## Payment Summary Integration

When products are selected, the PaymentSummary should update to show:

```
Payment Details
────────────────────────────
Massage Therapy          $75
Relaxation Oil           $24
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
Total                    $99
```

If a discount is configured for the product-service bundle:

```
Payment Details
────────────────────────────
Massage Therapy          $75
Relaxation Oil     $24  $19
                     20% off
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
Total                    $94
```

---

## Open Questions

1. **Should the product section be visible before or after the client fills in their details?** Currently, AddonsDetails renders regardless of form fill state. Products could follow the same pattern, or be revealed after basic details are filled (to reduce initial cognitive load).

2. **Can the business owner control the section title?** e.g. "Recommended products" vs. "Complete your look" vs. custom text. This could be a setting in the service form.

3. **Quantity selectors?** Should all products support quantity, or only specific ones? The current service add-ons model has per-group quantity limits. Products could use their Store inventory as the natural limit.

4. **Should product selection persist if the client navigates back and returns?** Form state should maintain selections, but what about across sessions (logged-in users)?

5. **Interaction with existing upsellPlugin?** The repo has a `upsellPlugin` slot placeholder in the CartModal. Product add-ons in the form would be a separate mechanism, but the upsell plugin could show additional recommendations post-add-to-cart.
