import io
import re
from datetime import datetime
from categorization_questions import get_disambiguation_questions, process_answer
import io
import base64

import os
import camelot
import pypdf

def _find_header_and_col_indices(table_rows):
    """
    Search all rows of the table to find the header row containing key M-PESA statement columns.
    Returns (header_row_index, col_indices_dict) or (None, None).
    """
    for idx, row in enumerate(table_rows):
        row_lower = [str(cell).lower() if cell is not None else '' for cell in row]
        has_receipt = any('receipt' in cell for cell in row_lower)
        has_details = any('detail' in cell for cell in row_lower)
        if has_receipt and has_details:
            col_indices = {
                'receipt': None,
                'details': None,
                'paid_in': None,
                'withdrawn': None,
                'balance': None,
                'time': None,
            }
            for cell_idx, cell_text in enumerate(row_lower):
                if 'receipt' in cell_text:
                    col_indices['receipt'] = cell_idx
                elif 'detail' in cell_text:
                    col_indices['details'] = cell_idx
                elif 'paid in' in cell_text or ('paid' in cell_text and 'in' in cell_text):
                    col_indices['paid_in'] = cell_idx
                elif 'withdrawn' in cell_text or 'withdraw' in cell_text:
                    col_indices['withdrawn'] = cell_idx
                elif 'balance' in cell_text:
                    col_indices['balance'] = cell_idx
                elif 'time' in cell_text or 'completion' in cell_text:
                    col_indices['time'] = cell_idx
            return idx, col_indices
    return None, None


class Transaction:
    def __init__(self, amount: float, description: str, category: str, balance: float, timestamp: datetime, transaction_code: str = None):
        self.amount = amount
        self.description = description
        self.category = category
        self.balance = balance
        self.timestamp = timestamp
        self.transaction_code = transaction_code

    def __repr__(self):
        return (
            f"Transaction(amount={self.amount}, description={self.description!r}, "
            f"category={self.category!r}, balance={self.balance}, timestamp={self.timestamp!r}, "
            f"transaction_code={self.transaction_code!r})")


def _parse_amount(value: str) -> float:
    return float(value.replace(',', ''))


# M-Pesa transaction codes: 10 alphanumeric chars, typically at the start of SMS
TX_CODE_PATTERN = re.compile(r'\b([A-Z0-9]{10})\b')
# Pattern to split messy pasted text into individual transactions by transaction code boundaries.
TX_SPLIT_PATTERN = re.compile(r'(?=[A-Z0-9]{10}(?=\s+Confirmed\b))', re.IGNORECASE)


def parse_mpesa_sms(message: str):
    if not isinstance(message, str) or not message.strip():
        return None

    message = re.sub(r'\s+', ' ', message).strip()

    tx_code_match = TX_CODE_PATTERN.search(message)
    transaction_code = tx_code_match.group(1) if tx_code_match else None

    balance_pattern = re.compile(
        r'(?:your\s+(?:m[- ]?pesa|mpesa)\s+balance\s+is|new\s+(?:m[- ]?pesa|mpesa)?\s*balance\s+is|balance)\s+Ksh\s*([0-9][0-9,]*(?:\.\d+)?)',
        re.IGNORECASE,
    )
    amount_pattern = re.compile(r'Ksh\s*([0-9][0-9,]*(?:\.\d+)?)', re.IGNORECASE)

    balance_match = balance_pattern.search(message)
    if not balance_match:
        return None

    balance = _parse_amount(balance_match.group(1))
    before_balance = message[:balance_match.start()].strip()

    amount_match = amount_pattern.search(before_balance)
    if not amount_match:
        return None

    amount = _parse_amount(amount_match.group(1))
    description_text = before_balance

    if transaction_code:
        description_text = re.sub(
            r'\b' + re.escape(transaction_code) + r'\b',
            '',
            description_text,
            flags=re.IGNORECASE,
        )
    description_text = re.sub(r'\bconfirmed\b\.?', '', description_text, flags=re.IGNORECASE)
    description_text = amount_pattern.sub('', description_text, count=1)
    description_text = re.sub(r'\btransaction cost,?\s*Ksh\s*[0-9][0-9,]*(?:\.\d+)?\b', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'\bamount you can transact within the day is\s*[0-9][0-9,]*(?:\.\d+)?\b', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'\bdownload my oneapp on\s*\S+\b', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'https?://\S+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'\bnew\s+(?:m[- ]?pesa|mpesa)\b', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'\s+', ' ', description_text).strip(' .,-')

    if not description_text:
        return None

    lower_desc = description_text.lower()
    # Incoming / credit to account
    if re.search(r'\b(received|credited|you have received|you received|paid to you|credited to)\b', lower_desc):
        category = 'inflow'
    elif re.search(r'\b(airtime|bundle|data|sms)\b', lower_desc):
        category = 'airtime'
    elif re.search(r'\b(sent|paid|paid to|transfer|paybill|till|deposit|withdrawal|withdraw)\b', lower_desc):
        category = 'expense'
    else:
        category = 'other'

    return Transaction(
        amount=amount,
        description=description_text,
        category=category,
        balance=balance,
        timestamp=datetime.now(),
        transaction_code=transaction_code,
    )


def split_mpesa_messages(text):
    """Split messy pasted text into individual M-Pesa messages using transaction codes as boundaries."""
    if not text or not isinstance(text, str):
        return []
    text = text.strip()
    if not text:
        return []
    chunks = TX_SPLIT_PATTERN.split(text)
    messages = [chunk.strip() for chunk in chunks if chunk.strip()]
    return messages if messages else [text]


def split_and_parse_mpesa_messages(text):
    """Split messy text into individual SMS messages and parse each one."""
    messages = split_mpesa_messages(text)
    transactions = []
    for msg in messages:
        tx = parse_mpesa_sms(msg)
        if tx is not None:
            transactions.append(tx)
    return transactions


def parse_mpesa_messages(mpesa_text: str):
    """Parse one or more M-Pesa SMS messages pasted together."""
    return split_and_parse_mpesa_messages(mpesa_text)


def _extract_text_from_pdf_bytes(pdf_bytes):
    text_pages = []
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text() or ''
            if page_text.strip():
                text_pages.append(page_text)
    except Exception:
        pass
    return '\n'.join(text_pages).strip()


def _find_mpesa_sms_candidates(text):
    if not text:
        return []

    pattern = re.compile(
        r'([^\n]*?Ksh\s*[0-9][0-9,]*(?:\.\d+)?[^\n]*?(?:balance\s+is|new\s+balance|balance)\s*Ksh\s*[0-9][0-9,]*(?:\.\d+)?[^\n]*)',
        re.IGNORECASE,
    )
    return [match.group(1).strip() for match in pattern.finditer(text)]


def _standardize_pdf_preview_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return ''

    try:
        disclaimer_pattern = re.compile(r'disclaimer[:\s\S]*?(?:conditions apply|terms and conditions|terms & conditions|terms apply)', re.IGNORECASE)
        text = disclaimer_pattern.sub('', text)
    except Exception:
        pass

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cleaned_lines = []
    discard_phrases = [
        r"page\s*\d+", r"statement", r"account", r"statement period", r"generated",
        r"printed", r"disclaimer", r"for more information", r"important information",
        r"contact us", r"safaricom plc", r"company\b", r"branch\b",
        r"customer care", r"call centre", r"call center", r"telephone", r"tel:\b", r"fax:\b",
        r"email", r"www\.", r"http", r"terms and conditions", r"privacy policy", r"powered by",
        r"vat", r"registration number", r"pin:\b", r"for enquiries", r"enquiries",
    ]
    discard_re = re.compile('|'.join(discard_phrases), re.IGNORECASE)

    for ln in lines:
        if discard_re.search(ln):
            continue
        if len(ln) < 4:
            continue
        cleaned_lines.append(ln)

    tx_indicator_re = re.compile(r'Ksh\s*[0-9]|balance|confirmed|receipt|paid in|withdrawn|paid to|credited|received', re.IGNORECASE)
    filtered_lines = [ln for ln in cleaned_lines if tx_indicator_re.search(ln)]
    use_lines = filtered_lines if filtered_lines else cleaned_lines

    blob = ' '.join(use_lines)
    blob = re.sub(r"\s+", ' ', blob).strip()

    split_points = [r'(?<=Confirmed)', r'(?=Ksh\s*[0-9])', r'(?=Balance\s+is)', r'(?<=balance)']
    split_regex = re.compile('|'.join(split_points), re.IGNORECASE)
    parts = [p.strip(" .,-") for p in split_regex.split(blob) if p and p.strip()]

    tx_like = []
    amt_re = re.compile(r'Ksh\s*[0-9][0-9,]*(?:\.\d+)?', re.IGNORECASE)
    balance_re = re.compile(r'balance\s*(?:is)?\s*Ksh\s*[0-9][0-9,]*(?:\.\d+)?', re.IGNORECASE)
    for p in parts:
        if amt_re.search(p):
            surrounding = p
            if not balance_re.search(p):
                m = balance_re.search(blob)
                if m:
                    surrounding = f"{p} {m.group(0)}"
            tx_like.append(surrounding.strip())

    if not tx_like:
        return blob

    standardized = '\n\n'.join(tx_like)
    return standardized


def _format_table_preview_from_table(table, max_rows=10):
    """Format a single extracted table into a readable plain-text table preview."""
    if not table or not isinstance(table, (list, tuple)):
        return ''

    rows = [[(str(cell).strip() if cell is not None else '') for cell in row] for row in table]
    if not rows:
        return ''

    header = rows[0]
    data_rows = rows[1:1 + max_rows]

    num_cols = max(len(r) for r in rows)
    widths = [0] * num_cols
    for r in [header] + data_rows:
        for i in range(num_cols):
            cell = r[i] if i < len(r) else ''
            widths[i] = max(widths[i], len(cell))

    def fmt_row(r):
        cells = [(r[i] if i < len(r) else '').ljust(widths[i]) for i in range(num_cols)]
        return ' | '.join(cells).rstrip()

    lines = []
    if header:
        lines.append(fmt_row(header))
        lines.append('-+-'.join('-' * w for w in widths))

    for r in data_rows:
        lines.append(fmt_row(r))

    if len(rows) > 1 + max_rows:
        lines.append(f"... ({len(rows) - 1 - max_rows} more rows)")

    return '\n'.join(lines)


def extract_text_from_pdf_bytes(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return ''
    return _extract_text_from_pdf_bytes(pdf_bytes)


def extract_mpesa_statement_pdf(pdf_bytes):
    """
    Extract transactions from a structured M-PESA statement PDF (table format) using Camelot.
    Returns list of Transaction objects.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return []
    
    temp_filename = f"temp_statement_{os.getpid()}.pdf"
    try:
        with open(temp_filename, "wb") as f:
            f.write(pdf_bytes)
        
        tables = camelot.read_pdf(temp_filename, pages='all', flavor='stream')
    except Exception as e:
        print(f"Camelot extraction failed: {e}")
        return []
    finally:
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception:
                pass

    if not tables:
        return []

    transactions = []
    current_tx = None

    for table in tables:
        rows = table.df.values.tolist()
        header_idx, col_indices = _find_header_and_col_indices(rows)
        if header_idx is None or col_indices is None:
            continue

        for row in rows[header_idx + 1:]:
            if len(row) <= max(col_indices.values()):
                continue

            receipt_no = row[col_indices['receipt']].strip() if col_indices['receipt'] is not None else ''
            details = row[col_indices['details']].strip() if col_indices['details'] is not None else ''
            paid_in_str = row[col_indices['paid_in']].strip() if col_indices['paid_in'] is not None else ''
            withdrawn_str = row[col_indices['withdrawn']].strip() if col_indices['withdrawn'] is not None else ''
            balance_str = row[col_indices['balance']].strip() if col_indices['balance'] is not None else ''

            if receipt_no and details:
                amount = 0.0
                is_inflow = False

                if paid_in_str and paid_in_str != '-':
                    try:
                        amount = _parse_amount(paid_in_str)
                        is_inflow = True
                    except ValueError:
                        pass
                
                if amount == 0.0 and withdrawn_str and withdrawn_str != '-':
                    try:
                        amount = abs(_parse_amount(withdrawn_str))
                        is_inflow = False
                    except ValueError:
                        pass

                try:
                    balance = _parse_amount(balance_str)
                except ValueError:
                    balance = 0.0

                if is_inflow:
                    category = 'inflow'
                else:
                    lower_desc = details.lower()
                    if re.search(r'\b(airtime|bundle|data|sms)\b', lower_desc):
                        category = 'airtime'
                    elif re.search(r'\b(sent|paid|paid to|transfer|paybill|till|deposit|withdrawal|withdraw)\b', lower_desc):
                        category = 'expense'
                    else:
                        category = 'other'

                current_tx = Transaction(
                    amount=amount,
                    description=details,
                    category=category,
                    balance=balance,
                    timestamp=datetime.now(),
                    transaction_code=receipt_no,
                )
                current_tx.candidate_text = details
                transactions.append(current_tx)

            elif not receipt_no and details and current_tx:
                current_tx.description = f"{current_tx.description} {details}"
                current_tx.candidate_text = current_tx.description
            elif not details:
                current_tx = None

    return transactions


def extract_mpesa_pdf_candidates(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return {
            'raw_text': '',
            'candidates': [],
            'parseable': [],
        }

    raw_text = _extract_text_from_pdf_bytes(pdf_bytes)
    transactions = extract_mpesa_statement_pdf(pdf_bytes)

    candidates = []
    parseable = []
    for tx in transactions:
        candidates.append(tx.candidate_text)
        parseable.append({
            'text': tx.candidate_text,
            'parseable': True,
            'description': tx.description,
            'amount': tx.amount,
        })

    table_preview = ''
    temp_filename = f"temp_statement_{os.getpid()}.pdf"
    try:
        with open(temp_filename, "wb") as f:
            f.write(pdf_bytes)
        tables = camelot.read_pdf(temp_filename, pages='1', flavor='stream')
        if tables:
            transaction_table = None
            for table in tables:
                rows = table.df.values.tolist()
                header_idx, col_indices = _find_header_and_col_indices(rows)
                if header_idx is not None:
                    transaction_table = rows
                    break
            if transaction_table:
                table_preview = _format_table_preview_from_table(transaction_table, max_rows=12)
    except Exception:
        pass
    finally:
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception:
                pass

    return {
        'raw_text': raw_text,
        'table_preview': table_preview,
        'page_image_preview': '',
        'standardized_text': '',
        'ocr_text': '',
        'candidates': candidates,
        'parseable': parseable,
        'has_table': bool(table_preview),
        'has_image_preview': False,
        'has_ocr': False,
    }


def parse_mpesa_pdf_all(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return []

    transactions = extract_mpesa_statement_pdf(pdf_bytes)
    if transactions:
        return transactions

    try:
        text = _extract_text_from_pdf_bytes(pdf_bytes)
    except Exception:
        return []

    if not text:
        return []

    standardized = _standardize_pdf_preview_text(text)
    candidates = _find_mpesa_sms_candidates(standardized)
    transactions = []
    for candidate in candidates:
        transaction = parse_mpesa_sms(candidate)
        if transaction is not None:
            transaction.candidate_text = candidate
            transactions.append(transaction)

    return transactions


def parse_mpesa_pdf(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return None

    transactions = extract_mpesa_statement_pdf(pdf_bytes)
    if transactions:
        return transactions[0]

    try:
        text = _extract_text_from_pdf_bytes(pdf_bytes)
    except Exception:
        return None

    if not text:
        return None

    standardized = _standardize_pdf_preview_text(text)
    candidates = _find_mpesa_sms_candidates(standardized)
    for candidate in candidates:
        transaction = parse_mpesa_sms(candidate)
        if transaction is not None:
            return transaction

    return None


def categorize_transaction_kenya(transaction):
    if transaction is None:
        return None

    description = (transaction.description or '').lower()
    amount = float(transaction.amount)

    informal_tax_keywords = [
        'funeral', 'wedding', 'harambee', 'medical', 'hospital', 'clinic'
    ]
    chama_keywords = ['chama', 'group', 'contribution']
    food_keywords = ['food', 'mama mboga', 'grocery', 'supermarket', 'restaurant', 'eating', 'cooking']
    transport_keywords = ['matatu', 'uber', 'bolt', 'boda', 'taxi', 'fare', 'transport']
    utilities_keywords = ['rent', 'water', 'electricity', 'bills', 'power', 'phone', 'wifi']
    entertainment_keywords = ['cinema', 'movie', 'club', 'bar', 'beer', 'fun']
    airtime_keywords = ['airtime', 'safaricom', 'telkom', 'airtel', 'mpesa']

    def contains_any(text, keywords):
        return any(keyword in text for keyword in keywords)

    def looks_like_name(text):
        common_names = {
            'jane', 'john', 'mary', 'wanjiru', 'wambui', 'naomi', 'edith', 'mercy',
            'joseph', 'samuel', 'victor', 'grace', 'faith', 'chebet', 'idah', 'paul',
            'george', 'julia', 'david', 'joyce', 'cyrus', 'alice', 'diana'
        }
        words = re.findall(r"[a-zA-Z']+", text)
        return any(word.lower() in common_names for word in words)

    new_category = 'Other'

    # Transfer-specific refinements
    if transaction.category == 'transfer':
        if contains_any(description, informal_tax_keywords):
            new_category = 'Informal Tax'
        elif contains_any(description, chama_keywords):
            new_category = 'Chama'
        elif 5000 <= amount <= 20000 and looks_like_name(description):
            new_category = 'Family Support'
        else:
            new_category = 'Other'

    # Expense-specific refinements
    elif transaction.category == 'expense':
        if contains_any(description, food_keywords):
            new_category = 'Food'
        elif contains_any(description, transport_keywords):
            new_category = 'Transport'
        elif contains_any(description, utilities_keywords):
            new_category = 'Utilities'
        elif contains_any(description, entertainment_keywords):
            new_category = 'Entertainment'
        else:
            new_category = 'Other'

    # Airtime stays Airtime, with extra Kenyan telcom keyword support
    elif transaction.category == 'airtime':
        if contains_any(description, airtime_keywords):
            new_category = 'Airtime'
        else:
            new_category = 'Airtime'

    else:
        new_category = transaction.category.title() if transaction.category else 'Other'

    transaction.category = new_category
    return new_category


def categorize_transaction_with_questions(transaction):
    """
    Use hierarchical questions instead of guessing.
    Returns: (category, sub_type, needs_user_input, question_state)
    """
    if transaction is None:
        return (None, None, False, None)

    description = (getattr(transaction, 'description', '') or '').lower()

    obvious_keywords = {
        'airtime': 'Airtime',
        'safaricom': 'Airtime',
        'telkom': 'Airtime',
        'airtel': 'Airtime',
        'uber': 'Transport',
        'bolt': 'Transport',
        'matatu': 'Transport',
        'boda': 'Transport',
        'taxi': 'Transport',
        'nakumatt': 'Food',
        'supermarket': 'Food',
        'restaurant': 'Food',
        'mama mboga': 'Food',
        'kplc': 'Utilities',
        'electricity': 'Utilities',
        'water': 'Utilities',
        'wifi': 'Utilities',
        'internet': 'Utilities',
    }

    for keyword, category in obvious_keywords.items():
        if keyword in description:
            return (category, None, False, None)

    first_question = get_disambiguation_questions(transaction)
    return (None, None, True, first_question)


def continue_categorization_with_questions(previous_level, user_answer):
    """
    Advance the question-based categorization flow.
    Returns: (category, sub_type, needs_user_input, question_state)
    """
    result = process_answer(previous_level, user_answer)
    if result is None:
        return (None, None, False, None)

    if isinstance(result, dict) and 'category' in result and 'sub_type' in result:
        return (result['category'], result['sub_type'], False, None)

    return (None, None, True, result)


def categorize_transaction_flow(transaction, previous_level=None, user_answer=None):
    """
    Single-entry categorization flow.
    - If no previous question state is provided, choose an obvious category or ask the first question.
    - If a previous question level and answer are provided, advance the flow.

    Returns: (category, sub_type, needs_user_input, question_state)
    """
    if transaction is None:
        return (None, None, False, None)

    if previous_level is not None and user_answer is not None:
        return continue_categorization_with_questions(previous_level, user_answer)

    return categorize_transaction_with_questions(transaction)

