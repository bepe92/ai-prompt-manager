"""Core prompt management — pure Python, no Flask, importable in other projects.

Each prompt is a JSON file under prompts/<project>/<name>.json with this shape:

    {
      "name": "Email Extraction",
      "project": "email-tracker",
      "current_version": 3,
      "active_prompt": "...",
      "validation_schema": {...},
      "versions": [
        {
          "version": 1,
          "prompt": "...",
          "saved_at": "ISO8601",
          "note": "human-readable note",
          "test_passed": true | false | null,
          "test_input": "..." | null,
          "test_output": {...} | null
        }
      ]
    }

Immutability rule:
  We NEVER overwrite a version in the versions[] list. save_new_version appends
  a new entry and bumps current_version. This is what makes the history view
  useful — every prompt change is preserved, every "I broke production last week"
  is recoverable by activating an older version.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PromptVersion:
    version: int
    prompt: str
    saved_at: str
    note: str = ""
    test_passed: bool | None = None      # None = never tested
    test_input: str | None = None
    test_output: dict | None = None


@dataclass
class TestFixture:
    """A canned (input, expected outcome) pair used for regression testing a prompt.

    Stored next to the prompt in the same JSON file, so a prompt and its
    regression suite move together through git. Updating the prompt? Re-run
    every fixture from the UI dropdown — no copy-pasting from a chat history.
    """
    id: str
    label: str                                  # human-readable name shown in the dropdown
    description: str = ""                       # one-sentence explanation of the case
    input: str = ""                             # the text/JSON to feed to the prompt
    expected_outcome: str = "pass"              # "pass" | "fail_validation" | "fail_parse"
    expected_notes: str = ""                    # what the trader should look for


@dataclass
class PromptRecord:
    name: str
    project: str
    current_version: int
    active_prompt: str
    validation_schema: dict[str, Any]
    versions: list[PromptVersion] = field(default_factory=list)
    test_fixtures: list[TestFixture] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "project": self.project,
            "current_version": self.current_version,
            "active_prompt": self.active_prompt,
            "validation_schema": self.validation_schema,
            "versions": [asdict(v) for v in self.versions],
            "test_fixtures": [asdict(f) for f in self.test_fixtures],
        }


class PromptManager:
    """Filesystem-backed prompt store with immutable version history."""

    def __init__(self, prompts_root: str | Path):
        self.root = Path(prompts_root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- discovery ----------
    def list_projects(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def list_prompts(self, project: str) -> list[str]:
        proj_dir = self.root / project
        if not proj_dir.exists():
            return []
        return sorted(p.stem for p in proj_dir.glob("*.json"))

    # ---------- read ----------
    def load(self, project: str, name: str) -> PromptRecord:
        path = self._path(project, name)
        if not path.exists():
            raise FileNotFoundError(f"No such prompt: {project}/{name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._record_from_dict(data)

    def get_active_prompt(self, project: str, name: str) -> str:
        """Convenience for downstream apps — what's the LIVE prompt right now?"""
        return self.load(project, name).active_prompt

    # ---------- write ----------
    def save_new_version(
        self,
        project: str,
        name: str,
        prompt: str,
        note: str = "",
        test_passed: bool | None = None,
        test_input: str | None = None,
        test_output: dict | None = None,
    ) -> int:
        """Append a new version and make it the active one. Never overwrites."""
        record = self.load(project, name)
        new_version_num = record.current_version + 1
        new_version = PromptVersion(
            version=new_version_num,
            prompt=prompt,
            saved_at=_now_iso(),
            note=note,
            test_passed=test_passed,
            test_input=test_input,
            test_output=test_output,
        )
        record.versions.append(new_version)
        record.current_version = new_version_num
        record.active_prompt = prompt
        self._write(project, name, record)
        return new_version_num

    def activate_version(self, project: str, name: str, version: int) -> PromptRecord:
        """Set an existing historical version as active. The full history is preserved."""
        record = self.load(project, name)
        target = next((v for v in record.versions if v.version == version), None)
        if target is None:
            raise ValueError(f"Version {version} not found in {project}/{name}")
        record.active_prompt = target.prompt
        record.current_version = version
        self._write(project, name, record)
        return record

    def update_test_outcome(
        self,
        project: str,
        name: str,
        version: int,
        test_passed: bool,
        test_input: str | None = None,
        test_output: dict | None = None,
    ) -> PromptRecord:
        """Record the result of a Tester run against a specific version."""
        record = self.load(project, name)
        for v in record.versions:
            if v.version == version:
                v.test_passed = test_passed
                if test_input is not None:
                    v.test_input = test_input
                if test_output is not None:
                    v.test_output = test_output
                break
        else:
            raise ValueError(f"Version {version} not found in {project}/{name}")
        self._write(project, name, record)
        return record

    def create_new_prompt(
        self,
        project: str,
        name: str,
        display_name: str,
        initial_prompt: str,
        validation_schema: dict[str, Any],
        note: str = "initial version",
    ) -> PromptRecord:
        """Create a brand-new prompt file. Useful for onboarding a new project."""
        path = self._path(project, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Prompt already exists: {project}/{name}")
        record = PromptRecord(
            name=display_name,
            project=project,
            current_version=1,
            active_prompt=initial_prompt,
            validation_schema=validation_schema,
            versions=[PromptVersion(
                version=1, prompt=initial_prompt, saved_at=_now_iso(), note=note,
            )],
        )
        self._write(project, name, record)
        return record

    # ---------- internals ----------
    def _path(self, project: str, name: str) -> Path:
        return self.root / project / f"{name}.json"

    def _write(self, project: str, name: str, record: PromptRecord):
        path = self._path(project, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write — tmp then rename. Prevents corruption if the process dies mid-save.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    @staticmethod
    def _record_from_dict(data: dict) -> PromptRecord:
        return PromptRecord(
            name=data["name"],
            project=data["project"],
            current_version=data["current_version"],
            active_prompt=data["active_prompt"],
            validation_schema=data.get("validation_schema", {}),
            versions=[PromptVersion(**v) for v in data.get("versions", [])],
            test_fixtures=[TestFixture(**f) for f in data.get("test_fixtures", [])],
        )

    def get_fixture(self, project: str, name: str, fixture_id: str) -> "TestFixture | None":
        record = self.load(project, name)
        return next((f for f in record.test_fixtures if f.id == fixture_id), None)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
