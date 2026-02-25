"""
File Parser Module

This module provides functionality for parsing different file types (CSV, Excel, PDF)
and converting them to a standardized format for data visualization.

Supported file types:
- CSV: Comma-separated values
- Excel: .xlsx and .xls files
- PDF: PDF documents (extract data)

The parser extracts data ands tables and text column headers that can be used by the LLM
to generate appropriate visualizations.
"""

import io
import base64
from typing import Optional
from enum import Enum

# Import pandas for data handling
try:
    import pandas as pd
except ImportError:
    pd = None

# Import Excel handling
try:
    import openpyxl
except ImportError:
    openpyxl = None

# Import PDF handling
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None


class FileType(Enum):
    """Enum for supported file types."""

    CSV = "csv"
    EXCEL = "excel"
    PDF = "pdf"
    UNKNOWN = "unknown"


def detect_file_type(filename: str, content: Optional[bytes] = None) -> FileType:
    """
    Detect the file type based on filename extension or content.

    Args:
        filename: The name of the file
        content: Optional file content bytes for further detection

    Returns:
        FileType enum value
    """
    if not filename:
        return FileType.UNKNOWN

    filename_lower = filename.lower()

    if filename_lower.endswith(".csv"):
        return FileType.CSV
    elif filename_lower.endswith((".xlsx", ".xls")):
        return FileType.EXCEL
    elif filename_lower.endswith(".pdf"):
        return FileType.PDF

    # Check content magic bytes if available
    if content:
        if content.startswith(b"%PDF"):
            return FileType.PDF
        elif content.startswith(b"PK\x03\x04"):  # Excel files are ZIP-based
            return FileType.EXCEL

    return FileType.UNKNOWN


def parse_csv(content: str) -> dict:
    """
    Parse CSV content.

    Args:
        content: CSV content as string

    Returns:
        Dictionary with parsed data and metadata
    """
    if pd is None:
        return {
            "success": False,
            "error": "pandas not installed",
            "headers": [],
            "data": [],
            "row_count": 0,
        }

    try:
        # Read CSV data
        df = pd.read_csv(io.StringIO(content))

        # Convert to list of dictionaries
        data = df.to_dict("records")
        headers = df.columns.tolist()

        return {
            "success": True,
            "headers": headers,
            "data": data,
            "row_count": len(df),
            "data_as_csv": content.strip(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "headers": [],
            "data": [],
            "row_count": 0,
        }


def parse_excel(content: bytes) -> dict:
    """
    Parse Excel file content.

    Args:
        content: Excel file content as bytes

    Returns:
        Dictionary with parsed data and metadata
    """
    if pd is None:
        return {
            "success": False,
            "error": "pandas not installed",
            "headers": [],
            "data": [],
            "row_count": 0,
        }

    if openpyxl is None:
        return {
            "success": False,
            "error": "openpyxl not installed",
            "headers": [],
            "data": [],
            "row_count": 0,
        }

    try:
        # Read Excel data from bytes
        df = pd.read_excel(io.BytesIO(content))

        # Convert to list of dictionaries
        data = df.to_dict("records")
        headers = df.columns.tolist()

        # Also convert to CSV for the visualization code
        csv_output = df.to_csv(index=False)

        return {
            "success": True,
            "headers": headers,
            "data": data,
            "row_count": len(df),
            "data_as_csv": csv_output,
            "sheet_names": [df.columns.name] if df.columns.name else [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "headers": [],
            "data": [],
            "row_count": 0,
        }


def parse_pdf(content: bytes) -> dict:
    """
    Parse PDF document and extract tabular data.

    For PDFs, this extracts text and tries to identify tables.
    Tables are converted to a format suitable for visualization.

    Args:
        content: PDF file content as bytes

    Returns:
        Dictionary with extracted data and metadata
    """
    if PyPDF2 is None:
        return {
            "success": False,
            "error": "PyPDF2 not installed",
            "headers": [],
            "data": [],
            "row_count": 0,
            "extracted_text": "",
        }

    try:
        # Read PDF from bytes
        pdf_file = io.BytesIO(content)
        reader = PyPDF2.PdfReader(pdf_file)

        all_text = []

        # Extract text from each page
        for page in reader.pages:
            text = page.extract_text()
            if text:
                all_text.append(text)

        # Try to identify and extract tables from the text
        # This is a simple heuristic approach
        combined_text = "\n".join(all_text)

        # Simple table extraction: look for lines that could be table rows
        # Split by double newlines to find potential table sections
        lines = combined_text.split("\n")

        # Try to identify header row (first row with consistent separators)
        table_lines = []
        for line in lines:
            # Look for lines with consistent delimiters (tabs or multiple spaces)
            if "\t" in line or "  " in line:
                # Normalize the line
                normalized = "\t".join(line.split())
                if normalized.strip():
                    table_lines.append(normalized)

        if table_lines:
            # Try to parse as DataFrame
            try:
                # First line is likely headers
                if len(table_lines) >= 1:
                    headers = [h.strip() for h in table_lines[0].split("\t")]

                    # Rest are data rows
                    data = []
                    for line in table_lines[1:]:
                        values = [v.strip() for v in line.split("\t")]
                        if len(values) == len(headers):
                            data.append(dict(zip(headers, values)))

                    # Convert to CSV format
                    if pd is not None:
                        df = pd.DataFrame(data)
                        csv_output = df.to_csv(index=False)
                    else:
                        csv_output = "\n".join(table_lines)

                    return {
                        "success": True,
                        "headers": headers,
                        "data": data,
                        "row_count": len(data),
                        "data_as_csv": csv_output,
                        "extracted_text": combined_text[:1000],  # First 1000 chars
                    }
            except Exception:
                pass

        # If table extraction failed, return the text data
        # Create a simple CSV with the text
        text_lines = [line.strip() for line in lines if line.strip()]

        if text_lines:
            # Create a simple single-column dataset from text
            headers = ["text"]
            data = [{"text": line} for line in text_lines[:100]]  # Limit to 100 rows

            csv_output = "text\n" + "\n".join(text_lines[:100])

            return {
                "success": True,
                "headers": headers,
                "data": data,
                "row_count": len(data),
                "data_as_csv": csv_output,
                "extracted_text": combined_text[:2000],  # First 2000 chars
                "note": "PDF text extracted. Consider formatting as table for better visualization.",
            }

        return {
            "success": False,
            "error": "No extractable content found in PDF",
            "headers": [],
            "data": [],
            "row_count": 0,
            "extracted_text": "",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "headers": [],
            "data": [],
            "row_count": 0,
            "extracted_text": "",
        }


def parse_file(
    file_content: str, filename: str, file_type: Optional[str] = None
) -> dict:
    """
    Parse a file based on its type.

    This is the main entry point for parsing files. It automatically
    detects the file type if not provided.

    Args:
        file_content: File content (base64 encoded or raw string for CSV)
        filename: Original filename
        file_type: Optional file type hint (csv, excel, pdf)

    Returns:
        Dictionary with parsed data and metadata
    """
    # Detect file type if not provided
    if file_type:
        detected_type = FileType(file_type.lower())
    else:
        # Try to decode base64 content if needed
        content_bytes = None
        try:
            # Try to decode as base64
            content_bytes = base64.b64decode(file_content)
            detected_type = detect_file_type(filename, content_bytes)
        except Exception:
            # Assume it's raw CSV content
            detected_type = FileType.CSV

    # Parse based on detected type
    if detected_type == FileType.CSV:
        # Try to decode if base64 encoded
        try:
            csv_content = base64.b64decode(file_content).decode("utf-8")
        except Exception:
            # Use as-is (likely already a string)
            csv_content = file_content
        return parse_csv(csv_content)

    elif detected_type == FileType.EXCEL:
        # Decode base64 to bytes
        try:
            excel_bytes = base64.b64decode(file_content)
        except Exception:
            # Already bytes
            excel_bytes = file_content
        return parse_excel(excel_bytes)

    elif detected_type == FileType.PDF:
        # Decode base64 to bytes
        try:
            pdf_bytes = base64.b64decode(file_content)
        except Exception:
            # Already bytes
            pdf_bytes = file_content
        return parse_pdf(pdf_bytes)

    else:
        return {
            "success": False,
            "error": f"Unsupported file type: {filename}",
            "headers": [],
            "data": [],
            "row_count": 0,
        }


def get_file_type_description(file_type: FileType) -> str:
    """
    Get a human-readable description of the file type.

    Args:
        file_type: The file type enum value

    Returns:
        Description string
    """
    descriptions = {
        FileType.CSV: "CSV (Comma-Separated Values)",
        FileType.EXCEL: "Excel Spreadsheet",
        FileType.PDF: "PDF Document",
        FileType.UNKNOWN: "Unknown file type",
    }
    return descriptions.get(file_type, "Unknown file type")


# Example usage when run directly
if __name__ == "__main__":
    # Test CSV parsing
    csv_content = """name,value,category
Item A,100,Cat1
Item B,150,Cat1
Item C,200,Cat2"""

    print("Testing CSV parsing...")
    csv_result = parse_csv(csv_content)
    print(f"Success: {csv_result['success']}")
    print(f"Headers: {csv_result['headers']}")
    print(f"Row count: {csv_result['row_count']}")
    print(f"CSV data:\n{csv_result['data_as_csv']}")
    print()

    # Test file type detection
    print("Testing file type detection...")
    print(f"test.csv: {detect_file_type('test.csv')}")
    print(f"data.xlsx: {detect_file_type('data.xlsx')}")
    print(f"document.pdf: {detect_file_type('document.pdf')}")
