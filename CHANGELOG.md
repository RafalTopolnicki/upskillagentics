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

## Automated evaluation harness
There was no way to measure pipeline quality or compare models objectively. An eval harness was added: `eval.py` runs the full pipeline (with mock answers, no human in the loop) on any combination of bundles and models, then calls a fixed Sonnet judge to score four dimensions against `expected_findings.json` — contradiction recall, question recall, required fact recall, and forbidden claim rate. Results are printed as a comparison table and saved to `eval_results.json` with per-item judge reasoning for auditability.

## Token usage and cost tracking
There was no visibility into how much each pipeline run cost. A `token_tracker.py` module was added to accumulate input, output, cache-write, and cache-read tokens across all pipeline and judge API calls. The eval table now shows per-run pipeline cost, judge cost, and total cost in USD, with per-model totals at the bottom.

## Pipeline variants and A/B evaluation

The pipeline had a single fixed architecture (extractor → writer → challenger), making it impossible to test whether simpler designs could achieve comparable quality at lower cost. Two variants were introduced and made selectable via a `--pipeline` flag in `eval.py`:

**Full variant** (`full`): the original pipeline. An extractor agent reads all source documents and compresses them into `{fact, source, quote}` triples. The writer is blind to raw documents and writes only from the fact list. The challenger checks every output claim against those same structured facts. The extractor acts as a firewall: the writer cannot hallucinate details that weren't explicitly extracted.

**Simple variant** (`simple`): skips the extractor entirely. The writer receives the raw source documents directly and writes from them. The challenger also receives the raw documents and checks claims against the prose. No intermediate compression step — both agents work from the original text.

Both variants use the same clarifying loop, and the challenger's revision loop (up to 3 rounds) runs in both. The flag accepts multiple values so both variants can be compared in a single run:

```
python eval.py --bundles 001 002 003 004 005 --models haiku --pipeline full simple
```

The comparison table gains a `Variant` column so full vs simple results appear side by side.

**A/B results on haiku across 5 bundles:**

| Variant | Contradict avg | Questions avg | ReqFacts | Forbidden | Overall avg | Total cost |
|---------|---------------|--------------|----------|-----------|-------------|------------|
| full    | 0.73          | 0.64         | 1.00     | 1.00      | **0.84**    | $0.68      |
| simple  | 0.62          | 0.74         | 1.00     | 1.00      | **0.84**    | $0.44      |

Key findings:
- Overall quality is identical at 0.84 average — the simple variant is competitive
- Required fact recall and forbidden claim rate hold at 1.00 in both — the challenger-over-raw-docs firewall is effective enough to prevent hallucination on these bundles
- Full wins on contradiction recall (0.73 vs 0.62) — structured facts make it easier to surface conflicts between documents
- Simple wins on question recall (0.74 vs 0.64) — the clarifying loop sees full context rather than compressed facts, so it asks sharper questions
- Simple is 34% cheaper ($0.44 vs $0.68 across 5 bundles) — savings come entirely from skipping the extractor API calls

## Multilingual support
The pipeline always produced output in English regardless of the source document language. A language detection rule was added to all five prompts — if all documents share a language, the entire pipeline output (questions, facts, artifacts, challenger verdicts) is produced in that language; if documents are mixed-language, English is used as the fallback.
