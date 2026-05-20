import os
import yaml

with open(os.path.join(os.path.dirname(__file__), "config.yaml")) as _f:
    _cfg = yaml.safe_load(_f)

MODEL = _cfg["model"]
DEV_MODE = bool(_cfg.get("dev_mode", False))
PDF_PAGES_PER_CHUNK = int(_cfg.get("pdf_pages_per_chunk", 15))
MAX_CLARIFY_ROUNDS = int(_cfg.get("max_clarify_rounds", 3))
INTERACTIVE = bool(_cfg.get("interactive", False))
MAX_REVISION_ROUNDS = int(_cfg.get("max_revision_rounds", 3))

_tokens = _cfg.get("max_tokens", {})
MAX_TOKENS_ANALYSIS = int(_tokens.get("analysis", 1024))
MAX_TOKENS_CLARIFY = int(_tokens.get("clarify", 512))
MAX_TOKENS_EXTRACTOR = int(_tokens.get("extractor", 8192))
MAX_TOKENS_WRITER = int(_tokens.get("writer", 4096))
MAX_TOKENS_CHALLENGER = int(_tokens.get("challenger", 2048))
