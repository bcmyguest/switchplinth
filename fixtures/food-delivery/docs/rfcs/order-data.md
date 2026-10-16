# RFC: durable order data

## Context

The Order Service writes the authoritative order record. Checkout and cancellation need transactions, while support staff need relational queries by order, restaurant, and delivery status.

## Decision

We selected PostgreSQL because transactional updates and relational support queries are required for order state. Redis remains useful for short-lived menu and courier-location caches, but it is not the authoritative order database.

## Considered alternative: cache-first storage

Redis would provide fast reads for transient data. It does not replace the durable order database or the transactional boundary for checkout.
