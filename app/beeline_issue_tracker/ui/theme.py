from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QWidget

from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, NO_ISSUES, UNKNOWN_ERROR


DARK_THEME = "dark"
LIGHT_THEME = "light"
DEFAULT_THEME = DARK_THEME


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    display_name: str
    background: str
    background_subtle: str
    panel: str
    panel_hover: str
    text_primary: str
    text_secondary: str
    border: str
    accent: str
    accent_muted: str
    button_background: str
    button_hover: str
    button_pressed: str
    button_text: str
    primary_button_text: str
    input_background: str
    input_border: str
    status_line_down: str
    status_line_down_text: str
    status_non_critical: str
    status_non_critical_text: str
    status_no_issues: str
    status_no_issues_text: str
    status_unknown: str
    status_unknown_text: str
    honeycomb_alpha: int


THEMES: dict[str, ThemeTokens] = {
    DARK_THEME: ThemeTokens(
        name=DARK_THEME,
        display_name="Dark Mode",
        background="#141515",
        background_subtle="#1b1d1e",
        panel="#222426",
        panel_hover="#2a2d2f",
        text_primary="#f5f2ea",
        text_secondary="#bbb8af",
        border="#3a3d3f",
        accent="#f3b333",
        accent_muted="#7a642d",
        button_background="#2b2e30",
        button_hover="#343739",
        button_pressed="#1b1d1e",
        button_text="#f5f2ea",
        primary_button_text="#17120a",
        input_background="#17191a",
        input_border="#4a4d4f",
        status_line_down="#d64545",
        status_line_down_text="#fff7f0",
        status_non_critical="#f4c542",
        status_non_critical_text="#1b1710",
        status_no_issues="#33b56b",
        status_no_issues_text="#07190f",
        status_unknown="#8a929a",
        status_unknown_text="#101418",
        honeycomb_alpha=12,
    ),
    LIGHT_THEME: ThemeTokens(
        name=LIGHT_THEME,
        display_name="Light Mode",
        background="#f4f5f2",
        background_subtle="#ecefea",
        panel="#ffffff",
        panel_hover="#f7f8f5",
        text_primary="#202326",
        text_secondary="#5d6468",
        border="#d4d8d1",
        accent="#c98205",
        accent_muted="#f1d28b",
        button_background="#eef0ec",
        button_hover="#e3e7df",
        button_pressed="#d8ddd3",
        button_text="#202326",
        primary_button_text="#17120a",
        input_background="#ffffff",
        input_border="#c1c7bd",
        status_line_down="#cf3939",
        status_line_down_text="#fff7f0",
        status_non_critical="#e0a816",
        status_non_critical_text="#1b1710",
        status_no_issues="#2f9b61",
        status_no_issues_text="#f4fff8",
        status_unknown="#7f878c",
        status_unknown_text="#ffffff",
        honeycomb_alpha=20,
    ),
}


STATUS_STATES = {
    LINE_DOWN: "line_down",
    NON_CRITICAL: "non_critical",
    NO_ISSUES: "no_issues",
    UNKNOWN_ERROR: "unknown",
}


class ThemeManager(QObject):
    theme_changed = Signal(str)

    SETTINGS_KEY = "ui/theme"

    def __init__(self, settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings or QSettings()
        stored_theme = str(self.settings.value(self.SETTINGS_KEY, DEFAULT_THEME))
        self._theme_name = stored_theme if stored_theme in THEMES else DEFAULT_THEME

    @property
    def current_theme_name(self) -> str:
        return self._theme_name

    @property
    def current_theme(self) -> ThemeTokens:
        return THEMES[self._theme_name]

    def set_theme(self, theme_name: str) -> None:
        if theme_name not in THEMES:
            raise ValueError(f"Unknown BeeLine theme: {theme_name}")
        if theme_name == self._theme_name:
            return
        self._theme_name = theme_name
        self.settings.setValue(self.SETTINGS_KEY, theme_name)
        self.settings.sync()
        self.theme_changed.emit(theme_name)

    def toggle_theme(self) -> None:
        self.set_theme(LIGHT_THEME if self._theme_name == DARK_THEME else DARK_THEME)

    def build_stylesheet(self) -> str:
        return build_stylesheet(self.current_theme)


def theme_from_name(theme_name: str | None) -> ThemeTokens:
    return THEMES.get(theme_name or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def status_state(status: str) -> str:
    return STATUS_STATES.get(status, STATUS_STATES[UNKNOWN_ERROR])


def status_color(status: str, theme: ThemeTokens | None = None) -> str:
    tokens = theme or THEMES[DEFAULT_THEME]
    return {
        LINE_DOWN: tokens.status_line_down,
        NON_CRITICAL: tokens.status_non_critical,
        NO_ISSUES: tokens.status_no_issues,
        UNKNOWN_ERROR: tokens.status_unknown,
    }.get(status, tokens.status_unknown)


def status_text_color(status: str, theme: ThemeTokens | None = None) -> str:
    tokens = theme or THEMES[DEFAULT_THEME]
    return {
        LINE_DOWN: tokens.status_line_down_text,
        NON_CRITICAL: tokens.status_non_critical_text,
        NO_ISSUES: tokens.status_no_issues_text,
        UNKNOWN_ERROR: tokens.status_unknown_text,
    }.get(status, tokens.status_unknown_text)


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def build_stylesheet(theme: ThemeTokens | str | None = None) -> str:
    tokens = theme_from_name(theme) if isinstance(theme, str) or theme is None else theme
    return f"""
    QMainWindow, QWidget {{
        background-color: {tokens.background};
        color: {tokens.text_primary};
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 15px;
    }}

    QWidget#transparentHost {{
        background: transparent;
    }}

    QLabel {{
        color: {tokens.text_primary};
        background: transparent;
    }}

    QLabel#mutedLabel {{
        color: {tokens.text_secondary};
    }}

    QLabel#subtitleLabel {{
        color: {tokens.text_secondary};
        font-size: 18px;
    }}

    QLabel#pageTitle {{
        color: {tokens.text_primary};
        font-size: 34px;
        font-weight: 700;
    }}

    QLabel#brandText {{
        color: {tokens.primary_button_text};
        background-color: {tokens.accent};
        border: 1px solid {tokens.accent};
        border-radius: 6px;
        font-size: 17px;
        font-weight: 800;
        padding: 8px;
    }}

    QLabel#sectionTitle {{
        color: {tokens.accent};
        font-size: 20px;
        font-weight: 700;
    }}

    QLabel#machineNumber {{
        color: {tokens.text_primary};
        font-size: 36px;
        font-weight: 800;
    }}

    QLabel#cardTitle {{
        color: {tokens.text_primary};
        font-size: 19px;
        font-weight: 800;
    }}

    QLabel#openCount {{
        color: {tokens.text_primary};
        font-size: 18px;
        font-weight: 700;
    }}

    QLabel#metricLabel,
    QLabel#controlLabel {{
        color: {tokens.text_secondary};
        font-size: 13px;
        font-weight: 650;
    }}

    QLabel#metricValue {{
        color: {tokens.text_primary};
        font-size: 17px;
        font-weight: 750;
    }}

    QPushButton {{
        background-color: {tokens.button_background};
        border: 1px solid {tokens.border};
        border-radius: 7px;
        color: {tokens.button_text};
        font-size: 16px;
        font-weight: 650;
        padding: 10px 15px;
    }}

    QPushButton:hover {{
        border-color: {tokens.accent};
        background-color: {tokens.button_hover};
    }}

    QPushButton:pressed {{
        background-color: {tokens.button_pressed};
    }}

    QPushButton#primaryButton,
    QPushButton#sectionPrimaryButton {{
        background-color: {tokens.accent};
        border-color: {tokens.accent};
        color: {tokens.primary_button_text};
        font-weight: 800;
    }}

    QPushButton#primaryButton:hover,
    QPushButton#sectionPrimaryButton:hover {{
        background-color: {tokens.status_non_critical};
    }}

    QPushButton#sectionPrimaryButton {{
        padding: 8px 13px;
        font-size: 15px;
    }}

    QPushButton#resolveButton {{
        background-color: {tokens.background_subtle};
        border-color: {tokens.accent};
        color: {tokens.accent};
        padding: 8px 12px;
    }}

    QPushButton#tableActionButton {{
        background-color: transparent;
        border-color: {tokens.accent};
        color: {tokens.accent};
        padding: 6px 10px;
        font-size: 14px;
        font-weight: 750;
    }}

    QPushButton#tableActionButton:hover {{
        background-color: {tokens.accent_muted};
        color: {tokens.text_primary};
    }}

    QPushButton#themeToggleButton {{
        background-color: {tokens.background_subtle};
        color: {tokens.text_primary};
        padding: 9px 14px;
    }}

    QPushButton#statusLineDownButton,
    QPushButton#statusNonCriticalButton {{
        min-height: 58px;
        font-size: 20px;
        font-weight: 800;
    }}

    QPushButton#statusLineDownButton:checked {{
        background-color: {tokens.status_line_down};
        border-color: {tokens.status_line_down};
        color: {tokens.status_line_down_text};
    }}

    QPushButton#statusNonCriticalButton:checked {{
        background-color: {tokens.status_non_critical};
        border-color: {tokens.status_non_critical};
        color: {tokens.status_non_critical_text};
    }}

    QFrame#machineCard,
    QFrame#infoPanel,
    QFrame#issueCard,
    QFrame#formPanel,
    QFrame#machineHeader,
    QFrame#listPanel {{
        background-color: {tokens.panel};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}

    QFrame#metricPill {{
        background-color: {tokens.background_subtle};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}

    QFrame#machineCard:hover {{
        border-color: {tokens.accent};
        background-color: {tokens.panel_hover};
    }}

    QFrame#machineCard[statusState="line_down"],
    QFrame#machineHeader[statusState="line_down"],
    QFrame#issueCard[statusState="line_down"] {{
        border-left: 5px solid {tokens.status_line_down};
    }}

    QFrame#machineCard[statusState="non_critical"],
    QFrame#machineHeader[statusState="non_critical"],
    QFrame#issueCard[statusState="non_critical"] {{
        border-left: 5px solid {tokens.status_non_critical};
    }}

    QFrame#machineCard[statusState="no_issues"],
    QFrame#machineHeader[statusState="no_issues"],
    QFrame#issueCard[statusState="no_issues"] {{
        border-left: 5px solid {tokens.status_no_issues};
    }}

    QFrame#machineCard[statusState="unknown"],
    QFrame#machineHeader[statusState="unknown"],
    QFrame#issueCard[statusState="unknown"] {{
        border-left: 5px solid {tokens.status_unknown};
    }}

    QFrame#issueCard[archiveState="resolved"] {{
        border-left: 5px solid {tokens.accent};
    }}

    QLabel#statusBadge {{
        border-radius: 6px;
        font-size: 15px;
        font-weight: 800;
        padding: 5px 10px;
    }}

    QLabel#statusBadge[statusState="line_down"] {{
        background-color: {tokens.status_line_down};
        color: {tokens.status_line_down_text};
    }}

    QLabel#statusBadge[statusState="non_critical"] {{
        background-color: {tokens.status_non_critical};
        color: {tokens.status_non_critical_text};
    }}

    QLabel#statusBadge[statusState="no_issues"] {{
        background-color: {tokens.status_no_issues};
        color: {tokens.status_no_issues_text};
    }}

    QLabel#statusBadge[statusState="unknown"] {{
        background-color: {tokens.status_unknown};
        color: {tokens.status_unknown_text};
    }}

    QLineEdit, QTextEdit, QComboBox {{
        background-color: {tokens.input_background};
        border: 1px solid {tokens.input_border};
        border-radius: 7px;
        color: {tokens.text_primary};
        selection-background-color: {tokens.accent};
        selection-color: {tokens.primary_button_text};
        padding: 8px;
    }}

    QLineEdit[readOnly="true"] {{
        color: {tokens.text_secondary};
        background-color: {tokens.background_subtle};
    }}

    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border-color: {tokens.accent};
    }}

    QComboBox::drop-down {{
        border: 0;
        width: 28px;
    }}

    QLineEdit#searchBox {{
        padding-left: 12px;
    }}

    QComboBox#compactDropdown {{
        min-width: 128px;
        padding: 7px 9px;
    }}

    QTableWidget#issueTable {{
        background-color: {tokens.panel};
        alternate-background-color: {tokens.background_subtle};
        border: 1px solid {tokens.border};
        border-radius: 7px;
        color: {tokens.text_primary};
        gridline-color: transparent;
        selection-background-color: {tokens.panel_hover};
        selection-color: {tokens.text_primary};
    }}

    QTableWidget#issueTable::item {{
        border-bottom: 1px solid {tokens.border};
        padding: 7px 8px;
    }}

    QTableWidget#issueTable::item:hover {{
        background-color: {tokens.panel_hover};
    }}

    QHeaderView::section {{
        background-color: {tokens.background_subtle};
        border: 0;
        border-bottom: 1px solid {tokens.border};
        color: {tokens.text_secondary};
        font-size: 13px;
        font-weight: 750;
        padding: 8px;
    }}

    QTableCornerButton::section {{
        background-color: {tokens.background_subtle};
        border: 0;
    }}

    QScrollArea {{
        border: 0;
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: {tokens.background_subtle};
        width: 14px;
    }}

    QScrollBar::handle:vertical {{
        background: {tokens.border};
        border-radius: 6px;
        min-height: 40px;
    }}

    QSplitter::handle {{
        background-color: {tokens.background_subtle};
    }}

    QStatusBar {{
        background-color: {tokens.background_subtle};
        color: {tokens.text_secondary};
    }}
    """
