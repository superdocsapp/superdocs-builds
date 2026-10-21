# Assumptions

1. All demonstration data is synthetic and contains no real employee information.

2. SuperDocs REST API is the primary integration surface.

3. Job-architecture reasoning is implemented in application/domain logic and remains independently testable.

4. SuperDocs is used for document handling, editing, review, templates, multi-document workflows, search, and export.

5. A role may remain unclassified when evidence is insufficient.

6. Job titles alone never determine family or level.

7. Workflow completion does not imply publication.

8. Generated content remains reviewable before becoming final.

9. Dependency propagation must be explicit and measurable.

10. Unrelated profile text must be preserved when canonical level definitions change.

11. The reviewer web API keeps analyzed architecture, framework, and pending review sessions in process memory. Restarting the API requires re-analysis. This is acceptable for the assignment demo and avoids introducing a database.
