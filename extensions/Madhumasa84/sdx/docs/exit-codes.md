# Exit codes

`sdx` reserves stable process exit codes so scripts can branch without parsing prose. Success is reported only after requested local output is verified.

| Code | Meaning |
|---:|---|
| 0 | Successful and verified |
| 2 | Nothing needed changing |
| 3 | Changes or a continuation are waiting for an explicit decision |
| 4 | All proposed changes were explicitly rejected |
| 10 | Invalid input/configuration, incomplete approval decisions, or approval attempted in an invalid job state |
| 20 | Missing/invalid authentication |
| 21 | Rate-limit or quota failure |
| 22 | API transport/terminal job failure, including an ambiguous submission whose remote state requires reconciliation |
| 23 | Upload or local-read failure |
| 24 | Export/local-write failure, including protected existing output |
| 25 | Successful HTTP response with an invalid/unexpected schema |
| 130 | Interrupted by the user; a reported remote job may still run unless cancellation is separately confirmed |

Codes 2–4 are intentional domain outcomes. JSON status/error and process code always describe the same result. Exit 22 does not mean a write is safe to repeat: when `error.details.remoteState` is `unknown`, the ledger blocks automatic resubmission and the message provides reconciliation guidance. Rate-limit errors remain 21 even when a retry budget is exhausted; their details include safe attempt/delay/usage metadata. Exit 130 preserves resumable state and never claims a remote job was cancelled.
