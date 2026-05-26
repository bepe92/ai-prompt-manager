"""Run a prompt against Claude and validate the response.

The tester is the bridge between editor (where the user types a prompt) and
validator (where its output is checked). It's synchronous on purpose: the UI
calls it once per click, no need for async complexity here.
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

    def to_dict(self) -> dict:
        return asdict(self)


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
            return TestResult(
                is_valid=False,
                errors=[parse_error or "Brak JSON w odpowiedzi"],
                raw_output=raw,
                parsed_output=None,
                latency_ms=latency_ms,
                model=self.model,
                parse_error=parse_error,
            )

        validator = PromptValidator(validation_schema)
        is_valid, errors = validator.validate(parsed_output)
        return TestResult(
            is_valid=is_valid,
            errors=errors,
            raw_output=raw,
            parsed_output=parsed_output,
            latency_ms=latency_ms,
            model=self.model,
        )


def _strip_fences(raw: str) -> str:
    """Models sometimes wrap JSON in ```json fences despite system prompt instructions."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    return s
