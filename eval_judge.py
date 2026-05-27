import json
import anthropic
from dotenv import load_dotenv
import token_tracker

load_dotenv()

client = anthropic.Anthropic()
JUDGE_MODEL = "claude-sonnet-4-6"

ITEM_SCORES_TOOL = {
    "name": "submit_scores",
    "description": "Submit scores for each item evaluated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string", "description": "Short label for the item being scored."},
                        "score": {"type": "number", "description": "Score: 1.0, 0.5, or 0.0"},
                        "reason": {"type": "string", "description": "One sentence justifying the score."},
                    },
                    "required": ["item", "score", "reason"],
                },
            }
        },
        "required": ["scores"],
    },
}


def _call_judge(prompt: str) -> list[dict]:
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=2048,
        tools=[ITEM_SCORES_TOOL],
        tool_choice={"type": "tool", "name": "submit_scores"},
        messages=[{"role": "user", "content": prompt}],
    )
    token_tracker.record_judge(response.usage)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input["scores"]


def judge_contradiction_recall(analysis: dict, expected: dict) -> dict:
    expected_items = expected.get("must_detect_contradictions", [])
    if not expected_items:
        return {"scores": [], "mean": 1.0}

    contradictions_found = analysis.get("contradictions", [])
    prompt = f"""You are evaluating whether a pipeline correctly detected contradictions in project documents.

EXPECTED CONTRADICTIONS (ground truth — each must be detected):
{json.dumps(expected_items, indent=2)}

PIPELINE OUTPUT — contradictions it detected:
{json.dumps(contradictions_found, indent=2)}

For each expected contradiction, score whether the pipeline detected it:
- 1.0 = detected the conflict and captured both sides (exact wording doesn't matter)
- 0.5 = detected a related ambiguity but missed one side, or was too vague
- 0.0 = missed it entirely

Use the topic field as the item label."""

    scores = _call_judge(prompt)
    mean = sum(s["score"] for s in scores) / len(scores) if scores else 1.0
    return {"scores": scores, "mean": round(mean, 3)}


def judge_question_recall(qa_pairs: list, expected: dict) -> dict:
    expected_questions = expected.get("must_ask_questions", [])
    if not expected_questions:
        return {"scores": [], "mean": 1.0}

    questions_asked = [qa["question"] for qa in qa_pairs]
    prompt = f"""You are evaluating whether a pipeline asked the right clarifying questions.

EXPECTED QUESTIONS (ground truth — these should have been asked):
{json.dumps(expected_questions, indent=2)}

QUESTIONS ACTUALLY ASKED by the pipeline:
{json.dumps(questions_asked, indent=2)}

For each expected question, score whether the pipeline asked an equivalent question:
- 1.0 = asked an equivalent, targeted question (exact wording doesn't matter)
- 0.5 = asked a vague or related question that partially covers this
- 0.0 = did not ask this at all

Use a short label for each expected question."""

    scores = _call_judge(prompt)
    mean = sum(s["score"] for s in scores) / len(scores) if scores else 1.0
    return {"scores": scores, "mean": round(mean, 3)}


def judge_required_facts(artifacts: dict, expected: dict) -> dict:
    requirements = expected.get("must_include_requirements", [])
    if not requirements:
        return {"scores": [], "mean": 1.0}

    combined = (
        f"PROJECT BRIEF:\n{artifacts.get('project_brief', '')}\n\n"
        f"IMPLEMENTATION PRD:\n{artifacts.get('implementation_prd', '')}"
    )
    prompt = f"""You are evaluating whether the pipeline's output artifacts include all required information.

REQUIRED ITEMS (must be clearly present in at least one artifact):
{json.dumps(requirements, indent=2)}

ARTIFACTS PRODUCED:
{combined}

For each required item, score whether it is present in the artifacts:
- 1.0 = clearly stated in at least one artifact
- 0.0 = missing or contradicted

Use a short label for each required item."""

    scores = _call_judge(prompt)
    mean = sum(s["score"] for s in scores) / len(scores) if scores else 1.0
    return {"scores": scores, "mean": round(mean, 3)}


def judge_forbidden_claims(artifacts: dict, expected: dict) -> dict:
    forbidden = expected.get("must_not_include", [])
    if not forbidden:
        return {"scores": [], "mean": 1.0}

    combined = (
        f"PROJECT BRIEF:\n{artifacts.get('project_brief', '')}\n\n"
        f"IMPLEMENTATION PRD:\n{artifacts.get('implementation_prd', '')}"
    )
    prompt = f"""You are evaluating whether the pipeline hallucinated forbidden claims in its output.

FORBIDDEN CLAIMS (must NOT appear as definite requirements in the artifacts):
{json.dumps(forbidden, indent=2)}

ARTIFACTS PRODUCED:
{combined}

For each forbidden item, score whether it is absent from the artifacts:
- 1.0 = correctly ABSENT — not asserted as a definite requirement (good)
- 0.0 = PRESENT as a definite requirement — the pipeline hallucinated or included a forbidden claim (bad)

Mentioning something as explicitly out of scope or as an open question is fine (score 1.0).
Only score 0.0 if it is stated as a confirmed requirement.

Use a short label for each forbidden item."""

    scores = _call_judge(prompt)
    mean = sum(s["score"] for s in scores) / len(scores) if scores else 1.0
    return {"scores": scores, "mean": round(mean, 3)}


def score_run(analysis: dict, qa_pairs: list, artifacts: dict, expected: dict) -> dict:
    print("[JUDGE] Scoring contradiction recall...")
    contradictions = judge_contradiction_recall(analysis, expected)

    print("[JUDGE] Scoring question recall...")
    questions = judge_question_recall(qa_pairs, expected)

    print("[JUDGE] Scoring required fact recall...")
    required = judge_required_facts(artifacts, expected)

    print("[JUDGE] Scoring forbidden claim rate...")
    forbidden = judge_forbidden_claims(artifacts, expected)

    count = len(qa_pairs)
    count_range = expected.get("preferred_clarification_count", {})
    count_ok = count_range.get("min", 0) <= count <= count_range.get("max", 999)

    overall = (contradictions["mean"] + questions["mean"] + required["mean"] + forbidden["mean"]) / 4

    return {
        "contradiction_recall": contradictions,
        "question_recall": questions,
        "required_fact_recall": required,
        "forbidden_claim_rate": forbidden,
        "clarification_count": {"count": count, "ok": count_ok, "expected_range": count_range},
        "overall": round(overall, 3),
    }
