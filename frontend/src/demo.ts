import type { Connection, GraphData } from './types'

export const demoGraph: GraphData = {
  entities: [
    { id: 'service-orders', name: 'Orders API', kind: 'service', description: 'Accepts orders and publishes order events.', epistemic_state: 'confirmed', evidence: [{ id: 'e-orders', path: 'services/orders/README.md', heading: 'Overview', passage: 'The Orders API accepts new orders and emits order events.' }] },
    { id: 'technology-kafka', name: 'Apache Kafka', kind: 'technology', description: 'Event streaming platform for domain events.', epistemic_state: 'confirmed', aliases: [{ id: 'a-kafka', name: 'Kafka', confidence: 0.99, epistemic_state: 'confirmed' }], evidence: [{ id: 'e-kafka', path: 'docs/platform.md', heading: 'Event transport', passage: 'Kafka provides durable event replay for consumers recovering from an outage.' }] },
    { id: 'service-fulfillment', name: 'Fulfillment', kind: 'service', description: 'Consumes order events and starts fulfillment workflows.', epistemic_state: 'inferred', confidence: 0.91, evidence: [{ id: 'e-fulfill', path: 'services/fulfillment/README.md', heading: 'Events', passage: 'The service consumes order-created events to begin fulfillment.' }] },
    { id: 'technology-postgres', name: 'PostgreSQL', kind: 'datastore', description: 'Primary transactional store for orders.', epistemic_state: 'confirmed', evidence: [{ id: 'e-db', path: 'docs/decisions/database.md', heading: 'Decision', passage: 'We will use PostgreSQL for transactional order data.' }] },
    { id: 'technology-sqs', name: 'Amazon SQS', kind: 'technology', description: 'Managed queue alternative with lower operational burden.', epistemic_state: 'inferred', confidence: 0.86, evidence: [{ id: 'e-sqs', path: 'docs/decisions/messaging.md', heading: 'Alternatives', passage: 'SQS would reduce infrastructure ownership but changes event replay guarantees.' }] },
    { id: 'technology-dlq', name: 'Dead letter queue', kind: 'queue', description: 'Captures messages after repeated delivery failures.', epistemic_state: 'inferred' },
  ],
  relationships: [
    { id: 'r-publish', from: 'service-orders', to: 'technology-kafka', kind: 'publishes_to', epistemic_state: 'confirmed', confidence: 0.98 },
    { id: 'r-consume', from: 'technology-kafka', to: 'service-fulfillment', kind: 'delivers_to', epistemic_state: 'inferred', confidence: 0.91 },
    { id: 'r-db', from: 'service-orders', to: 'technology-postgres', kind: 'stores_in', epistemic_state: 'confirmed', confidence: 0.99 },
  ],
  decisions: [
    { id: 'decision-messaging', title: 'Choose an event transport', status: 'decided', selected_option: 'option-kafka', context: 'Services need asynchronous delivery with replay for recovery.', evidence: [{ id: 'e-adr-17', path: 'docs/decisions/017-event-transport.md', heading: 'Context', passage: 'We need reliable asynchronous delivery, including replay after downstream outages.' }], options: [
      { id: 'option-kafka', title: 'Kafka', rationale: 'Durable replay and a shared event platform already operated by the team.', evidence: [{ id: 'e-kafka', path: 'docs/decisions/017-event-transport.md', heading: 'Decision', passage: 'We will use Kafka because replay and consumer groups fit recovery needs.' }], delta: { base: 'architecture', operations: [{ op: 'add_relationship', relationship: { id: 'r-publish', from: 'service-orders', to: 'technology-kafka', kind: 'publishes_to' } }] } },
      { id: 'option-sqs', title: 'Amazon SQS', rationale: 'Managed queues reduce operational ownership; replay requires a separate retention strategy.', evidence: [{ id: 'e-sqs', path: 'docs/decisions/017-event-transport.md', heading: 'Alternatives', passage: 'SQS reduces operations but would need additional handling for replay.' }], delta: { base: 'architecture', operations: [{ op: 'remove_relationship', relationship: { id: 'r-publish' }, expect: { exists: true } }, { op: 'remove_entity', entity: { id: 'technology-kafka', kind: 'technology', name: 'Apache Kafka' }, expect: { exists: true } }, { op: 'add_entity', entity: { id: 'technology-sqs', kind: 'technology', name: 'Amazon SQS', description: 'Managed queue alternative with lower operational burden.' } }, { op: 'add_entity', entity: { id: 'technology-dlq', kind: 'queue', name: 'Dead letter queue', description: 'Captures messages after repeated delivery failures.' } }, { op: 'add_relationship', relationship: { id: 'r-sqs-publish', from: 'service-orders', to: 'technology-sqs', kind: 'publishes_to' } }, { op: 'add_relationship', relationship: { id: 'r-sqs-delivery', from: 'technology-sqs', to: 'service-fulfillment', kind: 'delivers_to' } }] } },
    ] },
    { id: 'decision-database', title: 'Select the primary database', status: 'decided', selected_option: 'option-postgres', context: 'Order updates need transactional consistency.', options: [{ id: 'option-postgres', title: 'PostgreSQL', rationale: 'Transactional constraints and familiar operations.' }] },
  ],
}

export const demoConnection: Connection = { id: 'local-dev', name: 'Example local model', provider: 'OpenAI compatible', endpoint: 'http://localhost:1234/v1', model: 'example-model', status: 'demo only' }

demoGraph.claims = [
  { id: 'claim-kafka', subject: 'service-orders', predicate: 'publishes_to', object: 'technology-kafka', epistemic_state: 'inferred', confidence: 0.96, evidence: ['e-kafka'] },
]
demoGraph.aliases = [{ id: 'alias-kafka', entity_id: 'technology-kafka', name: 'Kafka', confidence: 0.99, epistemic_state: 'confirmed', evidence: [{ id: 'e-kafka', path: 'docs/platform.md', heading: 'Event transport', passage: 'Kafka provides durable event replay for consumers recovering from an outage.' }] }]
