# Workspace connector overlay

Export the complete `connectors` array from the target Sigma workspace into
`config/connector.workspace.json`. That file is ignored by Git and is read only
by `npm run package:sigma:workspace`; it is never copied into source control.

The overlay shape is:

```json
{
  "connectors": ["replace this array with Sigma-generated connector objects"]
}
```

The packager rejects an empty array, a missing `superdocsapi` link name,
credential-like keys, API-key-looking values, and bearer tokens.
