# Evaluation Guide

Use `expected_findings.json` as lightweight ground truth.

## Suggested checks

### 1. Contradiction recall
For each item in `must_detect_contradictions`, check whether the agent's analysis report identifies the same conflict.

Score:
- 1.0 = detects the conflict and names both sides
- 0.5 = detects related ambiguity but not both sides
- 0.0 = misses it

### 2. Question quality
Compare the agent's clarifying questions with `must_ask_questions`.

Score:
- 1.0 = asks an equivalent targeted question
- 0.5 = asks a vague/general related question
- 0.0 = does not ask

### 3. Required fact inclusion
Check whether final Project Brief and Implementation PRD include the items in `must_include_requirements`.

### 4. Hallucination / forbidden scope
Check that outputs do not assert items in `must_not_include` as definite MVP requirements.

### 5. Question count
Check that the agent asks a small number of targeted questions, usually 3–7.

## Suggested aggregate metrics

- contradiction_recall
- question_recall
- required_fact_recall
- forbidden_claim_rate
- clarification_count_ok
- overall_pass

For first experiments, manual scoring in a spreadsheet is enough.
