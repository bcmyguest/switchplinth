# Event delivery for food orders

## Context

The Order Service sends accepted orders, cancellations, and courier handoff updates to the Fulfillment Service. The stream must retain ordering per order and support replay after a downstream outage.

## Decision

We chose Apache Kafka because replay and per-order ordering matter more than reducing broker operations. The Order Service publishes the event stream to Kafka, and the Fulfillment Service consumes it with a durable offset.

## Alternative: managed queue

Amazon SQS would reduce infrastructure work. A dead-letter queue would isolate repeatedly failing messages, but replaying a selected range of historical order events would require additional application support.

## Consequences

The team operates Kafka and monitors consumer lag. Fulfillment updates remain asynchronous, so the customer interface reads order status from the Order Service rather than inferring completion from event delivery.
