import base64
import json
import os
import anthropic
import fitz

from dotenv import load_dotenv
from config import DEV_MODE, PDF_PAGES_PER_CHUNK, PDF_OVERLAP_PAGES, MODEL, MAX_TOKENS_ANALYSIS, language_rule
import token_tracker

load_dotenv()

client = anthropic.Anthropic()

SKIP_FILES = {"expected_findings.json", "dataset_manifest.json"}


def _split_pdf(path: str, pages_per_chunk: int = None, overlap: int = None) -> list[dict]:
    if pages_per_chunk is None:
        pages_per_chunk = PDF_PAGES_PER_CHUNK
    if overlap is None:
        overlap = PDF_OVERLAP_PAGES
    doc = fitz.open(path)
    total = len(doc)
    basename = os.path.basename(path)
    chunks = []
    for start in range(0, total, pages_per_chunk):
        end = min(start + pages_per_chunk, total)
        # overlap_start pulls in trailing pages from the previous chunk so facts
        # that straddle a chunk boundary are visible to both adjacent extractors
        overlap_start = max(0, start - overlap)
        chunk = fitz.open()
        chunk.insert_pdf(doc, from_page=overlap_start, to_page=end - 1)
        if total <= pages_per_chunk:
            label = basename
        elif overlap_start < start:
            label = f"{basename} (pages {start+1}-{end}, context: {overlap_start+1}-{start})"
        else:
            label = f"{basename} (pages {start+1}-{end})"
        if DEV_MODE:
            text = "\n".join(page.get_text() for page in chunk)
            chunks.append({"filename": label, "type": "text", "content": text})
        else:
            data = base64.standard_b64encode(chunk.tobytes()).decode("utf-8")
            chunks.append({"filename": label, "type": "pdf", "data": data})
        chunk.close()
    doc.close()
    return chunks


def load_bundle(folder: str) -> list[dict]:
    if DEV_MODE:
        print("[BUNDLE] DEV_MODE=true — PDFs processed via text extraction (cheaper, no vision)")
    docs = []
    for fname in sorted(os.listdir(folder)):
        if fname in SKIP_FILES:
            continue
        path = os.path.join(folder, fname)
        if fname.endswith(".pdf"):
            docs.extend(_split_pdf(path))
        elif fname.endswith((".md", ".txt")):
            with open(path) as f:
                docs.append({"filename": fname, "type": "text", "content": f.read()})
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


def build_docs_blocks(docs: list[dict]) -> list[dict]:
    blocks = []
    for doc in docs:
        if doc["type"] == "pdf":
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": doc["data"],
                },
                "title": doc["filename"],
            })
        else:
            blocks.append({
                "type": "text",
                "text": f"=== {doc['filename']} ===\n{doc['content']}",
            })
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def build_analysis_prompt(docs: list[dict]) -> list[dict]:
    return [
        *build_docs_blocks(docs),
        {
            "type": "text",
            "text": f"""You are analyzing a set of project input documents shown above.

{language_rule("LANGUAGE RULE: Detect the primary language of the source documents. If all documents are in the same language, write ALL text values in that language — gaps, contradictions, and question text. If documents are in multiple languages, use English.")}
The JSON keys (gaps, contradictions, clarifying_questions, topic, question) are always in English. Only the VALUES must be in the detected/forced language.

Identify the following and return ONLY valid JSON, no prose:
{{
  "gaps": ["list of missing information or undefined requirements"],
  "contradictions": ["list of conflicts between documents"],
  "clarifying_questions": [
    {{"topic": "short_snake_case_tag", "question": "Full question text in the detected language?"}}
  ]
}}

Each clarifying question must have a stable snake_case topic tag (e.g. "slack_mvp", "sso_required") and the full question text. Generate 3 to 7 questions.""",
        },
    ]


def run_analysis(folder: str) -> dict:
    docs = load_bundle(folder)
    print(f"[ANALYSIS] Loaded {len(docs)} document(s): {[d['filename'] for d in docs]}")
    content = build_analysis_prompt(docs)

    print("[ANALYSIS] Calling Claude to identify gaps and contradictions...")
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS_ANALYSIS,
        betas=["prompt-caching-2024-07-31"],
        messages=[{"role": "user", "content": content}],
    )

    log_cache_usage("ANALYSIS", response.usage)
    token_tracker.record_pipeline(response.usage)

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"[ANALYSIS] Response truncated — document too large for max_tokens={MAX_TOKENS_ANALYSIS}. "
            "Increase max_tokens.analysis in config.yaml."
        )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    if not raw:
        raise ValueError(
            "Claude returned an empty response — the selected folder probably doesn't contain "
            "real project documents. Make sure you selected a bundle folder, not the project root."
        )
    result = json.loads(raw)
    print(f"[ANALYSIS] Found {len(result.get('gaps', []))} gap(s), {len(result.get('contradictions', []))} contradiction(s), {len(result.get('clarifying_questions', []))} question(s)")
    return result


if __name__ == "__main__":
    result = run_analysis("project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot")
    print(json.dumps(result, indent=2))
