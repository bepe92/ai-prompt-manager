"""Run a prompt against Claude and validate the response.

When validation fails we also fire a second, cheaper LLM call asking the model
to explain — in plain language — what went wrong. Was it the prompt, the
input, the model? This is what turns a red "FAILED" pill into something a
human can actually act on.
"""
import json
import os
import time
from dataclasses import dataclass, asdict
from anthropic import Anthropic

from .validator import PromptValidator

DEFAULT_TEST_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")


@dataclass
class TestResult:
    is_valid: bool
    errors: list[str]
    raw_output: str
    parsed_output: dict | None
    latency_ms: int
    model: str
    parse_error: str | None = None
    failure_analysis: str | None = None       # LLM-written explanation when test fails

    def to_dict(self) -> dict:
        return asdict(self)


EXPLAINER_SYSTEM_PROMPT = """Jesteś analitykiem jakości promptów. Otrzymasz cztery rzeczy:
1. Aktywny prompt który był testowany
2. Input testowy (to co dostał prompt)
3. Surową odpowiedź LLM-a
4. Listę błędów walidatora Pydantic

Twoje zadanie: napisz JEDEN paragraf po polsku (3-5 zdań) odpowiadający na pytania:
- CO konkretnie poszło nie tak (która część odpowiedzi nie pasuje do schematu)
- DLACZEGO prawdopodobnie się to stało — czy to wina:
  a) PROMPTU (instrukcja niejasna, brak reguły dla edge case)
  b) INPUTU (dane są niepełne/uszkodzone — w takim razie LLM/walidator zachował się POPRAWNIE odrzucając)
  c) LLM (model halucynował, zignorował instrukcję)
- CO TRADER/DEWELOPER POWINIEN ZROBIĆ — popraw prompt? zignoruj input? eskaluj?

Bądź zwięzły. Bez markdown, bez bullet points, czysta proza."""


class PromptTester:
    """Runs prompts against Claude and reports back what came out, validated."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_TEST_MODEL):
        self.client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def test(self, prompt: str, test_input: str, validation_schema: dict) -> TestResult:
        """Send (prompt, input) to Claude, parse JSON, validate against schema."""
        start = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=prompt,
            messages=[{"role": "user", "content": test_input}],
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        raw = response.content[0].text.strip()
        cleaned = _strip_fences(raw)

        parsed_output: dict | None = None
        parse_error: str | None = None
        try:
            parsed_output = json.loads(cleaned)
        except json.JSONDecodeError as e:
            parse_error = f"Model nie zwrócił poprawnego JSON: {e}"

        if parse_error or parsed_output is None:
            errors = [parse_error or "Brak JSON w odpowiedzi"]
            analysis = self._explain_failure(prompt, test_input, raw, errors)
            return TestResult(
                is_valid=False, errors=errors, raw_output=raw, parsed_output=None,
                latency_ms=latency_ms, model=self.model, parse_error=parse_error,
                failure_analysis=analysis,
            )

        validator = PromptValidator(validation_schema)
        is_valid, errors = validator.validate(parsed_output)
        analysis = None
        if not is_valid:
            analysis = self._explain_failure(prompt, test_input, raw, errors)

        return TestResult(
            is_valid=is_valid, errors=errors, raw_output=raw, parsed_output=parsed_output,
            latency_ms=latency_ms, model=self.model, failure_analysis=analysis,
        )

    def _explain_failure(self, prompt: str, test_input: str, raw_output: str,
                          errors: list[str]) -> str | None:
        """Second LLM call: ask Claude to explain why the test failed in plain Polish.

        Returns None if the explanation call itself fails — we don't want a
        broken explainer to mask the actual primary failure.
        """
        try:
            payload = (
                f"### Active prompt (system instruction sent to LLM)\n{prompt}\n\n"
                f"### Test input\n{test_input}\n\n"
                f"### Raw LLM output\n{raw_output}\n\n"
                f"### Validator errors\n" + "\n".join(f"- {e}" for e in errors)
            )
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                system=EXPLAINER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": payload}],
            )
            return response.content[0].text.strip()
        except Exception:
            return None


def _strip_fences(raw: str) -> str:
    """Models sometimes wrap JSON in ```json fences despite system prompt instructions."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    return s
