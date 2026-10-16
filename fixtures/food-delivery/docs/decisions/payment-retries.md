# Payment retry delivery

## Context

The Payments Service must record authorization outcomes and retry transient provider failures without blocking order placement. The team needs a durable retry queue and an operator-visible dead-letter path.

## Decision

We chose Amazon SQS because managed retries and a dead-letter queue reduce operational work for payment-provider outages. The Payments Service records each authorization attempt before acknowledging the order workflow.

## Alternative: shared event stream

Apache Kafka could carry payment outcomes alongside order lifecycle events, but the payment retry consumer would need separate retry and dead-letter handling.

## Consequences

Payment retries are asynchronous and idempotent by authorization request ID. The service owns reconciliation for messages that reach the dead-letter queue.
