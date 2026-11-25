"""The authored repair plans: data integrity, not model output."""

from __future__ import annotations

from telemetry import procedures
from telemetry.models import COMPONENT_IDS


def test_every_component_has_a_procedure() -> None:
    assert set(procedures.PROCEDURES) == set(COMPONENT_IDS)


def test_procedures_are_well_formed() -> None:
    for component_id, procedure in procedures.PROCEDURES.items():
        assert procedure.component_id == component_id
        assert procedure.title.strip()
        assert procedure.tools, f"{component_id} should list its tools"
        assert procedure.safety, f"{component_id} should list its safety notes"

        step_ids = procedure.step_ids()
        assert len(step_ids) >= 4
        assert len(step_ids) == len(set(step_ids)), "step ids must be unique"
        assert procedure.steps[0].safety, "isolation must be the first step"
        assert procedure.safety_ids(), "every procedure needs at least one safety step"

        for step in procedure.steps:
            assert step.action.strip()
            assert step.detail.strip()
            if step.tool is not None:
                assert step.tool in procedure.tools, f"{step.id} uses an unlisted tool"


def test_unknown_component_falls_back_to_the_gearbox() -> None:
    assert procedures.for_component("reactor_core") is procedures.PROCEDURES["gearbox"]


def test_disclaimer_is_present() -> None:
    assert "not a certified" in procedures.DISCLAIMER.lower()
