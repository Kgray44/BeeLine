from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.config import AppPaths, RuntimeConfig
from beeline_issue_tracker.future_features import DataHealthSummary
from beeline_issue_tracker.perf import recent_operations
from beeline_issue_tracker.ui_v2.theme import (
    CARD_COLOR_STYLE_BRIGHT,
    CARD_COLOR_STYLE_LEGACY,
    DARK_THEME,
    LIGHT_THEME,
    SYSTEM_THEME,
    ThemeManager,
)
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground


class SettingsPage(HoneycombBackground):
    back_requested = Signal()
    logout_requested = Signal()
    archive_retry_requested = Signal()
    data_health_requested = Signal()
    archive_check_requested = Signal()
    archive_repair_requested = Signal()
    machine_config_save_requested = Signal(dict, str, bool)

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
        self._selected_machine_number = ""

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.card_color_style = QComboBox()
        self.card_color_style.addItem("Card Color Style Bright", CARD_COLOR_STYLE_BRIGHT)
        self.card_color_style.addItem("Card Color Style Legacy", CARD_COLOR_STYLE_LEGACY)
        self.card_color_style.setCurrentIndex(
            max(0, self.card_color_style.findData(theme_manager.current_card_color_style))
        )
        self.card_color_style.currentIndexChanged.connect(self._card_color_style_changed)
        appearance.addRow("Machine cards", self.card_color_style)
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
        self.check_archive = QPushButton("Check Excel Archive")
        self.check_archive.setObjectName("secondaryButton")
        self.check_archive.clicked.connect(self.archive_check_requested.emit)
        self.repair_archive = QPushButton("Repair Archive")
        self.repair_archive.setObjectName("secondaryButton")
        self.repair_archive.clicked.connect(self.archive_repair_requested.emit)
        archive_layout.addWidget(self.archive_health, 1)
        archive_layout.addWidget(self.retry_archive)
        archive_layout.addWidget(self.check_archive)
        archive_layout.addWidget(self.repair_archive)
        layout.addLayout(archive_layout)
        self.archive_check_status = QLabel("Excel archive is not opened during default health checks.")
        self.archive_check_status.setObjectName("mutedLabel")
        self.archive_check_status.setWordWrap(True)
        layout.addWidget(self.archive_check_status)

        data_health_title = QLabel("Data Health")
        data_health_title.setObjectName("sectionTitle")
        layout.addWidget(data_health_title)
        health_actions = QHBoxLayout()
        self.data_health = QLabel("Data Health: not refreshed")
        self.data_health.setObjectName("mutedLabel")
        self.data_health.setWordWrap(True)
        refresh_health = QPushButton("Refresh Health")
        refresh_health.setObjectName("secondaryButton")
        refresh_health.clicked.connect(self.data_health_requested.emit)
        health_actions.addWidget(self.data_health, 1)
        health_actions.addWidget(refresh_health)
        layout.addLayout(health_actions)

        perf_title = QLabel("Performance Guardrails")
        perf_title.setObjectName("sectionTitle")
        layout.addWidget(perf_title)
        self.performance_summary = QLabel("No slow operations recorded yet.")
        self.performance_summary.setObjectName("mutedLabel")
        self.performance_summary.setWordWrap(True)
        layout.addWidget(self.performance_summary)

        machine_title = QLabel("Machine Config Manager")
        machine_title.setObjectName("sectionTitle")
        layout.addWidget(machine_title)
        machine_note = QLabel("Changes are written to the local runtime config with a timestamped backup. Restart BeeLine Future to apply changes.")
        machine_note.setObjectName("mutedLabel")
        machine_note.setWordWrap(True)
        layout.addWidget(machine_note)
        self.machine_table = QTableWidget()
        self.machine_table.setObjectName("issueTable")
        self.machine_table.setColumnCount(6)
        self.machine_table.setHorizontalHeaderLabels(("Machine", "Name", "Area", "Cell", "Asset", "Order"))
        self.machine_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.machine_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.machine_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.machine_table.verticalHeader().setVisible(False)
        self.machine_table.itemSelectionChanged.connect(self._load_selected_machine)
        self.machine_table.setMaximumHeight(220)
        layout.addWidget(self.machine_table)

        machine_form = QFormLayout()
        machine_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.machine_number = QLineEdit()
        self.machine_name = QLineEdit()
        self.machine_area = QLineEdit()
        self.machine_cell = QLineEdit()
        self.machine_asset = QLineEdit()
        self.machine_order = QSpinBox()
        self.machine_order.setRange(0, 99999)
        self.machine_manufacturer = QLineEdit()
        self.machine_model = QLineEdit()
        self.machine_imm_serial = QLineEdit()
        self.machine_robot_type = QLineEdit()
        self.machine_robot_model = QLineEdit()
        self.machine_robot_serial = QLineEdit()
        machine_form.addRow("Machine number", self.machine_number)
        machine_form.addRow("Name", self.machine_name)
        machine_form.addRow("Area", self.machine_area)
        machine_form.addRow("Cell", self.machine_cell)
        machine_form.addRow("Asset tag", self.machine_asset)
        machine_form.addRow("Display order", self.machine_order)
        machine_form.addRow("Manufacturer", self.machine_manufacturer)
        machine_form.addRow("Model", self.machine_model)
        machine_form.addRow("IMM serial", self.machine_imm_serial)
        machine_form.addRow("Robot type", self.machine_robot_type)
        machine_form.addRow("Robot model", self.machine_robot_model)
        machine_form.addRow("Robot serial", self.machine_robot_serial)
        layout.addLayout(machine_form)
        machine_actions = QHBoxLayout()
        new_machine = QPushButton("New Machine")
        new_machine.setObjectName("quietButton")
        new_machine.clicked.connect(self._clear_machine_form)
        save_machine = QPushButton("Add / Update Machine")
        save_machine.setObjectName("secondaryButton")
        save_machine.clicked.connect(lambda: self.machine_config_save_requested.emit(self.machine_values(), self._selected_machine_number, False))
        deactivate_machine = QPushButton("Deactivate Machine")
        deactivate_machine.setObjectName("secondaryButton")
        deactivate_machine.clicked.connect(lambda: self.machine_config_save_requested.emit(self.machine_values(), self._selected_machine_number, True))
        machine_actions.addWidget(new_machine)
        machine_actions.addStretch(1)
        machine_actions.addWidget(save_machine)
        machine_actions.addWidget(deactivate_machine)
        layout.addLayout(machine_actions)
        self.machine_config_status = QLabel("")
        self.machine_config_status.setObjectName("mutedLabel")
        self.machine_config_status.setWordWrap(True)
        layout.addWidget(self.machine_config_status)
        self._populate_machine_table()

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

        scroll.setWidget(panel)
        page.addWidget(scroll, 1)

    def _theme_changed(self) -> None:
        self.theme_manager.set_theme(self.theme_mode.currentData() or DARK_THEME)

    def _card_color_style_changed(self) -> None:
        self.theme_manager.set_card_color_style(self.card_color_style.currentData() or CARD_COLOR_STYLE_BRIGHT)

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
        self._refresh_performance_summary()

    def set_data_health(self, summary: DataHealthSummary) -> None:
        self.data_health.setText(
            "\n".join(
                (
                    f"SQLite database: {'OK' if summary.db_exists else 'missing'} | {summary.db_path}",
                    f"Machines: {summary.machine_count}",
                    f"Active issues: {summary.active_issue_count}",
                    f"Resolved cache rows: {summary.resolved_cache_count}",
                    f"Archive pending: {summary.archive_pending_count}",
                    f"Archive failed: {summary.archive_failed_count}",
                    f"Last resolved issue: {summary.last_resolved_label}",
                    f"Last archive success: {summary.last_archive_success}",
                    f"Runtime config: {summary.runtime_config_path}",
                    f"Excel archive path exists: {'yes' if summary.archive_path_exists else 'no'} | {summary.archive_path}",
                )
            )
        )
        self._refresh_performance_summary()

    def set_archive_check_status(self, text: str) -> None:
        self.archive_check_status.setText(text)

    def set_machine_config_status(self, text: str) -> None:
        self.machine_config_status.setText(text)

    def machine_values(self) -> dict[str, object]:
        return {
            "machine_number": self.machine_number.text().strip(),
            "name": self.machine_name.text().strip(),
            "area": self.machine_area.text().strip(),
            "cell": self.machine_cell.text().strip(),
            "asset_tag": self.machine_asset.text().strip(),
            "display_order": self.machine_order.value(),
            "manufacturer": self.machine_manufacturer.text().strip(),
            "model": self.machine_model.text().strip(),
            "imm_serial": self.machine_imm_serial.text().strip(),
            "robot_type": self.machine_robot_type.text().strip(),
            "robot_model": self.machine_robot_model.text().strip(),
            "robot_serial": self.machine_robot_serial.text().strip(),
            "is_active": True,
        }

    def _populate_machine_table(self) -> None:
        rows = [machine for machine in self.runtime_config.machines if machine.is_active]
        self.machine_table.setRowCount(len(rows))
        for row, machine in enumerate(rows):
            values = (
                machine.machine_number,
                machine.name,
                machine.area,
                machine.cell,
                machine.asset_tag,
                str(machine.display_order),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setData(Qt.ItemDataRole.UserRole, machine.machine_number)
                self.machine_table.setItem(row, column, item)
            self.machine_table.setRowHeight(row, 34)
        self.machine_table.resizeColumnsToContents()

    def _load_selected_machine(self) -> None:
        selected = self.machine_table.selectedItems()
        if not selected:
            return
        machine_number = selected[0].data(Qt.ItemDataRole.UserRole)
        machine = next((item for item in self.runtime_config.machines if item.machine_number == machine_number), None)
        if machine is None:
            return
        self._selected_machine_number = machine.machine_number
        self.machine_number.setText(machine.machine_number)
        self.machine_name.setText(machine.name)
        self.machine_area.setText(machine.area)
        self.machine_cell.setText(machine.cell)
        self.machine_asset.setText(machine.asset_tag)
        self.machine_order.setValue(machine.display_order)
        self.machine_manufacturer.setText(machine.manufacturer)
        self.machine_model.setText(machine.model)
        self.machine_imm_serial.setText(machine.imm_serial)
        self.machine_robot_type.setText(machine.robot_type)
        self.machine_robot_model.setText(machine.robot_model)
        self.machine_robot_serial.setText(machine.robot_serial)

    def _clear_machine_form(self) -> None:
        self._selected_machine_number = ""
        for field in (
            self.machine_number,
            self.machine_name,
            self.machine_area,
            self.machine_cell,
            self.machine_asset,
            self.machine_manufacturer,
            self.machine_model,
            self.machine_imm_serial,
            self.machine_robot_type,
            self.machine_robot_model,
            self.machine_robot_serial,
        ):
            field.clear()
        self.machine_order.setValue(0)
        self.machine_table.clearSelection()

    def _refresh_performance_summary(self) -> None:
        samples = recent_operations(12)
        if not samples:
            self.performance_summary.setText("No slow operations recorded yet.")
            return
        lines = []
        for sample in samples:
            marker = {
                "warning": "WARNING",
                "slow": "SLOW",
                "critical": "CRITICAL",
            }.get(sample.level, "OK")
            lines.append(f"{marker}: {sample.event} | {sample.elapsed_ms} ms | {sample.created_at}")
        self.performance_summary.setText("\n".join(lines))
