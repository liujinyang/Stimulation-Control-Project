from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from perfusion_app.models.protocol import ProtocolStep


COLUMN_DURATION_S = "Duration time(in Sec)"
COLUMN_PULSE = "Pulse On/Off"
COLUMN_WIDTH_MS = "Pulse Width(in ms)"
COLUMN_FREQUENCY_HZ = "Pulse Frequency (in Hz)"

EXPECTED_COLUMNS = [COLUMN_DURATION_S, COLUMN_PULSE, COLUMN_WIDTH_MS, COLUMN_FREQUENCY_HZ]


class ProtocolFileError(Exception):
    pass


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _convert_xls_to_xlsx(path: Path) -> Path:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if libreoffice is None:
        raise ProtocolFileError(
            "This protocol file is .xls. Install LibreOffice or convert it to .xlsx first."
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="protocol_xls_"))
    try:
        subprocess.run(
            [libreoffice, "--headless", "--convert-to", "xlsx", "--outdir", str(temp_dir), str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ProtocolFileError(
            f"Failed to convert .xls protocol file: {exc.stderr.strip() or exc.stdout.strip()}"
        ) from exc

    converted = temp_dir / f"{path.stem}.xlsx"
    if not converted.exists():
        raise ProtocolFileError("Converted .xlsx file was not created.")
    return converted


def _read_protocol_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".xls":
            path = _convert_xls_to_xlsx(path)
        df = pd.read_excel(path)
    except Exception as exc:
        raise ProtocolFileError(f"Could not read protocol file '{path.name}': {exc}") from exc

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ProtocolFileError(f"Missing columns: {', '.join(missing)}")
    return df[EXPECTED_COLUMNS].copy()


def _parse_step(row_index: int, row: pd.Series) -> ProtocolStep:
    duration = row[COLUMN_DURATION_S]
    if pd.isna(duration):
        raise ProtocolFileError(f"Row {row_index}: {COLUMN_DURATION_S} is required")

    pulse_text = _normalize_text(row[COLUMN_PULSE]).lower()
    if pulse_text not in {"on", "off"}:
        raise ProtocolFileError(f"Row {row_index}: {COLUMN_PULSE} must be 'on' or 'off', got '{pulse_text}'")
    pulse_on = pulse_text == "on"

    width = 0.0 if pd.isna(row[COLUMN_WIDTH_MS]) else float(row[COLUMN_WIDTH_MS])
    frequency = 0.0 if pd.isna(row[COLUMN_FREQUENCY_HZ]) else float(row[COLUMN_FREQUENCY_HZ])

    if pulse_on and frequency > 0 and width <= 0:
        raise ProtocolFileError(f"Row {row_index}: {COLUMN_WIDTH_MS} must be > 0 when pulsing at a nonzero frequency")

    return ProtocolStep(
        duration_s=float(duration),
        pulse_on=pulse_on,
        pulse_width_ms=width,
        pulse_frequency_hz=frequency,
    )


def load_protocol_from_excel(path: str | Path) -> List[ProtocolStep]:
    df = _read_protocol_dataframe(Path(path))
    steps: List[ProtocolStep] = []
    for excel_row_index, (_, row) in enumerate(df.iterrows(), start=2):
        if row.isna().all():
            continue
        steps.append(_parse_step(excel_row_index, row))
    if not steps:
        raise ProtocolFileError("The protocol file did not contain any steps.")
    return steps


def save_protocol_to_excel(path: str | Path, steps: Iterable[ProtocolStep]) -> None:
    rows = []
    for step in steps:
        rows.append(
            {
                COLUMN_DURATION_S: step.duration_s,
                COLUMN_PULSE: "on" if step.pulse_on else "off",
                COLUMN_WIDTH_MS: step.pulse_width_ms,
                COLUMN_FREQUENCY_HZ: step.pulse_frequency_hz,
            }
        )
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
