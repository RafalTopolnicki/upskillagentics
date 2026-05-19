# Synthetic Dataset for Project Description Agent

Generated on: 2026-05-12

This dataset contains 5 synthetic project bundles for testing a Project Description Agent.

Each bundle contains:
- `brief.md` — short stakeholder-facing project idea
- `prd_draft.md` — incomplete or inconsistent PRD draft
- `transcript.txt` — messy discovery-call transcript with stakeholder discussion
- `constraints.md` — operational, compliance, technical, or scope constraints
- `expected_findings.json` — ground-truth labels for evals

The bundles intentionally contain:
- contradictions between files
- missing requirements
- ambiguous MVP scope
- post-MVP items mixed with MVP items
- compliance/security constraints
- requirements mentioned only once in transcripts

Recommended agent task:
1. Ingest all files in one bundle.
2. Extract grounded facts with provenance.
3. Detect contradictions, ambiguities, and missing information.
4. Ask 3–7 clarifying questions.
5. Produce:
   - Project Brief
   - Implementation PRD for a coding agent
6. Evaluate output against `expected_findings.json`.

Important eval principle:
A good agent should not invent requirements. Every generated requirement should be directly supported by source material, derived from user clarification, or explicitly marked as an assumption.
