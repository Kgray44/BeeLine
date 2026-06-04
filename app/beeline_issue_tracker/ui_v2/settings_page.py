from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from beeline_issue_tracker.config import AppPaths, RuntimeConfig
from beeline_issue_tracker.ui_v2.theme import DARK_THEME, LIGHT_THEME, SYSTEM_THEME, ThemeManager
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground


class SettingsPage(HoneycombBackground):
    back_requested = Signal()
    logout_requested = Signal()
    archive_retry_requested = Signal()

    def __init__(
        self,
        paths: AppPaths,
        runtime_config: RuntimeConfig,
        theme_manager: ThemeManager,
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.paths = paths
        self.runtime_config = runtime_config
        self.theme_manager = theme_manager

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quietButton")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(BrandHeader("Settings", "BeeLine configuration and archive tools", paths.logo_path(), theme_manager), 1)
        logout = QPushButton("Log Out")
        logout.setObjectName("quietButton")
        logout.clicked.connect(self.logout_requested.emit)
        header.addWidget(logout)
        page.addLayout(header)

        panel = QFrame()
        panel.setObjectName("formPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)

        theme_title = QLabel("Appearance")
        theme_title.setObjectName("sectionTitle")
        layout.addWidget(theme_title)
        appearance = QFormLayout()
        appearance.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.theme_mode = QComboBox()
        self.theme_mode.addItem("Light", LIGHT_THEME)
        self.theme_mode.addItem("Dark", DARK_THEME)
        self.theme_mode.addItem("System", SYSTEM_THEME)
        self.theme_mode.setCurrentIndex(max(0, self.theme_mode.findData(theme_manager.current_theme_name)))
        self.theme_mode.currentIndexChanged.connect(self._theme_changed)
        appearance.addRow("Theme mode", self.theme_mode)
        layout.addLayout(appearance)

        config_title = QLabel("Runtime Paths")
        config_title.setObjectName("sectionTitle")
        layout.addWidget(config_title)
        paths_form = QFormLayout()
        paths_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for label, value in (
            ("Logo path", str(paths.logo_path() or "")),
            ("Runtime config", str(paths.runtime_config_path)),
            ("Data storage", str(paths.db_path)),
            ("Excel archive", str(paths.archive_path)),
            ("Backup/export", str(paths.backups_dir)),
        ):
            field = QLineEdit(value)
            field.setReadOnly(True)
            paths_form.addRow(label, field)
        self.raw_paths = QCheckBox("Show raw paths in main status bar")
        self.raw_paths.setChecked(runtime_config.ui.show_raw_paths)
        self.raw_paths.setEnabled(False)
        paths_form.addRow("Privacy", self.raw_paths)
        layout.addLayout(paths_form)

        defaults_title = QLabel("Issue Defaults")
        defaults_title.setObjectName("sectionTitle")
        layout.addWidget(defaults_title)
        defaults = QFormLayout()
        defaults.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.default_filter = QComboBox()
        for label, value in (
            ("All Issues", "all"),
            ("Open Issues", "open"),
            ("Archived / Resolved Issues", "resolved"),
        ):
            self.default_filter.addItem(label, value)
        self.default_filter.setCurrentIndex(
            max(0, self.default_filter.findData(runtime_config.ui.default_dashboard_filter))
        )
        self.default_filter.setEnabled(False)
        self.default_sort = QLineEdit(runtime_config.ui.default_issue_sort)
        self.default_sort.setReadOnly(True)
        self.default_count = QSpinBox()
        self.default_count.setRange(1, 500)
        self.default_count.setValue(runtime_config.ui.default_issue_display_count)
        self.default_count.setEnabled(False)
        defaults.addRow("Dashboard issue filter", self.default_filter)
        defaults.addRow("Default issue sort", self.default_sort)
        defaults.addRow("Issue display count", self.default_count)
        layout.addLayout(defaults)

        archive_title = QLabel("Archive Health")
        archive_title.setObjectName("sectionTitle")
        layout.addWidget(archive_title)
        archive_layout = QHBoxLayout()
        self.archive_health = QLabel("Archive Health: Check Not Run")
        self.archive_health.setObjectName("mutedLabel")
        self.archive_health.setWordWrap(True)
        self.retry_archive = QPushButton("Retry Failed Archive Writes")
        self.retry_archive.setObjectName("secondaryButton")
        self.retry_archive.clicked.connect(self.archive_retry_requested.emit)
        archive_layout.addWidget(self.archive_health, 1)
        archive_layout.addWidget(self.retry_archive)
        layout.addLayout(archive_layout)

        categories_title = QLabel("Category Dropdown Values")
        categories_title.setObjectName("sectionTitle")
        layout.addWidget(categories_title)
        self.categories = QTextEdit()
        self.categories.setPlainText("\n".join(runtime_config.ui.category_options))
        self.categories.setMinimumHeight(92)
        self.categories.setReadOnly(True)
        layout.addWidget(self.categories)

        note = QLabel("Edit local config to change disabled settings; they are shown here for admin visibility.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        page.addWidget(panel)
        page.addStretch(1)

    def _theme_changed(self) -> None:
        self.theme_manager.set_theme(self.theme_mode.currentData() or DARK_THEME)

    def set_archive_health(self, counts: dict[str, int]) -> None:
        pending = int(counts.get("pending", 0))
        failed = int(counts.get("failed", 0)) + int(counts.get("archive_error", 0))
        retry_pending = int(counts.get("retry_pending", 0))
        if failed:
            text = f"Archive Health: Failed Writes ({failed} failed"
            if pending or retry_pending:
                text += f", {pending} pending, {retry_pending} retry pending"
            text += ")"
        elif retry_pending:
            text = f"Archive Health: Pending Writes ({retry_pending} retry pending, {pending} pending)"
        elif pending:
            text = f"Archive Health: Pending Writes ({pending} pending)"
        else:
            text = "Archive Health: OK"
        self.archive_health.setText(text)
        self.retry_archive.setEnabled(failed + retry_pending > 0)
