import os
import json

import pandas as pd

from robot.api import logger
from robot.api.deco import keyword


class ExcelDataLibrary:
    """
    Reads Excel/CSV files with pandas, exposes rows as dictionaries
    (header row = keys) and provides data-quality assertions for Robot Framework.
    """

    ROBOT_LIBRARY_SCOPE = 'GLOBAL'

    # How many mismatching rows are listed in a failure message
    DEFAULT_MAX_REPORTED_ERRORS = 20

    def __init__(self, default_sheet=0, strip_headers=True,
                 max_reported_errors=DEFAULT_MAX_REPORTED_ERRORS):
        self._default_sheet = default_sheet
        self._strip_headers = strip_headers
        self._max_reported_errors = int(max_reported_errors)
        logger.info(
            f"ExcelDataLibrary initialized: default_sheet={default_sheet}, "
            f"strip_headers={strip_headers}"
        )

    # ==================================================
    # READ EXCEL → PANDAS → LIST OF DICTIONARIES
    # ==================================================

    @keyword("Read Excel File")
    def read_excel_file(self, file_path, sheet_name=None, header_row=1,
                        read_as_string=False, drop_empty_rows=True,
                        strip_values=True, columns=None):
        """
        Read an Excel/CSV file and return it as a LIST OF DICTIONARIES,
        where the header row provides the keys.

        Args:
            file_path      : .xlsx | .xlsm | .xls | .xlsb | .csv
            sheet_name     : Sheet name or 0-based index (default: first sheet)
            header_row     : 1-based row number containing the headers (default: 1)
            read_as_string : True → read every cell as text (no 1 -> 1.0 conversion)
            drop_empty_rows: Drop rows where all cells are empty
            strip_values   : Strip whitespace from string cells
            columns        : Optional list of columns to keep

        Returns:
            [ {'id': 1, 'type': 1, 'name': 'abc'}, {...} ]

        Example:
            | ${rows}= | Read Excel File | ${EXCEL_FILE} |
            | ${rows}= | Read Excel File | ${EXCEL_FILE} | sheet_name=Summary | header_row=2 |
        """
        df = self.read_excel_file_as_dataframe(
            file_path, sheet_name=sheet_name, header_row=header_row,
            read_as_string=read_as_string, drop_empty_rows=drop_empty_rows,
            strip_values=strip_values, columns=columns
        )
        records = self._to_records(df)
        logger.info(f"Converted to {len(records)} dictionary row(s). "
                    f"Keys: {list(df.columns)}")
        return records

    @keyword("Read Excel File As Dataframe")
    def read_excel_file_as_dataframe(self, file_path, sheet_name=None, header_row=1,
                                     read_as_string=False, drop_empty_rows=True,
                                     strip_values=True, columns=None):
        """
        Read an Excel/CSV file into a pandas DataFrame (headers become column names).
        Use when you need pandas power (groupby, merge, compare with DB/Glue output).

        Example:
            | ${df}= | Read Excel File As Dataframe | ${EXCEL_FILE} |
        """
        path = os.path.abspath(file_path)
        if not os.path.isfile(path):
            raise AssertionError(f"Excel file not found: {path}")

        sheet = self._default_sheet if sheet_name is None else self._coerce_sheet(sheet_name)
        header_index = int(header_row) - 1
        dtype = str if str(read_as_string).lower() in ('true', 'yes', '1') else None
        extension = os.path.splitext(path)[1].lower()

        logger.info(f"Reading '{path}' (sheet={sheet}, header_row={header_row}, "
                    f"read_as_string={read_as_string})")

        try:
            if extension == '.csv':
                df = pd.read_csv(path, header=header_index, dtype=dtype)
            else:
                df = pd.read_excel(path, sheet_name=sheet, header=header_index,
                                   dtype=dtype, engine=self._resolve_engine(extension))
        except Exception as e:
            logger.error(f"Failed to read '{path}': {e}")
            raise

        # Headers → clean keys
        if self._strip_headers:
            df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.str.startswith('Unnamed')]

        if str(drop_empty_rows).lower() in ('true', 'yes', '1'):
            df = df.dropna(how='all')

        if str(strip_values).lower() in ('true', 'yes', '1'):
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)

        if columns:
            wanted = [self._resolve_column(df, c) for c in self._as_list(columns)]
            df = df[wanted]

        df = df.reset_index(drop=True)
        logger.info(f"Loaded {len(df)} row(s) x {len(df.columns)} column(s). "
                    f"Headers(keys): {list(df.columns)}")
        return df

    # ==================================================
    # ACCESSORS
    # ==================================================

    @keyword("Get Excel Headers")
    def get_excel_headers(self, data, **read_options):
        """Return the header names (dictionary keys) of the file/data."""
        df = self._as_dataframe(data, **read_options)
        headers = list(df.columns)
        logger.info(f"Headers: {headers}")
        return headers

    @keyword("Get Excel Row Count")
    def get_excel_row_count(self, data, **read_options):
        """Return the number of data rows (header excluded)."""
        df = self._as_dataframe(data, **read_options)
        count = len(df)
        logger.info(f"Row count: {count}")
        return count

    @keyword("Get Excel Column Values")
    def get_excel_column_values(self, data, column, unique=False, **read_options):
        """
        Return all values of one column as a list.

        Example:
            | ${types}= | Get Excel Column Values | ${EXCEL_FILE} | type |
        """
        df = self._as_dataframe(data, **read_options)
        col = self._resolve_column(df, column)
        series = df[col].drop_duplicates() if str(unique).lower() in ('true', 'yes', '1') \
            else df[col]
        values = [self._clean_value(v) for v in series.tolist()]
        logger.info(f"Column '{col}' values ({len(values)}): {values[:20]}"
                    f"{' ...' if len(values) > 20 else ''}")
        return values

    @keyword("Get Excel Rows Where")
    def get_excel_rows_where(self, data, column, value, **read_options):
        """
        Return rows (as dictionaries) where 'column' equals 'value'.

        Example:
            | ${rows}= | Get Excel Rows Where | ${EXCEL_FILE} | type | 1 |
        """
        df = self._as_dataframe(data, **read_options)
        col = self._resolve_column(df, column)
        mask = df[col].apply(lambda v: self._values_equal(v, value))
        rows = self._to_records(df[mask])
        logger.info(f"{len(rows)} row(s) where {col} == {value}")
        return rows

    # ==================================================
    # ASSERTIONS
    # ==================================================

    @keyword("Excel Should Contain Columns")
    def excel_should_contain_columns(self, data, *expected_columns, **read_options):
        """
        Assert the file contains the expected header names (case-insensitive).

        Example:
            | Excel Should Contain Columns | ${EXCEL_FILE} | id | type | status |
        """
        df = self._as_dataframe(data, **read_options)
        actual_lower = {str(c).strip().lower(): c for c in df.columns}
        missing = [c for c in expected_columns if str(c).strip().lower() not in actual_lower]
        if missing:
            raise AssertionError(
                f"Missing column(s) {missing} in Excel data. Actual headers: {list(df.columns)}"
            )
        logger.info(f"All expected columns present: {list(expected_columns)}")

    @keyword("Excel Column Values Should Be")
    def excel_column_values_should_be(self, data, column, expected_value,
                                      header_row=1, ignore_case=True,
                                      allow_empty=False, **read_options):
        """
        Assert EVERY row of 'column' equals 'expected_value'.
        Numeric-safe: 1, '1', 1.0 and ' 1 ' are all treated as equal.

        Failure message lists the Excel row numbers and the actual values.

        Examples:
            | Excel Column Values Should Be | ${EXCEL_FILE} | type | 1 |
            | Excel Column Values Should Be | ${rows}       | type | 1 | ignore_case=True |
        """
        df = self._as_dataframe(data, header_row=header_row, **read_options)
        col = self._resolve_column(df, column)
        ignore_case = str(ignore_case).lower() in ('true', 'yes', '1')
        allow_empty = str(allow_empty).lower() in ('true', 'yes', '1')
        row_offset = int(header_row) + 1          # +1 header, +1 for 1-based Excel rows

        mismatches = []
        for index, raw in enumerate(df[col].tolist()):
            value = self._clean_value(raw)
            if value is None and allow_empty:
                continue
            if not self._values_equal(value, expected_value, ignore_case):
                mismatches.append(
                    f"Excel row {index + row_offset}: '{col}' = {value!r} "
                    f"(expected {expected_value!r})"
                )

        total = len(df)
        if mismatches:
            shown = mismatches[:self._max_reported_errors]
            more = len(mismatches) - len(shown)
            raise AssertionError(
                f"{len(mismatches)} of {total} row(s) have '{col}' != {expected_value!r}:\n  "
                + "\n  ".join(shown)
                + (f"\n  ... and {more} more" if more > 0 else "")
            )

        logger.info(f"Verified: all {total} row(s) have '{col}' == {expected_value!r}")
        return total

    @keyword("Excel Column Values Should Be In")
    def excel_column_values_should_be_in(self, data, column, allowed_values,
                                         header_row=1, ignore_case=True, **read_options):
        """
        Assert every value of 'column' is one of 'allowed_values'.

        Example:
            | ${allowed}= | Create List | 1 | 2 |
            | Excel Column Values Should Be In | ${EXCEL_FILE} | type | ${allowed} |
        """
        df = self._as_dataframe(data, header_row=header_row, **read_options)
        col = self._resolve_column(df, column)
        allowed = self._as_list(allowed_values)
        ignore_case = str(ignore_case).lower() in ('true', 'yes', '1')
        row_offset = int(header_row) + 1

        mismatches = []
        for index, raw in enumerate(df[col].tolist()):
            value = self._clean_value(raw)
            if not any(self._values_equal(value, a, ignore_case) for a in allowed):
                mismatches.append(f"Excel row {index + row_offset}: '{col}' = {value!r}")

        if mismatches:
            shown = mismatches[:self._max_reported_errors]
            more = len(mismatches) - len(shown)
            raise AssertionError(
                f"{len(mismatches)} row(s) have '{col}' outside allowed values {allowed}:\n  "
                + "\n  ".join(shown)
                + (f"\n  ... and {more} more" if more > 0 else "")
            )
        logger.info(f"Verified: all {len(df)} row(s) have '{col}' in {allowed}")

    @keyword("Excel Should Not Be Empty")
    def excel_should_not_be_empty(self, data, min_rows=1, **read_options):
        """Assert the file has at least 'min_rows' data rows."""
        df = self._as_dataframe(data, **read_options)
        if len(df) < int(min_rows):
            raise AssertionError(
                f"Excel data has {len(df)} row(s), expected at least {min_rows}"
            )
        logger.info(f"Row count OK: {len(df)} >= {min_rows}")
        return len(df)

    # ==================================================
    # EVIDENCE
    # ==================================================

    @keyword("Save Excel Data As Json")
    def save_excel_data_as_json(self, data, output_path, **read_options):
        """Dump the parsed rows as JSON — handy CI evidence / debugging artifact."""
        records = data if isinstance(data, list) \
            else self._to_records(self._as_dataframe(data, **read_options))
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as fh:
            json.dump(records, fh, indent=2, default=str)
        logger.info(f"Saved {len(records)} row(s) → {output_path}")
        return output_path

    # ==================================================
    # PRIVATE HELPERS
    # ==================================================

    def _as_dataframe(self, data, **read_options):
        """Accept a file path, a list of dicts, or an existing DataFrame."""
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, str):
            return self.read_excel_file_as_dataframe(data, **read_options)
        if isinstance(data, (list, tuple)):
            if not data:
                return pd.DataFrame()
            return pd.DataFrame(list(data))
        if isinstance(data, dict):
            return pd.DataFrame([data])
        raise TypeError(
            f"Unsupported data type '{type(data).__name__}'. "
            f"Pass a file path, list of dictionaries or a DataFrame."
        )

    def _to_records(self, df):
        return [
            {str(k): self._clean_value(v) for k, v in row.items()}
            for row in df.to_dict(orient='records')
        ]

    def _resolve_column(self, df, column):
        """Case/whitespace-insensitive column lookup with a helpful error."""
        wanted = str(column).strip().lower()
        for actual in df.columns:
            if str(actual).strip().lower() == wanted:
                return actual
        raise AssertionError(
            f"Column '{column}' not found. Available headers: {list(df.columns)}"
        )

    def _clean_value(self, value):
        """NaN/NaT → None, numpy scalars → python, strings stripped."""
        if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
            return None
        if hasattr(value, 'item') and not isinstance(value, str):
            try:
                value = value.item()
            except Exception:
                pass
        if isinstance(value, str):
            value = value.strip()
            return value if value else None
        return value

    def _values_equal(self, actual, expected, ignore_case=True):
        """1 == '1' == 1.0 == ' 1 ' ; falls back to string comparison."""
        if actual is None:
            return expected in (None, '', 'None')
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            a, b = str(actual).strip(), str(expected).strip()
            return a.lower() == b.lower() if ignore_case else a == b

    def _resolve_engine(self, extension):
        return {'.xlsx': 'openpyxl', '.xlsm': 'openpyxl',
                '.xls': 'xlrd', '.xlsb': 'pyxlsb'}.get(extension)

    def _coerce_sheet(self, sheet_name):
        try:
            return int(sheet_name)          # allows sheet_name=0
        except (TypeError, ValueError):
            return sheet_name

    def _as_list(self, value):
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [v.strip() for v in str(value).split(',') if v.strip()]
