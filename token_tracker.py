"""
Tracks token usage and cost across pipeline and judge calls.
Reset before each (bundle, model) run; read after.
"""

# Prices per million tokens
PRICES = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_write": 1.00, "cache_read": 0.08},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
}

_pipeline = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
_judge    = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}


def reset() -> None:
    for d in (_pipeline, _judge):
        for k in d:
            d[k] = 0


def record_pipeline(usage) -> None:
    _pipeline["input"]       += getattr(usage, "input_tokens", 0) or 0
    _pipeline["output"]      += getattr(usage, "output_tokens", 0) or 0
    _pipeline["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
    _pipeline["cache_read"]  += getattr(usage, "cache_read_input_tokens", 0) or 0


def record_judge(usage) -> None:
    _judge["input"]       += getattr(usage, "input_tokens", 0) or 0
    _judge["output"]      += getattr(usage, "output_tokens", 0) or 0
    _judge["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
    _judge["cache_read"]  += getattr(usage, "cache_read_input_tokens", 0) or 0


def _compute_cost(tokens: dict, model_id: str) -> float:
    p = PRICES.get(model_id, PRICES["claude-haiku-4-5-20251001"])
    return (
        tokens["input"]       * p["input"]       / 1_000_000 +
        tokens["output"]      * p["output"]      / 1_000_000 +
        tokens["cache_write"] * p["cache_write"] / 1_000_000 +
        tokens["cache_read"]  * p["cache_read"]  / 1_000_000
    )


def summary(pipeline_model_id: str, judge_model_id: str = "claude-sonnet-4-6") -> dict:
    pipeline_cost = _compute_cost(_pipeline, pipeline_model_id)
    judge_cost    = _compute_cost(_judge, judge_model_id)
    return {
        "pipeline": {**_pipeline, "cost_usd": round(pipeline_cost, 4)},
        "judge":    {**_judge,    "cost_usd": round(judge_cost, 4)},
        "total_cost_usd": round(pipeline_cost + judge_cost, 4),
    }
