from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2


MACHINE_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")


def validate_machine_number(machine_number: str) -> str:
    value = " ".join(str(machine_number or "").split())
    if not value:
        raise ValueError("Machine number is required.")
    if not MACHINE_NUMBER_PATTERN.match(value):
        raise ValueError("Machine number may use letters, numbers, dot, dash, and underscore only.")
    return value


def save_machine_config(
    config_path: Path,
    backups_dir: Path,
    values: dict[str, object],
    *,
    original_machine_number: str = "",
    deactivate: bool = False,
) -> Path:
    raw = _load_config(config_path)
    machines = list(raw.get("machines", []))
    if not isinstance(machines, list):
        machines = []

    machine_number = validate_machine_number(str(values.get("machine_number", "")))
    original = str(original_machine_number or machine_number).strip()
    backup_path = backup_config(config_path, backups_dir)

    row = _machine_row_from_values(values, machine_number=machine_number)
    if deactivate:
        row["is_active"] = False

    replaced = False
    for index, machine in enumerate(machines):
        if not isinstance(machine, dict):
            continue
        if str(machine.get("machine_number", "")).strip() == original:
            machines[index] = {**machine, **row}
            replaced = True
            break

    if not replaced:
        duplicate_index = next(
            (
                index
                for index, machine in enumerate(machines)
                if isinstance(machine, dict)
                and str(machine.get("machine_number", "")).strip().casefold() == machine_number.casefold()
            ),
            None,
        )
        if duplicate_index is None:
            machines.append(row)
        else:
            machines[duplicate_index] = {**machines[duplicate_index], **row}

    raw["machines"] = machines
    _write_config(config_path, raw)
    return backup_path


def backup_config(config_path: Path, backups_dir: Path) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = backups_dir / f"beeline_config.{stamp}.json"
    copy2(config_path, backup_path)
    return backup_path


def _load_config(config_path: Path) -> dict[str, object]:
    with config_path.open("r", encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise ValueError("Runtime config root must be a JSON object.")
    return raw


def _write_config(config_path: Path, raw: dict[str, object]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as file:
        json.dump(raw, file, indent=2)
        file.write("\n")


def _machine_row_from_values(values: dict[str, object], *, machine_number: str) -> dict[str, object]:
    return {
        "machine_number": machine_number,
        "name": _text(values.get("name")),
        "area": _text(values.get("area")),
        "cell": _text(values.get("cell")),
        "asset_tag": _text(values.get("asset_tag")),
        "display_order": _display_order(values.get("display_order")),
        "manufacturer": _text(values.get("manufacturer")),
        "model": _text(values.get("model")),
        "imm_serial": _text(values.get("imm_serial")),
        "robot_type": _text(values.get("robot_type")),
        "robot_model": _text(values.get("robot_model")),
        "robot_serial": _text(values.get("robot_serial")),
        "is_active": bool(values.get("is_active", True)),
    }


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _display_order(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
