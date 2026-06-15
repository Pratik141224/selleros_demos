"""
check_dependencies.py

Validates all in-process dependencies for the SellerOS demo stack.
No HTTP calls — checks imports, env vars, and critical files only.

Run from repo root:
    python check_dependencies.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LQS  = os.path.join(_ROOT, "LQS")

# _ROOT must be at higher priority than _LQS because both contain a shared/ package.
# selleros_demos/shared/ (llm_router, zyte_client) must win over LQS/shared/.
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _LQS not in sys.path:
    sys.path.append(_LQS)


GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"

_ok  = f"{GREEN}✓{RESET}"
_fail = f"{RED}✗{RESET}"

results: list[tuple[bool, str]] = []


def check(label: str, fn) -> bool:
    try:
        fn()
        results.append((True, label))
        return True
    except Exception as exc:
        results.append((False, f"{label} — {exc}"))
        return False


# ── Import checks ──────────────────────────────────────────────────────────────

check("shared.llm_router importable",
      lambda: __import__("shared.llm_router", fromlist=["call", "TaskType"]))

check("shared.s3_cache importable",
      lambda: __import__("shared.s3_cache", fromlist=["get", "put"]))

check("shared.zyte_client importable",
      lambda: __import__("shared.zyte_client", fromlist=["fetch_own_listing"]))

def _check_a9_scorer():
    import importlib.util, sys as _sys
    _path = os.path.join(_LQS, "marketplaces", "amazon", "a9_scorer.py")
    spec  = importlib.util.spec_from_file_location("_lqs_a9_scorer_chk", _path)
    mod   = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = mod  # required before exec_module for @dataclass to work
    spec.loader.exec_module(mod)
    assert hasattr(mod, "score_a9")

check("LQS a9_scorer importable (deterministic scorer)", _check_a9_scorer)

check("LQS base_lqs ListingInput importable",
      lambda: __import__("marketplaces.base_lqs", fromlist=["ListingInput"]))

check("keyword_gap.agents importable",
      lambda: __import__("keyword_gap.agents", fromlist=["run_keyword_gap_analysis"]))

check("abd_optimizer.integration_bridge importable",
      lambda: __import__("abd_optimizer.integration_bridge",
                         fromlist=["get_lqs_scores", "get_missing_keywords"]))

# ── Env var checks ─────────────────────────────────────────────────────────────

provider = os.getenv("DEMO_LLM_PROVIDER", "openrouter")
check(f"DEMO_LLM_PROVIDER set ('{provider}')",
      lambda: None)  # always passes — just shows the value

_KEY_MAP = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "groq":       "GROQ_API_KEY",
}
_expected_key = _KEY_MAP.get(provider, "OPENROUTER_API_KEY")
check(f"{_expected_key} set",
      lambda: (_ for _ in ()).throw(EnvironmentError(f"{_expected_key} not set"))
              if not os.getenv(_expected_key) else None)

check("ZYTE_BASE_URL set",
      lambda: (_ for _ in ()).throw(EnvironmentError("ZYTE_BASE_URL not set"))
              if not os.getenv("ZYTE_BASE_URL") else None)

# ── File checks ────────────────────────────────────────────────────────────────

_model_path = os.path.join(_LQS, os.getenv("MODEL_PATH", "DataStore/models/lqs_model.pkl"))
check(f"LQS model file exists ({os.path.relpath(_model_path, _ROOT)})",
      lambda: (_ for _ in ()).throw(FileNotFoundError(f"not found: {_model_path}"))
              if not os.path.isfile(_model_path) else None)

check("abd_optimizer/integration_bridge.py exists",
      lambda: (_ for _ in ()).throw(FileNotFoundError("missing"))
              if not os.path.isfile(os.path.join(_ROOT, "abd_optimizer", "integration_bridge.py")) else None)

# ── Print results ──────────────────────────────────────────────────────────────

print()
print("SellerOS dependency check")
print("=" * 50)
for passed, label in results:
    icon = _ok if passed else _fail
    print(f"  {icon}  {label}")
print()

failures = sum(1 for p, _ in results if not p)
if failures == 0:
    print(f"{GREEN}All checks passed.{RESET}")
else:
    print(f"{RED}{failures} check(s) failed — fix the issues above before running ABD Optimizer.{RESET}")
    sys.exit(1)
