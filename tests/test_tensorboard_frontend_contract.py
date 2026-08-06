from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABS = ROOT / "desktop" / "research-assistant-extension" / "src" / "browser" / "tabs"


def test_reports_exposes_native_tensorboard_scalar_viewer() -> None:
    reports = (TABS / "reports-tab.ts").read_text(encoding="utf-8")
    panel = (TABS / "tensorboard-panel.ts").read_text(encoding="utf-8")

    assert "renderTensorBoardPanel" in reports
    assert "label: 'TensorBoard'" in reports
    assert "/api/tensorboard/catalog" in panel
    assert "/api/tensorboard/chart" in panel
    assert "events.out.tfevents.*" in panel
    assert "renderChart(view, chartVisual, result)" in panel
    assert "relative_time" in panel
    assert "smoothing" in panel
    assert "Select all" in panel
    assert "Common metrics" in panel
