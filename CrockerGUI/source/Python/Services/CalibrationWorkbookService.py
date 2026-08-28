from __future__ import annotations

import json
import time
import zipfile
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


CHANNEL_KEYS = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def export_scaling_curves(scaling_path: str | Path, workbook_path: str | Path) -> int:
    scaling = _load_scaling(scaling_path)
    sheets: list[tuple[str, list[list[Any]]]] = []
    exported = 0
    for channel_key in CHANNEL_KEYS:
        entry = scaling.get(channel_key)
        if not isinstance(entry, dict):
            continue
        rows: list[list[Any]] = [["direction", "input", "output"]]
        for direction in ("raw_to_eng", "eng_to_raw"):
            transform = entry.get(direction)
            if not isinstance(transform, dict):
                continue
            points = _points(transform)
            if not points:
                gain = float(transform.get("gain", 1.0))
                offset = float(transform.get("offset", 0.0))
                points = [[0.0, offset], [1.0, gain + offset]]
            for input_value, output_value in points:
                rows.append([direction, input_value, output_value])
        sheets.append((channel_key, rows))
        exported += 1
    Path(workbook_path).parent.mkdir(parents=True, exist_ok=True)
    _write_xlsx(workbook_path, sheets)
    return exported


def import_scaling_curves(workbook_path: str | Path) -> dict[str, Any]:
    workbook = _read_xlsx(workbook_path)
    scaling: dict[str, Any] = {}
    for channel_key in CHANNEL_KEYS:
        if channel_key not in workbook:
            continue
        rows = workbook[channel_key]
        if not rows:
            continue
        headers = [str(value).strip().lower() if value is not None else "" for value in rows[0]]
        direction_index = _find_header(headers, ("direction", "transform"))
        input_index = _find_header(headers, ("input", "raw", "x"))
        output_index = _find_header(headers, ("output", "eng", "engineering", "y"))
        if input_index is None or output_index is None:
            continue
        grouped = {"raw_to_eng": [], "eng_to_raw": []}
        for row in rows[1:]:
            if input_index >= len(row) or output_index >= len(row):
                continue
            raw_input = row[input_index]
            raw_output = row[output_index]
            if raw_input is None or raw_output is None:
                continue
            direction = "raw_to_eng"
            if direction_index is not None and direction_index < len(row):
                direction_text = str(row[direction_index]).strip()
                if direction_text in grouped:
                    direction = direction_text
            grouped[direction].append([float(raw_input), float(raw_output)])
        raw_to_eng = sorted(grouped["raw_to_eng"], key=lambda point: point[0])
        eng_to_raw = sorted(grouped["eng_to_raw"], key=lambda point: point[0])
        if len(raw_to_eng) >= 2:
            if len(eng_to_raw) < 2:
                eng_to_raw = sorted([[eng, raw] for raw, eng in raw_to_eng], key=lambda point: point[0])
            scaling[channel_key] = {
                "label": channel_key,
                "enabled": True,
                "raw_to_eng": {"type": "curve", "points": raw_to_eng},
                "eng_to_raw": {"type": "curve", "points": eng_to_raw},
            }
    return scaling


def append_calibration_record(records_path: str | Path, scaling_path: str | Path, *, operator_name: str = "", notes: str = "") -> int:
    path = Path(records_path)
    if path.exists():
        workbook = _read_xlsx(path)
        sheet_name = next(iter(workbook), "records")
        rows = workbook.get(sheet_name, [])
    else:
        rows = [["saved_at", "operator", "key", "enabled", "raw_to_eng", "eng_to_raw", "notes"]]

    scaling = _load_scaling(scaling_path)
    saved_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    appended = 0
    for channel_key in CHANNEL_KEYS:
        entry = scaling.get(channel_key)
        if not isinstance(entry, dict):
            continue
        rows.append(
            [
                saved_at,
                operator_name,
                channel_key,
                bool(entry.get("enabled", True)),
                json.dumps(entry.get("raw_to_eng", {}), sort_keys=True),
                json.dumps(entry.get("eng_to_raw", {}), sort_keys=True),
                notes,
            ]
        )
        appended += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_xlsx(path, [("records", rows)])
    return appended


def _load_scaling(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("scaling file must contain a JSON object")
    return data


def _points(transform: dict[str, Any]) -> list[list[float]]:
    points = transform.get("points", transform.get("curve", []))
    if not isinstance(points, list):
        return []
    parsed: list[list[float]] = []
    for point in points:
        if isinstance(point, dict):
            input_value = point.get("input", point.get("raw", point.get("x")))
            output_value = point.get("output", point.get("eng", point.get("y")))
            if input_value is not None and output_value is not None:
                parsed.append([float(input_value), float(output_value)])
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            parsed.append([float(point[0]), float(point[1])])
    return parsed


def _find_header(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        for index, header in enumerate(headers):
            if header == name or name in header:
                return index
    return None


def _write_xlsx(path: str | Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml([name for name, _rows in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _worksheet_xml(rows))


def _read_xlsx(path: str | Path) -> dict[str, list[list[Any]]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{{{REL_NS}}}Relationship")
        }
        sheets: dict[str, list[list[Any]]] = {}
        for sheet in workbook_root.findall(f".//{{{MAIN_NS}}}sheet"):
            name = str(sheet.attrib.get("name", "sheet"))
            rel_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
            target = rel_targets.get(str(rel_id))
            if not target:
                continue
            target = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            rows = _read_sheet(archive.read(target), shared_strings)
            sheets[name] = rows
        return sheets


def _read_sheet(xml_bytes: bytes, shared_strings: list[str]) -> list[list[Any]]:
    root = ElementTree.fromstring(xml_bytes)
    rows: list[list[Any]] = []
    for row in root.findall(f".//{{{MAIN_NS}}}row"):
        values: list[Any] = []
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            column = _column_index(str(cell.attrib.get("r", "A1")))
            while len(values) < column:
                values.append(None)
            values.append(_cell_value(cell, shared_strings))
        rows.append(values)
    return rows


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = cell.find(f"{{{MAIN_NS}}}is/{{{MAIN_NS}}}t")
        return "" if text is None or text.text is None else text.text
    value = cell.find(f"{{{MAIN_NS}}}v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        index = int(value.text)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    try:
        number = float(value.text)
    except ValueError:
        return value.text
    return int(number) if number.is_integer() else number


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall(f"{{{MAIN_NS}}}si"):
        parts = [text.text or "" for text in item.findall(f".//{{{MAIN_NS}}}t")]
        values.append("".join(parts))
    return values


def _worksheet_xml(rows: list[list[Any]]) -> str:
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{_column_name(column_index)}{row_index}"
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>')
            elif isinstance(value, int | float):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN_NS}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'


def _content_types_xml(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{OFFICE_REL_NS}"><sheets>{sheets}</sheets></workbook>'
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    sheets = "".join(
        f'<Relationship Id="rId{index}" Type="{OFFICE_REL_NS}/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">{sheets}'
        f'<Relationship Id="rId{sheet_count + 1}" Type="{OFFICE_REL_NS}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{MAIN_NS}"/>'


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _column_index(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return max(1, index)
