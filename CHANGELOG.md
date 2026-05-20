# Changelog

## Core pipeline — analysis → clarifying loop → writer
Raw project docs often contain gaps and missing requirements that would silently propagate into output. Three agents were wired in sequence: analysis spots gaps and contradictions, a clarifying loop fills them via Q&A with a human (with mock mode for automated testing), and the writer produces the Project Brief.

## Second output artifact — Implementation PRD
The writer only produced a stakeholder-facing Project Brief, leaving the coding agent without structured instructions. The writer was upgraded to produce both artifacts in a single call using tool use for structured output.

## Extractor + Writer firewall
The writer had direct access to raw documents and could hallucinate details that looked plausible but weren't in the source material. An extractor agent was introduced to produce `{fact, source, quote}` triples, and the writer was made blind to raw documents — it can only write from the fact list.

## Challenger agent
Even with the firewall, the writer could still invent claims not present in the extracted facts. A challenger agent was added to check every claim in both artifacts against the fact list, blocking output if anything was unsupported.

## Revision loop instead of hard block
A hard block on unsupported claims meant the pipeline could crash with no usable output. The hard block was replaced with a loop: the challenger sends issues back to the writer for up to 3 revision attempts, and if claims are still unsupported after 3 rounds, they are annotated with `⚠️ UNVERIFIED` and the output is saved anyway.

## Surgical revision
Sending issues back to the writer caused it to rewrite everything from scratch, sometimes introducing new hallucinations while fixing old ones. The writer now receives its previous output alongside the flagged claims, so it fixes only the specific issues rather than producing a full rewrite.

## Pipeline logging
There was no visibility into what each agent was doing during a run. `[STAGE]` prefix logs were added across all scripts so running `challenger.py` gives a full traceback of the process — documents loaded, facts extracted, cache hits, revision rounds, and final verdict.

## Prompt caching
The same document content was being sent to Claude three separate times (analysis, clarifying loop, extractor), paying full token cost each time. Documents are now formatted as a shared cacheable block via `build_docs_blocks()`, so the first agent call writes the cache and subsequent agents get an ~90% discount on those tokens.

## Native PDF support via Claude vision
Text extraction from PDFs using `pymupdf` silently lost tables, diagrams, and images, and failed completely on scanned documents. PDFs are now base64-encoded and passed directly to Claude as document blocks, letting Claude read them visually — understanding layout, tables, and scanned pages without any text extraction step.

## PDF chunking for large documents
Large PDFs caused the extractor to hit the output token limit mid-response, producing a truncated and unusable fact list. PDFs are now split into chunks of 20 pages using `pymupdf` before being passed to Claude, with each chunk extracted separately and facts merged at the end.

## Multilingual support
The pipeline always produced output in English regardless of the source document language. A language detection rule was added to all five prompts — if all documents share a language, the entire pipeline output (questions, facts, artifacts, challenger verdicts) is produced in that language; if documents are mixed-language, English is used as the fallback.
