import anthropic
from dotenv import load_dotenv
from config import MAX_REVISION_ROUNDS, MODEL, MAX_TOKENS_CHALLENGER

load_dotenv()

client = anthropic.Anthropic()

CHALLENGER_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the verdict after checking all claims in the artifacts against the fact list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["all_claims_supported", "unsupported_claims_found"],
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {
                            "type": "string",
                            "description": "The exact claim from the artifact that is unsupported.",
                        },
                        "note": {
                            "type": "string",
                            "description": "Why this claim is not supported by the fact list.",
                        },
                    },
                    "required": ["claim", "note"],
                },
            },
        },
        "required": ["verdict", "issues"],
    },
}


def build_challenger_prompt(facts: list[dict], artifacts: dict) -> str:
    facts_text = "\n".join(
        f"- [{fact['source']}] {fact['fact']}\n  Quote: \"{fact['quote']}\""
        for fact in facts
    )
    return f"""You are a strict fact-checker. You will be given a list of verified facts and two artifacts written from those facts.

Your job: find every claim in the artifacts that is NOT supported by the fact list.

## Verified facts
{facts_text}

## Project Brief
{artifacts['project_brief']}

## Implementation PRD
{artifacts['implementation_prd']}

Language rule: detect the language of the facts and artifacts. Respond (claims, notes) in that language. If mixed, use English.

Rules:
- A claim is supported if it can be directly traced to one or more facts above.
- A claim is NOT supported if it introduces information, numbers, decisions, or requirements not present in the fact list.
- Clarifications and assumptions explicitly labeled as such are allowed — do not flag those.
- Be strict. If you are unsure whether a claim is supported, flag it."""


def run_challenger(facts: list[dict], artifacts: dict) -> dict:
    prompt = build_challenger_prompt(facts, artifacts)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_CHALLENGER,
        tools=[CHALLENGER_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input


def annotate_artifacts(artifacts: dict, issues: list[dict]) -> dict:
    marker = "\n\n---\n⚠️ UNVERIFIED CLAIMS — not supported by source documents:\n" + "\n".join(
        f"- {i['claim']}: {i['note']}" for i in issues
    )
    return {
        "project_brief": artifacts["project_brief"] + marker,
        "implementation_prd": artifacts["implementation_prd"] + marker,
    }


def check_and_revise(facts: list[dict], artifacts: dict, qa_pairs: list[dict]) -> dict:
    from writer import write_artifacts  # local import avoids circular dependency at module load

    for attempt in range(1, MAX_REVISION_ROUNDS + 1):
        print(f"[CHALLENGER] Checking artifacts (attempt {attempt}/{MAX_REVISION_ROUNDS})...")
        result = run_challenger(facts, artifacts)

        if result["verdict"] == "all_claims_supported":
            print("[CHALLENGER] All claims supported — output approved.")
            return artifacts

        issues = result["issues"]
        print(f"[CHALLENGER] {len(issues)} unsupported claim(s) found:")
        for issue in issues:
            print(f"  CLAIM: {issue['claim']}")
            print(f"  WHY:   {issue['note']}")

        if attempt < MAX_REVISION_ROUNDS:
            print(f"[CHALLENGER] Sending issues back to writer for surgical revision...")
            artifacts = write_artifacts(facts, qa_pairs, issues=issues, previous_artifacts=artifacts)
        else:
            print(f"[CHALLENGER] Max revisions reached — annotating {len(issues)} unverified claim(s) and saving.")
            artifacts = annotate_artifacts(artifacts, issues)

    return artifacts


if __name__ == "__main__":
    from extractor import run_extraction
    from clarifying_loop import run_clarifying_loop
    from writer import write_artifacts

    #folder = "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
    #folder = "project_description_agent_synthetic_dataset/bundle_002_invoice_processing_app"
    folder = "project_description_agent_synthetic_dataset/bundle_006_orange"
    #folder = "project_description_agent_synthetic_dataset/bundle_007_zabka"


    extraction = run_extraction(folder)
    context = run_clarifying_loop(folder)
    initial_artifacts = write_artifacts(extraction["facts"], context["qa_pairs"])

    final_artifacts = check_and_revise(extraction["facts"], initial_artifacts, context["qa_pairs"])

    with open("output_project_brief.md", "w") as f:
        f.write(final_artifacts["project_brief"])
    with open("output_implementation_prd.md", "w") as f:
        f.write(final_artifacts["implementation_prd"])
    print("\n[Saved to output_project_brief.md and output_implementation_prd.md]")
