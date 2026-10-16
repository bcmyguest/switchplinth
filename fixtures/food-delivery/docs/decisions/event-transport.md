# Event delivery for food orders

## Context

The Order Service sends accepted orders, cancellations, and courier handoff updates to the Fulfillment Service. The Order Service requires replay of these events after a downstream outage, and the stream must retain ordering per order. Kafka supports replay by resetting a consumer group's offset.

## Decision

We chose Apache Kafka because replay and per-order ordering matter more than reducing broker operations. The Order Service publishes the event stream to Kafka, and the Fulfillment Service consumes it with a durable offset.

## Alternative: managed queue

Amazon SQS would reduce infrastructure work. A dead-letter queue would isolate repeatedly failing messages, but replaying a selected range of historical order events would require additional application support. SQS does not support replay once a consumer deletes a message.

## Consequences

The team operates Kafka and monitors consumer lag. Fulfillment updates remain asynchronous, so the customer interface reads order status from the Order Service rather than inferring completion from event delivery.
