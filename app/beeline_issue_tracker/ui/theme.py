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
        background="#10161d",
        background_subtle="#151d25",
        panel="#1b242c",
        panel_hover="#222d36",
        text_primary="#f7f3e8",
        text_secondary="#b9c2c9",
        border="#35424b",
        accent="#f6b73c",
        accent_muted="#8d6a2a",
        button_background="#25313a",
        button_hover="#2d3b45",
        button_pressed="#172027",
        button_text="#f7f3e8",
        primary_button_text="#17120a",
        input_background="#121b23",
        input_border="#46545d",
        status_line_down="#d64545",
        status_line_down_text="#fff7f0",
        status_non_critical="#f4c542",
        status_non_critical_text="#1b1710",
        status_no_issues="#33b56b",
        status_no_issues_text="#07190f",
        status_unknown="#8a929a",
        status_unknown_text="#101418",
        honeycomb_alpha=18,
    ),
    LIGHT_THEME: ThemeTokens(
        name=LIGHT_THEME,
        display_name="Light Mode",
        background="#f6f0e2",
        background_subtle="#efe4cf",
        panel="#fff8e9",
        panel_hover="#f7ebd3",
        text_primary="#1d252c",
        text_secondary="#59636b",
        border="#d8c8a7",
        accent="#c98512",
        accent_muted="#efd59c",
        button_background="#f0dfbd",
        button_hover="#e7cf9c",
        button_pressed="#ddbf83",
        button_text="#1d252c",
        primary_button_text="#17120a",
        input_background="#fffdf5",
        input_border="#cbb78d",
        status_line_down="#cf3939",
        status_line_down_text="#fff7f0",
        status_non_critical="#e0a816",
        status_non_critical_text="#1b1710",
        status_no_issues="#2f9b61",
        status_no_issues_text="#f4fff8",
        status_unknown="#7f878c",
        status_unknown_text="#ffffff",
        honeycomb_alpha=34,
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
        font-size: 21px;
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

    QPushButton {{
        background-color: {tokens.button_background};
        border: 1px solid {tokens.border};
        border-radius: 6px;
        color: {tokens.button_text};
        font-size: 17px;
        font-weight: 650;
        padding: 11px 16px;
    }}

    QPushButton:hover {{
        border-color: {tokens.accent};
        background-color: {tokens.button_hover};
    }}

    QPushButton:pressed {{
        background-color: {tokens.button_pressed};
    }}

    QPushButton#primaryButton {{
        background-color: {tokens.accent};
        border-color: {tokens.accent};
        color: {tokens.primary_button_text};
    }}

    QPushButton#primaryButton:hover {{
        background-color: {tokens.status_non_critical};
    }}

    QPushButton#resolveButton {{
        background-color: {tokens.background_subtle};
        border-color: {tokens.accent};
        color: {tokens.accent};
        padding: 8px 12px;
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
    QFrame#formPanel {{
        background-color: {tokens.panel};
        border: 1px solid {tokens.border};
        border-radius: 8px;
    }}

    QFrame#machineCard:hover {{
        border-color: {tokens.accent};
        background-color: {tokens.panel_hover};
    }}

    QFrame#machineCard[statusState="line_down"],
    QFrame#issueCard[statusState="line_down"] {{
        border-left: 8px solid {tokens.status_line_down};
    }}

    QFrame#machineCard[statusState="non_critical"],
    QFrame#issueCard[statusState="non_critical"] {{
        border-left: 8px solid {tokens.status_non_critical};
    }}

    QFrame#machineCard[statusState="no_issues"],
    QFrame#issueCard[statusState="no_issues"] {{
        border-left: 8px solid {tokens.status_no_issues};
    }}

    QFrame#machineCard[statusState="unknown"],
    QFrame#issueCard[statusState="unknown"] {{
        border-left: 8px solid {tokens.status_unknown};
    }}

    QFrame#issueCard[archiveState="resolved"] {{
        border-left: 8px solid {tokens.accent};
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
        border-radius: 6px;
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
