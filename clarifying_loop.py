import json
import os
import anthropic
from dotenv import load_dotenv
from analysis_pass import load_bundle, run_analysis, build_docs_blocks, log_cache_usage
from config import MAX_CLARIFY_ROUNDS, INTERACTIVE, MODEL, MAX_TOKENS_CLARIFY
import token_tracker

load_dotenv()

client = anthropic.Anthropic()


def load_mock_answers(folder: str) -> dict:
    path = os.path.join(folder, "mock_answers.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def get_answer(topic: str, question: str, mock_answers: dict) -> str:
    if INTERACTIVE:
        return input("A: ").strip()
    answer = mock_answers.get(topic) or mock_answers.get("default", "No answer available.")
    print(f"A: {answer} [mock]")
    return answer


def build_sufficiency_prompt(docs: list[dict], qa_pairs: list[dict]) -> list[dict]:
    qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs)
    return [
        *build_docs_blocks(docs),
        {
            "type": "text",
            "text": f"""You are assessing whether you have enough information to write a clear Project Brief and Implementation PRD.

LANGUAGE RULE: Detect the primary language of the source documents.
- If all documents are in the same language, write ALL follow-up question text in that language.
- If documents are in multiple languages, use English.
- The JSON keys (sufficient, follow_up_questions) are always in English. Only the question VALUES must be in the detected language.

## Clarifications collected so far
{qa_text}

Do you have enough information, or are there still critical gaps?

Return ONLY valid JSON:
{{
  "sufficient": true or false,
  "follow_up_questions": ["only if sufficient is false — 1 to 3 remaining critical questions"]
}}""",
        },
    ]


def run_clarifying_loop(folder: str) -> dict:
    docs = load_bundle(folder)
    analysis = run_analysis(folder)

    questions = analysis.get("clarifying_questions", [])
    qa_pairs = []
    mock_answers = load_mock_answers(folder)

    print(f"\n[CLARIFY] Starting clarifying loop — {len(questions)} initial question(s), max {MAX_CLARIFY_ROUNDS} follow-up round(s)")
    print("\n=== Clarifying Questions ===\n")

    # Round 1: ask initial questions from analysis pass
    for item in questions:
        topic = item.get("topic", "unknown")
        q = item.get("question", str(item))
        print(f"Q: {q}")
        answer = get_answer(topic, q, mock_answers)
        qa_pairs.append({"topic": topic, "question": q, "answer": answer})
        print()

    # Agent-driven follow-up rounds
    for round_num in range(MAX_CLARIFY_ROUNDS):
        content = build_sufficiency_prompt(docs, qa_pairs)
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_CLARIFY,
            betas=["prompt-caching-2024-07-31"],
            messages=[{"role": "user", "content": content}],
        )

        log_cache_usage(f"CLARIFY-round{round_num + 1}", response.usage)
        token_tracker.record_pipeline(response.usage)
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        decision = json.loads(raw)

        if decision["sufficient"]:
            print(f"[CLARIFY] Agent has enough information after round {round_num + 1}.\n")
            break

        follow_ups = decision.get("follow_up_questions", [])
        if not follow_ups:
            break

        print(f"=== Follow-up (round {round_num + 1}) ===\n")
        for q in follow_ups:
            print(f"Q: {q}")
            answer = get_answer("default", q, mock_answers)
            qa_pairs.append({"topic": "follow_up", "question": q, "answer": answer})
            print()

    print(f"[CLARIFY] Done — {len(qa_pairs)} Q&A pair(s) collected")
    return {
        "docs": docs,
        "analysis": analysis,
        "qa_pairs": qa_pairs,
    }


if __name__ == "__main__":
    context = run_clarifying_loop(
        "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
    )
    print("=== Collected context ===")
    print(json.dumps({"qa_pairs": context["qa_pairs"]}, indent=2))
