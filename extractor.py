import anthropic
from dotenv import load_dotenv
from analysis_pass import load_bundle

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


def build_extraction_prompt(docs: list[dict]) -> str:
    bundle = "\n\n".join(f"=== {d['filename']} ===\n{d['content']}" for d in docs)
    return f"""You are extracting facts from a set of project input documents.

{bundle}

Extract every distinct requirement, constraint, or decision that is explicitly stated in the documents.
Rules:
- Each fact must be atomic (one requirement per fact).
- Every fact must be grounded in a direct quote from a source document.
- Do not infer, interpret, or combine facts — only extract what is explicitly written.
- Do not include vague statements without a concrete quote to back them up."""


def run_extraction(folder: str) -> dict:
    docs = load_bundle(folder)
    print(f"[EXTRACTOR] Extracting facts from {len(docs)} document(s)...")
    prompt = build_extraction_prompt(docs)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_facts"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    facts = tool_use.input["facts"]
    print(f"[EXTRACTOR] Extracted {len(facts)} fact(s)")

    return {"docs": docs, "facts": facts}


if __name__ == "__main__":
    import json

    result = run_extraction(
        "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
    )
    print(json.dumps(result["facts"], indent=2))
    print(f"\n[{len(result['facts'])} facts extracted]")
