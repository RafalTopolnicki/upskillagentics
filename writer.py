import anthropic
from dotenv import load_dotenv
from config import MODEL, MAX_TOKENS_WRITER
import token_tracker

load_dotenv()

client = anthropic.Anthropic()

WRITING_TOOL = {
    "name": "submit_artifacts",
    "description": "Submit the two output artifacts produced from the project inputs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_brief": {
                "type": "string",
                "description": (
                    "A 300-500 word stakeholder-facing brief with sections: "
                    "What we're building, Who it's for, Core requirements, "
                    "Out of scope, Open assumptions."
                ),
            },
            "implementation_prd": {
                "type": "string",
                "description": (
                    "A coding-agent-ready PRD with sections: Overview, "
                    "Functional requirements (with acceptance criteria), "
                    "Non-goals, Tech stack, File/module structure hints, "
                    "Edge cases, Open questions."
                ),
            },
        },
        "required": ["project_brief", "implementation_prd"],
    },
}


def build_writing_prompt(
    facts: list[dict],
    qa_pairs: list[dict],
    issues: list[dict] | None = None,
    previous_artifacts: dict | None = None,
) -> str:
    facts_text = "\n".join(
        f"- [{fact['source']}] {fact['fact']}\n  Quote: \"{fact['quote']}\""
        for fact in facts
    )
    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs
    )
    issues_section = ""
    if issues and previous_artifacts:
        issues_text = "\n".join(
            f"- CLAIM: {i['claim']}\n  WHY UNSUPPORTED: {i['note']}" for i in issues
        )
        issues_section = f"""
## Your previous output — keep everything except the flagged claims below
Revise surgically. Do NOT rewrite sections that were not flagged.

### Previous Project Brief
{previous_artifacts['project_brief']}

### Previous Implementation PRD
{previous_artifacts['implementation_prd']}

## Flagged claims — fix or remove only these
A fact-checker found the following claims that are NOT supported by the fact list.
For each: either remove it entirely, or replace it with a version directly supported by a fact above.
Do NOT invent new information to justify a claim.

{issues_text}
"""
    return f"""You are producing two artifacts from a set of verified project facts and clarifications.{issues_section}

## Verified facts (each grounded in a source document)
{facts_text}

## Clarifications from the project lead
{qa_text}

Language rule: detect the language of the source documents. If all documents are in the same language, write both artifacts in that language. If documents are in multiple languages, write in English.

Produce both artifacts now.

Rules that apply to BOTH artifacts:
- Only use information present in the facts list or clarifications above.
- Do not invent requirements, constraints, or technical decisions.
- If something was not confirmed, list it as an open assumption or open question.

OVERRIDE RULE — this is the most important rule:
If a clarification contradicts a fact from the source documents, the clarification ALWAYS wins.
Treat the contradicted fact as if it does not exist. Do not mention it, include it, or hedge between the two versions.
Example: if a source doc says "Slack is required" but the clarification says "browser-only for now",
then Slack is NOT a requirement — do not include it anywhere in either artifact.

### Project Brief
Written for a non-technical stakeholder. 300-500 words. Sections:
- **What we're building** — one paragraph, plain language
- **Who it's for** — primary users and stakeholders
- **Core requirements** — 4-8 bullet points, confirmed only
- **Out of scope** — what is explicitly excluded
- **Open assumptions** — anything unresolved, stated as assumptions

### Implementation PRD
Written for a coding agent (Claude Code, Cursor, Codex) that will start implementing immediately.
Be explicit and structured. Sections:
- **Overview** — one paragraph, what to build and why
- **Functional requirements** — numbered list, each with acceptance criteria
- **Non-goals** — what the agent must NOT build
- **Tech stack** — only what is confirmed; mark anything unconfirmed as a recommendation
- **File/module structure hints** — suggested entry points and key modules
- **Edge cases** — specific failure modes the implementation must handle
- **Open questions** — decisions not yet made that will block implementation"""


def write_artifacts(
    facts: list[dict],
    qa_pairs: list[dict],
    issues: list[dict] | None = None,
    previous_artifacts: dict | None = None,
) -> dict:
    if issues:
        print(f"[WRITER] Revising artifacts — fixing {len(issues)} unsupported claim(s) (surgical rewrite)...")
    else:
        print(f"[WRITER] Writing artifacts from {len(facts)} fact(s) and {len(qa_pairs)} Q&A pair(s)...")
    prompt = build_writing_prompt(facts, qa_pairs, issues, previous_artifacts)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_WRITER,
        tools=[WRITING_TOOL],
        tool_choice={"type": "tool", "name": "submit_artifacts"},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"[WRITER] Response truncated — artifacts too large for max_tokens={MAX_TOKENS_WRITER}. "
            "Increase max_tokens.writer in config.yaml."
        )

    token_tracker.record_pipeline(response.usage)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    print("[WRITER] Artifacts produced (Project Brief + Implementation PRD)")
    return tool_use.input


if __name__ == "__main__":
    from extractor import run_extraction
    from clarifying_loop import run_clarifying_loop

    folder = "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"

    extraction = run_extraction(folder)
    context = run_clarifying_loop(folder)

    artifacts = write_artifacts(extraction["facts"], context["qa_pairs"])

    print("\n=== PROJECT BRIEF ===\n")
    print(artifacts["project_brief"])

    print("\n=== IMPLEMENTATION PRD ===\n")
    print(artifacts["implementation_prd"])

    with open("output_project_brief.md", "w") as f:
        f.write(artifacts["project_brief"])

    with open("output_implementation_prd.md", "w") as f:
        f.write(artifacts["implementation_prd"])

    print("\n[Saved to output_project_brief.md and output_implementation_prd.md]")