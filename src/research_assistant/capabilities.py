from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

SurfaceState = Literal["yes", "partial", "no", "internal"]
Stability = Literal["stable", "experimental", "internal"]


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    domain: str
    title: str
    cli: SurfaceState
    api: SurfaceState
    ui: SurfaceState
    stability: Stability = "stable"
    notes: str = ""


def _capability(
    capability_id: str,
    domain: str,
    title: str,
    *,
    stability: Stability = "stable",
) -> Capability:
    return Capability(
        capability_id=capability_id,
        domain=domain,
        title=title,
        cli="yes",
        api="yes",
        ui="yes",
        stability=stability,
    )


CAPABILITIES: tuple[Capability, ...] = (
    _capability(
        "config.compose",
        "configuration",
        "Compose and validate configurations",
    ),
    _capability("config.create", "configuration", "Create typed configurations"),
    _capability("model.graph", "models", "Design typed PyTorch graphs"),
    _capability(
        "launch.local",
        "execution",
        "Launch local and SSH-backed experiments",
    ),
    _capability(
        "launch.durable",
        "execution",
        "Recover, adopt, retry and cancel detached launches",
        stability="experimental",
    ),
    _capability(
        "checkpoint.infer",
        "execution",
        "Inspect checkpoints and run inference",
    ),
    _capability(
        "run.workspace",
        "runs",
        "Browse studies, trials and runs",
        stability="experimental",
    ),
    _capability(
        "run.aggregate",
        "runs",
        "Aggregate arbitrary selected runs across studies",
        stability="experimental",
    ),
    _capability(
        "artifact.catalog",
        "artifacts",
        "Discover and catalog scientific artifacts",
    ),
    _capability(
        "artifact.preview",
        "artifacts",
        "Preview, slice, compare and trace artifact lineage",
        stability="experimental",
    ),
    _capability(
        "notebook.context",
        "analysis",
        "Open notebooks with selected run and artifact context",
        stability="experimental",
    ),
    _capability(
        "analysis.session",
        "analysis",
        "Run detached analysis sessions",
    ),
    _capability(
        "report.build",
        "reporting",
        "Build charts, tables and evaluation reports",
    ),
    _capability(
        "workspace.manage",
        "workspace",
        "Manage local and SSH workspaces and environments",
    ),
    _capability(
        "lifecycle.manage",
        "workspace",
        "Pin, archive, trash and restore results",
    ),
    _capability(
        "plugin.contract",
        "plugins",
        "Validate plugin compatibility contracts",
        stability="experimental",
    ),
    _capability(
        "schema.migrate",
        "plugins",
        "Migrate persisted configuration schemas",
        stability="experimental",
    ),
    _capability(
        "assistant.plan",
        "assistant",
        "Create typed, validated research plans",
        stability="experimental",
    ),
)


def validate_capabilities(capabilities: tuple[Capability, ...] = CAPABILITIES) -> None:
    identifiers = [item.capability_id for item in capabilities]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("capability identifiers must be unique")
    for item in capabilities:
        if item.stability == "internal":
            continue
        if item.cli == "no" or item.api == "no" or item.ui == "no":
            raise ValueError(
                f"public capability {item.capability_id!r} must declare every user surface; "
                "use 'partial' while an interface is intentionally incomplete"
            )


def capability_matrix() -> dict[str, object]:
    validate_capabilities()
    rows = [asdict(item) for item in CAPABILITIES]
    totals = {
        surface: sum(row[surface] == "yes" for row in rows)
        for surface in ("cli", "api", "ui")
    }
    return {
        "schema_version": 1,
        "capabilities": rows,
        "totals": totals,
        "complete": all(
            row[surface] in {"yes", "internal"}
            for row in rows
            for surface in ("cli", "api", "ui")
        ),
    }
