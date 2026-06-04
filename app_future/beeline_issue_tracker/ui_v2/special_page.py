from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from beeline_issue_tracker.config import AppPaths, RuntimeConfig
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, NO_ISSUES, MachineSummary
from beeline_issue_tracker.special import (
    PlantDeteriorationState,
    SpecialEffectsSettings,
    load_special_effects_settings,
    save_special_effects_settings,
)
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground, MachineCard, MetricPill


class SpecialPage(HoneycombBackground):
    back_requested = Signal()
    settings_changed = Signal(object)

    def __init__(
        self,
        paths: AppPaths,
        runtime_config: RuntimeConfig,
        theme_manager,
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.paths = paths
        self.runtime_config = runtime_config
        self.theme_manager = theme_manager
        self._settings = load_special_effects_settings(
            theme_manager.settings,
            runtime_config.special_effects,
        )
        self._state = PlantDeteriorationState(
            down_count=0,
            threshold=self._settings.threshold,
            overage=0,
            effect_active=False,
            intensity_level=0,
            effects_enabled=self._settings.enabled,
            force_test=self._settings.force_test,
        )
        self._preview_tick = 0

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quietButton")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(
            BrandHeader(
                "Special",
                "Plant health visual effects and hidden diagnostics",
                paths.logo_path(),
                theme_manager,
            ),
            1,
        )
        page.addLayout(header)

        status_panel = QFrame()
        status_panel.setObjectName("infoPanel")
        status_layout = QHBoxLayout(status_panel)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(10)
        self.down_count_pill = MetricPill("Line Down Machines", "0")
        self.level_pill = MetricPill("Effect Level", "0")
        self.active_pill = MetricPill("Effects Active", "No")
        self.threshold_pill = MetricPill("Trigger Threshold", str(self._settings.threshold))
        for pill in (self.down_count_pill, self.level_pill, self.active_pill, self.threshold_pill):
            status_layout.addWidget(pill)
        status_layout.addStretch(1)
        page.addWidget(status_panel)

        controls_panel = QFrame()
        controls_panel.setObjectName("formPanel")
        controls = QGridLayout(controls_panel)
        controls.setContentsMargins(20, 18, 20, 18)
        controls.setHorizontalSpacing(18)
        controls.setVerticalSpacing(14)

        title = QLabel("Deterioration Controls")
        title.setObjectName("sectionTitle")
        controls.addWidget(title, 0, 0, 1, 2)

        self.enabled = QCheckBox("Enable Special Effects")
        self.enabled.setChecked(self._settings.enabled)
        self.enabled.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enabled, 1, 0, 1, 2)

        self.threshold = QSpinBox()
        self.threshold.setRange(0, 100)
        self.threshold.setValue(self._settings.threshold)
        self.threshold.valueChanged.connect(self._handle_controls_changed)
        controls.addWidget(QLabel("Start effects when more than this many machines are Line Down"), 2, 0)
        controls.addWidget(self.threshold, 2, 1)

        self.intensity_step = QSpinBox()
        self.intensity_step.setRange(1, 20)
        self.intensity_step.setValue(self._settings.intensity_step)
        self.intensity_step.valueChanged.connect(self._handle_controls_changed)
        controls.addWidget(QLabel("Increase effect strength every additional X machines down"), 3, 0)
        controls.addWidget(self.intensity_step, 3, 1)

        self.force_test = QCheckBox("Force Special Effects")
        self.force_test.setChecked(self._settings.force_test)
        self.force_test.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.force_test, 4, 0, 1, 2)

        self.test_intensity = QSlider(Qt.Orientation.Horizontal)
        self.test_intensity.setRange(1, 5)
        self.test_intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.test_intensity.setTickInterval(1)
        self.test_intensity.setValue(self._settings.test_intensity)
        self.test_intensity.valueChanged.connect(self._handle_controls_changed)
        self.test_intensity_value = QLabel(str(self._settings.test_intensity))
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_intensity, 1)
        test_row.addWidget(self.test_intensity_value)
        controls.addWidget(QLabel("Test Intensity"), 5, 0)
        controls.addLayout(test_row, 5, 1)

        self.enable_static = QCheckBox("Enable Static")
        self.enable_static.setChecked(self._settings.enable_static)
        self.enable_static.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_static, 6, 0)

        self.enable_glitch = QCheckBox("Enable Glitch/Tear")
        self.enable_glitch.setChecked(self._settings.enable_glitch)
        self.enable_glitch.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_glitch, 6, 1)

        self.enable_droop_drip = QCheckBox("Enable Droop/Drip")
        self.enable_droop_drip.setChecked(self._settings.enable_droop_drip)
        self.enable_droop_drip.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_droop_drip, 7, 0)

        self.enable_smear = QCheckBox("Enable Smear")
        self.enable_smear.setChecked(self._settings.enable_smear)
        self.enable_smear.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_smear, 7, 1)

        self.enable_card_impulses = QCheckBox("Enable Whole-Card Glitch Impulses")
        self.enable_card_impulses.setChecked(self._settings.enable_card_impulses)
        self.enable_card_impulses.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_card_impulses, 8, 0)

        self.enable_falling_drips = QCheckBox("Enable Falling Drips")
        self.enable_falling_drips.setChecked(self._settings.enable_falling_drips)
        self.enable_falling_drips.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.enable_falling_drips, 8, 1)

        self.drip_intensity = QSlider(Qt.Orientation.Horizontal)
        self.drip_intensity.setRange(1, 5)
        self.drip_intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.drip_intensity.setTickInterval(1)
        self.drip_intensity.setValue(self._settings.drip_intensity)
        self.drip_intensity.valueChanged.connect(self._handle_controls_changed)
        self.drip_intensity_value = QLabel(str(self._settings.drip_intensity))
        drip_row = QHBoxLayout()
        drip_row.addWidget(self.drip_intensity, 1)
        drip_row.addWidget(self.drip_intensity_value)
        controls.addWidget(QLabel("Drip Intensity"), 9, 0)
        controls.addLayout(drip_row, 9, 1)

        self.glitch_impulse_strength = QSlider(Qt.Orientation.Horizontal)
        self.glitch_impulse_strength.setRange(1, 5)
        self.glitch_impulse_strength.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.glitch_impulse_strength.setTickInterval(1)
        self.glitch_impulse_strength.setValue(self._settings.glitch_impulse_strength)
        self.glitch_impulse_strength.valueChanged.connect(self._handle_controls_changed)
        self.glitch_impulse_strength_value = QLabel(str(self._settings.glitch_impulse_strength))
        impulse_row = QHBoxLayout()
        impulse_row.addWidget(self.glitch_impulse_strength, 1)
        impulse_row.addWidget(self.glitch_impulse_strength_value)
        controls.addWidget(QLabel("Glitch Impulse Strength"), 10, 0)
        controls.addLayout(impulse_row, 10, 1)

        self.reduced_motion = QCheckBox("Reduced Motion Mode")
        self.reduced_motion.setChecked(self._settings.reduced_motion)
        self.reduced_motion.toggled.connect(self._handle_controls_changed)
        controls.addWidget(self.reduced_motion, 11, 0, 1, 2)

        page.addWidget(controls_panel)

        preview_title = QLabel("Preview")
        preview_title.setObjectName("sectionTitle")
        page.addWidget(preview_title)

        preview_panel = QFrame()
        preview_panel.setObjectName("infoPanel")
        preview_layout = QHBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        preview_layout.setSpacing(12)
        self.preview_cards = [
            MachineCard(_preview_machine("OK-1", "Stable press", NO_ISSUES)),
            MachineCard(_preview_machine("NC-1", "Warning press", NON_CRITICAL)),
            MachineCard(_preview_machine("LD-1", "Line down press", LINE_DOWN)),
        ]
        for card in self.preview_cards:
            card.setCursor(Qt.CursorShape.ArrowCursor)
            preview_layout.addWidget(card)
        page.addWidget(preview_panel)
        page.addStretch(1)

        self._sync_enabled_controls()
        self.set_state(self._state)

    def settings(self) -> SpecialEffectsSettings:
        return self._settings

    def set_state(self, state: PlantDeteriorationState) -> None:
        self._state = state
        self.down_count_pill.set_value(str(state.down_count))
        self.level_pill.set_value(str(state.intensity_level))
        self.active_pill.set_value("Yes" if state.effect_active else "No")
        self.threshold_pill.set_value(str(state.threshold))
        self._preview_tick += 1
        for card in self.preview_cards:
            card.set_special_effect_state(state, self._preview_tick, self._settings)

    def _handle_controls_changed(self) -> None:
        self.test_intensity_value.setText(str(self.test_intensity.value()))
        self.drip_intensity_value.setText(str(self.drip_intensity.value()))
        self.glitch_impulse_strength_value.setText(str(self.glitch_impulse_strength.value()))
        self._sync_enabled_controls()
        self._settings = SpecialEffectsSettings(
            enabled=self.enabled.isChecked(),
            threshold=self.threshold.value(),
            intensity_step=self.intensity_step.value(),
            force_test=self.force_test.isChecked(),
            test_intensity=self.test_intensity.value(),
            enable_static=self.enable_static.isChecked(),
            enable_glitch=self.enable_glitch.isChecked(),
            enable_droop_drip=self.enable_droop_drip.isChecked(),
            enable_smear=self.enable_smear.isChecked(),
            enable_card_impulses=self.enable_card_impulses.isChecked(),
            enable_falling_drips=self.enable_falling_drips.isChecked(),
            drip_intensity=self.drip_intensity.value(),
            glitch_impulse_strength=self.glitch_impulse_strength.value(),
            reduced_motion=self.reduced_motion.isChecked(),
        )
        save_special_effects_settings(self.theme_manager.settings, self._settings)
        self.settings_changed.emit(self._settings)

    def _sync_enabled_controls(self) -> None:
        controls_enabled = self.enabled.isChecked()
        force_enabled = controls_enabled and self.force_test.isChecked()
        motion_enabled = controls_enabled and not self.reduced_motion.isChecked()
        drip_controls_enabled = motion_enabled and self.enable_droop_drip.isChecked()
        impulse_controls_enabled = motion_enabled and self.enable_glitch.isChecked()
        self.threshold.setEnabled(controls_enabled)
        self.intensity_step.setEnabled(controls_enabled)
        self.force_test.setEnabled(controls_enabled)
        self.test_intensity.setEnabled(force_enabled)
        self.test_intensity_value.setEnabled(force_enabled)
        self.enable_static.setEnabled(controls_enabled)
        self.enable_glitch.setEnabled(controls_enabled)
        self.enable_droop_drip.setEnabled(controls_enabled)
        self.enable_smear.setEnabled(controls_enabled)
        self.enable_card_impulses.setEnabled(impulse_controls_enabled)
        self.glitch_impulse_strength.setEnabled(impulse_controls_enabled and self.enable_card_impulses.isChecked())
        self.glitch_impulse_strength_value.setEnabled(
            impulse_controls_enabled and self.enable_card_impulses.isChecked()
        )
        self.enable_falling_drips.setEnabled(drip_controls_enabled)
        self.drip_intensity.setEnabled(drip_controls_enabled and self.enable_falling_drips.isChecked())
        self.drip_intensity_value.setEnabled(drip_controls_enabled and self.enable_falling_drips.isChecked())
        self.reduced_motion.setEnabled(controls_enabled)


def _preview_machine(machine_number: str, name: str, status: str) -> MachineSummary:
    return MachineSummary(
        machine_number=machine_number,
        name=name,
        area="Preview",
        cell="Diagnostics",
        asset_tag="",
        display_order=0,
        manufacturer="BeeLine",
        model="Special",
        imm_serial="",
        robot_type="",
        robot_model="",
        robot_serial="",
        calculated_status=status,
        open_issue_count=1 if status != NO_ISSUES else 0,
    )
