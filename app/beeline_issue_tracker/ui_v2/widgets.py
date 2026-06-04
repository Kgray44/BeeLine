from __future__ import annotations

import math
import logging
import random
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.domain import Issue, MachineSummary, ResolvedIssue, display_issue_id
from beeline_issue_tracker.special import PlantDeteriorationState, SpecialEffectsSettings
from beeline_issue_tracker.ui_special_effects import (
    CardGlitchState,
    falling_drip_allowed,
    initial_card_glitch_state,
    next_falling_drip_tick,
    paint_machine_card_deterioration,
    update_card_glitch_state,
)
from beeline_issue_tracker.ui_v2.issue_list_model import (
    DATE_DESC,
    LATEST_OPTIONS,
    SORT_OPTIONS,
    filter_issues,
    format_duration_between,
    format_timestamp,
    prepare_issue_rows,
    preview_text,
)
from beeline_issue_tracker.ui_v2.theme import DARK_THEME, ThemeManager, repolish, status_state, theme_from_name


logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def load_scaled_logo(path: str, width: int, height: int) -> QPixmap:
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class BrandHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        logo_path: Path | None,
        theme_manager: ThemeManager | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._logo_source_pixmap: QPixmap | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.logo = QLabel("Nolato")
        self.logo.setObjectName("brandText")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setMinimumSize(92, 48)
        self.logo.setMaximumSize(154, 58)
        if logo_path is not None:
            pixmap = load_scaled_logo(str(logo_path), 148, 54)
            if not pixmap.isNull():
                self.logo.setText("")
                self.logo.setProperty("hasLogo", True)
                self._logo_source_pixmap = pixmap
                self._refresh_logo_pixmap()
                if self.theme_manager is not None:
                    self.theme_manager.theme_changed.connect(lambda _theme: self._refresh_logo_pixmap())
        layout.addWidget(self.logo)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("subtitleLabel")
        text_block.addWidget(self.title_label)
        text_block.addWidget(self.subtitle_label)
        layout.addLayout(text_block)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)

    def _refresh_logo_pixmap(self) -> None:
        if self._logo_source_pixmap is None:
            return
        scaled = self._logo_source_pixmap
        theme = self.theme_manager.current_theme if self.theme_manager is not None else theme_from_name(DARK_THEME)
        target = QColor(theme.text_primary)
        image = scaled.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if _is_dark_neutral_logo_pixel(color):
                    color.setRed(target.red())
                    color.setGreen(target.green())
                    color.setBlue(target.blue())
                    image.setPixelColor(x, y, color)
        self.logo.setPixmap(QPixmap.fromImage(image))


def _is_dark_neutral_logo_pixel(color: QColor) -> bool:
    if color.alpha() == 0:
        return False
    channels = (color.red(), color.green(), color.blue())
    return max(channels) < 90 and max(channels) - min(channels) < 40


class HoneycombBackground(QWidget):
    def __init__(self, theme_manager: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(lambda _theme: self.update())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        theme = (
            self.theme_manager.current_theme
            if self.theme_manager is not None
            else theme_from_name(DARK_THEME)
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme.accent)
        accent.setAlpha(theme.honeycomb_alpha)
        pen = QPen(accent, 1.6)
        painter.setPen(pen)

        radius = 34
        width = math.sqrt(3) * radius
        height = 2 * radius
        row_gap = height * 0.75

        clusters = (
            (self.width() - 282, 36, 5, 5),
            (-84, max(170, self.height() - 285), 5, 4),
            (self.width() // 2 - 130, max(110, self.height() - 150), 2, 4),
        )
        for origin_x, origin_y, rows, cols in clusters:
            for row in range(rows):
                y = origin_y + row * row_gap
                x_offset = 0 if row % 2 == 0 else width / 2
                for col in range(cols):
                    x = origin_x + col * width + x_offset
                    if (row + col) % 2 == 0:
                        self._draw_hexagon(painter, x, y, radius)

    @staticmethod
    def _draw_hexagon(painter: QPainter, cx: float, cy: float, radius: int) -> None:
        points = []
        for index in range(6):
            angle = math.radians(60 * index - 30)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        for start, end in zip(points, points[1:] + points[:1]):
            painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))


class StatusBadge(QLabel):
    def __init__(self, status: str, parent=None):
        super().__init__(status, parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(30)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        new_state = status_state(status)
        changed = False
        if self.text() != status:
            self.setText(status)
            changed = True
        if self.property("statusState") != new_state:
            self.setProperty("statusState", new_state)
            changed = True
        if changed:
            repolish(self)


class EmptyStatePanel(QFrame):
    def __init__(self, title: str = "", body: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("emptyStatePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("smallSectionTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.body_label = QLabel(body)
        self.body_label.setObjectName("mutedLabel")
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

    def set_text(self, title: str, body: str = "") -> None:
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.body_label.setVisible(bool(body))


class ThemeToggleButton(QPushButton):
    def __init__(self, theme_manager: ThemeManager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setObjectName("themeToggleButton")
        self.clicked.connect(self.theme_manager.toggle_theme)
        self.theme_manager.theme_changed.connect(lambda _theme: self._refresh_label())
        self._refresh_label()

    def _refresh_label(self) -> None:
        next_theme = "Light Mode" if self.theme_manager.current_theme_name == DARK_THEME else "Dark Mode"
        self.setText(next_theme)


class MachineCard(QFrame):
    clicked = Signal(str)

    def __init__(self, machine: MachineSummary, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._special_state: PlantDeteriorationState | None = None
        self._special_settings = SpecialEffectsSettings()
        self._glitch_state: CardGlitchState = initial_card_glitch_state(
            machine.machine_number,
            machine.calculated_status,
        )
        self._special_tick = 0
        self._special_source_pixmap = QPixmap()
        self._special_source_key: tuple[object, ...] | None = None
        self._rendering_special_source = False
        self._pending_falling_drips: list[tuple[str, str, QPoint, int]] = []
        self.setObjectName("machineCard")
        self.setProperty("statusState", status_state(machine.calculated_status))
        self.setProperty("specialActive", False)
        self.setProperty("specialIntensity", 0)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumSize(305, 185)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.number_label = QLabel()
        self.number_label.setObjectName("machineNumber")
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.number_label)

        self.name_label = QLabel()
        self.name_label.setObjectName("mutedLabel")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        self.model_label = QLabel()
        self.model_label.setObjectName("mutedLabel")
        self.model_label.setWordWrap(True)
        layout.addWidget(self.model_label)

        self.location_label = QLabel()
        self.location_label.setObjectName("mutedLabel")
        self.location_label.setWordWrap(True)
        layout.addWidget(self.location_label)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.status_badge = StatusBadge(machine.calculated_status)
        footer.addWidget(self.status_badge)
        self.open_count_label = QLabel()
        self.open_count_label.setObjectName("openCount")
        self.open_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self.open_count_label, 1)
        layout.addLayout(footer)
        self.update_machine(machine)
        self._effect_layer = _MachineCardEffectLayer(self)
        self._effect_layer.setGeometry(self.rect())
        self._effect_layer.raise_()

    def update_machine(self, machine: MachineSummary) -> None:
        self.machine = machine
        self._special_source_key = None
        self.number_label.setText(f"Machine {machine.machine_number}")
        self.name_label.setText(machine.name)
        model_text = " | ".join(
            part
            for part in (
                machine.manufacturer,
                machine.model,
                f"IMM {machine.imm_serial}" if machine.imm_serial else "",
            )
            if part
        )
        self.model_label.setText(model_text)
        self.model_label.setVisible(bool(model_text))
        location_text = " | ".join(part for part in (machine.area, machine.cell) if part)
        self.location_label.setText(location_text)
        self.location_label.setVisible(bool(location_text))
        self.status_badge.set_status(machine.calculated_status)
        self.open_count_label.setText(f"{machine.open_issue_count} open")
        new_state = status_state(machine.calculated_status)
        if self.property("statusState") != new_state:
            self.setProperty("statusState", new_state)
            repolish(self)
        if self._special_state is not None:
            self.set_special_effect_state(self._special_state, self._special_tick, self._special_settings)

    def set_special_effect_state(
        self,
        state: PlantDeteriorationState,
        tick: int,
        settings: SpecialEffectsSettings | None = None,
    ) -> None:
        self._special_state = state
        self._special_tick = int(tick)
        self._pending_falling_drips.clear()
        if settings is not None:
            self._special_settings = settings
        self._glitch_state = update_card_glitch_state(
            self._glitch_state,
            self.machine.machine_number,
            self.machine.calculated_status,
            state,
            self._special_settings,
            self._special_tick,
        )
        active = state.effect_active
        if self.property("specialActive") != active or self.property("specialIntensity") != state.intensity_level:
            self.setProperty("specialActive", active)
            self.setProperty("specialIntensity", state.intensity_level)
            repolish(self)

        if active:
            self._refresh_special_source_pixmap()
            self._maybe_queue_falling_drip()
        self._effect_layer.set_effect(
            state,
            self._special_settings,
            self._glitch_state,
            self._special_tick,
            self._special_source_pixmap,
            self.machine.calculated_status,
        )
        self._effect_layer.raise_()

    def take_pending_falling_drips(self, target: QWidget) -> list[tuple[str, str, QPoint, int]]:
        requests = [
            (machine_number, status, self.mapTo(target, origin), seed)
            for machine_number, status, origin, seed in self._pending_falling_drips
        ]
        self._pending_falling_drips.clear()
        return requests

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_effect_layer"):
            self._effect_layer.setGeometry(self.rect())
            self._effect_layer.raise_()
        self._special_source_key = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.machine.machine_number)
        super().mousePressEvent(event)

    def _refresh_special_source_pixmap(self) -> None:
        cache_key = self._current_special_source_key()
        if self._special_source_key == cache_key and not self._special_source_pixmap.isNull():
            return
        if self.size().isEmpty():
            return
        was_visible = self._effect_layer.isVisible()
        self._effect_layer.hide()
        self._rendering_special_source = True
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            self.render(painter, QPoint(0, 0))
        finally:
            painter.end()
            self._rendering_special_source = False
            self._effect_layer.setVisible(was_visible)
            self._effect_layer.raise_()
        self._special_source_pixmap = pixmap
        self._special_source_key = cache_key

    def _current_special_source_key(self) -> tuple[object, ...]:
        return (
            self.width(),
            self.height(),
            self.machine.machine_number,
            self.machine.name,
            self.machine.manufacturer,
            self.machine.model,
            self.machine.imm_serial,
            self.machine.area,
            self.machine.cell,
            self.machine.calculated_status,
            self.machine.open_issue_count,
            self.property("statusState"),
        )

    def _maybe_queue_falling_drip(self) -> None:
        if self._special_state is None or not self.isVisible():
            return
        status = self.machine.calculated_status
        if not falling_drip_allowed(status, self._special_state, self._special_settings):
            return
        if self._special_tick < self._glitch_state.next_falling_drip_tick:
            return

        anchor_ratio = min(0.88, max(0.12, self._glitch_state.drip_anchor_x_ratio))
        origin = QPoint(int(round(self.width() * anchor_ratio)), max(0, self.height() - 1))
        seed = self._glitch_state.seed + self._special_tick * 719
        self._pending_falling_drips.append((self.machine.machine_number, status, origin, seed))

        rng = random.Random(seed + self.width() * 13)
        self._glitch_state = replace(
            self._glitch_state,
            drip_anchor_x_ratio=rng.uniform(0.14, 0.86),
            next_falling_drip_tick=next_falling_drip_tick(
                status,
                self._special_state,
                self._special_settings,
                self._special_tick,
                seed,
            ),
        )


class _MachineCardEffectLayer(QWidget):
    def __init__(self, parent: MachineCard):
        super().__init__(parent)
        self._plant_state: PlantDeteriorationState | None = None
        self._settings = SpecialEffectsSettings()
        self._glitch_state = CardGlitchState()
        self._tick = 0
        self._source_pixmap = QPixmap()
        self._status = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.hide()

    def set_effect(
        self,
        plant_state: PlantDeteriorationState,
        settings: SpecialEffectsSettings,
        glitch_state: CardGlitchState,
        tick: int,
        source_pixmap: QPixmap,
        status: str,
    ) -> None:
        self._plant_state = plant_state
        self._settings = settings
        self._glitch_state = glitch_state
        self._tick = tick
        self._source_pixmap = source_pixmap
        self._status = status
        self.setVisible(plant_state.effect_active)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._plant_state is None:
            return
        painter = QPainter(self)
        paint_machine_card_deterioration(
            painter,
            self.rect(),
            self._source_pixmap,
            self._status,
            self._plant_state,
            self._settings,
            self._glitch_state,
            self._tick,
        )


class InfoRow(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        key = QLabel(label)
        key.setObjectName("mutedLabel")
        key.setMinimumWidth(115)
        val = QLabel(value or "-")
        val.setWordWrap(True)
        layout.addWidget(key)
        layout.addWidget(val, 1)


class MetricPill(QFrame):
    def __init__(self, label: str, value: str = "-", parent=None):
        super().__init__(parent)
        self.setObjectName("metricPill")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)

        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        self.value_widget = QLabel(value)
        self.value_widget.setObjectName("metricValue")
        layout.addWidget(label_widget)
        layout.addWidget(self.value_widget)

    def set_value(self, value: str) -> None:
        self.value_widget.setText(value or "-")


class PrimaryActionButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("primaryButton")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBox")
        self.setClearButtonEnabled(True)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(38)


class SortDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("compactDropdown")
        for label, value in SORT_OPTIONS:
            self.addItem(label, value)
        self.setMinimumHeight(38)
        self.setCurrentIndex(self.findData(DATE_DESC))


class LatestCountDropdown(QComboBox):
    def __init__(self, default_limit: int | None = 10, parent=None):
        super().__init__(parent)
        self.setObjectName("compactDropdown")
        for label, value in LATEST_OPTIONS:
            self.addItem(label, value)
        self.setMinimumHeight(38)
        self.setCurrentIndex(self.findData(default_limit))


class IssueListToolbar(QWidget):
    controls_changed = Signal()
    log_issue_requested = Signal()

    def __init__(
        self,
        title: str,
        search_placeholder: str,
        *,
        show_log_action: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.log_button: PrimaryActionButton | None = None
        self._page_index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("mutedLabel")
        header.addWidget(title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        if show_log_action:
            self.log_button = PrimaryActionButton("Report Problem")
            self.log_button.setObjectName("sectionPrimaryButton")
            self.log_button.clicked.connect(self._handle_log_button_clicked)
            header.addWidget(self.log_button)
        layout.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.search = SearchBox(search_placeholder)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search.textChanged.connect(self._handle_search_changed)
        self.search_timer.timeout.connect(self.controls_changed.emit)
        self.sort = SortDropdown()
        self.sort.currentIndexChanged.connect(self._handle_filter_changed)
        self.latest = LatestCountDropdown(10)
        self.latest.currentIndexChanged.connect(self._handle_filter_changed)
        self.display_mode = QComboBox()
        self.display_mode.setObjectName("compactDropdown")
        self.display_mode.addItem("Table", "table")
        self.display_mode.addItem("Kiosk", "kiosk")
        self.display_mode.setMinimumHeight(38)
        self.display_mode.currentIndexChanged.connect(self.controls_changed.emit)
        self.previous_page = QPushButton("Previous")
        self.previous_page.setObjectName("tableActionButton")
        self.previous_page.clicked.connect(self._go_previous_page)
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setObjectName("mutedLabel")
        self.next_page = QPushButton("Next")
        self.next_page.setObjectName("tableActionButton")
        self.next_page.clicked.connect(self._go_next_page)

        sort_label = QLabel("Sort")
        sort_label.setObjectName("controlLabel")
        show_label = QLabel("Show")
        show_label.setObjectName("controlLabel")
        mode_label = QLabel("Mode")
        mode_label.setObjectName("controlLabel")

        controls.addWidget(self.search, 1)
        controls.addWidget(sort_label)
        controls.addWidget(self.sort)
        controls.addWidget(show_label)
        controls.addWidget(self.latest)
        controls.addWidget(mode_label)
        controls.addWidget(self.display_mode)
        controls.addWidget(self.previous_page)
        controls.addWidget(self.page_label)
        controls.addWidget(self.next_page)
        layout.addLayout(controls)

    def update_count(self, shown: int, matched: int, total: int) -> None:
        if total == 0:
            text = "No issues"
        elif shown == matched == total:
            text = f"{shown} shown"
        else:
            text = f"{shown} of {matched} matched | {total} total"
        self.count_label.setText(text)
        self._update_pagination(matched)

    def offset(self) -> int:
        return self._page_index * self.page_size()

    def page_size(self) -> int:
        value = self.latest.currentData()
        return max(1, int(value if value is not None else 50))

    def reset_page(self) -> None:
        self._page_index = 0

    def set_log_action_enabled(self, enabled: bool) -> None:
        if self.log_button is not None:
            self.log_button.setEnabled(enabled)

    def _handle_search_changed(self) -> None:
        self.reset_page()
        self.search_timer.start()

    def _handle_filter_changed(self) -> None:
        self.reset_page()
        self.controls_changed.emit()

    def _go_previous_page(self) -> None:
        if self._page_index <= 0:
            return
        self._page_index -= 1
        self.controls_changed.emit()

    def _go_next_page(self) -> None:
        self._page_index += 1
        self.controls_changed.emit()

    def _update_pagination(self, matched: int) -> None:
        page_size = self.page_size()
        if matched <= 0:
            self._page_index = 0
            total_pages = 1
        else:
            total_pages = max(1, (matched + page_size - 1) // page_size)
            if self._page_index >= total_pages:
                self._page_index = total_pages - 1
        self.page_label.setText(f"Page {self._page_index + 1} of {total_pages}")
        self.previous_page.setEnabled(self._page_index > 0)
        self.next_page.setEnabled(self._page_index + 1 < total_pages)

    def _handle_log_button_clicked(self) -> None:
        logger.debug("Add Issue clicked")
        self.log_issue_requested.emit()


class IssueListView(QFrame):
    resolve_requested = Signal(int)
    log_issue_requested = Signal()
    detail_requested = Signal(int, str)
    open_requested = Signal(str, int)
    criteria_changed = Signal()

    ACTIVE_COLUMNS = (
        "Issue ID",
        "Issue Title",
        "Status",
        "Problem Description",
        "Logged By",
        "Created",
        "Age",
        "Category",
        "Actions",
    )
    RESOLVED_COLUMNS = (
        "Issue ID",
        "Issue Title",
        "Status When Logged",
        "Problem Description",
        "Solution",
        "Logged By",
        "Resolved By",
        "Resolved",
        "Time Open",
        "Category",
        "Action",
    )

    def __init__(self, mode: str, title: str, search_placeholder: str, *, show_log_action: bool = False, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.include_resolved_fields = mode == "resolved"
        self._issues: list[Issue | ResolvedIssue] = []
        self._visible_table_issues: list[Issue | ResolvedIssue] = []
        self._server_counts: tuple[int, int] | None = None
        self.setObjectName("listPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        self.toolbar = IssueListToolbar(
            title,
            search_placeholder,
            show_log_action=show_log_action,
        )
        self.toolbar.controls_changed.connect(self._handle_controls_changed)
        self.toolbar.log_issue_requested.connect(self.log_issue_requested.emit)
        layout.addWidget(self.toolbar)

        self.empty_panel = EmptyStatePanel()
        layout.addWidget(self.empty_panel)

        self.table = QTableWidget()
        self.table.setObjectName("issueTable")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setMinimumHeight(0)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.itemDoubleClicked.connect(self._open_table_item)
        self.table.itemActivated.connect(self._open_table_item)
        layout.addWidget(self.table, 1)

        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_host = QWidget()
        self.card_host.setObjectName("transparentHost")
        self.card_layout = QVBoxLayout(self.card_host)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(10)
        self.card_scroll.setWidget(self.card_host)
        self.card_scroll.setMinimumHeight(0)
        layout.addWidget(self.card_scroll, 1)
        self.card_scroll.hide()

        self._configure_columns()

    def set_issues(self, issues: list[Issue | ResolvedIssue]) -> None:
        self._issues = list(issues)
        self._server_counts = None
        self.toolbar.reset_page()
        self._refresh_view()

    def set_query_result(self, issues: list[Issue | ResolvedIssue], *, matched: int, total: int) -> None:
        self._issues = list(issues)
        self._server_counts = (max(0, int(matched)), max(0, int(total)))
        self._refresh_view()

    def criteria(self) -> tuple[str, str, int, int]:
        return (
            self.toolbar.search.text(),
            self.toolbar.sort.currentData() or DATE_DESC,
            self.toolbar.page_size(),
            self.toolbar.offset(),
        )

    def set_log_action_enabled(self, enabled: bool) -> None:
        self.toolbar.set_log_action_enabled(enabled)

    def _handle_controls_changed(self) -> None:
        self.criteria_changed.emit()
        if self._server_counts is not None:
            return
        self._refresh_view()

    def _configure_columns(self) -> None:
        columns = self.RESOLVED_COLUMNS if self.include_resolved_fields else self.ACTIVE_COLUMNS
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(74)
        header.setDefaultSectionSize(128)
        header.setStretchLastSection(False)

        for column in range(len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

        if self.include_resolved_fields:
            widths = (150, 180, 148, 280, 280, 118, 118, 146, 100, 116, 190)
            stretch_columns = (3, 4)
        else:
            widths = (150, 200, 126, 340, 120, 146, 86, 120, 210)
            stretch_columns = (3,)

        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        for column in stretch_columns:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def _refresh_view(self) -> None:
        query, sort_key, latest_limit, offset = self.criteria()

        if self._server_counts is None:
            matched = filter_issues(
                self._issues,
                query=query,
                include_resolved_fields=self.include_resolved_fields,
            )
            ordered = prepare_issue_rows(
                self._issues,
                query=query,
                sort_key=sort_key,
                latest_limit=None,
                include_resolved_fields=self.include_resolved_fields,
            )
            visible = ordered[offset : offset + latest_limit]
            matched_count = len(matched)
            total_count = len(self._issues)
        else:
            visible = list(self._issues)
            matched_count, total_count = self._server_counts

        self.toolbar.update_count(len(visible), matched_count, total_count)
        self._clear_cards()
        self.table.setRowCount(0)
        self._visible_table_issues = []
        self.empty_panel.setVisible(len(visible) == 0)
        self.table.setVisible(False)
        self.card_scroll.setVisible(False)
        if len(visible) == 0:
            title, body = self._empty_text(has_query=bool(query.strip()))
            self.empty_panel.set_text(title, body)
            self._adjust_table_height(0)
            self.card_scroll.setMaximumHeight(0)
            return

        if self.toolbar.display_mode.currentData() == "kiosk":
            self._populate_cards(visible)
            self._adjust_card_height(len(visible))
            self.card_scroll.setVisible(True)
            return

        self.table.setVisible(True)
        self._populate_table(visible)
        self._adjust_table_height(len(visible))

    def _populate_table(self, visible: list[Issue | ResolvedIssue]) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self._visible_table_issues = visible
            self.table.setRowCount(len(visible))
            for row, issue in enumerate(visible):
                if self.include_resolved_fields and isinstance(issue, ResolvedIssue):
                    self._populate_resolved_row(row, issue)
                elif isinstance(issue, Issue):
                    self._populate_active_row(row, issue)
                self.table.setRowHeight(row, 62)
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def _populate_cards(self, visible: list[Issue | ResolvedIssue]) -> None:
        for issue in visible:
            if isinstance(issue, ResolvedIssue):
                card = ResolvedIssueCard(issue)
                card.detail_requested.connect(lambda issue_id=issue.id: self._emit_open("resolved", issue_id))
            elif isinstance(issue, Issue):
                card = IssueCard(issue)
                card.resolve_requested.connect(self.resolve_requested.emit)
                card.detail_requested.connect(lambda issue_id=issue.id: self._emit_open("active", issue_id))
            else:
                continue
            self.card_layout.addWidget(card)
        self.card_layout.addStretch(1)

    def _populate_active_row(self, row: int, issue: Issue) -> None:
        self.table.setItem(row, 0, self._item(display_issue_id(issue)))
        self.table.setItem(row, 1, self._item(preview_text(issue.title, 64), issue.title))
        self.table.setCellWidget(row, 2, self._centered_widget(StatusBadge(issue.severity)))
        self.table.setItem(row, 3, self._item(preview_text(issue.description, 92), issue.description))
        self.table.setItem(row, 4, self._item(issue.logged_by))
        self.table.setItem(row, 5, self._item(format_timestamp(issue.created_at), issue.created_at))
        self.table.setItem(row, 6, self._item(format_duration_between(issue.created_at)))
        self.table.setItem(row, 7, self._item(issue.category or "-", issue.category or None))

        view_button = QPushButton("Open")
        view_button.setObjectName("tableActionButton")
        view_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self._emit_open("active", issue_id))
        resolve_button = QPushButton("Resolve")
        resolve_button.setObjectName("tableActionButton")
        resolve_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.resolve_requested.emit(issue_id))
        self.table.setCellWidget(row, 8, self._action_widget(view_button, resolve_button))

    def _populate_resolved_row(self, row: int, issue: ResolvedIssue) -> None:
        self.table.setItem(row, 0, self._item(display_issue_id(issue)))
        self.table.setItem(row, 1, self._item(preview_text(issue.title, 58), issue.title))
        self.table.setCellWidget(row, 2, self._centered_widget(StatusBadge(issue.severity)))
        self.table.setItem(row, 3, self._item(preview_text(issue.description, 86), issue.description))
        self.table.setItem(row, 4, self._item(preview_text(issue.solution, 86), issue.solution))
        self.table.setItem(row, 5, self._item(issue.logged_by))
        self.table.setItem(row, 6, self._item(issue.resolved_by or "-"))
        self.table.setItem(row, 7, self._item(format_timestamp(issue.resolved_at), issue.resolved_at))
        self.table.setItem(row, 8, self._item(format_duration_between(issue.created_at, issue.resolved_at)))
        self.table.setItem(row, 9, self._item(issue.category or "-", issue.category or None))
        view_button = QPushButton("Open")
        view_button.setObjectName("tableActionButton")
        view_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self._emit_open("resolved", issue_id))
        self.table.setCellWidget(row, 10, self._centered_widget(view_button))

    def _open_table_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._visible_table_issues):
            return
        issue = self._visible_table_issues[row]
        if isinstance(issue, ResolvedIssue):
            self._emit_open("resolved", issue.id)
        else:
            self._emit_open("active", issue.id)

    def _emit_open(self, mode: str, issue_id: int) -> None:
        self.open_requested.emit(mode, issue_id)
        self.detail_requested.emit(issue_id, mode)

    def _empty_text(self, *, has_query: bool) -> tuple[str, str]:
        if has_query:
            return ("No matching issues found", "Try a different keyword, machine number, category, or status.")
        if self.include_resolved_fields:
            return ("No resolved history yet", "Troubleshooting memory will appear here after issues are resolved.")
        return ("No active issues", "This machine is currently clear.")

    def _adjust_table_height(self, visible_count: int) -> None:
        if visible_count <= 0:
            self.table.setMinimumHeight(0)
            self.table.setMaximumHeight(0)
            return
        header_height = self.table.horizontalHeader().height() or 38
        row_height = 62
        padding = 14
        visible_rows = min(visible_count, 5)
        height = header_height + visible_rows * row_height + padding
        self.table.setMinimumHeight(height)
        self.table.setMaximumHeight(height if visible_count <= 3 else 16777215)

    def _adjust_card_height(self, visible_count: int) -> None:
        if visible_count <= 0:
            self.card_scroll.setMaximumHeight(0)
            return
        visible_rows = min(visible_count, 3)
        height = visible_rows * 150 + 24
        self.card_scroll.setMinimumHeight(height)
        self.card_scroll.setMaximumHeight(height if visible_count <= 2 else 16777215)

    @staticmethod
    def _item(text: str, tooltip: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text or "-")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    @staticmethod
    def _centered_widget(widget: QWidget) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(widget)
        layout.addStretch(1)
        return host

    @staticmethod
    def _action_widget(*widgets: QWidget) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(8)
        layout.addStretch(1)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return host

    def _clear_cards(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()


class IssueCard(QFrame):
    resolve_requested = Signal(int)
    detail_requested = Signal(int)

    def __init__(self, issue: Issue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("issueCard")
        self.setProperty("statusState", status_state(issue.severity))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(issue.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        top.addWidget(StatusBadge(issue.severity))
        layout.addLayout(top)

        description = QLabel(issue.description)
        description.setWordWrap(True)
        layout.addWidget(description)

        meta_parts = [display_issue_id(issue), f"Machine {issue.machine_number}", issue.severity, f"Logged by {issue.logged_by}", issue.created_at]
        if issue.category:
            meta_parts.insert(3, issue.category)
        meta = QLabel(" | ".join(meta_parts))
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        detail_button = QPushButton("View Details")
        detail_button.setObjectName("tableActionButton")
        detail_button.clicked.connect(lambda: self.detail_requested.emit(issue.id))
        resolve_button = QPushButton("Resolve Issue")
        resolve_button.setObjectName("resolveButton")
        resolve_button.clicked.connect(lambda: self.resolve_requested.emit(issue.id))
        actions.addWidget(detail_button)
        actions.addWidget(resolve_button)
        layout.addLayout(actions)


class ResolvedIssueCard(QFrame):
    detail_requested = Signal(int)

    def __init__(self, issue: ResolvedIssue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("issueCard")
        self.setProperty("archiveState", "resolved")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(issue.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        solution = QLabel(f"Fix: {issue.solution}")
        solution.setWordWrap(True)
        layout.addWidget(solution)

        archive_note = ""
        if issue.archive_status == "pending":
            archive_note = " | Archive pending"
        elif issue.archive_status in {"failed", "archive_error"}:
            archive_note = " | Archive needs attention"

        meta = QLabel(f"{display_issue_id(issue)} | Machine {issue.machine_number} | Resolved {issue.resolved_at} | {issue.severity}{archive_note}")
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        detail_button = QPushButton("View Details")
        detail_button.setObjectName("tableActionButton")
        detail_button.clicked.connect(lambda: self.detail_requested.emit(issue.id))
        actions.addWidget(detail_button)
        layout.addLayout(actions)
