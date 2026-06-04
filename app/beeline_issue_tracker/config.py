from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

from beeline_issue_tracker.security import RoleConfig, verify_pin


APP_NAME = "BeeLine Issue Tracker"
DEFAULT_ADMIN_PIN_HASH = (
    "pbkdf2_sha256$180000$beeline-admin-pin-v1$"
    "1037b58ba94f0bd31f21ea63c3e13e5d08a1844861a2807473dc324987b4a049"
)
DEFAULT_SPECIAL_PIN_HASH = (
    "pbkdf2_sha256$180000$beeline-special-pin-v1$"
    "34cee25eabcdd85cfd61da139c5dd71976fddea2ac96974bc00d4f829b83dfb1"
)


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
    manufacturer: str = ""
    model: str = ""
    imm_serial: str = ""
    robot_type: str = ""
    robot_model: str = ""
    robot_serial: str = ""

    def as_database_row(self) -> tuple[str, str, str, str, str, int, str, str, str, str, str, str]:
        return (
            self.machine_number,
            self.name,
            self.area,
            self.cell,
            self.asset_tag,
            self.display_order,
            self.manufacturer,
            self.model,
            self.imm_serial,
            self.robot_type,
            self.robot_model,
            self.robot_serial,
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
class UiConfig:
    category_options: tuple[str, ...] = ("Automation", "Machine", "Maintenance")
    default_dashboard_filter: str = "all"
    default_issue_sort: str = "date_desc"
    default_issue_display_count: int = 50
    show_raw_paths: bool = False


@dataclass(frozen=True)
class ArchiveCacheConfig:
    keep_days: int = 180
    keep_minimum: int = 1000
    keep_per_machine_minimum: int = 25


@dataclass(frozen=True)
class SpecialEffectsConfig:
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
    special_pin_hash: str = DEFAULT_SPECIAL_PIN_HASH


@dataclass(frozen=True)
class RuntimeConfig:
    machines: tuple[MachineConfig, ...]
    roles: dict[str, RoleConfig]
    analytics: AnalyticsConfig = AnalyticsConfig()
    ui: UiConfig = UiConfig()
    archive_cache: ArchiveCacheConfig = ArchiveCacheConfig()
    special_effects: SpecialEffectsConfig = SpecialEffectsConfig()

    def machine_rows(self) -> tuple[tuple[str, str, str, str, str, int, str, str, str, str, str, str], ...]:
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

    def role_requires_pin(self, role_name: str) -> bool:
        role = self.roles.get(role_name)
        return bool(role and role.enabled and role.pin_hash)

    def is_role_enabled(self, role_name: str) -> bool:
        role = self.roles.get(role_name)
        return bool(role and role.enabled)

    def verify_special_pin(self, pin: str) -> bool:
        return verify_pin(pin, self.special_effects.special_pin_hash)


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
    approved_logo_jpg_path: Path
    placeholder_logo_path: Path
    placeholder_logo_jpg_path: Path

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
            approved_logo_jpg_path=branding_dir / "nolato_logo.jpg",
            placeholder_logo_path=branding_dir / "nolato_logo_placeholder.png",
            placeholder_logo_jpg_path=branding_dir / "nolato_logo_placeholder.jpg",
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
        configured = os.environ.get("BEELINE_LOGO_PATH", "").strip()
        if configured:
            configured_path = Path(configured).expanduser()
            if configured_path.exists():
                return configured_path
        for path in (
            self.approved_logo_path,
            self.approved_logo_jpg_path,
            self.placeholder_logo_path,
            self.placeholder_logo_jpg_path,
        ):
            if path.exists():
                return path
        return None


def initialize_runtime_files(paths: AppPaths, *, include_archive: bool = False) -> None:
    paths.ensure_directories()
    copies = [
        (paths.config_template_path, paths.runtime_config_path),
        (paths.db_template_path, paths.db_path),
    ]
    if include_archive:
        copies.append((paths.archive_template_path, paths.archive_path))
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
                    manufacturer=str(
                        machine.get("manufacturer", machine.get("imm_make", ""))
                    ).strip(),
                    model=str(machine.get("model", machine.get("imm_model", ""))).strip(),
                    imm_serial=str(machine.get("imm_serial", "")).strip(),
                    robot_type=str(machine.get("robot_type", machine.get("robot_make", ""))).strip(),
                    robot_model=str(machine.get("robot_model", "")).strip(),
                    robot_serial=str(machine.get("robot_serial", "")).strip(),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Machine config row {index} is missing {exc.args[0]!r}.") from exc

    return RuntimeConfig(
        machines=tuple(machines),
        roles=_load_roles(raw.get("roles", {})),
        analytics=_load_analytics(raw.get("analytics", {})),
        ui=_load_ui(raw.get("ui", {})),
        archive_cache=_load_archive_cache(raw.get("archive_cache", {})),
        special_effects=_load_special_effects(raw.get("special_effects", {})),
    )


def _load_roles(raw_roles: object) -> dict[str, RoleConfig]:
    roles: dict[str, RoleConfig] = {}
    if not isinstance(raw_roles, dict):
        raw_roles = {}

    for role_name in ("viewer", "technician", "admin"):
        raw_role = raw_roles.get(role_name, {})
        if role_name == "viewer" and not raw_role:
            raw_role = raw_roles.get("operator", {})
        if not isinstance(raw_role, dict):
            raw_role = {}
        default_enabled = role_name == "admin"
        default_pin_hash = DEFAULT_ADMIN_PIN_HASH if role_name == "admin" else ""
        roles[role_name] = RoleConfig(
            name=role_name,
            enabled=_bool_setting(raw_role, "enabled", default_enabled),
            pin_hash=str(raw_role.get("pin_hash", default_pin_hash) or default_pin_hash).strip(),
        )
    return roles


def _load_ui(raw_ui: object) -> UiConfig:
    defaults = UiConfig()
    if not isinstance(raw_ui, dict):
        raw_ui = {}

    raw_categories = raw_ui.get("category_options", defaults.category_options)
    categories: list[str] = []
    if isinstance(raw_categories, (list, tuple)):
        for category in raw_categories:
            value = str(category).strip()
            if value and value.casefold() not in {existing.casefold() for existing in categories}:
                categories.append(value)
    if not categories:
        categories = list(defaults.category_options)

    return UiConfig(
        category_options=tuple(categories),
        default_dashboard_filter=str(raw_ui.get("default_dashboard_filter", defaults.default_dashboard_filter)).strip()
        or defaults.default_dashboard_filter,
        default_issue_sort=str(raw_ui.get("default_issue_sort", defaults.default_issue_sort)).strip()
        or defaults.default_issue_sort,
        default_issue_display_count=_int_setting(
            raw_ui,
            "default_issue_display_count",
            defaults.default_issue_display_count,
            minimum=1,
            maximum=500,
        ),
        show_raw_paths=_bool_setting(raw_ui, "show_raw_paths", defaults.show_raw_paths),
    )


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


def _load_archive_cache(raw_archive_cache: object) -> ArchiveCacheConfig:
    defaults = ArchiveCacheConfig()
    if not isinstance(raw_archive_cache, dict):
        raw_archive_cache = {}

    return ArchiveCacheConfig(
        keep_days=_int_setting(raw_archive_cache, "keep_days", defaults.keep_days, minimum=1),
        keep_minimum=_int_setting(raw_archive_cache, "keep_minimum", defaults.keep_minimum, minimum=1),
        keep_per_machine_minimum=_int_setting(
            raw_archive_cache,
            "keep_per_machine_minimum",
            defaults.keep_per_machine_minimum,
            minimum=0,
        ),
    )


def _load_special_effects(raw_special: object) -> SpecialEffectsConfig:
    defaults = SpecialEffectsConfig()
    if not isinstance(raw_special, dict):
        raw_special = {}

    special_pin_hash = str(raw_special.get("special_pin_hash", defaults.special_pin_hash) or defaults.special_pin_hash)
    if not special_pin_hash.startswith("pbkdf2_sha256$"):
        special_pin_hash = defaults.special_pin_hash

    return SpecialEffectsConfig(
        enabled=_bool_setting(raw_special, "enabled", defaults.enabled),
        threshold=_int_setting(raw_special, "threshold", defaults.threshold, minimum=0, maximum=100),
        intensity_step=_int_setting(raw_special, "intensity_step", defaults.intensity_step, minimum=1, maximum=20),
        force_test=_bool_setting(raw_special, "force_test", defaults.force_test),
        test_intensity=_int_setting(raw_special, "test_intensity", defaults.test_intensity, minimum=1, maximum=5),
        enable_static=_bool_setting(raw_special, "enable_static", defaults.enable_static),
        enable_glitch=_bool_setting(raw_special, "enable_glitch", defaults.enable_glitch),
        enable_droop_drip=_bool_setting(raw_special, "enable_droop_drip", defaults.enable_droop_drip),
        enable_smear=_bool_setting(raw_special, "enable_smear", defaults.enable_smear),
        enable_card_impulses=_bool_setting(
            raw_special,
            "enable_card_impulses",
            defaults.enable_card_impulses,
        ),
        enable_falling_drips=_bool_setting(
            raw_special,
            "enable_falling_drips",
            defaults.enable_falling_drips,
        ),
        drip_intensity=_int_setting(raw_special, "drip_intensity", defaults.drip_intensity, minimum=1, maximum=5),
        glitch_impulse_strength=_int_setting(
            raw_special,
            "glitch_impulse_strength",
            defaults.glitch_impulse_strength,
            minimum=1,
            maximum=5,
        ),
        reduced_motion=_bool_setting(raw_special, "reduced_motion", defaults.reduced_motion),
        special_pin_hash=special_pin_hash.strip(),
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
