"""Loader and validator for the declarative Scenario Lab catalog."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..models import COMPONENT_IDS, UNITS
from .models import (
    CATEGORIES,
    CATEGORY_LABELS,
    EFFECT_OPS,
    CatalogEntry,
    EffectSpec,
    Progression,
    WeatherInputSpec,
)

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")
WEATHER_INPUTS = ("wind_speed_ms", "ambient_temp_c")
SENSOR_KINDS = ("stuck", "dropout", "noise_burst", "bias_drift")


def _parse_entry(entry_id: str, raw: dict[str, Any]) -> CatalogEntry:
    category = str(raw["category"])
    if category not in CATEGORIES:
        raise ValueError(f"catalog entry '{entry_id}' has unknown category '{category}'")

    target = raw.get("target_component")
    if target is not None and target not in COMPONENT_IDS:
        raise ValueError(
            f"catalog entry '{entry_id}' has unknown target_component '{target}'"
        )

    effects: list[EffectSpec] = []
    for item in raw.get("effects") or ():
        signal = str(item["signal"])
        if signal not in UNITS:
            raise ValueError(
                f"catalog entry '{entry_id}' references unknown signal '{signal}'"
            )
        op = str(item["op"])
        if op not in EFFECT_OPS:
            raise ValueError(
                f"catalog entry '{entry_id}' has unsupported op '{op}'"
            )
        effects.append(
            EffectSpec(
                signal=signal,
                op=op,
                magnitude=float(item["magnitude"]),
                harmonic=item.get("harmonic"),
            )
        )

    weather_inputs: list[WeatherInputSpec] = []
    for item in raw.get("weather_inputs") or ():
        input_name = str(item["input"])
        if input_name not in WEATHER_INPUTS:
            raise ValueError(
                f"catalog entry '{entry_id}' has unknown weather input '{input_name}'"
            )
        op = str(item["op"])
        if op not in ("add", "mul"):
            raise ValueError(
                f"catalog entry '{entry_id}' has unsupported weather op '{op}'"
            )
        weather_inputs.append(
            WeatherInputSpec(
                input=input_name,
                op=op,
                magnitude=float(item["magnitude"]),
            )
        )

    sensor_kind = raw.get("sensor_kind")
    if sensor_kind is not None and sensor_kind not in SENSOR_KINDS:
        raise ValueError(
            f"catalog entry '{entry_id}' has unknown sensor_kind '{sensor_kind}'"
        )

    default_params = dict(raw.get("default_params") or {})
    if "signal" in default_params and default_params["signal"] not in UNITS:
        raise ValueError(
            f"catalog entry '{entry_id}' default signal '{default_params['signal']}' is unknown"
        )

    return CatalogEntry(
        id=entry_id,
        label=str(raw["label"]),
        category=category,
        description=str(raw.get("description", "")),
        target_component=target,
        default_progression=Progression.from_dict(raw.get("default_progression") or {}),
        default_params=default_params,
        effects=tuple(effects),
        weather_inputs=tuple(weather_inputs),
        sensor_kind=sensor_kind,
        special=raw.get("special"),
    )


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("catalog.yaml must parse to a mapping")
    return data


@lru_cache(maxsize=1)
def get_catalog() -> dict[str, CatalogEntry]:
    """Return the validated catalog keyed by scenario type id."""
    raw = _load_raw()
    entries_raw = raw.get("entries") or {}
    return {
        entry_id: _parse_entry(entry_id, spec)
        for entry_id, spec in entries_raw.items()
    }


def get_entry(type_id: str) -> CatalogEntry:
    catalog = get_catalog()
    if type_id not in catalog:
        raise KeyError(f"unknown injection type '{type_id}'")
    return catalog[type_id]


@lru_cache(maxsize=1)
def get_presets() -> tuple[dict[str, Any], ...]:
    """Return one-click Scenario Lab demo presets from ``catalog.yaml``."""
    raw = _load_raw()
    presets = raw.get("presets") or []
    catalog = get_catalog()
    validated: list[dict[str, Any]] = []
    for preset in presets:
        for inj in preset.get("injections") or ():
            if inj.get("type") not in catalog:
                raise ValueError(
                    f"preset '{preset.get('id')}' references unknown type '{inj.get('type')}'"
                )
        validated.append(dict(preset))
    return tuple(validated)


def catalog_metadata() -> dict[str, Any]:
    """Payload returned by ``GET /api/inject/catalog``."""
    catalog = get_catalog()
    return {
        "categories": [
            {"id": category, "label": CATEGORY_LABELS[category]}
            for category in CATEGORIES
        ],
        "signals": list(UNITS.keys()),
        "entries": [entry.to_dict() for entry in catalog.values()],
        "presets": list(get_presets()),
    }
