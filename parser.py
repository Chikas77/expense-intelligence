import io
import re
from datetime import datetime
from categorization_questions import get_disambiguation_questions, process_answer

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PIL import Image
except ImportError:
    Image = None

class Transaction:
    def __init__(self, amount: float, description: str, category: str, balance: float, timestamp: datetime):
        self.amount = amount
        self.description = description
        self.category = category
        self.balance = balance
        self.timestamp = timestamp

    def __repr__(self):
        return (
            f"Transaction(amount={self.amount}, description={self.description!r}, "
            f"category={self.category!r}, balance={self.balance}, timestamp={self.timestamp!r})"
        )


def _parse_amount(value: str) -> float:
    return float(value.replace(',', ''))


def parse_mpesa_sms(message: str):
    if not isinstance(message, str):
        return None

    balance_pattern = re.compile(
        r'(?:your\s+(?:m[- ]?pesa|mpesa)\s+balance\s+is|balance)\s+Ksh\s*([0-9][0-9,]*(?:\.\d+)?)',
        re.IGNORECASE,
    )
    amount_pattern = re.compile(r'Ksh\s*([0-9][0-9,]*(?:\.\d+)?)', re.IGNORECASE)

    balance_match = balance_pattern.search(message)
    if not balance_match:
        return None

    amount_match = amount_pattern.search(message)
    if not amount_match:
        return None

    amount = _parse_amount(amount_match.group(1))
    balance = _parse_amount(balance_match.group(1))

    # Remove the balance phrase and the first Ksh amount to isolate description
    description_text = balance_pattern.sub('', message).strip()
    description_text = amount_pattern.sub('', description_text, count=1).strip()
    description_text = re.sub(
        r'^(you\s+have|you\s+bought|you\s+paid|you)\s*', '',
        description_text,
        flags=re.IGNORECASE,
    ).strip()
    description_text = description_text.strip(' .')
    description_text = re.sub(r'\s+', ' ', description_text)

    if not description_text:
        return None

    lower_desc = description_text.lower()
    if 'airtime' in lower_desc:
        category = 'airtime'
    elif 'sent' in lower_desc or 'transfer' in lower_desc:
        category = 'transfer'
    elif 'paid' in lower_desc or 'bought' in lower_desc:
        category = 'expense'
    else:
        category = 'other'

    transaction = Transaction(
        amount=amount,
        description=description_text,
        category=category,
        balance=balance,
        timestamp=datetime.now(),
    )
    return transaction


def _extract_text_from_pdf_bytes(pdf_bytes):
    if pdfplumber is None:
        raise RuntimeError('pdfplumber is required to extract text from PDF files')

    text_pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ''
            if page_text.strip():
                text_pages.append(page_text)
                continue

            if pytesseract is None:
                continue

            page_image = page.to_image(resolution=300).original
            if Image is not None and isinstance(page_image, Image.Image):
                ocr_text = pytesseract.image_to_string(page_image)
                text_pages.append(ocr_text)

    return '\n'.join(text_pages).strip()


def _find_mpesa_sms_candidates(text):
    if not text:
        return []

    pattern = re.compile(
        r'([^\n]*?Ksh\s*[0-9][0-9,]*(?:\.\d+)?[^\n]*?(?:balance\s+is|new\s+balance|balance)\s*Ksh\s*[0-9][0-9,]*(?:\.\d+)?[^\n]*)',
        re.IGNORECASE,
    )
    return [match.group(1).strip() for match in pattern.finditer(text)]


def extract_text_from_pdf_bytes(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return ''
    return _extract_text_from_pdf_bytes(pdf_bytes)


def extract_mpesa_pdf_candidates(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return {
            'raw_text': '',
            'candidates': [],
            'parseable': [],
        }

    text = _extract_text_from_pdf_bytes(pdf_bytes)
    if not text:
        return {
            'raw_text': '',
            'candidates': [],
            'parseable': [],
        }

    candidates = _find_mpesa_sms_candidates(text)
    parseable = []
    for candidate in candidates:
        parsed = parse_mpesa_sms(candidate)
        parseable.append({
            'text': candidate,
            'parseable': parsed is not None,
            'description': parsed.description if parsed is not None else None,
            'amount': parsed.amount if parsed is not None else None,
        })

    return {
        'raw_text': text,
        'candidates': candidates,
        'parseable': parseable,
    }


def parse_mpesa_pdf_all(pdf_bytes):
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return []

    try:
        text = _extract_text_from_pdf_bytes(pdf_bytes)
    except RuntimeError:
        return []

    if not text:
        return []

    candidates = _find_mpesa_sms_candidates(text)
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

    try:
        text = _extract_text_from_pdf_bytes(pdf_bytes)
    except RuntimeError:
        return None

    if not text:
        return None

    candidates = _find_mpesa_sms_candidates(text)
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

