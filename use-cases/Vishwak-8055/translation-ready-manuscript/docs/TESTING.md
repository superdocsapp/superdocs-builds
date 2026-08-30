# Testing

## Local verification

```bash
npm run typecheck
npm test
npm run demo
npm run demo:second
npm run verify:all
```

## Test layers

### Unit tests

- parser metadata/chapter extraction
- term quality/evidence verification
- protected-term lifecycle
- alignment
- chunk-level document diff
- packet artifacts
- SuperDocs request construction and double-JSON parsing

### End-to-end deterministic demos

`npm run demo` demonstrates the Alice fixture, including a deliberate protected-term mismatch.

`npm run demo:second` uses a different manuscript with both bad and good returned translations. The good case must have zero findings.

### Live integration

Live SuperDocs access is intentionally not part of the normal test suite because it requires a real credential and can create external document operations. Use the UI's **Check API connection** and **Send packet to SuperDocs** controls for the real round trip.

A live pass must demonstrate:

1. authenticated server-side connection
2. document HTML accepted
3. proposed changes returned
4. human approval/rejection accepted
5. reviewed DOCX export
6. `data-chunk-id` anchors preserved

Never label a mock response as live evidence.
