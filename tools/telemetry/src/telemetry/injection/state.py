"""Session-scoped injection store with validation and JSON import/export."""

from __future__ import annotations

from typing import Any

from ..models import DEFAULT_TURBINE_ID, SCHEMA_VERSION, UNITS
from .catalog import get_entry
from .models import Injection, Progression, new_injection_id


def _validate_params(entry_type: str, raw_params: dict[str, Any] | None) -> dict[str, Any]:
    entry = get_entry(entry_type)
    params = dict(entry.default_params)
    if raw_params:
        params.update(raw_params)

    if entry.category == "sensor":
        signal = params.get("signal")
        if not isinstance(signal, str) or signal not in UNITS:
            raise ValueError(
                f"sensor injection '{entry_type}' requires a valid 'signal' in {sorted(UNITS)}"
            )
        for numeric_key in ("scale", "bias", "held_value"):
            if numeric_key in params and params[numeric_key] is not None:
                val = params[numeric_key]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise ValueError(f"param '{numeric_key}' must be numeric")
                if numeric_key == "scale" and float(val) < 0.0:
                    raise ValueError("param 'scale' must be non-negative")
                params[numeric_key] = float(val)
    return params


def build_injection(
    *,
    type_id: str,
    severity: float = 1.0,
    onset_asset_h: float | str | None = None,
    now_asset_h: float = 0.0,
    progression: Progression | dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    injection_id: str | None = None,
    existing_ids: set[str] | None = None,
) -> Injection:
    """Validate inputs and construct an immutable :class:`Injection`."""
    try:
        entry = get_entry(type_id)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc

    if onset_asset_h is None or onset_asset_h == "now":
        resolved_onset = max(0.0, float(now_asset_h))
    elif isinstance(onset_asset_h, bool) or not isinstance(onset_asset_h, (int, float)):
        raise ValueError("onset_asset_h must be a non-negative number or 'now'")
    else:
        resolved_onset = float(onset_asset_h)

    if progression is None:
        resolved_prog = entry.default_progression
    elif isinstance(progression, Progression):
        resolved_prog = progression
    elif isinstance(progression, dict):
        resolved_prog = Progression.from_dict(progression)
    else:
        raise ValueError("progression must be a mapping")

    resolved_params = _validate_params(type_id, params)

    taken = existing_ids or set()
    resolved_id = injection_id or new_injection_id()
    while resolved_id in taken:
        resolved_id = new_injection_id()

    return Injection(
        id=resolved_id,
        turbine_id=turbine_id or DEFAULT_TURBINE_ID,
        type=type_id,
        severity=float(severity),
        onset_asset_h=resolved_onset,
        progression=resolved_prog,
        params=resolved_params,
    )


class InjectionStore:
    """In-memory collection of active injections owned by :class:`SessionState`."""

    def __init__(self) -> None:
        self._items: list[Injection] = []

    def add(
        self,
        *,
        type_id: str,
        severity: float = 1.0,
        onset_asset_h: float | str | None = None,
        now_asset_h: float = 0.0,
        progression: Progression | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        turbine_id: str = DEFAULT_TURBINE_ID,
        injection_id: str | None = None,
    ) -> Injection:
        existing_ids = {item.id for item in self._items}
        injection = build_injection(
            type_id=type_id,
            severity=severity,
            onset_asset_h=onset_asset_h,
            now_asset_h=now_asset_h,
            progression=progression,
            params=params,
            turbine_id=turbine_id,
            injection_id=injection_id,
            existing_ids=existing_ids,
        )
        self._items.append(injection)
        return injection

    def list(self, turbine_id: str | None = None) -> tuple[Injection, ...]:
        if turbine_id is None:
            return tuple(self._items)
        return tuple(item for item in self._items if item.turbine_id == turbine_id)

    def for_turbine(self, turbine_id: str = DEFAULT_TURBINE_ID) -> tuple[Injection, ...]:
        target = turbine_id or DEFAULT_TURBINE_ID
        return tuple(item for item in self._items if item.turbine_id == target)

    def remove(self, injection_id: str) -> bool:
        for index, item in enumerate(self._items):
            if item.id == injection_id:
                del self._items[index]
                return True
        return False

    def clear(self, turbine_id: str | None = None) -> int:
        if turbine_id is None:
            count = len(self._items)
            self._items.clear()
            return count
        before = len(self._items)
        self._items = [item for item in self._items if item.turbine_id != turbine_id]
        return before - len(self._items)

    def export_payload(self, scenario: str = "nominal") -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "scenario": scenario,
            "injections": [item.to_dict() for item in self._items],
        }

    def import_payload(
        self, payload: dict[str, Any], now_asset_h: float = 0.0
    ) -> tuple[Injection, ...]:
        if not isinstance(payload, dict):
            raise ValueError("import payload must be a JSON object")
        raw_items = payload.get("injections")
        if not isinstance(raw_items, list):
            raise ValueError("import payload must contain an 'injections' list")

        imported: list[Injection] = []
        seen_ids: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError("each imported injection must be a JSON object")
            if "type" not in raw:
                raise ValueError("imported injection missing 'type'")
            inj = build_injection(
                type_id=str(raw["type"]),
                severity=raw.get("severity", 1.0),
                onset_asset_h=raw.get("onset_asset_h", 0.0),
                now_asset_h=now_asset_h,
                progression=raw.get("progression"),
                params=raw.get("params"),
                turbine_id=str(raw.get("turbine_id") or DEFAULT_TURBINE_ID),
                injection_id=raw.get("id"),
                existing_ids=seen_ids,
            )
            seen_ids.add(inj.id)
            imported.append(inj)

        self._items = imported
        return tuple(self._items)
