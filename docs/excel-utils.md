# Excel Utils

Shared Excel generation utilities for Haidilao automations, built on openpyxl.

## Overview

The `excel-utils` library provides reusable functions for reading, writing, and styling Excel files. Projects should depend on this library via `excel-utils = { workspace = true }` instead of using openpyxl directly.

## Architecture

```
libs/excel-utils/src/excel_utils/
    __init__.py        # Public API exports
    reader.py          # XLSX reading (data rows, mappings)
    style.py           # Styling (fonts, headers, column sizing)
    workbook.py        # Workbook creation, sheet writing, sheet copying
    py.typed           # PEP 561 marker
```

## Reading (`reader.py`)

### `load_data_rows(path, *, sheet_name, skip_empty_key)`

Load an XLSX file into a list of header-keyed dicts.

```python
from excel_utils import load_data_rows

rows = load_data_rows(Path("export.xlsx"), skip_empty_key="过账日期")
# [{"过账日期": datetime(...), "金额": 1234.56, ...}, ...]
```

- Reads first row as headers, remaining rows as data
- `skip_empty_key`: skip rows where this column is None (filters blank/summary rows)
- Raises `ValueError` on empty sheets

### `load_mapping(path, *, key_col, value_col, sheet_name, header_row)`

Load a two-column mapping from an XLSX file.

```python
from excel_utils import load_mapping

mapping = load_mapping(Path("报表科目.xlsx"), key_col=0, value_col=2)
# {"410100": "人工成本", "420200": "物料成本", ...}
```

- Normalizes numeric keys: `1234.0` → `"1234"`, preserves fractional floats as-is
- `header_row=True` (default) skips the first row

## Writing (`workbook.py`)

### `create_workbook()`

Create a new `Workbook` with the default empty sheet removed.

### `write_data_sheet(wb, title, *, headers, rows, auto_size)`

Create a sheet with bold headers and populate with dict rows.

```python
from excel_utils import create_workbook, write_data_sheet

wb = create_workbook()
write_data_sheet(
    wb, "Sales Data",
    headers=["Store", "Month", "Revenue"],
    rows=[{"Store": "Store A", "Month": 3, "Revenue": 50000}],
)
wb.save("report.xlsx")
```

- Title auto-truncated to 31 characters via `truncate_sheet_name()`
- `auto_size=True` (default) auto-sizes columns after writing

### `copy_sheet_data(wb, source_path, *, title, columns, sheet_name)`

Copy data from a source XLSX into a new sheet.

```python
from excel_utils import copy_sheet_data

copy_sheet_data(wb, Path("mapping.xlsx"), title="Reference", columns=3)
```

- `columns`: limit to first N columns (None = all)

### `truncate_sheet_name(name, *, prefix_to_strip)`

Truncate to Excel's 31-character sheet name limit, optionally stripping a prefix first.

```python
from excel_utils import truncate_sheet_name

truncate_sheet_name("加拿大一店销售公共组", prefix_to_strip="加拿大")
# "一店销售公共组"
```

## Styling (`style.py`)

### `BOLD_FONT`

Shared `Font(bold=True)` instance for consistent header styling.

### `set_header_row(ws, headers, *, row, font)`

Write a styled header row at the specified row number.

### `auto_size_columns(ws, *, max_width, min_width)`

Auto-size all columns based on content width.

- `max_width`: cap at 40 characters (default)
- `min_width`: floor at 10 characters (default)

## Dependencies

- `openpyxl>=3.1.0`
