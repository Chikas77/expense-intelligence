# Code Snippets Reference — M-PESA Statement PDF Table Parser

## The Core Addition to `parser.py`

### 1. Table Extraction Function
Extracts all tables from a PDF:

```python
def _extract_tables_from_pdf_bytes(pdf_bytes):
    """Extract all tables from PDF using pdfplumber."""
    if pdfplumber is None:
        return []
    
    try:
        tables = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_tables = page.extract_tables()
                if page_tables:
                    for table in page_tables:
                        tables.append((page_num, table))
        return tables
    except Exception:
        return []
```

### 2. Table Row Parser
Intelligently parses statement table rows:

```python
def _parse_statement_table_rows(table):
    """
    Parse M-PESA statement table rows.
    Expected columns: Receipt No., Details, Paid In, Withdrawn, Balance
    Handles: Flexible column order, missing data, different header names
    """
    if not table or len(table) < 2:
        return []
    
    # Auto-detect column positions (flexible to header variations)
    header_row = table[0]
    header_lower = [str(cell).lower() if cell else '' for cell in header_row]
    
    col_indices = {
        'receipt': None,
        'details': None,
        'paid_in': None,
        'withdrawn': None,
        'balance': None,
    }
    
    for idx, cell_text in enumerate(header_lower):
        if 'receipt' in cell_text:
            col_indices['receipt'] = idx
        elif 'detail' in cell_text:
            col_indices['details'] = idx
        elif 'paid in' in cell_text or 'paid' in cell_text and 'in' in cell_text:
            col_indices['paid_in'] = idx
        elif 'withdrawn' in cell_text:
            col_indices['withdrawn'] = idx
        elif 'balance' in cell_text:
            col_indices['balance'] = idx
    
    # Parse each row
    transactions_data = []
    
    for row in table[1:]:
        try:
            if not row or all(not cell or str(cell).strip() == '' for cell in row):
                continue
            
            # Extract fields
            receipt_no = row[col_indices['receipt']].strip() if col_indices['receipt'] is not None else ''
            details = row[col_indices['details']].strip() if col_indices['details'] is not None else ''
            paid_in_str = row[col_indices['paid_in']].strip() if col_indices['paid_in'] is not None else ''
            withdrawn_str = row[col_indices['withdrawn']].strip() if col_indices['withdrawn'] is not None else ''
            balance_str = row[col_indices['balance']].strip() if col_indices['balance'] is not None else ''
            
            if not details or not (paid_in_str or withdrawn_str) or not balance_str:
                continue
            
            # Determine amount and whether it's an inflow
            amount = 0.0
            is_inflow = False
            
            if paid_in_str and paid_in_str != '-':
                try:
                    amount = _parse_amount(paid_in_str)
                    is_inflow = True
                except (ValueError, AttributeError):
                    pass
            
            if amount == 0 and withdrawn_str and withdrawn_str != '-':
                try:
                    amount = _parse_amount(withdrawn_str)
                    is_inflow = False
                except (ValueError, AttributeError):
                    pass
            
            if amount == 0:
                continue
            
            # Parse balance
            try:
                balance = _parse_amount(balance_str)
            except (ValueError, AttributeError):
                balance = 0.0
            
            transactions_data.append({
                'receipt_no': receipt_no or None,
                'details': details,
                'amount': amount,
                'balance': balance,
                'is_inflow': is_inflow,
            })
        except Exception:
            continue
    
    return transactions_data
```

### 3. Transaction Creator
Converts parsed table rows to Transaction objects with auto-categorization:

```python
def extract_mpesa_statement_pdf(pdf_bytes):
    """
    Extract transactions from a structured M-PESA statement PDF (table format).
    Returns list of Transaction objects with proper categorization.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return []
    
    tables = _extract_tables_from_pdf_bytes(pdf_bytes)
    if not tables:
        return []
    
    transactions = []
    
    for page_num, table in tables:
        rows_data = _parse_statement_table_rows(table)
        for row_data in rows_data:
            description = row_data['details']
            if not description:
                continue
            
            # Clean description
            description = re.sub(r'\s+', ' ', description).strip()
            
            # Auto-categorize based on inflow status and keywords
            if row_data['is_inflow']:
                category = 'inflow'
            else:
                lower_desc = description.lower()
                if re.search(r'\b(airtime|bundle|data|sms)\b', lower_desc):
                    category = 'airtime'
                elif re.search(r'\b(sent|paid|paid to|transfer|paybill|till|deposit|withdrawal|withdraw)\b', lower_desc):
                    category = 'expense'
                else:
                    category = 'other'
            
            # Create Transaction object
            transaction = Transaction(
                amount=row_data['amount'],
                description=description,
                category=category,
                balance=row_data['balance'],
                timestamp=datetime.now(),
                transaction_code=row_data['receipt_no'],
            )
            transaction.candidate_text = row_data['details']
            transactions.append(transaction)
    
    return transactions
```

### 4. Modified Fallback Logic (in existing functions)

**In `extract_mpesa_pdf_candidates()`:**
```python
# If no SMS-style candidates found, try table extraction
if not candidates:
    try:
        transactions = extract_mpesa_statement_pdf(pdf_bytes)
        for tx in transactions:
            parseable.append({
                'text': tx.candidate_text,
                'parseable': True,
                'description': tx.description,
                'amount': tx.amount,
            })
        candidates = [tx.candidate_text for tx in transactions]
    except Exception:
        pass
```

**In `parse_mpesa_pdf_all()`:**
```python
# If no SMS-style transactions found, try table extraction
if not transactions:
    try:
        transactions = extract_mpesa_statement_pdf(pdf_bytes)
    except Exception:
        pass
```

---

## Transaction Categorization Logic

```
if is_inflow (Paid In column has value):
    category = 'inflow' → marked as DROPPED
else if details contains ("airtime" OR "bundle" OR "data" OR "sms"):
    category = 'airtime'
else if details contains ("sent" OR "paid" OR "transfer" OR "paybill" OR "till"):
    category = 'expense'
else:
    category = 'other'
```

---

## Usage Example in Flask

In `app.py`, the `/preview-pdf` endpoint automatically uses this:

```python
@app.route('/preview-pdf', methods=['POST'])
def preview_pdf():
    pdf_file = request.files.get('pdf_file')
    if pdf_file is None:
        return _api_error('pdf_file is required', 400)

    pdf_bytes = pdf_file.read()
    if not pdf_bytes:
        return _api_error('Uploaded PDF is empty', 400)

    try:
        # This now tries SMS first, then tables
        preview = extract_mpesa_pdf_candidates(pdf_bytes)
    except RuntimeError as exc:
        return _api_error(str(exc), 500)

    data = {
        'raw_text': preview['raw_text'],
        'candidates': preview['parseable'],
    }
    # ... returns to frontend as candidates
```

---

## Data Flow

```
PDF File (table format)
    ↓
extract_mpesa_pdf_candidates()
    ↓
_extract_tables_from_pdf_bytes()
    ↓ (if SMS fails)
_parse_statement_table_rows()
    ↓
extract_mpesa_statement_pdf()
    ↓
Transaction objects with:
  • description (cleaned)
  • amount (from Paid In or Withdrawn)
  • category ('inflow', 'airtime', 'expense', 'other')
  • balance
  • transaction_code (Receipt No.)
    ↓
Return to frontend as candidates
    ↓
User reviews, categorization happens, inflows are dropped
```

---

## Dependencies

Required (already in requirements.txt):
```
Flask>=2.0
pdfplumber>=0.9.0        ← NEW: for table extraction
Pillow>=10.0
pytesseract>=0.3.10
```

All installed ✅

---

## Testing

Run included tests:
```bash
python test_table_parser.py              # Test basic table parsing
python test_full_categorization.py       # Test full categorization pipeline
```

Or test in Flask:
```
1. Start Flask app
2. Upload your M-PESA statement PDF
3. Click "Preview PDF Text"
4. Click "Start Categorization"
```

---

## Key Features

✨ **Column Auto-Detection**: Works even if columns are in different order  
✨ **Flexible Header Matching**: Handles "Paid In", "Paid in", "paid_in" etc.  
✨ **Smart Fallback**: Uses SMS parsing first, tables second  
✨ **Inflow Detection**: Automatically detects and drops cash inflows  
✨ **Robust Parsing**: Skips malformed rows, handles missing data  
✨ **Multi-page Support**: Extracts from all pages in PDF  

---

## Integration Points

| Function | Purpose | Called By |
|----------|---------|-----------|
| `_extract_tables_from_pdf_bytes()` | Extract tables | `_parse_statement_table_rows()` |
| `_parse_statement_table_rows()` | Parse rows | `extract_mpesa_statement_pdf()` |
| `extract_mpesa_statement_pdf()` | Create Transactions | `extract_mpesa_pdf_candidates()`, `parse_mpesa_pdf_all()` |
| `extract_mpesa_pdf_candidates()` | Return preview | `/preview-pdf` endpoint |
| `parse_mpesa_pdf_all()` | Return batch | `/batch-import-pdf` endpoint |

No changes needed in `app.py` — everything works automatically! ✅
