# API Compatibility Report

**✅ BACKWARD COMPATIBLE**

- Base: `superdocs-old.json` — Universal Document AI API v2.0.0 (65 paths)
- Revision: `superdocs-new.json` — Universal Document AI API v2.0.0 (77 paths)
- Generated: 2026-08-24T05:27:19+00:00

**0 breaking**, 0 warning, 32 safe (32 total changes).

> ⚠️ Both specs declare version **2.0.0**, yet the contract changed (32 differences). The version string alone does not signal compatibility — this diff does.

## Breaking changes

_none_


## Safe / additive changes

| Change | Endpoint | Detail |
|---|---|---|
| `api-schema-removed` | `` | removed the schema `RenameDocumentRequest` |
| `endpoint-added` | `GET /.well-known/api-catalog` | endpoint added |
| `endpoint-added` | `GET /.well-known/mcp-server-card` | endpoint added |
| `endpoint-added` | `GET /.well-known/mcp.json` | endpoint added |
| `endpoint-added` | `POST /v1/agents/adopt` | endpoint added |
| `endpoint-added` | `GET /v1/agents/adopt-info` | endpoint added |
| `endpoint-added` | `GET /v1/agents/challenge` | endpoint added |
| `endpoint-added` | `POST /v1/agents/handoff` | endpoint added |
| `endpoint-added` | `POST /v1/agents/request-upgrade` | endpoint added |
| `endpoint-added` | `POST /v1/agents/signup` | endpoint added |
| `endpoint-added` | `GET /v1/agents/whoami` | endpoint added |
| `new-optional-request-property` | `POST /v1/chat` | added the new optional request property `deleted_part_chunk_ids` |
| `new-optional-request-property` | `POST /v1/chat` | added the new optional request property `touched_chunk_ids` |
| `response-optional-property-added` | `POST /v1/chat` | added the optional property `hint` to the response with the `200` status |
| `new-optional-request-property` | `POST /v1/chat/async` | added the new optional request property `deleted_part_chunk_ids` |
| `new-optional-request-property` | `POST /v1/chat/async` | added the new optional request property `touched_chunk_ids` |
| `new-optional-request-property` | `POST /v1/documents/export` | added the new optional request property `options/fidelity` |
| `new-optional-request-property` | `POST /v1/documents/export` | added the new optional request property `source_filename` |
| `new-optional-request-property` | `POST /v1/documents/export/email-request` | added the new optional request property `source_filename` |
| `endpoint-added` | `POST /v1/documents/images/upload-base64` | endpoint added |
| `new-optional-request-property` | `PATCH /v1/documents/{document_id}` | added the new optional request property `base_parts` |
| `new-optional-request-property` | `PATCH /v1/documents/{document_id}` | added the new optional request property `parts` |
| `request-property-became-optional` | `PATCH /v1/documents/{document_id}` | the request property `title` became optional |
| `request-property-list-of-types-widened` | `PATCH /v1/documents/{document_id}` | request property `title` list-of-types was widened by adding types `null` to media type `application/json` |
| `request-property-min-length-decreased` | `PATCH /v1/documents/{document_id}` | the `title` request property's minLength was decreased from `1` to `0` |
| `new-optional-request-property` | `POST /v1/downloads` | added the new optional request property `options/fidelity` |
| `endpoint-added` | `POST /v1/limits/increase-request` | endpoint added |
| `new-optional-request-property` | `POST /v1/sessions/{session_id}/documents/{document_id}/save` | added the new optional request property `deleted_part_chunk_ids` |
| `new-optional-request-property` | `POST /v1/sessions/{session_id}/documents/{document_id}/save` | added the new optional request property `touched_chunk_ids` |
| `new-optional-request-property` | `POST /v1/sessions/{session_id}/documents/{document_id}/unarchive` | added the new optional request property `anyOf[subschema #1: SaveDocumentRequest]/deleted_part_chunk_ids` |
| `new-optional-request-property` | `POST /v1/sessions/{session_id}/documents/{document_id}/unarchive` | added the new optional request property `anyOf[subschema #1: SaveDocumentRequest]/touched_chunk_ids` |
| `response-optional-property-added` | `POST /v1/uploads/{upload_id}/process` | added the optional property `warnings` to the response with the `200` status |

