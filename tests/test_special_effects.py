from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtCore import QPointF

from beeline_issue_tracker.config import DEFAULT_SPECIAL_PIN_HASH, load_runtime_config
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, NO_ISSUES, MachineSummary
from beeline_issue_tracker.permissions import can_open_special
from beeline_issue_tracker.special import (
    SpecialEffectsSettings,
    calculate_deterioration_state,
    calculate_plant_deterioration,
    load_special_effects_settings,
    save_special_effects_settings,
)
from beeline_issue_tracker.ui_special_effects import (
    CardGlitchState,
    FallingDrip,
    build_falling_drip,
    falling_drip_allowed,
    falling_drip_period_frames,
    initial_card_glitch_state,
    is_card_in_burst,
    status_effect_weight,
    update_card_glitch_state,
    update_falling_drip,
)


class SpecialEffectsStateTest(unittest.TestCase):
    def test_threshold_of_six_starts_at_seven_not_six(self) -> None:
        settings = SpecialEffectsSettings(threshold=6, intensity_step=1)

        at_threshold = calculate_deterioration_state(6, settings)
        over_threshold = calculate_deterioration_state(7, settings)

        self.assertFalse(at_threshold.effect_active)
        self.assertEqual(0, at_threshold.intensity_level)
        self.assertTrue(over_threshold.effect_active)
        self.assertEqual(1, over_threshold.intensity_level)

    def test_intensity_step_and_clamp(self) -> None:
        settings = SpecialEffectsSettings(threshold=6, intensity_step=2)

        self.assertEqual(1, calculate_deterioration_state(8, settings).intensity_level)
        self.assertEqual(2, calculate_deterioration_state(9, settings).intensity_level)
        self.assertEqual(5, calculate_deterioration_state(99, settings).intensity_level)

    def test_force_and_disable_behavior(self) -> None:
        forced = calculate_deterioration_state(
            0,
            SpecialEffectsSettings(force_test=True, test_intensity=4),
        )
        disabled = calculate_deterioration_state(
            20,
            SpecialEffectsSettings(enabled=False, force_test=True, test_intensity=4),
        )

        self.assertTrue(forced.effect_active)
        self.assertEqual(4, forced.intensity_level)
        self.assertFalse(disabled.effect_active)
        self.assertEqual(0, disabled.intensity_level)

    def test_line_down_count_uses_exact_machine_status(self) -> None:
        machines = (
            _machine("1", LINE_DOWN),
            _machine("2", LINE_DOWN.lower()),
            _machine("3", NON_CRITICAL),
            _machine("4", NO_ISSUES),
        )

        state = calculate_plant_deterioration(machines, SpecialEffectsSettings(threshold=0))

        self.assertEqual(1, state.down_count)
        self.assertEqual(1, state.intensity_level)

    def test_settings_persist_with_qsettings_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.ini"
            qsettings = QSettings(str(settings_path), QSettings.Format.IniFormat)
            saved = SpecialEffectsSettings(
                enabled=False,
                threshold=8,
                intensity_step=3,
                force_test=True,
                test_intensity=5,
                enable_static=False,
                enable_glitch=True,
                enable_droop_drip=False,
                enable_smear=True,
                enable_card_impulses=False,
                enable_falling_drips=False,
                drip_intensity=5,
                glitch_impulse_strength=2,
                reduced_motion=True,
            )

            save_special_effects_settings(qsettings, saved)
            restored = load_special_effects_settings(
                QSettings(str(settings_path), QSettings.Format.IniFormat),
                load_runtime_config(_config_path(tmp)).special_effects,
            )

            self.assertEqual(saved, restored)

    def test_special_config_defaults_and_pin_hash_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_runtime_config(_config_path(tmp))

        self.assertTrue(config.special_effects.enabled)
        self.assertEqual(6, config.special_effects.threshold)
        self.assertEqual(1, config.special_effects.intensity_step)
        self.assertTrue(config.special_effects.enable_static)
        self.assertTrue(config.special_effects.enable_glitch)
        self.assertTrue(config.special_effects.enable_droop_drip)
        self.assertTrue(config.special_effects.enable_smear)
        self.assertTrue(config.special_effects.enable_card_impulses)
        self.assertTrue(config.special_effects.enable_falling_drips)
        self.assertEqual(3, config.special_effects.drip_intensity)
        self.assertEqual(3, config.special_effects.glitch_impulse_strength)
        self.assertFalse(config.special_effects.reduced_motion)
        self.assertEqual(DEFAULT_SPECIAL_PIN_HASH, config.special_effects.special_pin_hash)
        self.assertTrue(config.verify_special_pin("041924"))
        self.assertFalse(config.verify_special_pin("000000"))

    def test_special_permission_is_admin_only(self) -> None:
        for role in (None, "viewer", "technician", "operator"):
            self.assertFalse(can_open_special(role))
        self.assertTrue(can_open_special("admin"))

    def test_burst_scheduler_has_bursts_and_quiet_periods(self) -> None:
        plant = calculate_deterioration_state(9, SpecialEffectsSettings(threshold=6))
        settings = SpecialEffectsSettings()
        ready = replace(initial_card_glitch_state("LD-1", LINE_DOWN), next_burst_tick=0)
        burst = update_card_glitch_state(
            ready,
            "LD-1",
            LINE_DOWN,
            plant,
            settings,
            0,
        )

        self.assertTrue(is_card_in_burst(burst, 0))
        self.assertGreater(burst.burst_strength, 0)
        self.assertTrue(burst.tear_bands)
        quiet = update_card_glitch_state(burst, "LD-1", LINE_DOWN, plant, settings, burst.burst_end_tick)
        self.assertFalse(is_card_in_burst(quiet, burst.burst_end_tick))
        self.assertEqual(0, quiet.jerk_offset_x)
        self.assertEqual(0, quiet.jerk_offset_y)

    def test_reduced_motion_disables_heavy_card_motion(self) -> None:
        plant = calculate_deterioration_state(12, SpecialEffectsSettings(threshold=6))
        reduced = SpecialEffectsSettings(reduced_motion=True)

        state = update_card_glitch_state(
            CardGlitchState(next_burst_tick=0, seed=1),
            "LD-1",
            LINE_DOWN,
            plant,
            reduced,
            50,
        )

        self.assertFalse(is_card_in_burst(state, 50))
        self.assertEqual(0, state.jerk_offset_x)
        self.assertEqual(0, state.jerk_offset_y)
        self.assertEqual(0, state.card_offset_x)
        self.assertEqual(0, state.card_offset_y)
        self.assertEqual((), state.tear_bands)
        self.assertEqual((), state.diagonal_bands)

    def test_whole_card_impulse_scheduler_has_quiet_gaps(self) -> None:
        plant = calculate_deterioration_state(12, SpecialEffectsSettings(threshold=6))
        settings = SpecialEffectsSettings(glitch_impulse_strength=4)
        ready = replace(
            initial_card_glitch_state("LD-1", LINE_DOWN),
            next_burst_tick=0,
            next_position_impulse_tick=0,
        )

        burst = update_card_glitch_state(ready, "LD-1", LINE_DOWN, plant, settings, 0)

        self.assertTrue(is_card_in_burst(burst, 0))
        self.assertNotEqual((0, 0), (round(burst.card_offset_x), round(burst.card_offset_y)))
        self.assertGreater(burst.next_position_impulse_tick, 1)

    def test_whole_card_offsets_decay_back_to_zero(self) -> None:
        plant = calculate_deterioration_state(12, SpecialEffectsSettings(threshold=6))
        state = replace(
            initial_card_glitch_state("LD-1", LINE_DOWN),
            next_burst_tick=999,
            card_offset_x=12.0,
            card_offset_y=-8.0,
            card_offset_decay=0.42,
        )

        decayed = update_card_glitch_state(state, "LD-1", LINE_DOWN, plant, SpecialEffectsSettings(), 1)

        self.assertLess(abs(decayed.card_offset_x), abs(state.card_offset_x))
        self.assertLess(abs(decayed.card_offset_y), abs(state.card_offset_y))

        for tick in range(2, 12):
            decayed = update_card_glitch_state(decayed, "LD-1", LINE_DOWN, plant, SpecialEffectsSettings(), tick)

        self.assertEqual(0, decayed.card_offset_x)
        self.assertEqual(0, decayed.card_offset_y)

    def test_reduced_motion_and_disabled_settings_disable_impulses_and_falling_drips(self) -> None:
        plant = calculate_deterioration_state(12, SpecialEffectsSettings(threshold=6))
        ready = replace(
            initial_card_glitch_state("LD-1", LINE_DOWN),
            next_burst_tick=0,
            next_position_impulse_tick=0,
        )

        no_impulse = update_card_glitch_state(
            ready,
            "LD-1",
            LINE_DOWN,
            plant,
            SpecialEffectsSettings(enable_card_impulses=False),
            0,
        )
        reduced = update_card_glitch_state(
            ready,
            "LD-1",
            LINE_DOWN,
            plant,
            SpecialEffectsSettings(reduced_motion=True),
            0,
        )

        self.assertEqual(0, no_impulse.card_offset_x)
        self.assertEqual(0, no_impulse.card_offset_y)
        self.assertEqual(0, reduced.card_offset_x)
        self.assertEqual(0, reduced.card_offset_y)
        self.assertFalse(falling_drip_allowed(LINE_DOWN, plant, SpecialEffectsSettings(enable_falling_drips=False)))
        self.assertFalse(falling_drip_allowed(LINE_DOWN, plant, SpecialEffectsSettings(reduced_motion=True)))

    def test_falling_drip_moves_downward_with_acceleration(self) -> None:
        drip = FallingDrip(
            x=20,
            y=30,
            velocity_x=0,
            velocity_y=12,
            gravity=120,
            width=6,
            length=20,
            opacity=1,
            fade_rate=0.1,
            wobble_phase=0,
            wobble_amplitude=0,
            color_rgba=(255, 7, 58, 180),
        )

        updated = update_falling_drip(drip, 0.2, 400)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertGreater(updated.y, drip.y)
        self.assertGreater(updated.velocity_y, drip.velocity_y)

    def test_falling_drips_are_removed_after_leaving_viewport_or_expiring(self) -> None:
        offscreen = FallingDrip(
            x=20,
            y=320,
            velocity_x=0,
            velocity_y=20,
            gravity=120,
            width=6,
            length=12,
            opacity=1,
            fade_rate=0.1,
            wobble_phase=0,
            wobble_amplitude=0,
            color_rgba=(255, 7, 58, 180),
        )
        expired = replace(offscreen, y=30, max_age_seconds=0.05, opacity=0.03, fade_rate=1.0)

        self.assertIsNone(update_falling_drip(offscreen, 0.1, 100))
        self.assertIsNone(update_falling_drip(expired, 0.2, 400))

    def test_falling_drip_spawning_is_status_and_intensity_aware(self) -> None:
        plant = calculate_deterioration_state(9, SpecialEffectsSettings(threshold=6))
        settings = SpecialEffectsSettings(drip_intensity=3)

        self.assertTrue(falling_drip_allowed(LINE_DOWN, plant, settings))
        self.assertTrue(falling_drip_allowed(NON_CRITICAL, plant, settings))
        self.assertFalse(falling_drip_allowed(NO_ISSUES, plant, settings))
        self.assertLess(
            falling_drip_period_frames(LINE_DOWN, plant, settings, seed=1),
            falling_drip_period_frames(NON_CRITICAL, plant, settings, seed=1),
        )

        intense = calculate_deterioration_state(12, SpecialEffectsSettings(threshold=6))
        self.assertTrue(falling_drip_allowed(NO_ISSUES, intense, SpecialEffectsSettings(drip_intensity=5)))

    def test_falling_drips_do_not_move_upward_by_default(self) -> None:
        plant = calculate_deterioration_state(10, SpecialEffectsSettings(threshold=6))
        drip = build_falling_drip(
            "LD-1",
            LINE_DOWN,
            QPointF(80, 120),
            plant,
            SpecialEffectsSettings(),
            seed=42,
            tick=0,
        )

        self.assertIsNotNone(drip)
        assert drip is not None
        y_positions = [drip.y]
        for _index in range(5):
            drip = update_falling_drip(drip, 0.1, 500)
            self.assertIsNotNone(drip)
            assert drip is not None
            y_positions.append(drip.y)

        self.assertEqual(y_positions, sorted(y_positions))

    def test_status_weights_make_line_down_most_corrupted(self) -> None:
        level = 4

        self.assertGreater(status_effect_weight(LINE_DOWN, level), status_effect_weight(NON_CRITICAL, level))
        self.assertGreater(status_effect_weight(NON_CRITICAL, level), status_effect_weight(NO_ISSUES, level))

    def test_initial_card_glitch_state_is_timer_free_data(self) -> None:
        state = initial_card_glitch_state("LD-1", LINE_DOWN)

        self.assertIsInstance(state, CardGlitchState)
        self.assertGreaterEqual(state.next_burst_tick, 5)


def _machine(machine_number: str, status: str) -> MachineSummary:
    return MachineSummary(
        machine_number=machine_number,
        name=f"Machine {machine_number}",
        area="Area",
        cell="Cell",
        asset_tag="",
        display_order=0,
        manufacturer="",
        model="",
        imm_serial="",
        robot_type="",
        robot_model="",
        robot_serial="",
        calculated_status=status,
        open_issue_count=1 if status != NO_ISSUES else 0,
    )


def _config_path(root: str) -> Path:
    path = Path(root) / "beeline_config.json"
    path.write_text(
        json.dumps(
            {
                "roles": {},
                "machines": [],
            },
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
