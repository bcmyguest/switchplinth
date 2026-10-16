# RFC: restaurant and menu reads

## Context

Restaurant availability and menu reads are frequent, while menu changes are less frequent. Checkout still validates the chosen menu item against the current restaurant record.

## Decision

We chose Redis because short-lived menu and availability caches reduce read load while PostgreSQL remains authoritative for restaurant and order records. Cache entries expire quickly and are invalidated when a restaurant changes its menu.

## Considered alternative: relational reads only

PostgreSQL could serve every menu read directly, but peak browse traffic would compete with transactional order writes.

## Consequences

The customer app can briefly display stale availability. Checkout performs an authoritative validation before creating an order.
