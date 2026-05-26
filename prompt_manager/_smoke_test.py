"""Smoke test for the core modules — no Flask, no LLM, just the data layer + validator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from prompt_manager import PromptManager, PromptValidator

ROOT = Path(__file__).parent.parent
pm = PromptManager(ROOT / "prompts")

print("Projects:", pm.list_projects())
for proj in pm.list_projects():
    print(f"\n[{proj}]")
    for name in pm.list_prompts(proj):
        rec = pm.load(proj, name)
        print(f"  - {name:20s} v{rec.current_version}  ({rec.name})")

print("\n--- validator smoke test ---")
rec = pm.load("email-tracker", "extraction")
v = PromptValidator(rec.validation_schema)

cases = [
    ("happy path", {
        "broker": "Vitol", "product": "Brent Crude", "volume_mt": 45000,
        "price_usd": 82.45, "trade_date": "2026-05-25",
        "price_unit": "per barrel", "reference": "VT-001",
    }),
    ("missing required (price_usd)", {
        "broker": "Vitol", "product": "Brent Crude", "volume_mt": 45000,
        "trade_date": "2026-05-25",
    }),
    ("LLM hallucinated 'quantity'", {
        "broker": "Vitol", "product": "Brent Crude", "quantity": 45000,
        "price_usd": 82.45, "trade_date": "2026-05-25",
    }),
    ("bad date format", {
        "broker": "Vitol", "product": "Brent Crude", "volume_mt": 45000,
        "price_usd": 82.45, "trade_date": "25/05/2026",
    }),
    ("negative volume", {
        "broker": "Vitol", "product": "Brent Crude", "volume_mt": -45000,
        "price_usd": 82.45, "trade_date": "2026-05-25",
    }),
]

for label, payload in cases:
    ok, errors = v.validate(payload)
    status = "[OK]" if ok else "[FAIL]"
    print(f"  {status} {label}")
    for err in errors:
        print(f"        - {err}")
