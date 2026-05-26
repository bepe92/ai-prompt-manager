"""Reusable prompt management for AI projects.

Import in your project:
    from prompt_manager import PromptManager, PromptTester, PromptValidator

    pm = PromptManager(prompts_root="path/to/prompts")
    record = pm.load("email-tracker", "extraction")
    print(record.active_prompt)
"""
from .manager import PromptManager, PromptRecord, PromptVersion, TestFixture
from .tester import PromptTester, TestResult
from .validator import PromptValidator

__all__ = [
    "PromptManager",
    "PromptRecord",
    "PromptVersion",
    "TestFixture",
    "PromptTester",
    "TestResult",
    "PromptValidator",
]
