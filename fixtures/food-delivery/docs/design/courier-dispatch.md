# Courier dispatch runtime

## Context

Courier assignment evaluates a driver's location, vehicle, and current workload. A dispatch attempt must be retried if a worker exits before recording its result.

## Decision

We chose Kubernetes because restarting failed dispatch workers and scaling them during meal-time peaks are operational requirements. Dispatch workers consume order events and write assignment results through the dispatch API.

## Alternative: fixed worker pool backed by Amazon SQS

A fixed worker pool could receive dispatch jobs from an Amazon SQS queue without a long-running broker. The team would still need to coordinate worker restarts and capacity changes separately.

## Consequences

Worker restarts do not lose queued work. Assignment handlers remain idempotent so retries cannot assign the same order twice.
