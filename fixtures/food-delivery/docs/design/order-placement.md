# Order placement and restaurant reservation

## Context

Checkout validates the menu item, authorizes payment, creates an order, and then asks the restaurant to accept it. A slow restaurant response should not make a paid checkout look like a failed request.

## Chosen flow: accept, then fulfill asynchronously

We chose asynchronous reservation because the Order Service can record an accepted order without holding the checkout request open for the Restaurant Service. Payment authorization is captured as a separate workflow step; a rejection or timeout moves the order into a visible recovery state. The Order Service then submits the reservation and publishes the accepted order for the Fulfillment Service.

## Alternative: wait for reservation during checkout

A synchronous reservation could return restaurant acceptance before checkout completes, but a slow restaurant would hold the customer request open and make retries harder to distinguish from new orders.

## Consequences

The customer sees an accepted order before restaurant confirmation. The status model distinguishes accepted, awaiting restaurant, confirmed, and rejected states.
