"""
Historical project similarity search.

Workflow:
  1. convert_new_pptx(tpx_dir)  — converts any PPTX that has no matching PDF yet
  2. build_index(tpx_dir)       — PDF → Claude summary → embedding, skips already-indexed projects
  3. find_similar(brief)        — embed brief, cosine similarity, Claude explanation
"""

import base64
import json
import os
import subprocess

import fitz
import numpy as np
import anthropic
from dotenv import load_dotenv

import config as _config

load_dotenv()

INDEX_FILENAME = "tpx_index.json"


# ── PPTX → PDF ────────────────────────────────────────────────────────────────

def convert_new_pptx(tpx_dir: str, progress_cb=None) -> list[str]:
    """Convert every PPTX in tpx_dir subdirs that has no matching PDF yet.
    Returns list of newly created PDF paths."""
    converted = []
    for entry in sorted(os.scandir(tpx_dir), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        for fname in sorted(os.listdir(entry.path)):
            if not fname.lower().endswith(".pptx"):
                continue
            pdf_path = os.path.join(entry.path, os.path.splitext(fname)[0] + ".pdf")
            if os.path.exists(pdf_path):
                continue
            pptx_path = os.path.join(entry.path, fname)
            if progress_cb:
                progress_cb(f"Converting {entry.name}/{fname} ...")
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf",
                 pptx_path, "--outdir", entry.path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"LibreOffice failed for {pptx_path}:\n{result.stderr.strip()}"
                )
            converted.append(pdf_path)
    return converted


# ── Summarisation ─────────────────────────────────────────────────────────────

MAX_PAGES_FOR_SUMMARY = 10  # first N pages across all PDFs in a project
SUMMARY_DPI = 96            # 96 DPI JPEG — readable by Claude, ~20x smaller than raw PDF


def _pages_as_jpeg_blocks(pdf_paths: list[str]) -> list[dict]:
    """Render the first MAX_PAGES_FOR_SUMMARY pages across all PDFs as JPEG image blocks."""
    blocks = []
    scale = SUMMARY_DPI / 72
    mat = fitz.Matrix(scale, scale)
    for path in pdf_paths:
        if len(blocks) >= MAX_PAGES_FOR_SUMMARY:
            break
        doc = fitz.open(path)
        for i in range(len(doc)):
            if len(blocks) >= MAX_PAGES_FOR_SUMMARY:
                break
            pix = doc.load_page(i).get_pixmap(matrix=mat)
            jpeg = pix.tobytes("jpeg")
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(jpeg).decode("utf-8"),
                },
            })
        doc.close()
    return blocks


def _summarize_project(pdf_paths: list[str]) -> str:
    """Render slide pages as JPEG and ask Claude for a ~200-word project summary."""
    client = anthropic.Anthropic()
    blocks = _pages_as_jpeg_blocks(pdf_paths)
    prompt = """You are summarizing a company project presentation for a similarity search index.

Write a concise 150-200 word summary covering:
- What problem this project solved
- What was built (system, product, or service)
- The industry or business domain
- Key technologies or methodologies used
- The client or business context (if mentioned)

Be specific and factual. Do not invent details not visible in the slides."""

    response = client.messages.create(
        model=_config.MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": [*blocks, {"type": "text", "text": prompt}]}],
    )
    return response.content[0].text.strip()


# ── Embedding ─────────────────────────────────────────────────────────────────

_embedding_model = None

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def _embed(text: str) -> list[float]:
    return _get_model().encode(text).tolist()


# ── Index management ──────────────────────────────────────────────────────────

def _index_path(tpx_dir: str) -> str:
    return os.path.join(tpx_dir, INDEX_FILENAME)


def load_index(tpx_dir: str) -> list[dict]:
    path = _index_path(tpx_dir)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_index(tpx_dir: str, index: list[dict]) -> None:
    with open(_index_path(tpx_dir), "w") as f:
        json.dump(index, f, indent=2)


def build_index(tpx_dir: str, progress_cb=None) -> int:
    """Summarise and embed any project subdir not yet in the index.
    Returns number of newly indexed projects."""
    index = load_index(tpx_dir)
    indexed_names = {e["project_name"] for e in index}
    new_count = 0

    for entry in sorted(os.scandir(tpx_dir), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        if entry.name in indexed_names:
            continue

        pdfs = sorted([
            os.path.join(entry.path, f)
            for f in os.listdir(entry.path)
            if f.lower().endswith(".pdf")
        ])
        if not pdfs:
            continue

        if progress_cb:
            progress_cb(f"Summarising {entry.name} ({len(pdfs)} PDF(s))...")

        summary = _summarize_project(pdfs)
        embedding = _embed(summary)

        index.append({
            "project_name": entry.name,
            "subdir": entry.path,
            "pdfs": [os.path.basename(p) for p in pdfs],
            "summary": summary,
            "embedding": embedding,
        })
        new_count += 1
        _save_index(tpx_dir, index)

    return new_count


def index_status(tpx_dir: str) -> dict:
    """Return counts useful for the UI status display."""
    index = load_index(tpx_dir)
    indexed_names = {e["project_name"] for e in index}

    total_subdirs = sum(
        1 for e in os.scandir(tpx_dir) if e.is_dir()
    ) if os.path.isdir(tpx_dir) else 0

    unindexed = [
        e.name for e in os.scandir(tpx_dir)
        if e.is_dir() and e.name not in indexed_names
        and any(f.lower().endswith(".pdf") for f in os.listdir(e.path))
    ] if os.path.isdir(tpx_dir) else []

    needs_conversion = [
        os.path.join(e.path, f)
        for e in os.scandir(tpx_dir) if e.is_dir()
        for f in os.listdir(e.path)
        if f.lower().endswith(".pptx")
        and not os.path.exists(os.path.join(e.path, os.path.splitext(f)[0] + ".pdf"))
    ] if os.path.isdir(tpx_dir) else []

    return {
        "indexed": len(index),
        "total_subdirs": total_subdirs,
        "unindexed": unindexed,
        "needs_conversion": needs_conversion,
    }


# ── Similarity search ─────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def find_similar(brief: str, tpx_dir: str, top_k: int = 3) -> dict:
    """Find the top_k most similar historical projects and explain why."""
    index = load_index(tpx_dir)
    if not index:
        raise ValueError("Index is empty — run indexing first.")

    query_vec = _embed(brief)
    scored = sorted(
        index,
        key=lambda e: _cosine(query_vec, e["embedding"]),
        reverse=True,
    )
    top = scored[:top_k]

    matches_text = "\n\n".join(
        f"### {i+1}. {m['project_name']} (score: {_cosine(query_vec, m['embedding']):.2f})\n{m['summary']}"
        for i, m in enumerate(top)
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_config.MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": f"""You are comparing a new project brief against similar historical company projects.

## New project
{brief}

## Top {top_k} most similar historical projects
{matches_text}

For each historical project write 2-3 sentences explaining specifically why it is similar to the new project. Focus on concrete overlaps: same domain, similar technical approach, shared methodology, comparable problem type. Avoid vague statements like "both use data" or "both are software projects".

Format as a numbered list matching the order above."""}],
    )

    return {
        "matches": [
            {
                "project_name": m["project_name"],
                "score": round(_cosine(query_vec, m["embedding"]), 3),
                "summary": m["summary"],
            }
            for m in top
        ],
        "explanation": response.content[0].text.strip(),
    }
