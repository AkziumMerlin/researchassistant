from __future__ import annotations

import sys
from typing import Any

_INSTALLED = False


def install() -> None:
    """Install resilient pipeline behavior into legacy entrypoints exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    from research_assistant import execution
    from research_assistant.adoption import adopt_job, maybe_adopt
    from research_assistant.jobs import JobService
    from research_assistant.launching import LocalSubprocessLauncher
    from research_assistant.pipeline_execution import execute_run_cached
    from research_assistant.pipeline_launcher import launch_resilient

    execution.execute_run = execute_run_cached
    cli_module = sys.modules.get("research_assistant.cli")
    if cli_module is not None:
        setattr(cli_module, "execute_run", execute_run_cached)

    LocalSubprocessLauncher.launch = launch_resilient  # type: ignore[method-assign]

    original_list = JobService.list
    original_detail = JobService.detail

    def list_with_adoption(self: JobService) -> list[dict[str, Any]]:
        return [maybe_adopt(self, row) for row in original_list(self)]

    def detail_with_adoption(
        self: JobService,
        job_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return maybe_adopt(self, original_detail(self, job_id, run_id))

    def adopt(self: JobService, job_id: str) -> dict[str, Any]:
        return adopt_job(self, job_id, require_live_worker=True)

    JobService.list = list_with_adoption  # type: ignore[method-assign]
    JobService.detail = detail_with_adoption  # type: ignore[method-assign]
    JobService.adopt = adopt  # type: ignore[attr-defined]
    _INSTALLED = True
