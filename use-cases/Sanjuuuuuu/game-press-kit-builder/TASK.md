\# Game Press Kit Builder — SuperDocs Round 2



\## Objective



Build a Game Press Kit Builder on top of the SuperDocs API.



The tool is intended for indie game developers and PR leads preparing a launch press kit.



\## Assigned Requirements



The builder must produce:



1\. Fact sheet

&#x20;  - Studio

&#x20;  - Release date

&#x20;  - Platforms

&#x20;  - Price

&#x20;  - Availability



2\. Game descriptions in three lengths

&#x20;  - One line

&#x20;  - One paragraph

&#x20;  - Long form



3\. Feature list



4\. History and inspiration section



5\. Verbatim quote block



6\. Awards and coverage list



7\. Asset index

&#x20;  - Screenshot

&#x20;  - Key art

&#x20;  - Trailer still

&#x20;  - Caption

&#x20;  - Credit



8\. Localization

&#x20;  - Generate the complete press kit in another language

&#x20;  - Keep the fact sheet identical

&#x20;  - Keep the asset index identical

&#x20;  - Translate/localize the descriptive content



\## SuperDocs Integration



The application must build on the SuperDocs API.



Core API flow:



1\. Upload document

2\. Send edit instruction

3\. Review proposed changes

4\. Approve changes

5\. Export finished document



Implemented client operations:



\- upload\_document()

\- chat()

\- approve()

\- export\_document()



\## Quality Requirements



The system should:



\- Keep facts consistent across all sections.

\- Ensure the three description lengths express the same information at different levels of detail.

\- Never invent unsupported game facts.

\- Clearly identify information that cannot be verified from the source documents.

\- Keep the asset index synchronized with the actual assets.

\- Keep the fact sheet unchanged during localization.

\- Keep the asset index unchanged during localization.

\- Preserve verbatim quotes exactly.

\- Provide a human review step before irreversible changes.

\- Handle API failures gracefully.

\- Avoid exposing API keys or secrets.

\- Keep operations economical.

\- Provide tests that do not require a live API key.



\## Development Principles



\- Build on SuperDocs; do not build a clone of SuperDocs.

\- Prefer configuration/data over hard-coded rules.

\- Keep the workflow resumable.

\- Save intermediate results.

\- Make important operations idempotent where possible.

\- Validate generated content against extracted facts.

\- Test the system using synthetic game data.



\## Planned Architecture



Input Documents / Assets

&#x20;       |

&#x20;       v

Document \& Asset Ingestion

&#x20;       |

&#x20;       v

Fact Extraction

&#x20;       |

&#x20;       v

Fact Validation

&#x20;       |

&#x20;       v

Press Kit Generation

&#x20;       |

&#x20;       v

SuperDocs Review

&#x20;       |

&#x20;       v

Human Approval

&#x20;       |

&#x20;       v

Localization

&#x20;       |

&#x20;       v

Export



\## Definition of Done



The build is considered complete when:



\- A synthetic game dataset can be processed.

\- A complete English press kit can be generated.

\- The fact sheet contains the required fields.

\- Three description lengths are generated.

\- Features, history, quote, awards and coverage are included.

\- Every supplied asset appears in the asset index.

\- A localized press kit can be generated.

\- The localized fact sheet remains identical to the source fact sheet.

\- The localized asset index remains identical to the source asset index.

\- Human review is demonstrated.

\- The final document can be exported.

\- Tests run without a live SuperDocs API key.

\- README documentation allows another developer to run the project.

