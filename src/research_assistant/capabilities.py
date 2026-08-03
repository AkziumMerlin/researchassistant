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


CAPABILITIES: tuple[Capability, ...] = (
    Capability("config.compose", "configuration", "Compose and validate configurations", "yes", "yes", "yes"),
    Capability("config.create", "configuration", "Create typed configurations", "yes", "yes", "yes"),
    Capability("model.graph", "models", "Design typed PyTorch graphs", "yes", "yes", "yes"),
    Capability("launch.local", "execution", "Launch local and SSH-backed experiments", "yes", "yes", "yes"),
    Capability("launch.durable", "execution", "Recover, adopt, retry and cancel detached launches", "yes", "yes", "yes", "experimental"),
    Capability("checkpoint.infer", "execution", "Inspect checkpoints and run inference", "yes", "yes", "yes"),
    Capability("run.workspace", "runs", "Browse studies, trials and runs", "yes", "yes", "yes", "experimental"),
    Capability("run.aggregate", "runs", "Aggregate arbitrary selected runs across studies", "yes", "yes", "yes", "experimental"),
    Capability("artifact.catalog", "artifacts", "Discover and catalog scientific artifacts", "yes", "yes", "yes"),
    Capability("artifact.preview", "artifacts", "Preview, slice, compare and trace artifact lineage", "yes", "yes", "yes", "experimental"),
    Capability("notebook.context", "analysis", "Open notebooks with selected run and artifact context", "yes", "yes", "yes", "experimental"),
    Capability("analysis.session", "analysis", "Run detached analysis sessions", "yes", "yes", "yes"),
    Capability("report.build", "reporting", "Build charts, tables and evaluation reports", "yes", "yes", "yes"),
    Capability("workspace.manage", "workspace", "Manage local and SSH workspaces and environments", "yes", "yes", "yes"),
    Capability("lifecycle.manage", "workspace", "Pin, archive, trash and restore results", "yes", "yes", "yes"),
    Capability("plugin.contract", "plugins", "Validate plugin compatibility contracts", "yes", "yes", "yes", "experimental"),
    Capability("schema.migrate", "plugins", "Migrate persisted configuration schemas", "yes", "yes", "yes", "experimental"),
    Capability("assistant.plan", "assistant", "Create typed, validated research plans", "yes", "yes", "yes", "experimental"),
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
