# Platform Engineer, EHR Services

## Team
Clinical Platform

## Role purpose
Build and operate the FHIR-facing services that Meridian clinical applications use to read and write electronic health record data for contracted health systems.

## Responsibilities
- Implement and maintain EHR integration services, including FHIR R4 resources used by inpatient and ambulatory apps.
- Own on-call for EHR connectivity, including vendor downtime playbooks.
- Add contract tests against partner sandbox systems before promoting a mapping change.
- Instrument latency and error budgets for medication, problem-list, and encounter reads.
- Partner with clinical informatics on coding systems (ICD-10, SNOMED, RxNorm) when mappings drift.
- Document interface behavior so implementation specialists can explain it at a go-live.

## Scope and autonomy
You own a defined set of EHR interface services, not the full clinical product. Mapping changes that could alter what a clinician sees require an informatics review. You choose implementation details inside published interface standards. You do not negotiate health-system contracts.

## Leadership and management
No direct reports. You review interface PRs from peers. You do not hire or conduct performance reviews.

## Stakeholders
- Clinical application engineers
- Health informatics analysts
- Implementation specialists at go-live
- Partner EHR vendor technical contacts
- Information security for PHI access patterns
- Your clinical-platform manager

## Requirements
- Production experience with healthcare interoperability or similarly contract-heavy integrations.
- Comfort with FHIR or HL7 concepts and with debugging vendor sandbox failures.
- Discipline around PHI access, audit logs, and least privilege.
- Clear written interface notes for non-engineers who will sit in a hospital IT meeting.
