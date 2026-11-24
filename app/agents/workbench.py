"""The one place that decides whether an agent gets the code workbench (the
provider's code sandbox, backend-plan section 4.2).

It combines, in order: the caller's choice, the Settings switch
`code_workbench`, whether the model can carry the provider's code tool here
(`factory.code_tool_supported`), and for Claude the Settings switch
`claude_sandbox_real_documents`, off by default (owner, 18 November 2026:
Claude's sandbox is for test documents only, since data in it is outside
zero retention).

Step 4 uses the workbench for calculation only: no file is put in the
sandbox, so the agent types in the numbers it works on. Giving it the
pages and the template is deferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from app.models import factory


@dataclass(frozen=True)
class Workbench:
    on: bool
    why: str   # one plain sentence, for the instructions and the run's events


def decide(model_id: str, *, wanted: bool = True, settings: Optional[Mapping[str, Any]] = None) -> Workbench:
    if settings is None:
        from app.settings import store

        settings = store.read()
    if not wanted:
        return Workbench(False, "The code workbench is not used for this agent.")
    if not settings.get("code_workbench", True):
        return Workbench(False, "The code workbench is switched off on the Settings page.")
    if not factory.code_tool_supported(model_id):
        return Workbench(False, f"{model_id} cannot use the code workbench on this machine's connection.")
    if factory.provider_of(model_id) == "anthropic" and not settings.get("claude_sandbox_real_documents", False):
        return Workbench(False, "Claude's code sandbox is kept for test documents, and the Settings switch "
                                "that allows it is off.")
    return Workbench(True, "The code workbench is on.")
