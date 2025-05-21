import pandas as pd
from pathlib import Path
import os
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from docx import Document
import openpyxl
import fitz

from scripts.constants import PROJECT_ROOT, KPI_LABELS, SEGMENTS


def read_text_file(file_path: str) -> str:
    """
    Reads a UTF-8 encoded text file and returns its content as a string.

    Args:
        file_path (str): Path to the text file.

    Returns:
        str: The full content of the file as a single string.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"The file does not exist: {file_path}")
    if path.suffix.lower() != ".txt":
        raise ValueError("Only .txt files are supported.")

    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise IOError(f"Failed to read file '{file_path}': {e}")


def load_ifo_data(csv_path: Path, start_date: str = None) -> pd.DataFrame:
    """
    Load and preprocess IFO business climate data from a prepared CSV file.

    Args:
        csv_path (Path): Path to the prepared IFO CSV file

    Returns:
        pd.DataFrame: Preprocessed DataFrame with datetime index
    """
    # Read CSV with proper separators and decimal handling
    df = pd.read_csv(csv_path, sep=";", decimal=",")

    # Convert 'Monat/Jahr' to datetime
    df["Monat/Jahr"] = pd.to_datetime(df["Monat/Jahr"], format=" %m/%Y")

    # Normalize column names
    df.columns = [
        col.strip()
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        for col in df.columns
    ]

    # Set date as index (optional, useful for time series work)
    df.set_index("monat/jahr", inplace=True)
    df.dropna(how="all", inplace=True, axis="columns")
    df.dropna(how="all", inplace=True, axis="index")

    if start_date:
        df = df[df.index >= pd.to_datetime(start_date)]

    return df


def load_pmi_time_series(csv_path: Path) -> pd.DataFrame:
    """
    Load and preprocess PMI Time Series from a prepared CSV file.

    Args:
        csv_path (Path): Path to the prepared PMI CSV file

    Returns:
        pd.DataFrame: Preprocessed DataFrame with datetime index
    """
    df = pd.read_csv(csv_path, sep=",", decimal=".")
    df["Month"] = pd.to_datetime(df["Month"], format="%m/%Y")
    df.dropna(how="all", inplace=True, axis="index")

    return df


def extract_text_from_pdf(filepath):
    try:
        doc = fitz.open(filepath)
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        print(f"Fehler beim PDF-Parsing: {e}")
        return ""


def extract_text_from_docx(filepath):
    try:
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        print(f"Fehler beim DOCX-Parsing: {e}")
        return ""


def extract_text_from_excel(filepath):
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        text = ""
        for sheet in wb.worksheets:
            text += f"--- Sheet: {sheet.title} ---\n"
            for row in sheet.iter_rows(values_only=True):
                row_text = "\t".join(
                    str(cell) if cell is not None else "" for cell in row
                )
                text += row_text + "\n"
        return text
    except Exception as e:
        print(f"Fehler beim Excel-Parsing: {e}")
        return ""


def extract_metrics_from_excel(path: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    Extract key financial KPIs from multiple sheets within a financial summary Excel file using flexible keyword matching.

    Args:
        path (Path): Path to the Excel file

    Returns:
        Dict[str, Dict[str, Dict[str, str]]]: Nested dictionary of segment → KPI → period → value
    """
    xls = pd.ExcelFile(path)
    data = {}

    for sheet, segment_key in SEGMENTS.items():
        df = xls.parse(sheet, header=None)
        headers = df.iloc[3]
        content_df = df.iloc[5:].copy()
        content_df.columns = headers
        content_df.dropna(how="all", inplace=True)
        content_df.fillna("", inplace=True)

        segment_data = {}

        for row_idx, row in content_df.iterrows():
            row_label = str(row.iloc[0]).lower()
            for kpi_key, keywords in KPI_LABELS.items():
                if any(kw in row_label for kw in keywords):
                    values = row.iloc[1:]
                    metrics = {
                        str(period)
                        .replace(" ", "_")
                        .replace(".", "")
                        .replace("\n", "_")
                        .strip(): str(v)
                        .strip()
                        for period, v in zip(values.index, values.values)
                        if str(v).strip() != ""
                    }
                    segment_data[kpi_key] = metrics

        data[segment_key] = segment_data

    return data


def extract_asset_quality_metrics(path: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extracts GCA and ACL metrics from the 'Asset Quality' sheet of the given Excel file.

    Parameters:
        path (Path): Path to the Excel file.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: DataFrames for GCA and ACL.
    """
    try:
        xls = pd.ExcelFile(path)
        df = xls.parse("Asset Quality", header=None)
        dates = df.iloc[17:26, 0]
        base_date = datetime(1899, 12, 30)

        # Wandeln von Excel-Serialdaten (z. B. 45657) zu datetime
        dates = df.iloc[17:26, 0].apply(lambda x: base_date + timedelta(days=float(x)))
        columns_list = ["Stage 1", "Stage 2", "Stage 3", "Stage 3 POCI", "Total"]

        gca_values = df.iloc[17:26, 2:11]
        gca_values.dropna(how="all", inplace=True, axis="columns")
        gca_values.columns = columns_list
        df_gca = pd.DataFrame(gca_values.values, columns=gca_values.columns)
        df_gca.insert(0, "Date", dates.values)

        acl_values = df.iloc[17:26, 12:21]
        acl_values.dropna(how="all", inplace=True, axis="columns")
        acl_values.columns = columns_list
        df_acl = pd.DataFrame(acl_values.values, columns=acl_values.columns)
        df_acl.insert(0, "Date", dates.values)
        return df_gca, df_acl
    except:
        return None, None


def prepare_chart_data(
    bank_data_dict, segment_name, kpi_key, df_ifo=None, include_ifo=False
):
    """
    Prepare time-series chart data for the specified KPI and optional macro indicators.

    Args:
        bank_data_dict (Dict): Dictionary containing extracted metrics for different segments
        segment_name (str): Name of the segment to extract data for
        kpi_key (str): Key of the KPI to extract
        df_ifo (pd.DataFrame, optional): DataFrame containing IFO data
        include_ifo (bool): Whether to include IFO data in the chart

    Returns:
        Dict: Chart data object with labels and datasets
    """
    try:
        # Get KPI data for the specified segment
        segment_data = bank_data_dict.get(segment_name, {})
        kpi_data = segment_data.get(kpi_key, {})

        # Filter and prepare time period labels (exclude YoY comparison columns)
        periods = []
        for period in kpi_data.keys():
            if period and "vs" not in str(period).lower():
                periods.append(period)

        # Sort periods chronologically
        # Use simpler sorting based on quarter number and year
        sorted_periods = []
        quarterly_periods = []
        fiscal_periods = []

        for period in periods:
            period_str = str(period).strip().upper()
            if period_str.startswith("FY"):
                fiscal_periods.append(period)
            elif "Q" in period_str:
                quarterly_periods.append(period)

        # Sort quarterly periods (Q1 2023, Q2 2023, etc.)
        def quarter_sort_key(period):
            period_str = str(period).strip().upper()
            if "Q" not in period_str:
                return (0, 0)

            parts = period_str.split()
            if len(parts) < 2:
                return (0, 0)

            try:
                quarter = int(parts[0].replace("Q", ""))
                year = int(parts[1])
                return (year, quarter)
            except ValueError:
                return (0, 0)

        sorted_quarterly = sorted(quarterly_periods, key=quarter_sort_key)

        # Sort fiscal years (FY2022, FY2023, etc.)
        def fiscal_sort_key(period):
            period_str = str(period).strip().upper()
            if not period_str.startswith("FY"):
                return 0

            try:
                year = int(period_str.replace("FY", ""))
                return year
            except ValueError:
                return 0

        sorted_fiscal = sorted(fiscal_periods, key=fiscal_sort_key)

        # Combine sorted periods (quarterly first, then fiscal years)
        sorted_periods = sorted_quarterly + sorted_fiscal

        # Convert data values to float, handling non-numeric values
        values = []
        for period in sorted_periods:
            try:
                # Get the original value from kpi_data
                value_str = str(kpi_data.get(period, "0"))

                # Clean the string and convert to float
                # Remove common non-numeric characters
                cleaned_value = (
                    value_str.replace("%", "")
                    .replace("bps", "")
                    .replace(",", "")
                    .strip()
                )

                # Handle empty or non-numeric values
                if not cleaned_value or cleaned_value == "-":
                    values.append(None)
                else:
                    values.append(float(cleaned_value))
            except (ValueError, TypeError):
                values.append(None)  # Use None for missing or invalid values

        # Prepare chart data
        chart_data = {
            "labels": sorted_periods,
            "datasets": [
                {
                    "label": "Provision for Credit Losses (bps of Avg Loans)",
                    "data": values,
                    "borderColor": "#4285F4",
                    "backgroundColor": "rgba(66, 133, 244, 0.2)",
                }
            ],
        }

        # Add IFO data if requested and available
        if include_ifo and df_ifo is not None:
            try:
                # Convert IFO monthly data to quarterly averages
                quarterly_ifo = {}

                for period in sorted_periods:
                    try:
                        period_str = str(period).strip().upper()

                        # Check if we have IFO data for the relevant time periods
                        print(f"Processing period: {period_str}")
                        print(f"Available IFO years: {df_ifo.index.year.unique()}")

                        if "FY" in period_str:
                            # For fiscal years, extract the year number
                            # Handle format like "FY_2022" or "FY2022"
                            year_str = (
                                period_str.replace("FY", "").replace("_", "").strip()
                            )
                            year = int(year_str)
                            print(f"Looking for IFO data for fiscal year {year}")

                            # For fiscal year, get all months in that year
                            quarter_data = df_ifo[df_ifo.index.year == year]

                        else:
                            # Handle quarterly format like "Q1_2023" or "Q1 2023"
                            # Extract quarter and year from formats like "Q1_2023"
                            quarter_part = ""
                            year_part = ""

                            if "_" in period_str:
                                parts = period_str.split("_")
                                if len(parts) >= 2:
                                    quarter_part = parts[0]
                                    year_part = parts[1]
                            else:
                                # Try to extract Q and year another way
                                quarter_part = "".join(
                                    [
                                        c
                                        for c in period_str
                                        if c.isalpha() or c.isspace()
                                    ]
                                )
                                year_part = "".join(
                                    [c for c in period_str if c.isdigit()]
                                )

                            # Now extract quarter number and year
                            quarter = int(quarter_part.replace("Q", ""))
                            year = int(year_part)
                            print(f"Looking for IFO data for Q{quarter} {year}")

                            # Calculate start and end months for the quarter
                            start_month = (quarter - 1) * 3 + 1
                            end_month = quarter * 3

                            # Filter IFO data for the quarter
                            quarter_data = df_ifo[
                                (df_ifo.index.year == year)
                                & (df_ifo.index.month >= start_month)
                                & (df_ifo.index.month <= end_month)
                            ]

                        # Debug info about the data we found
                        print(
                            f"Found {len(quarter_data)} IFO data points for period {period}"
                        )

                        # Calculate average IFO for the period
                        if not quarter_data.empty:
                            # Check which column to use for geschaeftsklima
                            ifo_column = None
                            for col in quarter_data.columns:
                                if "geschaeftsklima" in col.lower():
                                    ifo_column = col
                                    break

                            if ifo_column:
                                quarterly_ifo[period] = float(
                                    quarter_data[ifo_column].values[-1]
                                )
                                print(
                                    f"IFO data for period {period}: {quarterly_ifo[period]}"
                                )
                            else:
                                print(
                                    f"No 'geschaeftsklima' column found in IFO data. Available columns: {quarter_data.columns.tolist()}"
                                )
                                quarterly_ifo[period] = None
                        else:
                            quarterly_ifo[period] = None
                            print(f"No IFO data found for period {period}")
                    except Exception as e:
                        print(f"Error processing IFO data for period {period}: {e}")
                        quarterly_ifo[period] = None

                # Add IFO dataset to chart
                ifo_values = [quarterly_ifo.get(period) for period in sorted_periods]

                # Debug: Check if we have any valid IFO values
                valid_ifo_count = sum(1 for val in ifo_values if val is not None)
                print(
                    f"Total periods: {len(sorted_periods)}, Valid IFO values: {valid_ifo_count}"
                )
                print(f"IFO values: {ifo_values}")

                if valid_ifo_count > 0:
                    chart_data["datasets"].append(
                        {
                            "label": "IFO Business Climate Index",
                            "data": ifo_values,
                            "borderColor": "#34A853",
                            "backgroundColor": "rgba(52, 168, 83, 0.2)",
                            "yAxisID": "y1",  # Use secondary y-axis for IFO data
                        }
                    )
                else:
                    print("No valid IFO data found to display on chart")
            except Exception as e:
                print(f"Error adding IFO data to chart: {e}")
                import traceback

                print(traceback.format_exc())

        return chart_data

    except Exception as e:
        print(f"Error in prepare_chart_data: {e}")
        # Return a simple empty chart structure as fallback
        return {
            "labels": [],
            "datasets": [
                {
                    "label": "Provision for Credit Losses (bps of Avg Loans)",
                    "data": [],
                    "borderColor": "#4285F4",
                    "backgroundColor": "rgba(66, 133, 244, 0.2)",
                }
            ],
        }
