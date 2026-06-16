import os
import anthropic
from dotenv import load_dotenv
from config import MAX_REVISION_ROUNDS, MODEL, MAX_TOKENS_CHALLENGER, language_rule
import token_tracker

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

{language_rule("Language rule: detect the language of the facts and artifacts. Respond (claims, notes) in that language. If mixed, use English.")}

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

    token_tracker.record_pipeline(response.usage)
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


def check_and_revise(facts: list[dict], artifacts: dict) -> dict:
    from writer import write_artifacts  # local import avoids circular dependency at module load

    for attempt in range(1, MAX_REVISION_ROUNDS + 1):
        print(f"[CHALLENGER] Checking artifacts (attempt {attempt}/{MAX_REVISION_ROUNDS})...")
        result = run_challenger(facts, artifacts)

        if result["verdict"] == "all_claims_supported":
            print("[CHALLENGER] All claims supported — output approved.")
            return artifacts

        issues = result.get("issues", [])
        print(f"[CHALLENGER] {len(issues)} unsupported claim(s) found:")
        for issue in issues:
            print(f"  CLAIM: {issue['claim']}")
            print(f"  WHY:   {issue['note']}")

        if attempt < MAX_REVISION_ROUNDS:
            print(f"[CHALLENGER] Sending issues back to writer for surgical revision...")
            artifacts = write_artifacts(facts, issues=issues, previous_artifacts=artifacts)
        else:
            print(f"[CHALLENGER] Max revisions reached — annotating {len(issues)} unverified claim(s) and saving.")
            artifacts = annotate_artifacts(artifacts, issues)

    return artifacts


def build_challenger_prompt_from_docs(docs: list[dict], artifacts: dict) -> list[dict]:
    from analysis_pass import build_docs_blocks
    instruction = f"""You are a strict fact-checker. You will be given source project documents and two artifacts written from those documents.

Your job: find every claim in the artifacts that is NOT supported by the source documents.

## Project Brief
{artifacts['project_brief']}

## Implementation PRD
{artifacts['implementation_prd']}

{language_rule("Language rule: detect the language of the documents and artifacts. Respond (claims, notes) in that language. If mixed, use English.")}

Rules:
- A claim is supported if it can be directly traced to content in the source documents above.
- A claim is NOT supported if it introduces information, numbers, decisions, or requirements not present in the documents.
- Clarifications and assumptions explicitly labeled as such are allowed — do not flag those.
- Be strict. If you are unsure whether a claim is supported, flag it."""
    return [*build_docs_blocks(docs), {"type": "text", "text": instruction}]


def run_challenger_from_docs(docs: list[dict], artifacts: dict) -> dict:
    content = build_challenger_prompt_from_docs(docs, artifacts)

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_CHALLENGER,
        betas=["prompt-caching-2024-07-31"],
        tools=[CHALLENGER_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[{"role": "user", "content": content}],
    )

    token_tracker.record_pipeline(response.usage)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input


def check_and_revise_from_docs(docs: list[dict], artifacts: dict, qa_pairs: list[dict]) -> dict:
    from writer import write_artifacts_from_docs

    for attempt in range(1, MAX_REVISION_ROUNDS + 1):
        print(f"[CHALLENGER-SIMPLE] Checking artifacts (attempt {attempt}/{MAX_REVISION_ROUNDS})...")
        result = run_challenger_from_docs(docs, artifacts)

        if result["verdict"] == "all_claims_supported":
            print("[CHALLENGER-SIMPLE] All claims supported — output approved.")
            return artifacts

        issues = result.get("issues", [])
        print(f"[CHALLENGER-SIMPLE] {len(issues)} unsupported claim(s) found:")
        for issue in issues:
            print(f"  CLAIM: {issue['claim']}")
            print(f"  WHY:   {issue['note']}")

        if attempt < MAX_REVISION_ROUNDS:
            print("[CHALLENGER-SIMPLE] Sending issues back to writer for surgical revision...")
            artifacts = write_artifacts_from_docs(docs, qa_pairs, issues=issues, previous_artifacts=artifacts)
        else:
            print(f"[CHALLENGER-SIMPLE] Max revisions reached — annotating {len(issues)} unverified claim(s) and saving.")
            artifacts = annotate_artifacts(artifacts, issues)

    return artifacts


if __name__ == "__main__":
    import argparse
    import config as _config

    parser = argparse.ArgumentParser(description="Run the full project description pipeline.")
    parser.add_argument("--folder", required=True, help="Path to the bundle folder, e.g. project_description_agent_synthetic_dataset/bundle_006_orange")
    parser.add_argument(
        "--language", choices=["auto", "english", "polish"], default=None,
        help="Output language: auto detects from source docs, english/polish force the language. Overrides config.yaml.",
    )
    args = parser.parse_args()

    if args.language is not None:
        _config.LANGUAGE = args.language
    folder = args.folder

    from extractor import run_extraction
    from clarifying_loop import run_clarifying_loop
    from writer import write_artifacts
    from config import make_output_dir

    print(f"[PIPELINE] Bundle: {folder} | Language: {args.language}")

    context = run_clarifying_loop(folder)
    extraction = run_extraction(folder, qa_pairs=context["qa_pairs"])
    initial_artifacts = write_artifacts(extraction["facts"])
    final_artifacts = check_and_revise(extraction["facts"], initial_artifacts)

    out = make_output_dir(folder)
    with open(os.path.join(out, "project_brief.md"), "w") as f:
        f.write(final_artifacts["project_brief"])
    with open(os.path.join(out, "implementation_prd.md"), "w") as f:
        f.write(final_artifacts["implementation_prd"])
    print(f"\n[Saved to {out}/]")
