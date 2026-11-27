"""Scenario Lab fault, weather, and sensor injection engine."""

from .catalog import (
    catalog_metadata,
    get_catalog,
    get_entry,
    get_presets,
)
from .engine import (
    apply_physical_injections,
    apply_sensor_injections,
    has_physical_fault,
    weather_deltas,
)
from .envelopes import envelope
from .models import (
    CATEGORIES,
    CATEGORY_LABELS,
    EFFECT_OPS,
    PROGRESSION_KINDS,
    CatalogEntry,
    EffectSpec,
    Injection,
    Progression,
    WeatherInputSpec,
)
from .state import InjectionStore

__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "EFFECT_OPS",
    "PROGRESSION_KINDS",
    "CatalogEntry",
    "EffectSpec",
    "Injection",
    "InjectionStore",
    "Progression",
    "WeatherInputSpec",
    "apply_physical_injections",
    "apply_sensor_injections",
    "catalog_metadata",
    "envelope",
    "get_catalog",
    "get_entry",
    "get_presets",
    "has_physical_fault",
    "weather_deltas",
]
