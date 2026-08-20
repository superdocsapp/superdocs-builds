---
title: Circuit provisioning API
docsync:
  covers:
    - api.endpoints
    - api.request_timeout_seconds
    - api.default_bandwidth_mbps
---

# Circuit provisioning API

*Synthetic example document for the docsync extension. Not any real company's
specification.*

The provisioning API is the only supported way to move a signed service order
into the carrier's fulfilment system. It is internal: there is no public
edge for it and there will not be one.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /v1/circuits` | List circuits visible to the calling tenant. |
| `POST /v1/circuits` | Register a circuit from a signed order. |
| `GET /v1/circuits/{circuit_id}` | Fetch one circuit and its current state. |
| `POST /v1/circuits/{circuit_id}/provision` | Hand the circuit to fulfilment. |

Every route is versioned in the path. A route is removed only after two
consecutive releases in which it has served no traffic.

## Timeouts

A single call to the carrier API is given 30 seconds. Past that the call is
abandoned and the job is handed to the retry path rather than being held open,
because the carrier's own gateway closes idle connections at a minute and a
half-open socket is worse than a clean failure.

Clients should set their own timeout above ours, not below it.

## Defaults

When a service order does not name a bandwidth, the circuit is registered at
1000 Mbps. This is a deliberate choice rather than a guess: it is the smallest
tier the carrier will provision without a site survey, so an order that arrives
incomplete still moves.

Per-tenant request volume is capped at 1000 requests per minute. The two
numbers are unrelated and it is unfortunate that they are the same.
