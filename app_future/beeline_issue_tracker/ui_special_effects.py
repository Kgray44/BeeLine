from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, NO_ISSUES
from beeline_issue_tracker.special import PlantDeteriorationState, SpecialEffectsSettings


@dataclass(frozen=True)
class TearBand:
    y_ratio: float
    height_ratio: float
    offset_x: int
    offset_y: int
    alpha: int


@dataclass(frozen=True)
class DiagonalBand:
    center_y_ratio: float
    slope: float
    width: int
    offset_x: int
    offset_y: int
    alpha: int


@dataclass(frozen=True)
class CardGlitchState:
    next_burst_tick: int = 0
    burst_end_tick: int = 0
    burst_strength: float = 0.0
    jerk_offset_x: int = 0
    jerk_offset_y: int = 0
    card_offset_x: float = 0.0
    card_offset_y: float = 0.0
    card_offset_decay: float = 0.0
    next_position_impulse_tick: int = 0
    tear_bands: tuple[TearBand, ...] = ()
    diagonal_bands: tuple[DiagonalBand, ...] = ()
    drip_phase: float = 0.0
    drip_anchor_x_ratio: float = 0.5
    next_falling_drip_tick: int = 0
    smudge_strength: float = 0.0
    seed: int = 1


@dataclass(frozen=True)
class FallingDripSatellite:
    offset_x: float
    offset_y: float
    radius: float
    alpha_scale: float


@dataclass(frozen=True)
class FallingDrip:
    x: float
    y: float
    velocity_x: float
    velocity_y: float
    gravity: float
    width: float
    length: float
    opacity: float
    fade_rate: float
    wobble_phase: float
    wobble_amplitude: float
    color_rgba: tuple[int, int, int, int]
    age_seconds: float = 0.0
    max_age_seconds: float = 3.2
    satellites: tuple[FallingDripSatellite, ...] = ()
    seed: int = 1


def is_card_in_burst(glitch_state: CardGlitchState, tick: int) -> bool:
    return tick < glitch_state.burst_end_tick


def status_effect_weight(status: str, intensity_level: int) -> float:
    if status == LINE_DOWN:
        return 1.0
    if status == NON_CRITICAL:
        return 0.6 if intensity_level >= 2 else 0.22
    if status == NO_ISSUES:
        return 0.18 if intensity_level >= 4 else 0.0
    return 0.35 if intensity_level >= 3 else 0.12


def initial_card_glitch_state(seed_text: str, status: str, tick: int = 0) -> CardGlitchState:
    seed = _stable_seed(f"{seed_text}:{status}")
    rng = random.Random(seed)
    return CardGlitchState(
        next_burst_tick=tick + rng.randint(5, 28),
        next_position_impulse_tick=tick + rng.randint(18, 72),
        drip_phase=rng.random() * math.tau,
        drip_anchor_x_ratio=rng.uniform(0.16, 0.84),
        next_falling_drip_tick=tick + rng.randint(34, 140),
        seed=seed,
    )


def update_card_glitch_state(
    previous: CardGlitchState | None,
    seed_text: str,
    status: str,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
    tick: int,
) -> CardGlitchState:
    state = previous or initial_card_glitch_state(seed_text, status, tick)
    seed = _stable_seed(f"{seed_text}:{status}")
    if state.seed != seed:
        state = initial_card_glitch_state(seed_text, status, tick)
    state = _decay_card_position_impulse(state, settings)

    level = plant_state.intensity_level
    weight = status_effect_weight(status, level)
    if not plant_state.effect_active or weight <= 0:
        return _clear_card_motion(state)

    if settings.reduced_motion or not settings.enable_glitch:
        return _clear_card_motion(
            replace(
                state,
                next_burst_tick=max(state.next_burst_tick, tick + _quiet_frames(status, level, weight, seed)),
            )
        )

    if tick < state.burst_end_tick:
        active_state = replace(state, **_jerk_for_frame(state, status, level, tick))
        return _maybe_start_card_position_impulse(active_state, status, level, weight, settings, tick)

    if tick >= state.next_burst_tick:
        burst = _start_burst(seed_text, status, level, weight, tick)
        burst = replace(
            burst,
            card_offset_x=state.card_offset_x,
            card_offset_y=state.card_offset_y,
            card_offset_decay=state.card_offset_decay,
            next_position_impulse_tick=state.next_position_impulse_tick,
            drip_anchor_x_ratio=state.drip_anchor_x_ratio,
            next_falling_drip_tick=state.next_falling_drip_tick,
        )
        return _maybe_start_card_position_impulse(burst, status, level, weight, settings, tick)

    return replace(
        state,
        burst_end_tick=0,
        burst_strength=0.0,
        jerk_offset_x=0,
        jerk_offset_y=0,
        tear_bands=(),
        diagonal_bands=(),
        smudge_strength=0.0,
    )


def machine_card_special_offset(glitch_state: CardGlitchState, settings: SpecialEffectsSettings) -> QPoint:
    if settings.reduced_motion:
        return QPoint(0, 0)
    offset_x = glitch_state.jerk_offset_x
    offset_y = glitch_state.jerk_offset_y
    if settings.enable_card_impulses:
        offset_x += int(round(glitch_state.card_offset_x))
        offset_y += int(round(glitch_state.card_offset_y))
    return QPoint(offset_x, offset_y)


def paint_machine_card_deterioration(
    painter: QPainter,
    rect,
    source_pixmap: QPixmap | None,
    status: str,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
    glitch_state: CardGlitchState,
    tick: int,
) -> None:
    if not plant_state.effect_active:
        return

    level = plant_state.intensity_level
    weight = status_effect_weight(status, level)
    if weight <= 0:
        return

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = _status_color(status)
    burst_active = is_card_in_burst(glitch_state, tick) and not settings.reduced_motion

    if settings.enable_card_impulses and source_pixmap is not None and not settings.reduced_motion:
        _paint_card_position_impulse(painter, source_pixmap, glitch_state, level)

    if settings.enable_smear and source_pixmap is not None:
        _paint_smear_ghosts(painter, rect, source_pixmap, glitch_state, level, weight, burst_active)

    if settings.enable_droop_drip:
        _paint_sagged_bottom(painter, rect, source_pixmap, base, glitch_state, level, weight, tick, settings.reduced_motion)

    if settings.enable_glitch and source_pixmap is not None and burst_active:
        _paint_full_impulse(painter, source_pixmap, glitch_state, level)
        _paint_horizontal_slices(painter, rect, source_pixmap, glitch_state, status, level)
        _paint_diagonal_slices(painter, rect, source_pixmap, glitch_state, status, level)

    if settings.enable_smear:
        _paint_color_smears(painter, rect, base, glitch_state, level, weight, burst_active)

    if settings.enable_droop_drip:
        _paint_drips(painter, rect, base, glitch_state, level, weight, tick, settings.reduced_motion)

    if settings.enable_static:
        _paint_card_static(painter, rect, level, weight, glitch_state, tick, burst_active, settings.reduced_motion)

    _paint_glow_edges(painter, rect, base, glitch_state, level, weight, burst_active)
    painter.restore()


class SpecialScreenOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = SpecialEffectsSettings()
        self._state = PlantDeteriorationState(
            down_count=0,
            threshold=6,
            overage=0,
            effect_active=False,
            intensity_level=0,
            effects_enabled=True,
            force_test=False,
        )
        self._tick = 0
        self._falling_drips: list[FallingDrip] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(95)
        self._timer.timeout.connect(self._advance)
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

    def set_settings(self, settings: SpecialEffectsSettings) -> None:
        self._settings = settings
        if not _falling_drips_enabled(self._state, settings):
            self._falling_drips.clear()
        self._sync_visibility()
        self.update()

    def set_state(self, state: PlantDeteriorationState) -> None:
        self._state = state
        if not _falling_drips_enabled(state, self._settings):
            self._falling_drips.clear()
        self._sync_visibility()
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.update()

    def spawn_falling_drip(
        self,
        card_id: str,
        status: str,
        origin: QPoint | QPointF,
        plant_state: PlantDeteriorationState,
        settings: SpecialEffectsSettings,
        seed: int,
    ) -> None:
        drip = build_falling_drip(card_id, status, QPointF(origin), plant_state, settings, seed, self._tick)
        if drip is None:
            return
        self._falling_drips.append(drip)
        if len(self._falling_drips) > 96:
            self._falling_drips = self._falling_drips[-96:]
        self._sync_visibility()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._state.effect_active and not self._falling_drips:
            return

        level = self._state.intensity_level
        painter = QPainter(self)
        width = max(1, self.width())
        height = max(1, self.height())

        if self._state.effect_active and self._settings.enable_static:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            rng = random.Random(self._tick * 211 + level * 977)
            _paint_scanlines(painter, width, height, level, self._settings.reduced_motion)
            _paint_global_static(painter, width, height, level, rng, self._settings.reduced_motion)
            if not self._settings.reduced_motion:
                _paint_global_bands(painter, width, height, level, rng)
            _paint_vignette(painter, width, height, level)

        if self._falling_drips:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for drip in self._falling_drips:
                _paint_falling_drip(painter, drip)

    def _advance(self) -> None:
        self._tick += 1
        if self._falling_drips:
            next_drips = []
            for drip in self._falling_drips:
                updated = update_falling_drip(drip, self._timer.interval() / 1000.0, self.height())
                if updated is not None:
                    next_drips.append(updated)
            self._falling_drips = next_drips
        self.update()
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        visible = self._state.effect_active and (
            self._settings.enable_static or _falling_drips_enabled(self._state, self._settings)
        )
        visible = visible or bool(self._falling_drips)
        self.setVisible(visible)
        if visible and not self._timer.isActive():
            self._timer.start()
        elif not visible and self._timer.isActive():
            self._timer.stop()


def falling_drip_allowed(
    status: str,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
) -> bool:
    if not _falling_drips_enabled(plant_state, settings):
        return False
    level = plant_state.intensity_level
    if status == LINE_DOWN:
        return level >= 2
    if status == NON_CRITICAL:
        return level >= 3
    if status == NO_ISSUES:
        return level >= 5 and settings.drip_intensity >= 4
    return level >= 4


def falling_drip_period_frames(
    status: str,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
    seed: int = 0,
) -> int:
    if not falling_drip_allowed(status, plant_state, settings):
        return 0
    level = plant_state.intensity_level
    if status == LINE_DOWN:
        ranges = {2: (64, 112), 3: (44, 86), 4: (30, 64), 5: (22, 48)}
    elif status == NON_CRITICAL:
        ranges = {3: (98, 172), 4: (72, 132), 5: (50, 96)}
    elif status == NO_ISSUES:
        ranges = {5: (190, 340)}
    else:
        ranges = {4: (118, 210), 5: (84, 160)}
    low, high = ranges.get(level, ranges[max(ranges)])
    rng = random.Random(seed + level * 619)
    intensity_scale = 1.28 - max(1, min(5, settings.drip_intensity)) * 0.12
    return max(12, int(rng.randint(low, high) * intensity_scale))


def next_falling_drip_tick(
    status: str,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
    tick: int,
    seed: int,
) -> int:
    period = falling_drip_period_frames(status, plant_state, settings, seed)
    if period <= 0:
        return tick + 999_999
    return tick + period


def build_falling_drip(
    card_id: str,
    status: str,
    origin: QPointF,
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
    seed: int,
    tick: int,
) -> FallingDrip | None:
    if not falling_drip_allowed(status, plant_state, settings):
        return None

    level = plant_state.intensity_level
    weight = status_effect_weight(status, level)
    rng = random.Random(_stable_seed(f"{card_id}:{status}:{seed}:{tick}") + tick * 317)
    color = _status_color(status)
    intensity = max(1, min(5, settings.drip_intensity))
    scale = 0.72 + intensity * 0.12
    width = rng.uniform(4.6, 9.8 + level * 0.9) * scale * (0.78 + weight * 0.34)
    length = rng.uniform(18.0, 34.0 + level * 5.0) * (0.86 + weight * 0.22)
    velocity_y = rng.uniform(34.0, 74.0 + level * 9.0) * (0.74 + intensity * 0.1)
    gravity = rng.uniform(125.0, 218.0 + level * 20.0)
    alpha = int(min(215, 120 + level * 16 + weight * 38))
    satellites = _make_falling_drip_satellites(rng, level, weight)
    return FallingDrip(
        x=origin.x() + rng.uniform(-3.0, 3.0),
        y=origin.y() + rng.uniform(0.0, 4.5),
        velocity_x=rng.uniform(-9.0, 9.0) * (0.5 + weight * 0.45),
        velocity_y=velocity_y,
        gravity=gravity,
        width=width,
        length=length,
        opacity=1.0,
        fade_rate=rng.uniform(0.14, 0.26),
        wobble_phase=rng.random() * math.tau,
        wobble_amplitude=rng.uniform(1.5, 6.0 + level * 0.8),
        color_rgba=(color.red(), color.green(), color.blue(), alpha),
        max_age_seconds=rng.uniform(2.4, 4.2),
        satellites=satellites,
        seed=seed,
    )


def update_falling_drip(
    drip: FallingDrip,
    dt_seconds: float,
    viewport_height: int,
) -> FallingDrip | None:
    dt = max(0.0, float(dt_seconds))
    velocity_y = max(0.0, drip.velocity_y + drip.gravity * dt)
    next_y = drip.y + max(0.0, drip.velocity_y) * dt + 0.5 * drip.gravity * dt * dt
    next_x = drip.x + drip.velocity_x * dt
    age = drip.age_seconds + dt
    opacity = max(0.0, drip.opacity - drip.fade_rate * dt)
    if age > drip.max_age_seconds:
        opacity *= max(0.0, 1.0 - (age - drip.max_age_seconds) * 2.0)
    if next_y - drip.length > viewport_height + 90 or opacity <= 0.02:
        return None
    return replace(
        drip,
        x=next_x,
        y=next_y,
        velocity_y=velocity_y,
        opacity=opacity,
        age_seconds=age,
    )


def _falling_drips_enabled(
    plant_state: PlantDeteriorationState,
    settings: SpecialEffectsSettings,
) -> bool:
    return bool(
        plant_state.effect_active
        and settings.enable_falling_drips
        and settings.enable_droop_drip
        and not settings.reduced_motion
    )


def _make_falling_drip_satellites(
    rng: random.Random,
    level: int,
    weight: float,
) -> tuple[FallingDripSatellite, ...]:
    count = rng.randint(0, max(1, min(3, int(level * weight))))
    satellites = []
    for index in range(count):
        satellites.append(
            FallingDripSatellite(
                offset_x=rng.uniform(-10.0, 10.0),
                offset_y=rng.uniform(-8.0, 18.0 + index * 6.0),
                radius=rng.uniform(1.6, 4.8),
                alpha_scale=rng.uniform(0.28, 0.62),
            )
        )
    return tuple(satellites)


def _clear_card_motion(state: CardGlitchState) -> CardGlitchState:
    return replace(
        state,
        burst_end_tick=0,
        burst_strength=0.0,
        jerk_offset_x=0,
        jerk_offset_y=0,
        card_offset_x=0.0,
        card_offset_y=0.0,
        card_offset_decay=0.0,
        tear_bands=(),
        diagonal_bands=(),
        smudge_strength=0.0,
    )


def _decay_card_position_impulse(
    state: CardGlitchState,
    settings: SpecialEffectsSettings,
) -> CardGlitchState:
    if settings.reduced_motion or not settings.enable_card_impulses:
        return replace(state, card_offset_x=0.0, card_offset_y=0.0, card_offset_decay=0.0)
    if abs(state.card_offset_x) < 0.35 and abs(state.card_offset_y) < 0.35:
        return replace(state, card_offset_x=0.0, card_offset_y=0.0, card_offset_decay=0.0)
    decay = state.card_offset_decay if 0.0 < state.card_offset_decay < 1.0 else 0.48
    next_x = state.card_offset_x * decay
    next_y = state.card_offset_y * decay
    if abs(next_x) < 0.35:
        next_x = 0.0
    if abs(next_y) < 0.35:
        next_y = 0.0
    return replace(state, card_offset_x=next_x, card_offset_y=next_y, card_offset_decay=decay)


def _maybe_start_card_position_impulse(
    state: CardGlitchState,
    status: str,
    level: int,
    weight: float,
    settings: SpecialEffectsSettings,
    tick: int,
) -> CardGlitchState:
    if settings.reduced_motion or not settings.enable_card_impulses:
        return replace(state, card_offset_x=0.0, card_offset_y=0.0, card_offset_decay=0.0)
    if tick < state.next_position_impulse_tick:
        return state

    rng = random.Random(state.seed + tick * 881 + int(state.burst_strength * 4000))
    magnitude = _card_impulse_magnitude(status, level, weight, settings, rng)
    if magnitude <= 0:
        return replace(
            state,
            next_position_impulse_tick=tick + _position_impulse_quiet_frames(status, level, weight, settings, state.seed),
        )

    angle = rng.uniform(0, math.tau)
    if status == LINE_DOWN and rng.random() < 0.58:
        angle = rng.choice((0, math.pi)) + rng.uniform(-0.34, 0.34)
    offset_x = math.cos(angle) * magnitude
    offset_y = math.sin(angle) * magnitude * (1.0 if status == LINE_DOWN else 0.72)
    return replace(
        state,
        card_offset_x=offset_x,
        card_offset_y=offset_y,
        card_offset_decay=rng.uniform(0.34, 0.58),
        next_position_impulse_tick=tick
        + _position_impulse_quiet_frames(status, level, weight, settings, state.seed + tick),
    )


def _card_impulse_magnitude(
    status: str,
    level: int,
    weight: float,
    settings: SpecialEffectsSettings,
    rng: random.Random,
) -> float:
    if level <= 0 or weight <= 0:
        return 0.0
    status_scale = 1.0
    if status == LINE_DOWN:
        status_scale = 1.18
    elif status == NON_CRITICAL:
        status_scale = 0.78
    elif status == NO_ISSUES:
        status_scale = 0.42
    strength_scale = 0.66 + max(1, min(5, settings.glitch_impulse_strength)) * 0.18
    minimum = 4.0 + level * 0.55
    maximum = 7.0 + level * 2.4
    magnitude = rng.uniform(minimum, maximum) * status_scale * strength_scale
    if status == NO_ISSUES and level < 5:
        magnitude *= 0.45
    return min(18.0, max(0.0, magnitude))


def _position_impulse_quiet_frames(
    status: str,
    level: int,
    weight: float,
    settings: SpecialEffectsSettings,
    seed: int,
) -> int:
    rng = random.Random(seed + level * 431 + int(weight * 100))
    if status == LINE_DOWN:
        ranges = {1: (70, 130), 2: (42, 94), 3: (28, 70), 4: (18, 52), 5: (13, 38)}
    elif status == NON_CRITICAL:
        ranges = {1: (145, 245), 2: (95, 178), 3: (64, 132), 4: (44, 96), 5: (32, 72)}
    else:
        ranges = {1: (260, 440), 2: (220, 380), 3: (180, 320), 4: (125, 245), 5: (86, 178)}
    low, high = ranges.get(level, ranges[5])
    strength = max(1, min(5, settings.glitch_impulse_strength))
    scale = 1.22 - strength * 0.08
    return max(4, int(rng.randint(low, high) * scale))


def _start_burst(seed_text: str, status: str, level: int, weight: float, tick: int) -> CardGlitchState:
    seed = _stable_seed(f"{seed_text}:{status}")
    rng = random.Random(seed + tick * 157 + level * 997)
    duration = _burst_duration_frames(status, level, weight, rng)
    strength = _burst_strength(status, level, weight, rng)
    burst_end = tick + duration
    next_burst = burst_end + _quiet_frames(status, level, weight, seed + tick)
    base = CardGlitchState(
        next_burst_tick=next_burst,
        burst_end_tick=burst_end,
        burst_strength=strength,
        tear_bands=_make_tear_bands(rng, status, level, strength),
        diagonal_bands=_make_diagonal_bands(rng, status, level, strength),
        drip_phase=rng.random() * math.tau,
        smudge_strength=max(0.0, min(1.0, strength * (0.45 + level * 0.08))),
        seed=seed,
    )
    return replace(base, **_jerk_for_frame(base, status, level, tick))


def _quiet_frames(status: str, level: int, weight: float, seed: int) -> int:
    rng = random.Random(seed + level * 71)
    if status == LINE_DOWN:
        ranges = {1: (18, 55), 2: (12, 38), 3: (8, 30), 4: (5, 22), 5: (3, 15)}
    elif status == NON_CRITICAL:
        ranges = {1: (42, 90), 2: (25, 68), 3: (16, 48), 4: (10, 34), 5: (7, 26)}
    else:
        ranges = {1: (120, 220), 2: (95, 180), 3: (70, 145), 4: (40, 95), 5: (22, 68)}
    low, high = ranges.get(level, ranges[5])
    adjusted_high = max(low, int(high / max(0.35, weight)))
    return rng.randint(low, adjusted_high)


def _burst_duration_frames(status: str, level: int, weight: float, rng: random.Random) -> int:
    maximum = 2 + min(4, level)
    minimum = 1 if level <= 2 else 2
    if status == LINE_DOWN:
        maximum += 1
    if weight < 0.4:
        maximum = max(minimum, maximum - 2)
    return rng.randint(minimum, maximum)


def _burst_strength(status: str, level: int, weight: float, rng: random.Random) -> float:
    status_boost = 1.18 if status == LINE_DOWN else 0.82 if status == NON_CRITICAL else 0.48
    return min(1.0, (0.22 + level * 0.14 + rng.random() * 0.22) * weight * status_boost)


def _jerk_for_frame(state: CardGlitchState, status: str, level: int, tick: int) -> dict[str, int]:
    rng = random.Random(state.seed + tick * 613 + int(state.burst_strength * 1000))
    if level <= 1 and rng.random() < 0.58:
        return {"jerk_offset_x": 0, "jerk_offset_y": 0}
    max_x = max(1, int((2 + level * 3) * state.burst_strength))
    max_y = max(1, int((1 + level) * state.burst_strength * (1.0 if status == LINE_DOWN else 0.55)))
    return {
        "jerk_offset_x": rng.randint(-max_x, max_x),
        "jerk_offset_y": rng.randint(-max_y, max_y),
    }


def _make_tear_bands(rng: random.Random, status: str, level: int, strength: float) -> tuple[TearBand, ...]:
    if level <= 1 and status != LINE_DOWN and rng.random() < 0.72:
        return ()
    maximum = max(1, int(level * strength * (2.0 if status == LINE_DOWN else 1.15)))
    maximum = min(7, maximum + (1 if level >= 4 and status == LINE_DOWN else 0))
    count = rng.randint(1, max(1, maximum))
    bands = []
    for _index in range(count):
        bands.append(
            TearBand(
                y_ratio=rng.uniform(0.12, 0.84),
                height_ratio=rng.uniform(0.018, 0.035 + level * 0.012),
                offset_x=rng.choice((-1, 1)) * rng.randint(3, 4 + level * 4),
                offset_y=rng.randint(-1, max(1, level + 1)),
                alpha=rng.randint(28, 68 + level * 8),
            )
        )
    return tuple(bands)


def _make_diagonal_bands(rng: random.Random, status: str, level: int, strength: float) -> tuple[DiagonalBand, ...]:
    if level < 3 and not (status == LINE_DOWN and level >= 2):
        return ()
    chance = min(0.9, 0.28 + level * 0.12 + strength * 0.4)
    if rng.random() > chance:
        return ()
    count = 1 + (1 if level >= 5 and status == LINE_DOWN and rng.random() < 0.45 else 0)
    bands = []
    for _index in range(count):
        angle = math.radians(rng.choice((-1, 1)) * rng.uniform(15, 35))
        bands.append(
            DiagonalBand(
                center_y_ratio=rng.uniform(0.24, 0.76),
                slope=math.tan(angle),
                width=rng.randint(10, 18 + level * 5),
                offset_x=rng.choice((-1, 1)) * rng.randint(5, 6 + level * 4),
                offset_y=rng.randint(-4, 3 + level),
                alpha=rng.randint(42, 88 + level * 10),
            )
        )
    return tuple(bands)


def _paint_full_impulse(
    painter: QPainter,
    source_pixmap: QPixmap,
    glitch_state: CardGlitchState,
    level: int,
) -> None:
    offset = QPoint(glitch_state.jerk_offset_x, glitch_state.jerk_offset_y)
    if offset.isNull():
        return
    painter.save()
    painter.setOpacity(min(0.22, 0.06 + glitch_state.burst_strength * 0.18 + level * 0.01))
    painter.drawPixmap(offset, source_pixmap)
    painter.restore()


def _paint_card_position_impulse(
    painter: QPainter,
    source_pixmap: QPixmap,
    glitch_state: CardGlitchState,
    level: int,
) -> None:
    if abs(glitch_state.card_offset_x) < 0.5 and abs(glitch_state.card_offset_y) < 0.5:
        return
    painter.save()
    painter.setOpacity(min(0.86, 0.48 + level * 0.065))
    painter.drawPixmap(QPoint(round(glitch_state.card_offset_x), round(glitch_state.card_offset_y)), source_pixmap)
    painter.restore()


def _paint_horizontal_slices(
    painter: QPainter,
    rect,
    source_pixmap: QPixmap,
    glitch_state: CardGlitchState,
    status: str,
    level: int,
) -> None:
    width = source_pixmap.width()
    height = source_pixmap.height()
    for band in glitch_state.tear_bands:
        band_y = max(0, min(height - 2, int(height * band.y_ratio)))
        band_height = max(3, min(26, int(height * band.height_ratio)))
        source = QRect(0, band_y, width, min(band_height, height - band_y))
        target = QRect(band.offset_x, band_y + band.offset_y, width, source.height())
        painter.drawPixmap(target, source_pixmap, source)
        color = _status_color(status)
        color.setAlpha(min(120, band.alpha))
        painter.fillRect(QRectF(rect.left() + band.offset_x, band_y, rect.width(), source.height()), color)
        _paint_band_noise(painter, QRect(0, band_y, width, source.height()), level, glitch_state.seed + band_y)


def _paint_diagonal_slices(
    painter: QPainter,
    rect,
    source_pixmap: QPixmap,
    glitch_state: CardGlitchState,
    status: str,
    level: int,
) -> None:
    width = max(1, source_pixmap.width())
    height = max(1, source_pixmap.height())
    for band in glitch_state.diagonal_bands:
        path = _diagonal_band_path(width, height, band)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(QPoint(band.offset_x, band.offset_y), source_pixmap)
        tint = _status_color(status)
        tint.setAlpha(min(110, band.alpha))
        painter.fillPath(path, tint)
        _paint_diagonal_edges(painter, width, height, band, level)
        painter.restore()


def _diagonal_band_path(width: int, height: int, band: DiagonalBand) -> QPainterPath:
    center_y = height * band.center_y_ratio
    half = band.width / 2
    left_y = center_y + band.slope * (0 - width / 2)
    right_y = center_y + band.slope * (width - width / 2)
    polygon = QPolygonF(
        [
            QPointF(-12, left_y - half),
            QPointF(width + 12, right_y - half),
            QPointF(width + 12, right_y + half),
            QPointF(-12, left_y + half),
        ]
    )
    path = QPainterPath()
    path.addPolygon(polygon)
    path.closeSubpath()
    card_path = QPainterPath()
    card_path.addRoundedRect(QRectF(0, 0, width, height), 8, 8)
    return path.intersected(card_path)


def _paint_diagonal_edges(painter: QPainter, width: int, height: int, band: DiagonalBand, level: int) -> None:
    center_y = height * band.center_y_ratio
    half = band.width / 2
    left_y = center_y + band.slope * (0 - width / 2)
    right_y = center_y + band.slope * (width - width / 2)
    bright = QColor(255, 255, 255, min(130, 34 + level * 18))
    dark = QColor(0, 0, 0, min(120, 28 + level * 14))
    painter.setPen(QPen(bright, 1))
    painter.drawLine(QPointF(0, left_y - half), QPointF(width, right_y - half))
    painter.setPen(QPen(dark, 1))
    painter.drawLine(QPointF(0, left_y + half), QPointF(width, right_y + half))


def _paint_smear_ghosts(
    painter: QPainter,
    rect,
    source_pixmap: QPixmap,
    glitch_state: CardGlitchState,
    level: int,
    weight: float,
    burst_active: bool,
) -> None:
    if not burst_active or glitch_state.smudge_strength <= 0:
        return
    painter.save()
    copies = 1 + (1 if level >= 4 else 0)
    for index in range(copies):
        direction = -1 if index % 2 else 1
        offset_x = direction * int((4 + level * 3 + index * 5) * glitch_state.smudge_strength)
        offset_y = int((index + 1) * weight)
        painter.setOpacity(max(0.04, 0.16 * glitch_state.smudge_strength / (index + 1)))
        painter.drawPixmap(QPoint(offset_x, offset_y), source_pixmap)
    painter.restore()


def _paint_color_smears(
    painter: QPainter,
    rect,
    color: QColor,
    glitch_state: CardGlitchState,
    level: int,
    weight: float,
    burst_active: bool,
) -> None:
    if not burst_active and level < 4:
        return
    smear_count = max(1, int(level * weight * (1.7 if burst_active else 0.6)))
    rng = random.Random(glitch_state.seed + level * 283 + int(glitch_state.smudge_strength * 1000))
    for _index in range(smear_count):
        y = rect.top() + rng.randint(8, max(9, rect.height() - 18))
        width = rng.randint(24, 64 + level * 18)
        smear = QColor(color)
        smear.setAlpha(int(22 + level * 13 * weight))
        gradient = QLinearGradient(rect.left(), y, rect.left() + width, y)
        gradient.setColorAt(0.0, smear)
        fade = QColor(smear)
        fade.setAlpha(0)
        gradient.setColorAt(1.0, fade)
        painter.fillRect(QRectF(rect.left() + rng.randint(-4, 10), y, width, rng.randint(3, 8)), gradient)


def _paint_sagged_bottom(
    painter: QPainter,
    rect,
    source_pixmap: QPixmap | None,
    color: QColor,
    glitch_state: CardGlitchState,
    level: int,
    weight: float,
    tick: int,
    reduced_motion: bool,
) -> None:
    if level < 2 or weight <= 0:
        return
    sag = int((level - 1) * 1.7 * weight)
    if reduced_motion:
        sag = min(1, sag)
    if sag <= 0:
        return

    if source_pixmap is not None:
        height = source_pixmap.height()
        width = source_pixmap.width()
        band_count = 3 + min(3, level)
        band_height = max(8, int(height * 0.11))
        start_y = max(0, height - band_height * band_count)
        for index in range(band_count):
            source_y = start_y + index * band_height
            shift = int((index + 1) / band_count * sag)
            wobble = 0 if reduced_motion else int(math.sin(tick * 0.28 + glitch_state.drip_phase + index) * weight)
            source = QRect(0, source_y, width, min(band_height, height - source_y))
            target = QRect(wobble, source_y + shift, width, source.height())
            painter.drawPixmap(target, source_pixmap, source)

    droop = QColor(color)
    droop.setAlpha(int(24 + level * 10 * weight))
    path = QPainterPath()
    left = rect.left() + 8
    right = rect.right() - 8
    bottom = rect.bottom() - 2
    top = bottom - 10
    path.moveTo(left, top)
    segments = 5
    for index in range(segments + 1):
        x = left + (right - left) * index / segments
        wave = 0.5 + 0.5 * math.sin(tick * 0.18 + glitch_state.drip_phase + index * 1.3)
        y = top + wave * sag
        path.lineTo(x, y)
    path.lineTo(right, bottom)
    path.lineTo(left, bottom)
    path.closeSubpath()
    painter.fillPath(path, droop)


def _paint_drips(
    painter: QPainter,
    rect,
    color: QColor,
    glitch_state: CardGlitchState,
    level: int,
    weight: float,
    tick: int,
    reduced_motion: bool,
) -> None:
    if level < 2 or weight <= 0:
        return
    count = max(1, int((level - 1) * weight * (1.35 if not reduced_motion else 0.55)))
    if count <= 0:
        return
    rng = random.Random(glitch_state.seed + 5431)
    for index in range(count):
        x_ratio = rng.uniform(0.08, 0.92)
        width = rng.uniform(7, 13 + level * 1.8) * (0.72 + weight * 0.45)
        max_height = rng.uniform(12, 18 + level * 8) * (0.7 + weight * 0.55)
        speed = rng.uniform(0.08, 0.22) * (0.55 if reduced_motion else 1.0)
        phase = glitch_state.drip_phase + rng.uniform(0, math.tau)
        wave = 0.5 + 0.5 * math.sin(tick * speed + phase)
        height = max_height * (0.35 + 0.65 * wave)
        x = rect.left() + rect.width() * x_ratio - width / 2
        origin_y = rect.bottom() - 2
        neck_top = origin_y - min(7.0, max(2.0, height * 0.13))
        drop_bottom = origin_y + height
        drip = QColor(color)
        drip.setAlpha(int(min(180, 38 + level * 18 * weight + wave * 34)))
        path = QPainterPath()
        path.moveTo(x + width * 0.24, neck_top)
        path.cubicTo(x, origin_y + height * 0.25, x + width * 0.1, drop_bottom, x + width * 0.5, drop_bottom)
        path.cubicTo(
            x + width * 0.9,
            drop_bottom,
            x + width,
            origin_y + height * 0.25,
            x + width * 0.76,
            neck_top,
        )
        path.closeSubpath()
        painter.fillPath(path, drip)
        if level >= 4 and not reduced_motion and index % 3 == 0:
            drop = QColor(drip)
            drop.setAlpha(int(drop.alpha() * 0.45))
            painter.setBrush(drop)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(
                _organic_drop_path(
                    x + width * 0.5,
                    origin_y + height * 0.32,
                    width * 0.24,
                    height * 0.16,
                ),
                drop,
            )


def _paint_falling_drip(painter: QPainter, drip: FallingDrip) -> None:
    red, green, blue, alpha = drip.color_rgba
    wobble = math.sin(drip.age_seconds * 5.2 + drip.wobble_phase) * drip.wobble_amplitude
    x = drip.x + wobble
    y = drip.y
    stretch = min(38.0, drip.velocity_y * 0.085)
    length = drip.length + stretch
    width = drip.width * (0.88 + min(0.35, drip.velocity_y / 520.0))
    opacity_alpha = max(0, min(255, int(alpha * drip.opacity)))
    if opacity_alpha <= 0:
        return

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    trail = QLinearGradient(x, y - length * 0.55, x, y + length)
    trail_color = QColor(red, green, blue, int(opacity_alpha * 0.26))
    clear = QColor(red, green, blue, 0)
    trail.setColorAt(0.0, clear)
    trail.setColorAt(0.35, trail_color)
    trail.setColorAt(1.0, clear)
    painter.fillRect(QRectF(x - width * 0.7, y - length * 0.55, width * 1.4, length * 1.55), trail)

    body = QColor(red, green, blue, opacity_alpha)
    painter.fillPath(_organic_drop_path(x, y, width, length), body)

    highlight = QColor(255, 255, 255, int(opacity_alpha * 0.2))
    painter.setPen(QPen(highlight, max(1.0, width * 0.12)))
    painter.drawLine(QPointF(x - width * 0.18, y + length * 0.16), QPointF(x - width * 0.05, y + length * 0.52))

    for satellite in drip.satellites:
        satellite_alpha = int(opacity_alpha * satellite.alpha_scale)
        if satellite_alpha <= 0:
            continue
        satellite_color = QColor(red, green, blue, satellite_alpha)
        satellite_x = x + satellite.offset_x + math.sin(drip.age_seconds * 6.5 + satellite.offset_x) * 1.6
        satellite_y = y + satellite.offset_y + min(22.0, drip.velocity_y * 0.03)
        painter.fillPath(
            _organic_drop_path(
                satellite_x,
                satellite_y,
                satellite.radius * 1.25,
                satellite.radius * 2.4,
            ),
            satellite_color,
        )
    painter.restore()


def _organic_drop_path(x: float, y: float, width: float, length: float) -> QPainterPath:
    width = max(1.0, float(width))
    length = max(2.0, float(length))
    top_y = y
    bulb_y = y + length * 0.78
    bottom_y = y + length
    path = QPainterPath()
    path.moveTo(QPointF(x, top_y))
    path.cubicTo(
        QPointF(x - width * 0.52, y + length * 0.18),
        QPointF(x - width * 0.78, y + length * 0.58),
        QPointF(x - width * 0.22, bulb_y),
    )
    path.cubicTo(
        QPointF(x - width * 0.18, y + length * 0.94),
        QPointF(x - width * 0.04, bottom_y),
        QPointF(x, bottom_y),
    )
    path.cubicTo(
        QPointF(x + width * 0.04, bottom_y),
        QPointF(x + width * 0.2, y + length * 0.94),
        QPointF(x + width * 0.22, bulb_y),
    )
    path.cubicTo(
        QPointF(x + width * 0.82, y + length * 0.58),
        QPointF(x + width * 0.48, y + length * 0.18),
        QPointF(x, top_y),
    )
    path.closeSubpath()
    return path


def _paint_card_static(
    painter: QPainter,
    rect,
    level: int,
    weight: float,
    glitch_state: CardGlitchState,
    tick: int,
    burst_active: bool,
    reduced_motion: bool,
) -> None:
    rng = random.Random(glitch_state.seed + tick * 97 + level * 409)
    scale = 0.38 if reduced_motion else 1.0
    alpha = int((9 + level * 6 * weight + (18 if burst_active else 0)) * scale)
    painter.setPen(QPen(QColor(255, 255, 255, max(4, alpha)), 1))
    step = max(5, 13 - level)
    for y in range(rect.top() + 8, rect.bottom() - 8, step):
        if rng.random() < (0.22 if not burst_active else 0.62):
            painter.drawLine(rect.left() + 7, y, rect.right() - 7, y)
    points = int((8 + level * 10 * weight + (level * 16 if burst_active else 0)) * scale)
    for _index in range(points):
        color = QColor(255, 255, 255, rng.randint(18, 70))
        if rng.random() < 0.42:
            color = QColor(0, 0, 0, rng.randint(14, 55))
        painter.setPen(color)
        painter.drawPoint(
            rng.randint(rect.left() + 5, rect.right() - 5),
            rng.randint(rect.top() + 5, rect.bottom() - 5),
        )


def _paint_band_noise(painter: QPainter, band_rect: QRect, level: int, seed: int) -> None:
    rng = random.Random(seed)
    points = 8 + level * 6
    for _index in range(points):
        painter.setPen(QColor(255, 255, 255, rng.randint(35, 115)))
        painter.drawPoint(
            rng.randint(band_rect.left(), max(band_rect.left(), band_rect.right())),
            rng.randint(band_rect.top(), max(band_rect.top(), band_rect.bottom())),
        )


def _paint_glow_edges(
    painter: QPainter,
    rect,
    color: QColor,
    glitch_state: CardGlitchState,
    level: int,
    weight: float,
    burst_active: bool,
) -> None:
    glow = QColor(color)
    pulse = 1.0 + (0.45 * math.sin(glitch_state.drip_phase + level) if burst_active else 0.0)
    glow.setAlpha(int(min(160, (30 + level * 14 * weight) * pulse)))
    painter.setPen(QPen(glow, max(1, int(level * weight))))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 8, 8)
    if burst_active:
        cyan = QColor(0, 255, 255, int(42 + level * 8 * weight))
        red = QColor(255, 30, 50, int(46 + level * 9 * weight))
        shift = max(1, int(level * weight))
        painter.setPen(QPen(cyan, 1))
        painter.drawRoundedRect(rect.adjusted(3 + shift, 4, -5 + shift, -5), 8, 8)
        painter.setPen(QPen(red, 1))
        painter.drawRoundedRect(rect.adjusted(3 - shift, 2, -5 - shift, -7), 8, 8)


def _paint_scanlines(painter: QPainter, width: int, height: int, level: int, reduced_motion: bool) -> None:
    alpha = min(34, 7 + level * (3 if reduced_motion else 5))
    painter.setPen(QPen(QColor(255, 255, 255, alpha), 1))
    step = max(4, 9 - level)
    for y in range(0, height, step):
        painter.drawLine(0, y, width, y)


def _paint_global_static(
    painter: QPainter,
    width: int,
    height: int,
    level: int,
    rng: random.Random,
    reduced_motion: bool,
) -> None:
    points = min(650, 60 + level * (55 if reduced_motion else 110))
    for _index in range(points):
        alpha = rng.randint(12, 28 + level * (4 if reduced_motion else 8))
        color = QColor(255, 255, 255, alpha) if rng.random() > 0.42 else QColor(0, 0, 0, alpha)
        painter.setPen(color)
        painter.drawPoint(rng.randint(0, width - 1), rng.randint(0, height - 1))


def _paint_global_bands(
    painter: QPainter,
    width: int,
    height: int,
    level: int,
    rng: random.Random,
) -> None:
    band_count = max(1, level // 2)
    for _index in range(band_count):
        y = rng.randint(0, height - 1)
        band_height = rng.randint(3, 9 + level * 4)
        color = QColor(255, 255, 255, min(52, 12 + level * 7))
        if rng.random() < 0.35:
            color = QColor(255, 40, 60, min(46, 11 + level * 6))
        painter.fillRect(0, y, width, band_height, color)


def _paint_vignette(painter: QPainter, width: int, height: int, level: int) -> None:
    gradient = QRadialGradient(width / 2, height / 2, max(width, height) * 0.68)
    clear = QColor(0, 0, 0, 0)
    edge = QColor(0, 0, 0, min(68, 16 + level * 8))
    gradient.setColorAt(0.0, clear)
    gradient.setColorAt(0.72, clear)
    gradient.setColorAt(1.0, edge)
    painter.fillRect(0, 0, width, height, gradient)


def _status_color(status: str) -> QColor:
    if status == LINE_DOWN:
        return QColor(255, 7, 58)
    if status == NON_CRITICAL:
        return QColor(255, 247, 0)
    if status == NO_ISSUES:
        return QColor(57, 255, 20)
    return QColor(150, 160, 168)


def _stable_seed(value: str) -> int:
    return sum((index + 1) * ord(character) for index, character in enumerate(str(value))) or 1
