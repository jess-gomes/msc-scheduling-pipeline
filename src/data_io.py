# ==============================================================================
# MODULE: DATA INGESTION AND SERIALIZATION (data_io.py)
# ==============================================================================
# Provides deterministic, auditable parsing of enterprise XLSX workbooks
# and handles byte-reproducible CSV and JSON serialization using only the
# standard Python library.
# ==============================================================================

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import posixpath
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile

# ==============================================================================
# SECTION 1: GLOBAL CONSTANTS AND NAMESPACE DEFINITIONS
# ==============================================================================

# OpenXML schema namespaces for spreadsheet inspection
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
DOC_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

# Canonical missing value tokens recognized across ERP extracts
MISSING = {'', '.', 'NULL', 'NAN', 'NONE', 'NAT'}

# Microsecond time scale constants
US = 1_000_000
HOUR_US = 3600 * US

# Reference epochs for timestamp synchronization
EPOCH = datetime(1970, 1, 1)
EXCEL_EPOCH = datetime(1899, 12, 30)


# ==============================================================================
# SECTION 2: CRYPTOGRAPHIC HASHING AND AUDIT VERIFICATION
# ==============================================================================

def sha256(path: Path) -> str:
    """
    Compute the SHA-256 hexadecimal digest of a target file using buffered streaming.

    Args:
        path: Absolute or relative Path pointing to the target file.

    Returns:
        Hexadecimal SHA-256 checksum string.

    Raises:
        FileNotFoundError: If the target file does not exist.
    """
    digest_calculator = hashlib.sha256()
    with path.open('rb') as file_stream:
        for block_chunk in iter(lambda: file_stream.read(1024 * 1024), b''):
            digest_calculator.update(block_chunk)
    return digest_calculator.hexdigest()


# ==============================================================================
# SECTION 3: LOW-LEVEL OPENXML SPREADSHEET PARSING
# ==============================================================================

def read_xlsx_values(path: Path, sheet_name: str | None = None) -> list[dict[str, str | None]]:
    """
    Extract non-empty rows from an XLSX worksheet using pure XML traversal.

    Rejects workbooks configured with the 1904 calendar system, dynamic formulas,
    duplicate column headers, or unmapped cell coordinates.

    Args:
        path: Path pointing to the source XLSX workbook.
        sheet_name: Optional target worksheet name. Defaults to the first sheet.

    Returns:
        List of dictionaries mapping column header names to cell string values.

    Raises:
        FileNotFoundError: If the workbook file does not exist.
        ValueError: If the 1904 date system is active, the worksheet is missing,
            formulas are encountered, header labels are duplicated, or cells lack headers.
    """
    with ZipFile(path) as zip_archive:
        workbook_xml_root = ET.fromstring(zip_archive.read('xl/workbook.xml'))
        workbook_properties = workbook_xml_root.find('m:workbookPr', NS)

        if workbook_properties is not None and workbook_properties.get('date1904') in {'1', 'true'}:
            raise ValueError('The 1904 date system is unauthorized in this experimental study.')

        sheet_nodes = workbook_xml_root.findall('m:sheets/m:sheet', NS)
        target_sheet_node = (
            next((s for s in sheet_nodes if s.get('name') == sheet_name), None)
            if sheet_name
            else sheet_nodes[0]
        )

        if target_sheet_node is None:
            raise ValueError(f'Worksheet {sheet_name!r} not found in {path.name}')

        relationships_xml_root = ET.fromstring(zip_archive.read('xl/_rels/workbook.xml.rels'))
        relationship_mapping = {
            rel.get('Id'): rel.get('Target') for rel in relationships_xml_root
        }

        relationship_id = target_sheet_node.get(f'{{{DOC_REL_NS}}}id')
        relative_target_path = relationship_mapping[relationship_id]

        if relative_target_path.startswith('/'):
            normalized_sheet_path = relative_target_path.lstrip('/')
        else:
            normalized_sheet_path = posixpath.normpath('xl/' + relative_target_path)

        # Ingest shared strings repository if populated
        shared_strings_table = []
        if 'xl/sharedStrings.xml' in zip_archive.namelist():
            shared_strings_root = ET.fromstring(zip_archive.read('xl/sharedStrings.xml'))
            shared_strings_table = [
                ''.join(text_node.text or '' for text_node in item_node.iter(f"{{{NS['m']}}}t"))
                for item_node in shared_strings_root
            ]

        # Parse target worksheet XML tree
        worksheet_xml_root = ET.fromstring(zip_archive.read(normalized_sheet_path))
        column_header_mapping = None
        extracted_tabular_rows = []

        for row_node in worksheet_xml_root.findall('m:sheetData/m:row', NS):
            row_cell_values = {}

            for cell_node in row_node:
                if cell_node.tag != f"{{{NS['m']}}}c":
                    continue

                cell_reference = cell_node.attrib['r']
                column_letters = ''.join(char for char in cell_reference if char.isalpha())
                cell_type = cell_node.get('t', 'n')

                if cell_node.find('m:f', NS) is not None:
                    raise ValueError(
                        f'Dynamic formula detected in {path.name}:{cell_reference}; provide explicit values.'
                    )

                value_node = cell_node.find('m:v', NS)

                if cell_type == 'inlineStr':
                    parsed_value = ''.join(
                        text_node.text or '' for text_node in cell_node.iter(f"{{{NS['m']}}}t")
                    )
                elif value_node is None:
                    parsed_value = None
                elif cell_type == 's':
                    parsed_value = shared_strings_table[int(value_node.text)]
                elif cell_type == 'e':
                    raise ValueError(
                        f'Excel cell error in {path.name}:{cell_reference}: {value_node.text}'
                    )
                else:
                    parsed_value = value_node.text

                row_cell_values[column_letters] = parsed_value

            # Ignore empty rows devoid of any recorded content
            if not any(v is not None and v != '' for v in row_cell_values.values()):
                continue

            if column_header_mapping is None:
                column_header_mapping = {
                    col: str(val).strip()
                    for col, val in row_cell_values.items()
                    if val is not None and str(val).strip()
                }
                if len(set(column_header_mapping.values())) != len(column_header_mapping):
                    raise ValueError(f'Duplicate header labels detected in {path.name}')
            else:
                unmapped_columns = [
                    col for col, val in row_cell_values.items()
                    if col not in column_header_mapping and val not in (None, '')
                ]
                if unmapped_columns:
                    raise ValueError(
                        f'Data cells without header in {path.name}: {unmapped_columns}'
                    )

                record_dictionary = {
                    header_name: row_cell_values.get(col)
                    for col, header_name in column_header_mapping.items()
                }
                extracted_tabular_rows.append(record_dictionary)

        if column_header_mapping is None:
            raise ValueError(f'Empty worksheet structure: {path}')

        return extracted_tabular_rows


# ==============================================================================
# SECTION 4: DATA CLEANSING AND VALUE CASTING HELPERS
# ==============================================================================

def missing(value: Any) -> bool:
    """
    Evaluate whether a raw attribute value represents a null or missing indicator.

    Args:
        value: Raw attribute value to inspect.

    Returns:
        True if the value is null or matches canonical missing tokens, False otherwise.
    """
    return value is None or str(value).strip().upper() in MISSING


def identifier(value: Any) -> str | None:
    """
    Normalize textual identifiers while preserving leading zeroes.

    Args:
        value: Raw identifier value extracted from source files.

    Returns:
        Sanitized identifier string, or None if the input is missing.
    """
    if missing(value):
        return None
    normalized_text = str(value).strip()
    if normalized_text.endswith('.0') and normalized_text[:-2].isdigit():
        return normalized_text[:-2]
    return normalized_text


def quantity(value: Any) -> int | None:
    """
    Parse production volume counts, enforcing finite integer validity without truncation.

    Args:
        value: Raw numerical count to parse.

    Returns:
        Exact integer piece count, or None if missing.

    Raises:
        ValueError: If the numerical representation is non-finite or fractional.
    """
    if missing(value):
        return None
    decimal_number = Decimal(str(value))
    if not decimal_number.is_finite() or decimal_number != decimal_number.to_integral_value():
        raise ValueError(f'Non-integer unit quantity: {value!r}')
    return int(decimal_number)


# ==============================================================================
# SECTION 5: TEMPORAL CONVERSION AND SERIALIZATION HELPERS
# ==============================================================================

def excel_time_us(value: Any) -> tuple[int | None, Decimal]:
    """
    Convert an Excel serial date into microseconds since the Unix epoch.

    Values within 1 ms of an integer second are aligned to that second; otherwise,
    microsecond granularity is preserved. Serial discrepancy is returned for audit traces.

    Args:
        value: Raw Excel float serial date representation.

    Returns:
        Tuple of (integer microseconds since Unix epoch, serial deviation Decimal).

    Raises:
        ValueError: If the serial value is non-finite.
    """
    if missing(value):
        return None, Decimal(0)

    serial_decimal = Decimal(str(value))
    if not serial_decimal.is_finite():
        raise ValueError(f'Invalid date serial representation: {value}')

    total_seconds = serial_decimal * Decimal(86400)
    rounded_second = total_seconds.to_integral_value(rounding=ROUND_HALF_EVEN)

    discrepancy_delta = rounded_second - total_seconds
    if abs(discrepancy_delta) <= Decimal('0.001'):
        second_correction = discrepancy_delta
    else:
        second_correction = Decimal(0)

    corrected_seconds = total_seconds + second_correction
    total_microseconds = int(
        (corrected_seconds * US).to_integral_value(rounding=ROUND_HALF_EVEN)
    )
    base_epoch_microseconds = int((EXCEL_EPOCH - EPOCH).total_seconds()) * US

    final_epoch_us = base_epoch_microseconds + total_microseconds
    return final_epoch_us, second_correction


def iso(us: int | None) -> str | None:
    """
    Format an integer microsecond timestamp into an ISO 8601 string representation.

    Args:
        us: Integer timestamp in microseconds since Unix epoch.

    Returns:
        Formatted ISO 8601 string, or None if timestamp is absent.
    """
    if us is None:
        return None
    timestamp_object = EPOCH + timedelta(microseconds=us)
    output_precision = 'seconds' if us % US == 0 else 'microseconds'
    return timestamp_object.isoformat(sep=' ', timespec=output_precision)


# ==============================================================================
# SECTION 6: STRUCTURED FILE PERSISTENCE AND REPRODUCIBLE I/O
# ==============================================================================

def json_default(value: Any) -> Any:
    """
    Provide serializable string representations for Decimal and Path objects.

    Args:
        value: Object instance undergoing JSON serialization.

    Returns:
        String representation for supported custom types.

    Raises:
        TypeError: If the object type is unsupported.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, obj: Any) -> None:
    """
    Persist structured data to JSON using deterministic formatting and UTF-8 encoding.

    Args:
        path: Destination file Path.
        obj: Structured dictionary or list to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized_payload = (
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False, default=json_default)
        + '\n'
    )
    path.write_text(serialized_payload, encoding='utf-8')


def write_csv(path: Path, rows: Iterable[dict], fields: list[str] | None = None) -> None:
    """
    Persist tabular rows to standard CSV or GZIP-compressed CSV with mtime zeroing.

    Args:
        path: Destination file Path (GZIP activated if suffix is .gz).
        rows: Iterable of dictionary records.
        fields: Explicit list of fieldnames. Defaults to keys of the first row.
    """
    materialized_rows = list(rows)
    if fields is None:
        fields = list(materialized_rows[0]) if materialized_rows else []

    path.parent.mkdir(parents=True, exist_ok=True)

    text_buffer = io.StringIO(newline='')
    csv_writer = csv.DictWriter(
        text_buffer, fieldnames=fields, extrasaction='raise', lineterminator='\n'
    )
    csv_writer.writeheader()

    for row_dict in materialized_rows:
        serialized_row = {
            col_key: (
                '|'.join(str(item) for item in col_val)
                if isinstance(col_val, (list, tuple, set))
                else col_val
            )
            for col_key, col_val in row_dict.items()
        }
        csv_writer.writerow(serialized_row)

    encoded_content = text_buffer.getvalue().encode('utf-8')
    if path.suffix == '.gz':
        path.write_bytes(gzip.compress(encoded_content, mtime=0))
    else:
        path.write_bytes(encoded_content)


def read_csv(path: Path) -> list[dict[str, str]]:
    """
    Ingest plain or GZIP-compressed CSV records into standard dictionary structures.

    Args:
        path: Target CSV or GZIP-compressed CSV Path.

    Returns:
        List of dictionaries mapping column headers to string values.
    """
    file_opener = gzip.open if path.suffix == '.gz' else open
    with file_opener(path, 'rt', encoding='utf-8', newline='') as input_file:
        return list(csv.DictReader(input_file))