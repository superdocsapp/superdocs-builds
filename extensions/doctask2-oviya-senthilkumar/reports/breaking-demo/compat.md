# API Compatibility Report

**❌ BREAKING CHANGES**

- Base: `superdocs-new.json` — Universal Document AI API v2.0.0 (77 paths)
- Revision: `superdocs-breaking.json` — Universal Document AI API v2.0.0 (76 paths)
- Generated: 2026-08-19T12:25:30+00:00

**3 breaking**, 0 warning, 1 safe (4 total changes).

> ⚠️ Both specs declare version **2.0.0**, yet the contract changed (4 differences). The version string alone does not signal compatibility — this diff does.

## Breaking changes

| Change | Endpoint | Detail |
|---|---|---|
| `request-parameter-became-required` | `POST /v1/chat` | the `header` request parameter `authorization` became required |
| `api-path-removed-without-deprecation` | `POST /v1/documents/export` | api path removed without deprecation |
| `request-parameter-type-changed` | `GET /v1/documents/{document_id}` | for the `path` request parameter `document_id`, the `type` was changed from `string` to `integer` |


## Safe / additive changes

| Change | Endpoint | Detail |
|---|---|---|
| `api-version-not-bumped` | `` | a breaking change was detected but the version is still `2.0.0` |

