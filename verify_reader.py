#!/usr/bin/env python3
# ==============================================================================
# SCRIPT: INDEPENDENT SPREADSHEET AUDIT VERIFIER (verify_reader.py)
# ==============================================================================
# Audits all 30,261 raw worksheet cells from production_order.xlsx by comparing
# the project ingestion engine (xml.etree.ElementTree) against an independent
# streaming SAX parser (xml.parsers.expat) using only the standard library.
# ==============================================================================

from __future__ import annotations

import datetime
import hashlib
import json
import math
import sys
import xml.parsers.expat
import zipfile
from pathlib import Path
from typing import Any

from src.analysis import load_orders


# ==============================================================================
# SECTION 1: INDEPENDENT EXPAT-BASED SAX OPENXML PARSER
# ==============================================================================

class ExpatOpenXMLReader:
    """
    Independent streaming parser for Excel XML structures using xml.parsers.expat.
    Operates without dependency on xml.etree or third-party spreadsheet libraries.
    """

    def __init__(self, workbook_path: Path) -> None:
        self.workbook_path = workbook_path

    def read_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        """Parse xl/sharedStrings.xml into a string lookup list."""
        if 'xl/sharedStrings.xml' not in archive.namelist():
            return []

        shared_strings: list[str] = []
        current_text: list[str] = []
        capture: bool = False

        def start_element(name: str, attrs: dict[str, str]) -> None:
            nonlocal capture
            if name == 't':
                capture = True

        def end_element(name: str) -> None:
            nonlocal capture
            if name == 't':
                capture = False
            elif name == 'si':
                shared_strings.append(''.join(current_text))
                current_text.clear()

        def char_data(data: str) -> None:
            if capture:
                current_text.append(data)

        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = start_element
        parser.EndElementHandler = end_element
        parser.CharacterDataHandler = char_data
        parser.Parse(archive.read('xl/sharedStrings.xml'))

        return shared_strings

    def read_first_sheet(self) -> tuple[list[str], list[list[Any]]]:
        """
        Extract header columns and data rows from the primary sheet.

        Returns:
            Tuple containing header attribute names and matrix of row cells.
        """
        with zipfile.ZipFile(self.workbook_path, 'r') as archive:
            shared_strings = self.read_shared_strings(archive)

            sheet_path = 'xl/worksheets/sheet1.xml'
            rows: list[list[Any]] = []
            current_row: list[Any] = []
            current_val: list[str] = []
            cell_type: str = ''
            capture_val: bool = False

            def start_element(name: str, attrs: dict[str, str]) -> None:
                nonlocal cell_type, capture_val
                if name == 'row':
                    current_row.clear()
                elif name == 'c':
                    cell_type = attrs.get('t', 'n')
                    current_val.clear()
                elif name == 'v':
                    capture_val = True

            def end_element(name: str) -> None:
                nonlocal capture_val
                if name == 'v':
                    capture_val = False
                elif name == 'c':
                    raw_str = ''.join(current_val).strip()
                    if not raw_str:
                        current_row.append(None)
                    elif cell_type == 's':
                        idx = int(raw_str)
                        current_row.append(shared_strings[idx] if idx < len(shared_strings) else raw_str)
                    elif cell_type == 'b':
                        current_row.append(raw_str == '1')
                    else:
                        current_row.append(raw_str)
                elif name == 'row':
                    if current_row:
                        rows.append(list(current_row))

            def char_data(data: str) -> None:
                if capture_val:
                    current_val.append(data)

            parser = xml.parsers.expat.ParserCreate()
            parser.StartElementHandler = start_element
            parser.EndElementHandler = end_element
            parser.CharacterDataHandler = char_data
            parser.Parse(archive.read(sheet_path))

        if not rows:
            raise ValueError('Workbook sheet1 contains no parsed rows.')

        headers = [str(cell) for cell in rows[0]]
        data_rows = rows[1:]
        return headers, data_rows


# ==============================================================================
# SECTION 2: AUDIT EXECUTION AND ARTIFACT GENERATION
# ==============================================================================

def execute_independent_audit(root_dir: Path) -> dict[str, Any]:
    """
    Compare raw cell matrices between primary data_io loader and ExpatOpenXMLReader.

    Args:
        root_dir: Project root directory path.

    Returns:
        Audit report summary dictionary.
    """
    workbook_path = root_dir / 'input' / 'production_order.xlsx'
    if not workbook_path.is_file():
        raise FileNotFoundError(f'Target spreadsheet not found: {workbook_path}')

    # Compute source workbook SHA-256
    file_bytes = workbook_path.read_bytes()
    source_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Engine A: Primary project parser (data_io.py via load_orders)
    raw_primary, _, _ = load_orders(workbook_path)

    # Engine B: Independent streaming SAX parser
    expat_reader = ExpatOpenXMLReader(workbook_path)
    expat_headers, expat_rows = expat_reader.read_first_sheet()

    total_rows = len(raw_primary)
    total_columns = len(expat_headers)
    expected_cells = total_rows * total_columns
    tolerance = 1e-10
    mismatches = 0

    if len(expat_rows) != total_rows:
        raise ValueError(
            f'Row count discrepancy: Primary has {total_rows}, Expat has {len(expat_rows)}.'
        )

    for row_idx, (row_a, row_b) in enumerate(zip(raw_primary, expat_rows)):
        for col_idx, col_name in enumerate(expat_headers):
            val_a = row_a.get(col_name)
            val_b = row_b[col_idx] if col_idx < len(row_b) else None

            # Normalize representations
            if val_a is None or val_a == '' or val_a == '.':
                is_empty_a = True
            else:
                is_empty_a = False

            if val_b is None or val_b == '' or val_b == '.':
                is_empty_b = True
            else:
                is_empty_b = False

            if is_empty_a and is_empty_b:
                continue

            if is_empty_a != is_empty_b:
                mismatches += 1
                continue

            # Numerical comparison with float tolerance
            try:
                num_a = float(val_a)
                num_b = float(val_b)
                if abs(num_a - num_b) > tolerance:
                    mismatches += 1
                continue
            except (ValueError, TypeError):
                pass

            # String literal comparison
            if str(val_a).strip() != str(val_b).strip():
                mismatches += 1

    audit_payload: dict[str, Any] = {
        'source': 'production_order.xlsx',
        'independent_reader': 'python_expat_sax_engine',
        'production_table_rows': total_rows,
        'columns': total_columns,
        'compared_cells': expected_cells,
        'mismatches': mismatches,
        'numeric_absolute_tolerance': tolerance,
        'input_sha256': source_sha256,
        'verification_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Dual-engine standard library audit comparing ElementTree against Expat SAX.'
    }

    docs_dir = root_dir / 'docs'
    docs_dir.mkdir(parents=True, exist_ok=True)
    output_path = docs_dir / 'independent_reader_check.json'
    output_path.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    return audit_payload


def main() -> int:
    """Execute the standalone verification audit and display results."""
    root_dir = Path(__file__).resolve().parent
    try:
        report = execute_independent_audit(root_dir)
        print('\n' + '=' * 80)
        print('INDEPENDENT CELL-BY-CELL SPREADSHEET AUDIT COMPLETED')
        print('=' * 80)
        print(f'Input SHA-256:      {report["input_sha256"]}')
        print(f'Evaluated Rows:     {report["production_table_rows"]}')
        print(f'Evaluated Columns:  {report["columns"]}')
        print(f'Compared Cells:     {report["compared_cells"]:,}')
        print(f'Detected Mismatches: {report["mismatches"]}')
        print(f'Audit File Written: docs/independent_reader_check.json')
        print('=' * 80 + '\n')
        return 0
    except Exception as err:
        print(f'Audit failed: {err}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())