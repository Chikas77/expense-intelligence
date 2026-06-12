# M-PESA Statement PDF Table Parser — Integration Guide

## Problem Fixed
- ❌ **Before:** PDF with structured table format would show "failed to fetch" on preview
- ✅ **After:** Parser automatically detects and extracts transactions from M-PESA statement tables

## What Was Added to `parser.py`

### 1. **`_extract_tables_from_pdf_bytes(pdf_bytes)`**
Extracts all tables from a PDF using pdfplumber's table detection.
```python
- Input: PDF bytes
- Output: List of (page_number, table) tuples
- Handles: Multi-page PDFs with multiple tables
```

### 2. **`_parse_statement_table_rows(table)`**
Parses M-PESA statement table rows by automatically detecting column positions.
```python
- Detects column headers: Receipt No., Details, Paid In, Withdrawn, Balance
- Handles: Missing columns, flexible header names, messy data
- Returns: List of transaction dictionaries with amount, details, balance, is_inflow flag
```

### 3. **`extract_mpesa_statement_pdf(pdf_bytes)`**
Main function to convert structured PDF tables into Transaction objects.
```python
- Input: PDF bytes
- Output: List of Transaction objects
- Features:
  * Automatically categorizes as 'inflow', 'airtime', 'expense', or 'other'
  * Sets dropped=True for inflow transactions (cash inflows)
  * Works seamlessly with existing batch processing
```

### 4. **Modified Functions**
- **`extract_mpesa_pdf_candidates()`** — Now falls back to table extraction if SMS-style parsing finds nothing
- **`parse_mpesa_pdf_all()`** — Now tries table extraction if no SMS candidates found

## How It Works

### Flow for Your PDF:
```
PDF with table format
         ↓
extract_mpesa_pdf_candidates()
         ↓
Try SMS-style regex (finds nothing)
         ↓
Fall back to _extract_tables_from_pdf_bytes()
         ↓
For each table: _parse_statement_table_rows()
         ↓
Extract: Receipt No., Details, Paid In/Withdrawn, Balance
         ↓
Create Transaction objects with auto-categorization
         ↓
Return to frontend as candidates
```

## Expected Behavior

### When You Upload Your Statement PDF:

1. **Press "Preview PDF Text"**
   - System extracts table rows
   - Shows each transaction: `Description — Ksh Amount — (Category)`
   - Example:
     ```
     1. Customer Payment to Small Business to - 01...163 Peter Ndirangu — Ksh 20.00 — expense
     2. Funds received from - 07...901 SWALEHE DZINA — Ksh 267.00 — Dropped — Cash inflow (not an expense)
     3. Merchant Payment to 865212 - DORCAS WAMBUI 2 — Ksh 10.00 — expense
     ```

2. **Press "Start Categorization"**
   - System automatically processes all extracted transactions
   - Inflows are marked as "Dropped"
   - Expenses and others show "Needs review" or auto-categorized status
   - No more "please enter an mpesa sms message" error

## Transaction Categorization Logic

From the PDF table:

| Column | Meaning | Category |
|--------|---------|----------|
| **Paid In** | Money received (inflow) | `inflow` (marked as dropped) |
| **Withdrawn** + Keywords (airtime, bundle, data) | Airtime purchase | `airtime` |
| **Withdrawn** + Keywords (sent, paid, transfer, paybill, till) | Expense | `expense` |
| **Withdrawn** + Other | Miscellaneous | `other` |

## Test Cases Handled

### Your PDF Examples:
```
✓ Receipt: UEQAR5FV3M | Details: Customer Payment to Small Business | Withdrawn: 10.00 | Balance: 4,663.37
  → Category: expense | Amount: 10.00

✓ Receipt: UEQAR5FS9X | Details: Business Payment from CO-OP BANK via API | Paid In: 5,000.00 | Balance: 5,280.37
  → Category: inflow (DROPPED) | Amount: 5,000.00

✓ Receipt: UEBAR3PO2J | Details: Airtime Purchase | Withdrawn: 30.00 | Balance: 299.04
  → Category: airtime | Amount: 30.00
```

## Requirements

```
Flask>=2.0
pdfplumber>=0.9.0     ← NEW: For table extraction
Pillow>=10.0
pytesseract>=0.3.10
```

**pdfplumber is now required** for table parsing. Already installed via pip.

## Testing

### Quick Test in Python:
```python
from parser import extract_mpesa_statement_pdf

# Load your PDF
with open('your_statement.pdf', 'rb') as f:
    pdf_bytes = f.read()

# Extract transactions
transactions = extract_mpesa_statement_pdf(pdf_bytes)

# Check results
for tx in transactions:
    print(f"{tx.description} | Ksh {tx.amount} | {tx.category}")
```

### Expected Output:
```
Customer Payment to Small Business to - 01...163 Peter Ndirangu | Ksh 20.0 | expense
Funds received from - 07...901 SWALEHE DZINA | Ksh 267.0 | inflow
Business Payment from CO-OP BANK via API | Ksh 5000.0 | inflow
Airtime Purchase | Ksh 30.0 | airtime
```

## Error Handling

- **No tables found:** Falls back to SMS-style parsing
- **Malformed table:** Skips invalid rows silently
- **Missing columns:** Returns empty list and tries other methods
- **PDF extraction error:** Returns empty list, prompts user to try again

## Integration Status

✅ **Fully integrated** — No additional changes needed in `app.py`
- The `/preview-pdf` endpoint automatically uses the updated `extract_mpesa_pdf_candidates()`
- The `/batch-import-pdf` endpoint automatically uses the updated `parse_mpesa_pdf_all()`
- Inflows are automatically flagged as dropped in the batch view

## Next Steps

1. ✅ Code is already integrated in `parser.py`
2. ✅ pdfplumber is installed
3. 🔄 **Ready to test:** Upload your M-PESA statement PDF and try "Preview PDF Text"
4. 📊 All extracted transactions will appear with proper categorization and inflow handling
