# Mock server

There is no hand-written mock here — that's the point. The mock is **Stoplight
Prism**, run directly from the OpenAPI spec:

```bash
docker run --rm -p 4010:4010 -v "$PWD:/tmp" \
  stoplight/prism:4 mock -h 0.0.0.0 /tmp/specs/superdocs-new.json
```

Prism serves schema-valid example responses for every operation in the spec, so
the generated clients can be smoke-tested with no API key and no live service.
`make all` starts and stops it automatically; `make mock` runs it standalone.
