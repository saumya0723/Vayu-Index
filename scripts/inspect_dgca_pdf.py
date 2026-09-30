"""
Inspection script for DGCA PDF.
Run this first to understand the raw structure before extraction.
"""

import pdfplumber
import os

PDF_PATH = r"data/official/dgca/raw/TABLE 5.01 (INDIAN CITY-WISE PASSENGER TRAFFIC).pdf"

def inspect_pdf():
    with pdfplumber.open(PDF_PATH) as pdf:
        print(f"PDF: {os.path.basename(PDF_PATH)}")
        print(f"Total pages: {len(pdf.pages)}")
        print("=" * 80)

        for page_num, page in enumerate(pdf.pages, 1):
            print(f"\n--- PAGE {page_num} ---")
            text = page.extract_text()
            if text:
                lines = text.strip().split("\n")
                print(f"  First 15 lines of page {page_num}:")
                for i, line in enumerate(lines[:15]):
                    print(f"    [{i+1}] {repr(line)}")
                print(f"  Total text lines: {len(lines)}")
            else:
                print("  [NO TEXT EXTRACTED]")

            tables = page.extract_tables()
            print(f"  Tables found by pdfplumber: {len(tables)}")
            for t_idx, table in enumerate(tables):
                print(f"  Table {t_idx+1}: {len(table)} rows x {len(table[0]) if table else 0} cols")
                if table:
                    print(f"    Header row: {table[0]}")
                    if len(table) > 1:
                        print(f"    Row 1:      {table[1]}")
                    if len(table) > 2:
                        print(f"    Row 2:      {table[2]}")

if __name__ == "__main__":
    inspect_pdf()
