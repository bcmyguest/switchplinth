# Order service persistence

## Context

Order records require transactions and relational queries.

## Outcome

We selected PostgreSQL for the Order Service. PostgreSQL keeps order updates transactional and supports reporting queries without a separate store.

## Considered alternative

Redis is useful for short lived cache data but does not replace the durable order database.
