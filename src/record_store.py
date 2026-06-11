from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

FIELDNAMES = [
    "source_file",
    "copied_file",
    "order_id",
    "invoice_id",
    "status",
    "message",
    "uploaded",
]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_records(record_path: Path, records: Iterable[dict[str, str]]) -> None:
    ensure_parent(record_path)
    exists = record_path.exists()
    with record_path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        if not exists:
            writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in FIELDNAMES}
            writer.writerow(row)


def read_records(record_path: Path) -> list[dict[str, str]]:
    if not record_path.exists():
        return []
    with record_path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def write_records(record_path: Path, records: list[dict[str, str]]) -> None:
    ensure_parent(record_path)
    with record_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in FIELDNAMES}
            writer.writerow(row)
