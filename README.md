# AI Prompt Manager

A reusable, file-backed prompt management tool that works with **every** AI project in this portfolio. Edit prompts, test them against Claude with one click, validate their JSON output against a per-prompt Pydantic schema, and keep an immutable version history — all without grepping through source code.

This is the **meta-project**: the others build features, this one builds the workflow for safely evolving the LLM logic those features depend on.

## The Problem

Every project in this portfolio has at least one production-critical prompt:
- [`ai-email-trade-tracker`](https://github.com/bepe92/ai-email-trade-tracker) — email extraction prompt in `src/parser.py`
- [`ai-pdf-trade-parser`](https://github.com/bepe92/ai-pdf-trade-parser) — Vision extraction prompt in `src/parser.py`
- [`ai-ecommerce-ops-assistant`](https://github.com/bepe92/ai-ecommerce-ops-assistant) — 5 distinct agent prompts, one per file

Without tooling, editing those prompts means:
1. Opening the source file
2. Editing a triple-quoted string buried in Python
3. Manually running a test script
4. Forgetting what the previous version said when the new one regresses
5. Hoping no one else changed the same file in the meantime

Prompt engineering is a real discipline. It deserves real tooling.

## The Solution

```
┌──────────────────────────────────────────────────────────────────┐
│                       prompts/                                    │
│    ├── email-tracker/extraction.json                              │
│    ├── pdf-parser/extraction.json                                 │
│    └── ecommerce-ops/                                             │
│         ├── price_anomaly.json                                    │
│         ├── deals_anomaly.json                                    │
│         ├── sales_anomaly.json                                    │
│         ├── event_manager.json                                    │
│         └── click_spike.json                                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │  (each file: active prompt + schema + version history)
                             ▼
                ┌────────────────────────────┐
                │  prompt_manager (pure py)  │   importable in any project:
                │  ├── PromptManager         │     from prompt_manager import PromptManager
                │  ├── PromptValidator       │     pm = PromptManager("path/to/prompts")
                │  └── PromptTester          │     prompt = pm.get_active_prompt("email-tracker", "extraction")
                └────────────┬───────────────┘
                             │
                             ▼
                ┌────────────────────────────┐
                │  Flask UI (3 tabs)         │
                │  📝 Editor                  │
                │  ⚗️  Tester                  │
                │  🕓 History                 │
                └────────────────────────────┘
```

### The three tabs

| Tab | What it does |
|---|---|
| **📝 Editor** | Pick a project + a prompt. Edit the active prompt in a big textarea. Add a note ("dodano obsługę emaili w języku norweskim"). Save as a new version — the previous one stays in history, the new one becomes active. |
| **⚗️ Tester** | Pick a **test fixture** from the dropdown (or paste your own input), click Run. See raw Claude output, parsed JSON, and a green PASSED / red FAILED pill from the per-prompt Pydantic validator. Pass/fail outcome is recorded on the active version. |
| **🕓 History** | Every version ever saved, newest first. Each has its note, timestamp, test outcome, and one click to **restore** it as the active version. Nothing is ever overwritten. |

### Test fixtures — regression suite that lives with the prompt

Each prompt JSON ships with a `test_fixtures` array — predefined `(input, expected_outcome)` pairs that the Tester loads via a dropdown. No copy-pasting examples from chat logs or scratchpads.

Four outcome categories shipped:

| Outcome | What it means | Why a good prompt should have these |
|---|---|---|
| `pass` ✅ | Happy path; LLM extracts correctly and Pydantic accepts. | Baseline — prove the prompt works at all. |
| `fail_validation` ❌ | LLM behaves correctly (e.g. returns `null` for missing data) but Pydantic rejects because required fields are empty. | The GOOD failure — pipeline deliberately blocks incomplete data instead of fabricating it. |
| `fail_parse` ❌ | LLM returned malformed/non-JSON output. Pipeline must not crash. | Tests defensive parsing for garbage inputs, adversarial inputs, model regressions. |
| `false_positive` ⚠️ | Pydantic accepts but the data is semantically wrong. | **The most important category** — proves the limit of structural validation and why human-in-the-loop is non-optional. |

```json
"test_fixtures": [
  {
    "id": "mercuria-tbd-price",
    "label": "Mercuria — price TBD (should auto-reject)",
    "description": "Tests null-over-guessing rule. Price marked TBD; LLM must return null; validator must reject.",
    "input": "From: deals-desk@mercuria-energy.com\n...",
    "expected_outcome": "fail_validation",
    "expected_notes": "price_usd is None → validator complaints 'price_usd nie jest liczbą'"
  }
]
```

This solves three real problems:
- **No memory loss.** Test inputs travel with the prompt in git; the dropdown is the same on every machine that clones the repo.
- **Cheap regression checking.** Edit prompt → load fixture → click Run → compare to `expected_outcome`. ~$0.001 per test on Haiku 4.5.
- **Self-documenting failure modes.** Browsing the dropdown is a guided tour of every weird case the prompt was designed to handle.

In production this is where you'd plug in a golden dataset of real anonymised inputs, run them all on every prompt activation, and refuse to promote a prompt to prod if any regression fixture flips from `pass` to `fail_validation`.

### Failure analysis — second LLM explains what broke

When a test fails validation, the Tester fires a second cheap Claude call asking the model to write a one-paragraph explanation in plain Polish:
- **WHAT** went wrong (which field, which rule)
- **WHY** it happened — bad prompt, bad input, or model regression?
- **WHAT** the trader/dev should do — fix the prompt, ignore the input, escalate?

This turns a red `FAILED` pill from "your test broke" into "your test correctly caught X because Y — here's what to do next". Costs ~$0.001 per failed test on Haiku 4.5.

### The `false_positive` category — limit of structural validation

A `false_positive` fixture is one where **Pydantic accepts the output** but the data is semantically wrong. Examples shipped in the repo:

- **email-tracker**: a trader forwarded a year-old confirmation. All fields present, schema valid, but the trade date is from 2025 — not a new deal. A human sees "FWD: …" in the subject and rejects; the validator never had a chance.
- **deals_anomaly**: a deal references `product_id: "FAKE-PROD-999"` which doesn't exist in the catalog. Structurally fine, semantically broken — needs cross-check against the product DB.
- **click_spike**: a 900% click spike that's actually bot scraping, not viral traffic. Numbers look organic to the LLM; only an anti-bot signal would reveal the truth.

These fixtures exist to demonstrate a fundamental point: **structural validation (Pydantic) catches FORM errors. Semantic validation requires either domain knowledge, cross-references to other systems, or a human review step.** That's why every project in this portfolio routes valid extractions to a *pending* queue for trader sign-off — the validator is necessary but not sufficient. The trader's eye comparing extracted data against the original source is the only defense against this category of failure.

In an interview this is the strongest signal of architectural maturity you can give: *"I know what my validator catches AND what it doesn't, and I designed the workflow accordingly."*

### Honest answer to "but your prompts are tuned to demo data"

Yes — and that's exactly why this tooling exists. The production workflow is:

1. Collect a real dataset from production (100–500 representative documents)
2. Hand-annotate to establish ground truth
3. Iterate the prompt against that dataset — measure accuracy, hallucination rate, token cost
4. Deploy with monitoring; sample real outputs periodically
5. When a new edge case appears, add it as a fixture and re-run the whole regression suite

Steps 3 and 5 are exactly what the Editor + Tester + History triad makes cheap. Without this kind of harness, prompt engineering is folklore. With it, it's iterative software development with a contract, a test suite, and a rollback.

## Design rules visible in code

| Rule | Where |
|---|---|
| **Core is pure Python — Flask is just one frontend** | `prompt_manager/` has no Flask import. You can `from prompt_manager import PromptManager` from anywhere. |
| **Validation schema lives next to the prompt** | Each `*.json` file includes its own `validation_schema` — when the prompt changes, its contract is right there too. |
| **Pydantic models built at runtime from a JSON DSL** | `validator.py` translates `{"required_fields": [...], "field_types": {...}, "extra_forbidden": true}` into a real Pydantic `BaseModel` via `create_model()`. |
| **Immutable history** | `save_new_version()` only appends. The previous version is never lost. Restore is one click. |
| **Atomic writes** | `manager.py` writes via tmp + rename so a crashed process can't corrupt the JSON file. |
| **Per-prompt test outcome** | Every Tester run records `test_passed`, `test_input`, `test_output` on the active version — provable answer to "did anyone try this prompt before deploying it?" |

## Tech stack

- **Python 3.12**
- **Pydantic 2** — runtime model construction via `create_model` from JSON spec
- **Anthropic Claude API** — Haiku 4.5 by default for the Tester (overridable via `TEST_MODEL` env)
- **Flask 3** — single-file UI with three tabs
- No DB — everything on disk as human-readable JSON

## Quick start

```bash
# 1. Clone
git clone https://github.com/bepe92/ai-prompt-manager.git
cd ai-prompt-manager

# 2. Virtual env
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux

# 3. Install
pip install -r requirements.txt

# 4. Configure
copy .env.example .env           # Windows
# cp .env.example .env           # macOS/Linux
# edit .env and paste your Anthropic API key

# 5. Start the UI (auto-opens at http://localhost:5005)
python app.py
```

The repo already ships with prompts for the three sibling projects so you have something to look at on first run.

## How to plug it into your own AI project (3 steps)

Say you have an existing project with a hard-coded prompt in `src/parser.py`:

```python
SYSTEM_PROMPT = """Jesteś asystentem ..."""

def parse(text):
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        system=SYSTEM_PROMPT,
        ...
    )
```

To swap to the prompt manager:

**Step 1.** Move the prompt to a JSON file (one of the existing examples is a good template):

```
prompts/my-project/extraction.json
```

with the prompt under `active_prompt` and a `validation_schema` describing your expected output.

**Step 2.** Install this package as an editable dependency in your project:

```bash
pip install -e /path/to/ai-prompt-manager
```

**Step 3.** Replace the constant with a lookup:

```python
from prompt_manager import PromptManager

pm = PromptManager("/path/to/ai-prompt-manager/prompts")

def parse(text):
    prompt = pm.get_active_prompt("my-project", "extraction")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        system=prompt,
        ...
    )
```

That's it. Now any prompt edit in the manager UI is picked up on the next call. No redeploy, no source change.

## What would change for production

This is intentionally a developer-grade tool. Real corporate deployment swaps a few things:

| Demo | Production |
|---|---|
| Filesystem JSON under `prompts/` | **Azure Blob Storage** container with versioning enabled; manager reads/writes through a blob client |
| Single-user, no auth | **Role-based access** — trader can edit + test, only senior manager can activate a new version |
| Direct activation | **Approval workflow** — every prompt change is a draft until a second person approves; production prompts cannot be edited without sign-off |
| `secret_key = "dev"` Flask cookie | **Entra ID (Azure AD) SSO** with group-based RBAC |
| API key in `.env` | **Azure Key Vault** + Managed Identity — no secrets on disk |
| Test outcome stored on the version | **Append-only audit log** in Azure Data Lake — every edit, test, and activation logged with `who`, `when`, `from`, `to`, `test_outcome`. SOX-friendly. |
| Manual testing | **Scheduled eval suite** — every active prompt re-runs nightly against a golden dataset; failures alert on Teams |
| One Claude model | **Multi-model A/B** — same prompt tested against Haiku / Sonnet / Opus to find the cheapest acceptable tier |
| One environment | **Dev/Staging/Prod** prompt sets — promoted via approval, not copy-pasted |

## Why this matters

Most teams treat prompts like configuration constants. They aren't. A prompt is a piece of logic with a contract, a failure mode, and a regression surface. Treating it like code — with versioning, testing, review, and rollback — is the difference between an LLM feature that gets steadily better and one that breaks silently every six weeks when someone "just tweaked it real quick".

## Project layout

```
.
├── prompt_manager/              # Pure Python — importable in other projects
│   ├── __init__.py
│   ├── manager.py               # PromptManager: load/save/version
│   ├── validator.py             # PromptValidator: Pydantic from JSON DSL
│   ├── tester.py                # PromptTester: Claude call + validate
│   └── _smoke_test.py           # Sanity check, no LLM call
├── prompts/                     # File-backed prompt store
│   ├── email-tracker/extraction.json
│   ├── pdf-parser/extraction.json
│   └── ecommerce-ops/
│       ├── price_anomaly.json
│       ├── deals_anomaly.json
│       ├── sales_anomaly.json
│       ├── event_manager.json
│       └── click_spike.json
├── templates/                   # Editor / Tester / History
├── static/style.css
├── app.py                       # Flask UI
└── .env                         # (gitignored)
```

## Roadmap

- [ ] Diff view: side-by-side compare of any two versions of the same prompt
- [ ] A/B testing: run the same input through two prompt versions and compare outputs
- [ ] Eval suite hooks: define a golden dataset per prompt; auto-run on every save
- [ ] Multi-model testing: pick which Claude tier the Tester uses per run
- [ ] Approval workflow (production-mode feature flag): edits create drafts that need a second reviewer
- [ ] Webhook: notify Teams/Slack when a prompt is activated in production

## License

Personal project for portfolio / interview demonstration. No license granted for production use.
