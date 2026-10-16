# Fictional food delivery platform

## Customer ordering

Customers browse nearby restaurants, place an order, and receive status updates while a courier is assigned. The Order Service owns order state and publishes order lifecycle events to Kafka. The Fulfillment Service consumes those events to coordinate restaurant preparation and courier pickup. In incident recovery, operators can replay an order event range without creating a second order.

## Payments

The Payments Service authorizes a charge before the restaurant accepts an order. Payment state remains owned by the Payments Service; order events carry a payment reference rather than card data.

## Repeated architecture reference

The Orders Service is the same Order Service named in the event delivery decision. It publishes the same order lifecycle stream to Kafka; this is a second description of the existing components, not a second deployment.
