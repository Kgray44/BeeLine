from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

from beeline_issue_tracker.security import RoleConfig, verify_pin


APP_NAME = "BeeLine Issue Tracker"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MachineConfig:
    machine_number: str
    name: str
    area: str
    cell: str
    asset_tag: str
    display_order: int

    def as_database_row(self) -> tuple[str, str, str, str, str, int]:
        return (
            self.machine_number,
            self.name,
            self.area,
            self.cell,
            self.asset_tag,
            self.display_order,
        )


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = True
    risk_window_days: int = 30
    recurrence_window_days: int = 60
    high_risk_threshold: int = 65
    critical_risk_threshold: int = 85
    grouped_chart_periods: int = 8
    persist_predictive_alerts: bool = True
    enable_fix_suggestions: bool = True
    enable_related_issues: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
    machines: tuple[MachineConfig, ...]
    roles: dict[str, RoleConfig]
    analytics: AnalyticsConfig = AnalyticsConfig()

    def machine_rows(self) -> tuple[tuple[str, str, str, str, str, int], ...]:
        return tuple(machine.as_database_row() for machine in self.machines)

    def enabled_roles(self) -> tuple[RoleConfig, ...]:
        return tuple(role for role in self.roles.values() if role.enabled and role.pin_hash)

    def resolve_requires_pin(self) -> bool:
        return any(
            self.roles.get(role_name, RoleConfig(role_name)).enabled
            and bool(self.roles.get(role_name, RoleConfig(role_name)).pin_hash)
            for role_name in ("technician", "admin")
        )

    def verify_pin_for_roles(self, pin: str, role_names: tuple[str, ...]) -> bool:
        for role_name in role_names:
            role = self.roles.get(role_name)
            if role and role.enabled and role.pin_hash and verify_pin(pin, role.pin_hash):
                return True
        return False


@dataclass(frozen=True)
class AppPaths:
    root_dir: Path
    template_dir: Path
    config_dir: Path
    data_dir: Path
    archive_dir: Path
    logs_dir: Path
    backups_dir: Path
    attachments_dir: Path
    branding_dir: Path
    config_template_path: Path
    db_template_path: Path
    archive_template_path: Path
    runtime_config_path: Path
    db_path: Path
    archive_path: Path
    approved_logo_path: Path
    placeholder_logo_path: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        root_dir = Path(os.environ.get("BEELINE_ROOT_DIR", project_root())).expanduser().resolve()
        template_dir = Path(os.environ.get("BEELINE_TEMPLATE_DIR", root_dir / "templates")).expanduser().resolve()
        config_dir = Path(os.environ.get("BEELINE_CONFIG_DIR", root_dir / "config")).expanduser().resolve()
        data_dir = Path(os.environ.get("BEELINE_DATA_DIR", root_dir / "data")).expanduser().resolve()
        archive_dir = Path(os.environ.get("BEELINE_ARCHIVE_DIR", root_dir / "archive")).expanduser().resolve()
        logs_dir = Path(os.environ.get("BEELINE_LOG_DIR", root_dir / "logs")).expanduser().resolve()
        backups_dir = Path(os.environ.get("BEELINE_BACKUP_DIR", root_dir / "backups")).expanduser().resolve()
        branding_dir = root_dir / "assets" / "branding"
        return cls(
            root_dir=root_dir,
            template_dir=template_dir,
            config_dir=config_dir,
            data_dir=data_dir,
            archive_dir=archive_dir,
            logs_dir=logs_dir,
            backups_dir=backups_dir,
            attachments_dir=data_dir / "attachments",
            branding_dir=branding_dir,
            config_template_path=template_dir / "beeline_config.template.json",
            db_template_path=template_dir / "beeline.template.sqlite",
            archive_template_path=template_dir / "beeline_archive.template.xlsx",
            runtime_config_path=config_dir / "beeline_config.json",
            db_path=data_dir / "beeline.sqlite",
            archive_path=archive_dir / "beeline_resolved_archive.xlsx",
            approved_logo_path=branding_dir / "nolato_logo.png",
            placeholder_logo_path=branding_dir / "nolato_logo_placeholder.png",
        )

    def ensure_directories(self) -> None:
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.branding_dir.mkdir(parents=True, exist_ok=True)

    def logo_path(self) -> Path | None:
        if self.approved_logo_path.exists():
            return self.approved_logo_path
        if self.placeholder_logo_path.exists():
            return self.placeholder_logo_path
        return None


def initialize_runtime_files(paths: AppPaths) -> None:
    paths.ensure_directories()
    copies = (
        (paths.config_template_path, paths.runtime_config_path),
        (paths.db_template_path, paths.db_path),
        (paths.archive_template_path, paths.archive_path),
    )
    for template_path, runtime_path in copies:
        if runtime_path.exists():
            continue
        if not template_path.exists():
            raise FileNotFoundError(f"Missing BeeLine template file: {template_path}")
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        copy2(template_path, runtime_path)


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    with config_path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    machines = []
    for index, machine in enumerate(raw.get("machines", []), start=1):
        try:
            machines.append(
                MachineConfig(
                    machine_number=str(machine["machine_number"]).strip(),
                    name=str(machine["name"]).strip(),
                    area=str(machine.get("area", "")).strip(),
                    cell=str(machine.get("cell", "")).strip(),
                    asset_tag=str(machine.get("asset_tag", "")).strip(),
                    display_order=int(machine.get("display_order", index * 10)),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Machine config row {index} is missing {exc.args[0]!r}.") from exc

    return RuntimeConfig(
        machines=tuple(machines),
        roles=_load_roles(raw.get("roles", {})),
        analytics=_load_analytics(raw.get("analytics", {})),
    )


def _load_roles(raw_roles: object) -> dict[str, RoleConfig]:
    roles: dict[str, RoleConfig] = {}
    if not isinstance(raw_roles, dict):
        raw_roles = {}

    for role_name in ("operator", "technician", "admin"):
        raw_role = raw_roles.get(role_name, {})
        if not isinstance(raw_role, dict):
            raw_role = {}
        roles[role_name] = RoleConfig(
            name=role_name,
            enabled=bool(raw_role.get("enabled", False)),
            pin_hash=str(raw_role.get("pin_hash", "") or "").strip(),
        )
    return roles


def _load_analytics(raw_analytics: object) -> AnalyticsConfig:
    defaults = AnalyticsConfig()
    if not isinstance(raw_analytics, dict):
        raw_analytics = {}

    return AnalyticsConfig(
        enabled=_bool_setting(raw_analytics, "enabled", defaults.enabled),
        risk_window_days=_int_setting(raw_analytics, "risk_window_days", defaults.risk_window_days, minimum=1),
        recurrence_window_days=_int_setting(
            raw_analytics,
            "recurrence_window_days",
            defaults.recurrence_window_days,
            minimum=1,
        ),
        high_risk_threshold=_int_setting(
            raw_analytics,
            "high_risk_threshold",
            defaults.high_risk_threshold,
            minimum=1,
            maximum=100,
        ),
        critical_risk_threshold=_int_setting(
            raw_analytics,
            "critical_risk_threshold",
            defaults.critical_risk_threshold,
            minimum=1,
            maximum=100,
        ),
        grouped_chart_periods=_int_setting(
            raw_analytics,
            "grouped_chart_periods",
            defaults.grouped_chart_periods,
            minimum=1,
            maximum=52,
        ),
        persist_predictive_alerts=_bool_setting(
            raw_analytics,
            "persist_predictive_alerts",
            defaults.persist_predictive_alerts,
        ),
        enable_fix_suggestions=_bool_setting(
            raw_analytics,
            "enable_fix_suggestions",
            defaults.enable_fix_suggestions,
        ),
        enable_related_issues=_bool_setting(
            raw_analytics,
            "enable_related_issues",
            defaults.enable_related_issues,
        ),
    )


def _bool_setting(raw: dict[str, object], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _int_setting(
    raw: dict[str, object],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        value = int(raw.get(key, default))
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value
