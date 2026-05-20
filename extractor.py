import anthropic
from dotenv import load_dotenv
from analysis_pass import load_bundle, build_docs_blocks, log_cache_usage

load_dotenv()

client = anthropic.Anthropic()

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


def build_extraction_prompt(docs: list[dict]) -> list[dict]:
    return [
        *build_docs_blocks(docs),
        {
            "type": "text",
            "text": """Extract every distinct requirement, constraint, or decision that is explicitly stated in the source documents shown above.

Language rule: detect the language of the source documents. If all documents are in the same language, write facts and quotes in that language. If documents are in multiple languages, use English.

Rules:
- Each fact must be atomic (one requirement per fact).
- Every fact must be grounded in a direct quote from a source document.
- Do not infer, interpret, or combine facts — only extract what is explicitly written.
- Do not include vague statements without a concrete quote to back them up.""",
        },
    ]


def _extract_from_doc(doc: dict, index: int, total: int) -> list[dict]:
    tag = f"EXTRACTOR-{index+1}/{total}"
    content = build_extraction_prompt([doc])

    response = client.beta.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        betas=["prompt-caching-2024-07-31"],
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_facts"},
        messages=[{"role": "user", "content": content}],
    )

    log_cache_usage(tag, response.usage)

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"[{tag}] Response truncated — '{doc['filename']}' produced too many facts to fit in one call. "
            "Reduce PDF_PAGES_PER_CHUNK in analysis_pass.py."
        )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    facts = tool_use.input["facts"]
    print(f"[{tag}] Extracted {len(facts)} fact(s) from '{doc['filename']}'")
    return facts


def run_extraction(folder: str) -> dict:
    docs = load_bundle(folder)
    print(f"[EXTRACTOR] Extracting facts from {len(docs)} document(s)...")

    all_facts = []
    for i, doc in enumerate(docs):
        all_facts.extend(_extract_from_doc(doc, i, len(docs)))

    print(f"[EXTRACTOR] Total: {len(all_facts)} fact(s) extracted")
    return {"docs": docs, "facts": all_facts}


if __name__ == "__main__":
    import json

    result = run_extraction(
        "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
    )
    print(json.dumps(result["facts"], indent=2))
    print(f"\n[{len(result['facts'])} facts extracted]")
