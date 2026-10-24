import io
from typing import Any

import pandas as pd


class CSVParseError(Exception):
    pass


def parse_csv_input(content: str) -> dict[str, Any]:
    """Deterministically parse a single-record CSV input into a flat dict.

    The first data row is treated as the record to extract. Additional rows
    are ignored for the MVP single-record flow.
    """
    if not isinstance(content, str) or not content.strip():
        raise CSVParseError("CSV input is empty.")

    try:
        df = pd.read_csv(io.StringIO(content))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as CSVParseError
        raise CSVParseError(f"Invalid CSV: {exc}") from exc

    if df.empty:
        raise CSVParseError("CSV input has no data rows.")

    row = df.iloc[0]
    result: dict[str, Any] = {}
    for column in df.columns:
        value = row[column]
        if pd.isna(value):
            continue
        result[str(column).strip()] = value.item() if hasattr(value, "item") else value
    return result
