import json
import os
import anthropic
import fitz

from dotenv import load_dotenv
load_dotenv()

client = anthropic.Anthropic()

SKIP_FILES = {"expected_findings.json", "dataset_manifest.json"}

def _read_pdf(path: str) -> str:
    doc = fitz.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text

def load_bundle(folder: str) -> list[dict]:
    docs = []
    for fname in sorted(os.listdir(folder)):
        if fname in SKIP_FILES:
            continue
        path = os.path.join(folder, fname)
        if fname.endswith(".pdf"):
            content = _read_pdf(path)
            if not content.strip():
                print(f"[warn] {fname}: no text extracted (scanned PDF?)")
                continue
            docs.append({"filename": fname, "content": content})
        elif fname.endswith((".md", ".txt")):
            with open(path) as f:
                docs.append({"filename": fname, "content": f.read()})
    return docs

def log_cache_usage(tag: str, usage) -> None:
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    regular = getattr(usage, "input_tokens", 0) or 0
    if created:
        print(f"[CACHE:{tag}] written={created} tokens (first call, full price)")
    elif read:
        print(f"[CACHE:{tag}] hit={read} tokens saved (~90% discount), regular={regular}")
    else:
        print(f"[CACHE:{tag}] no cache activity, input={regular} tokens")


def build_docs_block(docs: list[dict]) -> dict:
    bundle = "\n\n".join(f"=== {d['filename']} ===\n{d['content']}" for d in docs)
    return {
        "type": "text",
        "text": f"## Source documents\n\n{bundle}",
        "cache_control": {"type": "ephemeral"},
    }


def build_analysis_prompt(docs: list[dict]) -> list[dict]:
    return [
        build_docs_block(docs),
        {
            "type": "text",
            "text": """You are analyzing a set of project input documents shown above.

Identify the following and return ONLY valid JSON, no prose:
{
  "gaps": ["list of missing information or undefined requirements"],
  "contradictions": ["list of conflicts between documents"],
  "clarifying_questions": [
    {"topic": "short_snake_case_tag", "question": "Full question text?"}
  ]
}

Each clarifying question must have a stable snake_case topic tag (e.g. "slack_mvp", "sso_required") and the full question text. Generate 3 to 7 questions.""",
        },
    ]


def run_analysis(folder: str) -> dict:
    docs = load_bundle(folder)
    print(f"[ANALYSIS] Loaded {len(docs)} document(s): {[d['filename'] for d in docs]}")
    content = build_analysis_prompt(docs)

    print("[ANALYSIS] Calling Claude to identify gaps and contradictions...")
    response = client.beta.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        betas=["prompt-caching-2024-07-31"],
        messages=[{"role": "user", "content": content}],
    )

    log_cache_usage("ANALYSIS", response.usage)
    raw = response.content[0].text.strip()
    # Strip markdown code fences if the model added them
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    print(f"[ANALYSIS] Found {len(result.get('gaps', []))} gap(s), {len(result.get('contradictions', []))} contradiction(s), {len(result.get('clarifying_questions', []))} question(s)")
    return result

if __name__ == "__main__":
    result = run_analysis("project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot")
    print(json.dumps(result, indent=2))