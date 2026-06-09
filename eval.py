"""
Evaluate the project description pipeline across bundles and models.

Usage:
  python eval.py --bundles 001 002 003 004 005 --models haiku sonnet opus
  python eval.py --bundles 001 --models haiku sonnet   # quick comparison
  python eval.py --bundles 001 002 003 --models haiku --pipeline full simple   # A/B: full vs simple
  python eval.py --bundles 001 --models haiku --pipeline simple   # simple pipeline only
"""

import argparse
import json
import os

from dotenv import load_dotenv
import token_tracker

load_dotenv()

BUNDLES = {
    "001": "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot",
    "002": "project_description_agent_synthetic_dataset/bundle_002_invoice_processing_app",
    "003": "project_description_agent_synthetic_dataset/bundle_003_recruitment_screening_tool",
    "004": "project_description_agent_synthetic_dataset/bundle_004_customer_support_triage",
    "005": "project_description_agent_synthetic_dataset/bundle_005_field_inspection_mobile_app",
}

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}


def _patch_model(model_id: str) -> None:
    """Patch MODEL in all pipeline modules so the next run uses the given model."""
    import analysis_pass, clarifying_loop, extractor, writer, challenger
    for mod in [analysis_pass, clarifying_loop, extractor, writer, challenger]:
        mod.MODEL = model_id


def _load_expected(folder: str) -> dict:
    with open(os.path.join(folder, "expected_findings.json")) as f:
        return json.load(f)


def run_pipeline(folder: str, model_id: str) -> dict:
    _patch_model(model_id)

    from extractor import run_extraction
    from clarifying_loop import run_clarifying_loop
    from writer import write_artifacts
    from challenger import check_and_revise

    extraction = run_extraction(folder, use_cache=False)
    context = run_clarifying_loop(folder)
    initial_artifacts = write_artifacts(extraction["facts"], context["qa_pairs"])
    final_artifacts = check_and_revise(extraction["facts"], initial_artifacts, context["qa_pairs"])

    return {
        "analysis": context["analysis"],
        "qa_pairs": context["qa_pairs"],
        "artifacts": final_artifacts,
    }


def run_pipeline_simple(folder: str, model_id: str) -> dict:
    """Simplified pipeline: skips extractor, writer and challenger work directly from raw docs."""
    _patch_model(model_id)

    from analysis_pass import load_bundle
    from clarifying_loop import run_clarifying_loop
    from writer import write_artifacts_from_docs
    from challenger import check_and_revise_from_docs

    docs = load_bundle(folder)
    context = run_clarifying_loop(folder)
    initial_artifacts = write_artifacts_from_docs(docs, context["qa_pairs"])
    final_artifacts = check_and_revise_from_docs(docs, initial_artifacts, context["qa_pairs"])

    return {
        "analysis": context["analysis"],
        "qa_pairs": context["qa_pairs"],
        "artifacts": final_artifacts,
    }


def print_table(results: dict, bundles: list[str], models: list[str], pipelines: list[str]) -> None:
    dims = ["contradiction_recall", "question_recall", "required_fact_recall", "forbidden_claim_rate"]
    labels = ["Contradict", "Questions", "ReqFacts", "Forbidden"]

    col_w = 11
    header = (
        f"{'Bundle':<7} {'Model':<8} {'Variant':<7}"
        + "".join(f"{l:>{col_w}}" for l in labels)
        + f"{'CountOK':>{col_w}}{'OVERALL':>{col_w}}"
        + f"{'Pipeline$':>{col_w}}{'Judge$':>{col_w}}{'Total$':>{col_w}}"
    )
    sep = "-" * len(header)
    print(f"\n{sep}\n{header}\n{sep}")

    for bundle_id in bundles:
        for model_name in models:
            for pipeline in pipelines:
                key = f"{bundle_id}_{model_name}_{pipeline}"
                if key not in results:
                    continue
                r = results[key]
                variant = "full" if pipeline == "full" else "simple"
                row = f"{bundle_id:<7} {model_name:<8} {variant:<7}"
                for dim in dims:
                    row += f"{r[dim]['mean']:>{col_w}.2f}"
                ok = "✓" if r["clarification_count"]["ok"] else "✗"
                row += f"{ok:>{col_w}}"
                row += f"{r['overall']:>{col_w}.2f}"
                usage = r.get("usage", {})
                row += f"${usage.get('pipeline', {}).get('cost_usd', 0):>{col_w-1}.4f}"
                row += f"${usage.get('judge', {}).get('cost_usd', 0):>{col_w-1}.4f}"
                row += f"${usage.get('total_cost_usd', 0):>{col_w-1}.4f}"
                print(row)

    print(sep)

    if len(bundles) > 1:
        print()
        for model_name in models:
            for pipeline in pipelines:
                keys = [f"{b}_{model_name}_{pipeline}" for b in bundles if f"{b}_{model_name}_{pipeline}" in results]
                if not keys:
                    continue
                avg_score = sum(results[k]["overall"] for k in keys) / len(keys)
                total_cost = sum(results[k].get("usage", {}).get("total_cost_usd", 0) for k in keys)
                variant = "full" if pipeline == "full" else "simple"
                print(f"  {model_name:<8} [{variant}] avg overall: {avg_score:.2f}  total cost: ${total_cost:.4f}  (across {len(keys)} bundle(s))")


def main():
    parser = argparse.ArgumentParser(description="Evaluate the project description pipeline.")
    parser.add_argument(
        "--bundles", nargs="+", default=["001", "002", "003", "004", "005"],
        choices=list(BUNDLES.keys()), metavar="BUNDLE",
        help="Bundle IDs to evaluate (001–005)",
    )
    parser.add_argument(
        "--models", nargs="+", default=["haiku"],
        choices=list(MODELS.keys()), metavar="MODEL",
        help="Models to compare: haiku, sonnet, opus",
    )
    parser.add_argument(
        "--pipeline", nargs="+", default=["full"],
        choices=["full", "simple"], metavar="PIPELINE",
        help="Pipeline variants to compare: full (extractor+writer+challenger), simple (raw-docs→writer+challenger)",
    )
    args = parser.parse_args()

    from eval_judge import score_run

    results = {}

    for model_name in args.models:
        model_id = MODELS[model_name]
        for bundle_id in args.bundles:
            folder = BUNDLES[bundle_id]
            if not os.path.isdir(folder):
                print(f"[EVAL] Bundle {bundle_id} not found at {folder}, skipping.")
                continue

            for pipeline in args.pipeline:
                print(f"\n{'='*60}")
                print(f"[EVAL] Bundle {bundle_id} | Model: {model_name} ({model_id}) | Pipeline: {pipeline}")
                print(f"{'='*60}")

                try:
                    token_tracker.reset()
                    if pipeline == "simple":
                        run = run_pipeline_simple(folder, model_id)
                    else:
                        run = run_pipeline(folder, model_id)
                    expected = _load_expected(folder)
                    scores = score_run(run["analysis"], run["qa_pairs"], run["artifacts"], expected)
                    scores["usage"] = token_tracker.summary(model_id)
                    results[f"{bundle_id}_{model_name}_{pipeline}"] = scores
                    u = scores["usage"]
                    print(f"[EVAL] Done — overall: {scores['overall']:.2f}  |  pipeline: ${u['pipeline']['cost_usd']:.4f}  judge: ${u['judge']['cost_usd']:.4f}  total: ${u['total_cost_usd']:.4f}")
                except Exception as e:
                    import traceback
                    print(f"[EVAL] ERROR on bundle {bundle_id} / model {model_name} / pipeline {pipeline}: {e}")
                    traceback.print_exc()

    if results:
        print_table(results, args.bundles, args.models, args.pipeline)

        with open("eval_results.json", "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("\n[EVAL] Full results (including per-item judge reasoning) saved to eval_results.json")


if __name__ == "__main__":
    main()
