import json
import os
import anthropic
from dotenv import load_dotenv
from analysis_pass import load_bundle, build_docs_blocks, log_cache_usage
from config import MODEL, MAX_TOKENS_EXTRACTOR, language_rule
import token_tracker

load_dotenv()

client = anthropic.Anthropic()

FACTS_CACHE_FILE = "facts_cache.json"


def _load_cache(folder: str) -> list[dict] | None:
    path = os.path.join(folder, FACTS_CACHE_FILE)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(folder: str, facts: list[dict]) -> None:
    path = os.path.join(folder, FACTS_CACHE_FILE)
    with open(path, "w") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)
    print(f"[EXTRACTOR] Facts cached to {path}")

EXTRACTION_TOOL = {
    "name": "submit_facts",
    "description": "Submit all facts extracted from the source documents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact": {
                            "type": "string",
                            "description": "A single, atomic, self-contained requirement or constraint.",
                        },
                        "source": {
                            "type": "string",
                            "description": "Filename the fact was taken from.",
                        },
                        "quote": {
                            "type": "string",
                            "description": "Verbatim or near-verbatim text from the source that supports this fact.",
                        },
                    },
                    "required": ["fact", "source", "quote"],
                },
            }
        },
        "required": ["facts"],
    },
}


def build_extraction_prompt(docs: list[dict], qa_pairs: list[dict] | None = None) -> list[dict]:
    qa_section = ""
    if qa_pairs:
        qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs)
        qa_section = f"""
## Clarifications from the project lead (these override the source documents)
{qa_text}

If a document states something directly contradicted by a clarification above, skip that document fact entirely — do not extract it.
"""
    return [
        *build_docs_blocks(docs),
        {
            "type": "text",
            "text": f"""Extract every distinct requirement, constraint, or decision that is explicitly stated in the source documents shown above.
{qa_section}
{language_rule("Language rule: detect the language of the source documents. If all documents are in the same language, write facts and quotes in that language. If documents are in multiple languages, use English.")}

Rules:
- Each fact must be atomic (one requirement per fact).
- Every fact must be grounded in a direct quote from a source document.
- Do not infer, interpret, or combine facts — only extract what is explicitly written.
- Do not include vague statements without a concrete quote to back them up.""",
        },
    ]


def _extract_from_doc(doc: dict, index: int, total: int, qa_pairs: list[dict] | None = None) -> list[dict]:
    tag = f"EXTRACTOR-{index+1}/{total}"
    content = build_extraction_prompt([doc], qa_pairs)

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_EXTRACTOR,
        betas=["prompt-caching-2024-07-31"],
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_facts"},
        messages=[{"role": "user", "content": content}],
    )

    log_cache_usage(tag, response.usage)
    token_tracker.record_pipeline(response.usage)

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"[{tag}] Response truncated — '{doc['filename']}' produced too many facts to fit in one call. "
            "Reduce PDF_PAGES_PER_CHUNK in analysis_pass.py."
        )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    facts = tool_use.input["facts"]
    if not isinstance(facts, list) or (facts and not isinstance(facts[0], dict)):
        raise RuntimeError(
            f"[{tag}] Malformed extractor response — 'facts' is not a list of dicts "
            f"(got {type(facts).__name__} with {len(facts)} item(s)). "
            "Increase max_tokens.extractor or reduce PDF_PAGES_PER_CHUNK in config.yaml."
        )
    print(f"[{tag}] Extracted {len(facts)} fact(s) from '{doc['filename']}'")
    return facts


def _extract_qa_facts(qa_pairs: list[dict]) -> list[dict]:
    """Convert Q&A clarifications into structured facts with source='clarification'."""
    if not qa_pairs:
        return []
    qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_EXTRACTOR,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_facts"},
        messages=[{"role": "user", "content": f"""Convert these Q&A clarifications into structured facts.

{qa_text}

For each answer that provides a concrete requirement, constraint, or decision:
- Extract it as an atomic fact
- Use "clarification" as the source
- Use the answer text as the quote

Skip vague answers like "no preference", "no answer available", or answers that add no concrete information."""}],
    )
    token_tracker.record_pipeline(response.usage)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    facts = tool_use.input["facts"]
    for f in facts:
        f["source"] = "clarification"
    print(f"[EXTRACTOR] Extracted {len(facts)} fact(s) from Q&A clarifications")
    return facts


def run_extraction(folder: str, qa_pairs: list[dict] | None = None, use_cache: bool = True) -> dict:
    # Bypass cache when Q&A is provided — the fact list depends on clarifications
    if use_cache and not qa_pairs:
        cached = _load_cache(folder)
        if cached is not None:
            print(f"[EXTRACTOR] Loaded {len(cached)} fact(s) from cache (skipping API calls)")
            docs = load_bundle(folder)
            return {"docs": docs, "facts": cached}

    docs = load_bundle(folder)
    print(f"[EXTRACTOR] Extracting facts from {len(docs)} document(s): {[d['filename'] for d in docs]}")

    all_facts = []
    for i, doc in enumerate(docs):
        all_facts.extend(_extract_from_doc(doc, i, len(docs), qa_pairs))

    if qa_pairs:
        all_facts.extend(_extract_qa_facts(qa_pairs))

    print(f"[EXTRACTOR] Total: {len(all_facts)} fact(s) extracted")
    if not qa_pairs:
        _save_cache(folder, all_facts)
    return {"docs": docs, "facts": all_facts}


if __name__ == "__main__":
    import json

    result = run_extraction(
        "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
    )
    print(json.dumps(result["facts"], indent=2))
    print(f"\n[{len(result['facts'])} facts extracted]")
