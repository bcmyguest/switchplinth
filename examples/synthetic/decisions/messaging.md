# Event delivery for order processing

## Context

The Order Service sends fulfillment updates to the Fulfillment Service. The team needs durable delivery and a way to replay events after outages.

## Decision

We chose Apache Kafka because replay and ordering across fulfillment events matter more than operating a managed queue. The Order Service publishes order events to Kafka, and the Fulfillment Service consumes them.

## Alternative: managed queue

Amazon SQS would reduce infrastructure work. A dead-letter queue would hold messages after repeated failures, but replaying a selected range of old events would require extra application support.

## Consequences

The team operates Kafka and monitors consumer lag. The decision can be revisited if operational load becomes more important than replay.
