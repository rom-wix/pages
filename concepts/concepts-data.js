var CONCEPTS_DATA = {
  "title": "Book on Behalf",
  "concepts": [
    {
      "id": "concept-1-fork-at-front-door",
      "name": "Concept 1: Fork at the Front Door",
      "desc": "Binary 'For me / For someone else' choice as the very first step — healthcare-proxy mental model, zero ambiguity about who the booking is for.",
      "src": "concept-1-fork-at-front-door/booking-widget.html",
      "areas": [
        { "id": "booking-widget", "name": "Booking Widget", "src": "concept-1-fork-at-front-door/booking-widget.html" },
        { "id": "service-settings", "name": "Service Settings", "src": "concept-1-fork-at-front-door/service-settings.html" }
      ]
    },
    {
      "id": "concept-2-smart-attendee-stepper",
      "name": "Concept 2: Smart Attendee Stepper",
      "desc": "A single '− / +' stepper ('How many are coming?') unifies proxy booking and group booking — proxy is just '1 attendee who isn't me.'",
      "src": "concept-2-smart-attendee-stepper/booking-widget.html"
    },
    {
      "id": "concept-3-saved-people-picker",
      "name": "Concept 3: Saved People Picker",
      "desc": "Avatar-chip grid of saved family/friends — tap who's coming, details are remembered forever. Fastest repeat-booking flow.",
      "src": "concept-3-saved-people-picker/booking-widget.html"
    },
    {
      "id": "concept-4-invite-and-fill",
      "name": "Concept 4: Invite-and-Fill",
      "desc": "Payer reserves seats + pays. Each attendee gets a personalized link to fill their own intake details (name, health info, consent). Best for medical/legal flows.",
      "src": "concept-4-invite-and-fill/booking-widget.html"
    },
    {
      "id": "concept-5-conversational-concierge",
      "name": "Concept 5: Conversational Booking Concierge",
      "desc": "EXPERIMENTAL — AI chat understands natural language ('book a massage for me and my daughter Saturday morning') and handles identity, count, scheduling, and per-person details through dialogue.",
      "src": "concept-5-conversational-concierge/booking-widget.html"
    }
  ],
  "existing": {
    "id": "existing-product",
    "name": "Existing Product",
    "desc": "Current Wix Bookings — the baseline all concepts improve upon.",
    "src": "../current-product/screens/booking-widget-schedule.html",
    "areas": [
      { "id": "booking-schedule", "name": "Booking Widget — Schedule", "src": "../current-product/screens/booking-widget-schedule.html" },
      { "id": "booking-form", "name": "Booking Widget — Form", "src": "../current-product/screens/booking-widget-form.html" },
      { "id": "service-settings", "name": "Service Settings", "src": "../current-product/screens/service-settings.html" },
      { "id": "booking-details", "name": "Booking Details", "src": "../current-product/screens/booking-details.html" },
      { "id": "calendar", "name": "Calendar", "src": "../current-product/screens/calendar.html" }
    ]
  }
};
