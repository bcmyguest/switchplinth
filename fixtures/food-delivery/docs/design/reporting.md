# Reporting data design

## Separate reporting database

The Analytics Service uses a separately provisioned PostgreSQL instance for reporting aggregates. This is the reporting database in the analytics environment; it is physically separate from the PostgreSQL instance owned by the Order Service. The two databases share a product name but have different owners, workloads, and deployment contexts.

The reporting instance receives an asynchronous copy of order events and does not participate in checkout transactions. A reporting outage therefore cannot block order creation.
