from __future__ import annotations

from dataclasses import dataclass

from beeline_issue_tracker.config import SpecialEffectsConfig
from beeline_issue_tracker.domain import LINE_DOWN, MachineSummary


MAX_INTENSITY_LEVEL = 5
SPECIAL_EFFECTS_ENABLED_KEY = "special_effects/enabled"
SPECIAL_EFFECTS_THRESHOLD_KEY = "special_effects/threshold"
SPECIAL_EFFECTS_INTENSITY_STEP_KEY = "special_effects/intensity_step"
SPECIAL_EFFECTS_FORCE_TEST_KEY = "special_effects/force_test"
SPECIAL_EFFECTS_TEST_INTENSITY_KEY = "special_effects/test_intensity"
SPECIAL_EFFECTS_STATIC_KEY = "special_effects/enable_static"
SPECIAL_EFFECTS_GLITCH_KEY = "special_effects/enable_glitch"
SPECIAL_EFFECTS_DROOP_DRIP_KEY = "special_effects/enable_droop_drip"
SPECIAL_EFFECTS_SMEAR_KEY = "special_effects/enable_smear"
SPECIAL_EFFECTS_CARD_IMPULSES_KEY = "special_effects/enable_card_impulses"
SPECIAL_EFFECTS_FALLING_DRIPS_KEY = "special_effects/enable_falling_drips"
SPECIAL_EFFECTS_DRIP_INTENSITY_KEY = "special_effects/drip_intensity"
SPECIAL_EFFECTS_GLITCH_IMPULSE_STRENGTH_KEY = "special_effects/glitch_impulse_strength"
SPECIAL_EFFECTS_REDUCED_MOTION_KEY = "special_effects/reduced_motion"


@dataclass(frozen=True)
class SpecialEffectsSettings:
    enabled: bool = True
    threshold: int = 6
    intensity_step: int = 1
    force_test: bool = False
    test_intensity: int = 3
    enable_static: bool = True
    enable_glitch: bool = True
    enable_droop_drip: bool = True
    enable_smear: bool = True
    enable_card_impulses: bool = True
    enable_falling_drips: bool = True
    drip_intensity: int = 3
    glitch_impulse_strength: int = 3
    reduced_motion: bool = False

    @classmethod
    def from_config(cls, config: SpecialEffectsConfig) -> "SpecialEffectsSettings":
        return cls(
            enabled=config.enabled,
            threshold=config.threshold,
            intensity_step=config.intensity_step,
            force_test=config.force_test,
            test_intensity=config.test_intensity,
            enable_static=config.enable_static,
            enable_glitch=config.enable_glitch,
            enable_droop_drip=config.enable_droop_drip,
            enable_smear=config.enable_smear,
            enable_card_impulses=config.enable_card_impulses,
            enable_falling_drips=config.enable_falling_drips,
            drip_intensity=config.drip_intensity,
            glitch_impulse_strength=config.glitch_impulse_strength,
            reduced_motion=config.reduced_motion,
        )


@dataclass(frozen=True)
class PlantDeteriorationState:
    down_count: int
    threshold: int
    overage: int
    effect_active: bool
    intensity_level: int
    effects_enabled: bool
    force_test: bool


def count_line_down_machines(machines: list[MachineSummary] | tuple[MachineSummary, ...]) -> int:
    return sum(1 for machine in machines if machine.calculated_status == LINE_DOWN)


def calculate_plant_deterioration(
    machines: list[MachineSummary] | tuple[MachineSummary, ...],
    settings: SpecialEffectsSettings,
) -> PlantDeteriorationState:
    return calculate_deterioration_state(count_line_down_machines(machines), settings)


def calculate_deterioration_state(
    down_count: int,
    settings: SpecialEffectsSettings,
) -> PlantDeteriorationState:
    down_count = max(0, int(down_count))
    threshold = max(0, int(settings.threshold))
    intensity_step = max(1, int(settings.intensity_step))
    overage = down_count - threshold

    if not settings.enabled:
        intensity_level = 0
    elif settings.force_test:
        intensity_level = _clamp_intensity(settings.test_intensity)
    elif down_count <= threshold:
        intensity_level = 0
    else:
        intensity_level = 1 + ((down_count - threshold - 1) // intensity_step)
        intensity_level = _clamp_intensity(intensity_level)

    return PlantDeteriorationState(
        down_count=down_count,
        threshold=threshold,
        overage=overage,
        effect_active=bool(settings.enabled and intensity_level > 0),
        intensity_level=intensity_level,
        effects_enabled=settings.enabled,
        force_test=settings.force_test,
    )


def load_special_effects_settings(qsettings, defaults: SpecialEffectsConfig) -> SpecialEffectsSettings:
    default_settings = SpecialEffectsSettings.from_config(defaults)
    return SpecialEffectsSettings(
        enabled=_bool_value(qsettings.value(SPECIAL_EFFECTS_ENABLED_KEY, default_settings.enabled), default_settings.enabled),
        threshold=_int_value(
            qsettings.value(SPECIAL_EFFECTS_THRESHOLD_KEY, default_settings.threshold),
            default_settings.threshold,
            minimum=0,
            maximum=100,
        ),
        intensity_step=_int_value(
            qsettings.value(SPECIAL_EFFECTS_INTENSITY_STEP_KEY, default_settings.intensity_step),
            default_settings.intensity_step,
            minimum=1,
            maximum=20,
        ),
        force_test=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_FORCE_TEST_KEY, default_settings.force_test),
            default_settings.force_test,
        ),
        test_intensity=_int_value(
            qsettings.value(SPECIAL_EFFECTS_TEST_INTENSITY_KEY, default_settings.test_intensity),
            default_settings.test_intensity,
            minimum=1,
            maximum=MAX_INTENSITY_LEVEL,
        ),
        enable_static=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_STATIC_KEY, default_settings.enable_static),
            default_settings.enable_static,
        ),
        enable_glitch=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_GLITCH_KEY, default_settings.enable_glitch),
            default_settings.enable_glitch,
        ),
        enable_droop_drip=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_DROOP_DRIP_KEY, default_settings.enable_droop_drip),
            default_settings.enable_droop_drip,
        ),
        enable_smear=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_SMEAR_KEY, default_settings.enable_smear),
            default_settings.enable_smear,
        ),
        enable_card_impulses=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_CARD_IMPULSES_KEY, default_settings.enable_card_impulses),
            default_settings.enable_card_impulses,
        ),
        enable_falling_drips=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_FALLING_DRIPS_KEY, default_settings.enable_falling_drips),
            default_settings.enable_falling_drips,
        ),
        drip_intensity=_int_value(
            qsettings.value(SPECIAL_EFFECTS_DRIP_INTENSITY_KEY, default_settings.drip_intensity),
            default_settings.drip_intensity,
            minimum=1,
            maximum=MAX_INTENSITY_LEVEL,
        ),
        glitch_impulse_strength=_int_value(
            qsettings.value(
                SPECIAL_EFFECTS_GLITCH_IMPULSE_STRENGTH_KEY,
                default_settings.glitch_impulse_strength,
            ),
            default_settings.glitch_impulse_strength,
            minimum=1,
            maximum=MAX_INTENSITY_LEVEL,
        ),
        reduced_motion=_bool_value(
            qsettings.value(SPECIAL_EFFECTS_REDUCED_MOTION_KEY, default_settings.reduced_motion),
            default_settings.reduced_motion,
        ),
    )


def save_special_effects_settings(qsettings, settings: SpecialEffectsSettings) -> None:
    qsettings.setValue(SPECIAL_EFFECTS_ENABLED_KEY, settings.enabled)
    qsettings.setValue(SPECIAL_EFFECTS_THRESHOLD_KEY, settings.threshold)
    qsettings.setValue(SPECIAL_EFFECTS_INTENSITY_STEP_KEY, settings.intensity_step)
    qsettings.setValue(SPECIAL_EFFECTS_FORCE_TEST_KEY, settings.force_test)
    qsettings.setValue(SPECIAL_EFFECTS_TEST_INTENSITY_KEY, settings.test_intensity)
    qsettings.setValue(SPECIAL_EFFECTS_STATIC_KEY, settings.enable_static)
    qsettings.setValue(SPECIAL_EFFECTS_GLITCH_KEY, settings.enable_glitch)
    qsettings.setValue(SPECIAL_EFFECTS_DROOP_DRIP_KEY, settings.enable_droop_drip)
    qsettings.setValue(SPECIAL_EFFECTS_SMEAR_KEY, settings.enable_smear)
    qsettings.setValue(SPECIAL_EFFECTS_CARD_IMPULSES_KEY, settings.enable_card_impulses)
    qsettings.setValue(SPECIAL_EFFECTS_FALLING_DRIPS_KEY, settings.enable_falling_drips)
    qsettings.setValue(SPECIAL_EFFECTS_DRIP_INTENSITY_KEY, settings.drip_intensity)
    qsettings.setValue(SPECIAL_EFFECTS_GLITCH_IMPULSE_STRENGTH_KEY, settings.glitch_impulse_strength)
    qsettings.setValue(SPECIAL_EFFECTS_REDUCED_MOTION_KEY, settings.reduced_motion)
    qsettings.sync()


def _clamp_intensity(value: int) -> int:
    return min(MAX_INTENSITY_LEVEL, max(0, int(value)))


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _int_value(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum or parsed > maximum:
        return default
    return parsed
