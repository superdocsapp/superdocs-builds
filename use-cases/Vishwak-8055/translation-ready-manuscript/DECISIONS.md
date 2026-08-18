# Engineering decisions

## 1. Conservative terminology extraction

Capitalization alone is insufficient evidence. The extractor uses multiple source signals and a post-provider quality gate. This avoids polluting the reviewer queue with ordinary words.

## 2. Human authority boundary

Only a confirmed term produces an enforceable translation rule. Suggested and rejected terms remain auditable but are not authoritative.

## 3. Chapter-level QA counts

Protected terms are checked at chapter scope because translation can legitimately split or merge paragraphs. Evidence is still localized to source/returned blocks where possible.

## 4. Format adapters instead of pretending universal support

The system declares supported formats and normalizes them into one manuscript model. Unsupported publisher-specific structures are not silently rewritten.

## 5. SuperDocs as an adapter boundary

Business logic does not know REST paths. This makes the SuperDocs transport replaceable and keeps the use case focused on translation preparation and validation.

## 6. Live verification is opt-in

A real SuperDocs credential is never needed for local tests. Live status remains explicitly pending until a real round trip is executed.
