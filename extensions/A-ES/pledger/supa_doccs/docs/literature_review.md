# Literature Review — Agentic Document Intelligence for Microfinance Compliance

**Scope.** This review surveys the literature underpinning a system that ingests a pile of financial documents (loan agreements, modification agreements, repayment statements as PDF/DOCX/plain text), extracts structured facts with source-span provenance, evaluates declarative compliance playbooks, routes findings through a human approval gate, and guarantees checkpointed resumability and concurrent-run isolation. Five themes structure the discussion; each closes by connecting an identified gap to a concrete design choice recorded in `DECISIONS.md`.

---

## 1. Document AI & Information Extraction

Extracting structured facts from financial documents sits between two research traditions. Vision-layout pretraining models such as LayoutLM jointly model text tokens and their 2-D bounding-box coordinates, achieving strong results on scanned forms and receipts [1]; Donut removes the OCR dependency entirely with an end-to-end encoder-decoder over document images [2]. Both lines presuppose layout signal and substantial task-specific training data, which born-digital, text-layer loan documents do not consistently reward. Benchmark work confirms the problem remains open even in narrow business domains: the DocILE benchmark shows information localization and extraction on semi-structured business documents is far from solved, with neither neural nor rule-based baselines dominating across categories [3]. At the parsing layer, Bast and Korzen demonstrate that PDF-to-text tools disagree substantially on line, paragraph, and reading-order reconstruction — meaning upstream extraction inherits parser-dependent noise before any intelligence is applied [4]. Finally, zero-shot LLM extraction promises robustness to lexical variation, but introduces hallucination risk: fabricated or normalized values that look plausible and carry no verifiable anchor [5].

**Gap.** The literature offers either layout-hungry supervised models, opaque end-to-end transformers, or brittle hand-written patterns; there is little guidance on combining them under an auditability constraint, and benchmark comparisons of zero-shot LLM extraction against fine-tuned layout models specifically on financial-contract prose remain scarce [CITATION NEEDED]. Crucially, none of these approaches treats provenance as a first-class output of the extractor.

**Connection to this system.** Our own paraphrase experiment (`DECISIONS.md`, 2026-08-12) reproduced DocILE's lesson locally: regex extractors achieved 100% field coverage on templated documents but collapsed to 17% on naturally reworded equivalents — the combinatorial space of legal phrasing cannot be enumerated. The resolution recorded in `DECISIONS.md` (2026-08-26) is a deliberate hybrid rather than a wholesale bet on either pole: type-specific structured extractors run first for template-mandated formats, and every field they miss is re-extracted by an LLM whose per-field output must include a verbatim quoted span, programmatically located in the source text to compute exact character offsets. Each claim records which strategy produced it (`structured`, `llm_fallback`, or `llm`), so downstream auditing knows how much to trust each fact.

---

## 2. Agentic Pipelines & Workflow Orchestration

Modern LLM agents trace to ReAct, which interleaves chain-of-thought reasoning with tool actions and showed large gains over reasoning- or acting-alone [6]. Multi-agent frameworks such as AutoGen generalize this into conversational programs where agents collaborate through typed message exchanges [7]. These works define *control flow* but leave *durability* undefined: agent state lives in memory, and a crash mid-run loses progress. The durable-execution tradition addresses precisely this. Durable Functions gives stateful serverless workflows replay semantics in which function progress survives process death by construction [8], and the workflow-patterns canon provides the control-flow vocabulary — cancellation, compensation, milestone resume — that long-running pipelines implicitly rely on [9]. Among AI-native frameworks, LangGraph packages these ideas for agents: typed persistent state, checkpointers, conditional edges, and `interrupt()` nodes purpose-built for pausing execution on a human gate [10].

**Gap.** General-purpose durable-execution engines offer rigorous crash semantics but no native AI/HITL abstractions, while AI-native frameworks offer the right abstractions atop runtimes still maturing — early coupling risks inheriting breaking changes in exchange for features the application could own. Little published work validates kill-and-resume behavior for LLM pipelines with property-based tests rather than anecdote.

**Connection to this system.** This tension explains our orchestration split (`README.md`, Architecture Decisions): `langgraph` is installed and `graph.py` compiles a real `StateGraph` with all 13 nodes and conditional edges, keeping the topology first-class, but production runs execute through our own executor, which drives nodes sequentially with PostgreSQL-backed per-node checkpoints — owning the durability contract directly rather than delegating it. Kill-and-resume invariants ("never re-run a completed node's side effects") and concurrent-run isolation (per-run scoping plus optimistic version columns) are enforced by dedicated property and concurrency test suites, mirroring the replay discipline of [8] while remaining portable to LangGraph's runtime checkpointer when needed.

---

## 3. Human-in-the-Loop Systems

Trust calibration theory distinguishes appropriate reliance from overtrust and undertrust, arguing automation interfaces must convey confidence and limits so operators calibrate rather than defer [11]. Horvitz's mixed-initiative principles formalize when a system should act autonomously versus defer to the human [12]. Empirical work sharpens this for AI advice: Buçinca et al. show cognitive forcing functions — prompting the reviewer to form an independent judgment first — reduce overreliance more effectively than adding explanations, which often deepen deference [13]. The interactive-ML tradition frames the human as a continuous participant providing labels, corrections, and supervision throughout a system's life [14], and Microsoft's synthesis of overreliance research identifies presentation of uncertainty and evidence quality as the dominant levers [15].

**Gap.** Most of this literature studies model-development labeling or single-shot advisory interactions; regulated document pipelines instead need *durable, item-level, attributable* approvals embedded in workflow execution state — a pause that survives restarts, produces an immutable record of who decided what and why, and cannot silently duplicate or lose requests. Publication-quality evidence that item-level justification requirements improve downstream reviewer calibration in audit settings is also thin [CITATION NEEDED].

**Connection to this system.** This is why the approval gate is a first-class graph node rather than a UI afterthought: `interrupt()`-style pause points enqueue items into a Postgres-backed `approval_queue`; decisions are written atomically under row locks with a guard trigger enforcing decision-before-status ordering; `reviewer_id` and free-text justification are mandatory; re-entry deduplicates by claim so reviewers are never asked twice; and cross-document contradictions arrive with both source attributions attached — an evidence-presentation choice aimed squarely at calibrated review [13], [15].

---

## 4. RegTech & Compliance Automation

Arner, Barberis, and Buckley chart the shift from manual to technology-mediated regulation, positioning RegTech as the digitization of compliance itself [16]. The engineering lineage runs back to production rule systems: Forgy's RETE algorithm made large condition-action rule bases tractable [17], and formal treatments of business-process compliance established how obligations and prohibitions map onto executable checks [18]. Yet classic rule engines suffer a persistent knowledge-acquisition bottleneck: rules live in code or proprietary formats maintained by engineers, while the source regulations are prose. The regulatory substrate relevant here includes disclosure regimes mandating APR computation and presentation in consumer credit [19], and supervisory guidance warning that opaque algorithmic credit decisions still carry full adverse-action notification obligations — i.e., lenders must be able to explain specific reasons derived from automated systems [20].

**Gap.** Two failure modes bracket the space. Rules-as-code makes compliance auditable but freezes domain experts out — every new clause requires a developer — while leaving the interpretation of natural-language contract language entirely to brittle string matching. Empirical evidence on how interest-rate caps actually perform in microfinance markets — and therefore how a rate-cap rule should behave on edge cases — is contested and jurisdiction-specific [CITATION NEEDED].

**Connection to this system.** This is why compliance rules live entirely in YAML playbooks under `rules/`: adding MF-001 (APR ≤ 36%) or MF-004 (penalty ≤ 5% of outstanding) is a reviewed git diff touching zero `.py` files; a `playbook_id` whitelist makes playbook selection an explicit, auditable per-run parameter; and each rule declares either an LLM evaluator (open-ended language) or a `structured` checker (deterministic numerics) — the same flexibility/rigor layering the RegTech literature calls for but rarely operationalizes [16], [18].

---

## 5. Provenance & Explainability

The W3C PROV data model remains the canonical vocabulary for derivation provenance — entities, activities, and the agents connecting them [21]. Within NLP, the ALCE benchmark evaluates whether LLMs can generate output with accurate supporting citations, finding citation quality lags fluency badly [22]. Post-hoc explainability methods fare worse under scrutiny: LIME popularized local surrogate explanations [23], but Jain and Wallace show attention weights — often presented as rationales — frequently fail to identify what drives predictions, cautioning against treating plausible-looking attributions as evidence [24]. Financial regulators impose stricter demands than academic explainability: the Federal Reserve's model-risk guidance requires documentation sufficient for effective challenge, conceptual soundness review, and reproducible outcomes for models used in supervisory contexts [25].

**Gap.** Provenance research concentrates on citing generated *text* or tracking dataset/model lineage; comparatively little work binds individual *structured fields* extracted from documents to exact source locations under database-enforced integrity, with an append-only event log capturing every mutation in the same transaction. Citation-style "the answer came from somewhere in this document" does not survive an auditor asking *which characters justify this number*.

**Connection to this system.** This is why provenance is schema-enforced rather than convention: every claim references rows in `source_locations` carrying document ID and character-offset spans; `audit_events` are appended in the same transaction as the change they describe; `document_versions` preserves history so deliverables are reconstructible; and the "no silent overwrite" invariant routes contradicting evidence to the approval queue instead of mutating prior findings. LLM-extracted facts implement the citation discipline ALCE measures as lacking: the model must return a verbatim quoted span, which is located exactly (or normalized-matched) in the source; when location fails, the claim survives but is downgraded to `citation_status: "unverifiable"` with its span zeroed — an explicit, queryable admission of unanchored output rather than a plausible-looking citation. This is effective-challenge readiness in the spirit of [25], grounded at span level rather than document level.

---

## Synthesis

Read together, the five literatures describe a fork. On one branch, LLM-agent pipelines [6], [7] offer unmatched tolerance of natural-language variation but ship with hallucination risk [5], weak citation fidelity [22], in-memory state unsuited to long compliance runs [8], and review interactions too shallow to calibrate trust [13]. On the other, rule engines [17], [18] are perfectly auditable yet rigid: they demand that reality phrase itself in the grammar of their patterns — a demand our paraphrase experiments show real documents refuse (17% coverage on reworded text). The architecture of this system occupies the deliberate middle ground. Stochastic components (LLM extraction fallback, LLM rule evaluation) are retained for linguistic reach, but every output they produce is (a) anchored to exact source offsets or explicitly flagged unverifiable, (b) evaluated against declarative YAML playbooks diffable in git, (c) subject to durable, attributable human approval before taking effect, and (d) executed inside a checkpointed, concurrently-isolated run fabric with transactionally-logged mutations. Determinism here is not achieved by eliminating probabilistic machinery but by structurally enclosing it: flexibility at the edges, auditability in the frame. That enclosure — provenance-bearing hybrid extraction, DSL-governed evaluation, interrupt-based HITL, replay-safe orchestration — is the contribution this project claims relative to both poles.

---

## References

[1] Y. Xu, M. Li, L. Cui, S. Huang, F. Wei, and M. Zhou, "LayoutLM: Pre-training of text and layout for document image understanding," in *Proc. 26th ACM SIGKDD Conf. Knowledge Discovery and Data Mining (KDD)*, 2020, pp. 1192–1200.

[2] G. Kim *et al.*, "OCR-free document understanding transformer," in *Proc. European Conf. Computer Vision (ECCV)*, 2022, pp. 498–517.

[3] Š. Šimsa *et al.*, "DocILE benchmark for document information localization and extraction," in *Proc. 61st Annual Meeting of the Association for Computational Linguistics (ACL)*, 2023.

[4] H. Bast and C. Korzen, "A benchmark and evaluation for text extraction from PDF," in *Proc. 14th Int. Conf. Document Analysis and Recognition (ICDAR)*, 2017.

[5] Z. Ji, N. Lee, R. Frieske, T. Yu, D. Su, Y. Xu, E. Ishii, Y. J. Bang, A. Madotto, and P. Fung, "Survey of hallucination in natural language generation," *ACM Computing Surveys*, vol. 55, no. 12, pp. 1–38, 2023.

[6] S. Yao *et al.*, "ReAct: Synergizing reasoning and acting in language models," in *Proc. Int. Conf. Learning Representations (ICLR)*, 2023.

[7] Q. Wu *et al.*, "AutoGen: Enabling next-gen LLM applications via multi-agent conversation," *arXiv preprint arXiv:2308.08155*, 2023.

[8] S. Burckhardt, B. Chandramouli, C. Gilligan, X. Huang, J. Meijer, R. P. Spina, and V. Vuppalapati, "Durable Functions: Semantics for stateful serverless," *Proc. ACM Programming Languages*, vol. 5, no. OOPSLA, 2021.

[9] W. M. P. van der Aalst, A. H. M. ter Hofstede, B. Kiepuszewski, and A. P. Barros, "Workflow patterns," *Distributed and Parallel Databases*, vol. 14, no. 1, pp. 5–51, 2003.

[10] LangChain Inc., "LangGraph documentation," https://langchain-ai.github.io/langgraph/, accessed Aug. 2026.

[11] J. D. Lee and K. A. See, "Trust in automation: Designing for appropriate reliance," *Human Factors*, vol. 46, no. 1, pp. 50–80, 2004.

[12] E. Horvitz, "Principles of mixed-initiative user interfaces," in *Proc. SIGCHI Conf. Human Factors in Computing Systems (CHI)*, 1999, pp. 159–166.

[13] Z. Buçinca, M. B. Malaya, and K. Z. Gajos, "To trust or to think: Cognitive forcing functions can reduce overreliance on AI in AI-assisted decision-making," *Proc. ACM Human-Computer Interaction*, vol. 5, no. CSCW1, 2021.

[14] S. Amershi, M. Cakmak, W. B. Knox, and T. Kulesza, "Power to the people: The role of humans in interactive machine learning," *AI Magazine*, vol. 35, no. 4, pp. 105–120, 2014.

[15] S. Passi and M. Vorvoreanu, "Overreliance on AI: A literature review," Microsoft Research, Redmond, WA, USA, Tech. Rep., 2022.

[16] D. W. Arner, J. Barberis, and R. P. Buckley, "FinTech, RegTech, and the reconceptualization of financial regulation," *Northwestern Journal of International Law & Business*, vol. 37, no. 3, pp. 371–413, 2017.

[17] C. L. Forgy, "Rete: A fast algorithm for the many pattern/many object pattern match problem," *Artificial Intelligence*, vol. 19, no. 1, pp. 17–37, 1982.

[18] G. Governatori and S. Sadiq, "The journey to business process compliance," in *Handbook of Research on Business Process Modeling*. Hershey, PA, USA: IGI Global, 2009, pp. 426–454.

[19] Truth in Lending Act, 15 U.S.C. § 1601 *et seq.*; implementing regulation: Consumer Financial Protection Bureau, "Regulation Z (Truth in Lending)," 12 C.F.R. Part 1026.

[20] Consumer Financial Protection Bureau, "Adverse action notification requirements in connection with credit decisions based on complex algorithms," Circular 2022-03, Washington, DC, USA, 2022.

[21] L. Moreau and P. Missier, Eds., "PROV-DM: The PROV data model," W3C Recommendation, Apr. 2013.

[22] T. Gao, H. Yen, J. Yu, and D. Chen, "Enabling large language models to generate text with citations," in *Proc. Conf. Empirical Methods in Natural Language Processing (EMNLP)*, 2023.

[23] M. T. Ribeiro, S. Singh, and C. Guestrin, "'Why should I trust you?': Explaining the predictions of any classifier," in *Proc. 22nd ACM SIGKDD Conf. Knowledge Discovery and Data Mining (KDD)*, 2016, pp. 1135–1144.

[24] S. Jain and B. C. Wallace, "Attention is not explanation," in *Proc. Conf. North American Chapter of the Association for Computational Linguistics (NAACL-HLT)*, 2019, pp. 3543–3556.

[25] Board of Governors of the Federal Reserve System, "Supervisory guidance on model risk management," SR Letter 11-7, Washington, DC, USA, 2011.
