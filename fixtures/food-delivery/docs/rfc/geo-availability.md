# RFC: courier and restaurant availability

## Context

Dispatch needs a short-lived view of courier locations and restaurant availability. The source of truth remains in the owning services; the lookup path can be rebuilt after a cache outage.

## Decision

We chose Redis because the dispatch workflow needs a context-specific availability cache whose location entries expire quickly and can be reconstructed from service updates. The cache is a separate instance from the restaurant menu cache.

## Alternative: Reporting PostgreSQL database queries

The Analytics Service's reporting PostgreSQL instance can answer historical availability questions, but it is not the source for live courier assignment.

## Consequences

Dispatch tolerates a cache miss by requesting a fresh location update. Historical analysis stays isolated from live checkout and dispatch reads.
