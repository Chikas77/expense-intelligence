from dataclasses import dataclass


@dataclass
class CategorizationQuestion:
    code: str
    level: int
    question: str
    options: list

    def to_dict(self):
        return {
            'question_level': self.code,
            'level': self.level,
            'question': self.question,
            'options': self.options,
        }


QUESTION_NODES = {
    '1': CategorizationQuestion(
        code='1',
        level=1,
        question='Is this transaction money going TO a person or FOR a service/product?',
        options=[
            {'code': 'A', 'label': 'I sent/gave money to a person'},
            {'code': 'B', 'label': 'I paid for a service or product'},
            {'code': 'C', 'label': "I'm unsure"},
        ],
    ),
    '2A': CategorizationQuestion(
        code='2A',
        level=2,
        question='What is your relationship to this person?',
        options=[
            {'code': 'A1', 'label': 'Family member (parent, sibling, aunt, uncle, cousin, relative)'},
            {'code': 'A2', 'label': 'Friend or colleague'},
            {'code': 'A3', 'label': "Unknown person - I don't know them well"},
            {'code': 'A4', 'label': 'Actually, this is a business or service provider'},
        ],
    ),
    '2B': CategorizationQuestion(
        code='2B',
        level=2,
        question='What type of service or product?',
        options=[
            {'code': 'B1', 'label': 'Food (groceries, supermarket, restaurant, mama mboga, food supplier)'},
            {'code': 'B2', 'label': 'Transport (matatu, uber, bolt, boda, taxi, fuel, parking, toll)'},
            {'code': 'B3', 'label': 'Utilities (rent, water, electricity, internet, phone bill, WiFi)'},
            {'code': 'B4', 'label': 'Entertainment (cinema, movie, club, bar, event, concert, drinking)'},
            {'code': 'B5', 'label': 'Airtime or mobile credit (Safaricom airtime, data bundle, telecom credit)'},
            {'code': 'B6', 'label': 'Insurance or loan repayment (bank loan, insurance premium)'},
            {'code': 'B7', 'label': 'Business expense (if for work or business purposes)'},
            {'code': 'B8', 'label': 'Healthcare (clinic, hospital, pharmacy, medical service)'},
            {'code': 'B9', 'label': 'Other service or product'},
            {'code': 'B10', 'label': 'Inventories and Supplies (soaps, deodorants, books, phone, furniture, assets)'},
        ],
    ),
    '3': CategorizationQuestion(
        code='3',
        level=3,
        question='Is the money going OUT to someone/something, or is it staying in M-Pesa?',
        options=[
            {'code': 'C1', 'label': 'Going OUT to someone/something'},
            {'code': 'C2', 'label': 'Staying in M-Pesa'},
        ],
    ),
    'C1': CategorizationQuestion(
        code='C1',
        level=4,
        question='Is this payment going to a person or to a business/service provider?',
        options=[
            {'code': 'A', 'label': 'Person'},
            {'code': 'B', 'label': 'Business or service provider'},
        ],
    ),
    '3A': CategorizationQuestion(
        code='3A',
        level=3,
        question='What type of family support?',
        options=[
            {'code': 'A1-i', 'label': 'Regular monthly support (allowance, living expenses)'},
            {'code': 'A1-ii', 'label': 'One-time emergency help (medical, job loss, crisis)'},
            {'code': 'A1-iii', 'label': 'School fees or education expense'},
            {'code': 'A1-iv', 'label': "Wedding contribution or harambee (their wedding)"},
            {'code': 'A1-v', 'label': 'Funeral contribution or harambee (death in family)'},
            {'code': 'A1-vi', 'label': "Loan I'm giving to family member"},
            {'code': 'A1-vii', 'label': "Loan repayment (they lent me money)"},
            {'code': 'A1-viii', 'label': 'Other family-related (birthday gift, relocation, other)'},
        ],
    ),
    '3B': CategorizationQuestion(
        code='3B',
        level=3,
        question='Why are you sending money to this friend?',
        options=[
            {'code': 'A2-i', 'label': 'Group contribution (chama, merry-go-round, burial society, savings circle)'},
            {'code': 'A2-ii', 'label': "Wedding contribution or harambee (friend's wedding)"},
            {'code': 'A2-iii', 'label': "Funeral contribution or harambee (friend's death)"},
            {'code': 'A2-iv', 'label': "Medical emergency harambee (friend's medical crisis)"},
            {'code': 'A2-v', 'label': "Loan I'm giving to friend"},
            {'code': 'A2-vi', 'label': 'Loan repayment (friend lent me money)'},
            {'code': 'A2-vii', 'label': 'Food supplier (mama mboga, restaurant owner, food business)'},
            {'code': 'A2-viii', 'label': 'Transport provider (matatu conductor, boda driver, taxi, transport service)'},
            {'code': 'A2-ix', 'label': 'Other payment to friend'},
        ],
    ),
    '3C': CategorizationQuestion(
        code='3C',
        level=3,
        question='Tell me more about this payment so I can classify it.',
        options=[
            {'code': 'A3-i', 'label': 'Regular monthly support (allowance, living expenses)'},
            {'code': 'A3-ii', 'label': 'One-time emergency help (medical, job loss, crisis)'},
            {'code': 'A3-iii', 'label': 'School fees or education expense'},
            {'code': 'A3-iv', 'label': "Wedding contribution or harambee (their wedding)"},
            {'code': 'A3-v', 'label': 'Funeral contribution or harambee (death in family)'},
            {'code': 'A3-vi', 'label': "Loan I'm giving to family member"},
            {'code': 'A3-vii', 'label': "Loan repayment (they lent me money)"},
            {'code': 'A3-viii', 'label': 'Other family-related (birthday gift, relocation, other)'},
            {'code': 'A3-ix', 'label': 'Group contribution (chama, merry-go-round, burial society, savings circle)'},
            {'code': 'A3-x', 'label': "Wedding contribution or harambee (friend's wedding)"},
            {'code': 'A3-xi', 'label': "Funeral contribution or harambee (friend's death)"},
            {'code': 'A3-xii', 'label': "Medical emergency harambee (friend's medical crisis)"},
            {'code': 'A3-xiii', 'label': "Loan I'm giving to friend"},
            {'code': 'A3-xiv', 'label': 'Loan repayment (friend lent me money)'},
            {'code': 'A3-xv', 'label': 'Food supplier (mama mboga, restaurant owner, food business)'},
            {'code': 'A3-xvi', 'label': 'Transport provider (matatu conductor, boda driver, taxi, transport service)'},
            {'code': 'A3-xvii', 'label': 'Other payment to friend or unknown person'},
        ],
    ),
}

FINAL_CATEGORY_MAP = {
    'A1-i': {'category': 'Family Support', 'sub_type': 'Regular monthly support', 'code': 'A1-i'},
    'A1-ii': {'category': 'Informal Tax', 'sub_type': 'One-time emergency help', 'code': 'A1-ii'},
    'A1-iii': {'category': 'Family Support', 'sub_type': 'School fees or education expense', 'code': 'A1-iii'},
    'A1-iv': {'category': 'Informal Tax', 'sub_type': 'Wedding contribution or harambee', 'code': 'A1-iv'},
    'A1-v': {'category': 'Informal Tax', 'sub_type': 'Funeral contribution or harambee', 'code': 'A1-v'},
    'A1-vi': {'category': 'Personal-Loan', 'sub_type': "Loan I'm giving to family member", 'code': 'A1-vi'},
    'A1-vii': {'category': 'Personal-Loan', 'sub_type': 'Loan repayment', 'code': 'A1-vii'},
    'A1-viii': {'category': 'Family Support', 'sub_type': 'Other family-related', 'code': 'A1-viii'},
    'A2-i': {'category': 'Chama', 'sub_type': 'Group contribution', 'code': 'A2-i'},
    'A2-ii': {'category': 'Informal Tax', 'sub_type': 'Wedding contribution or harambee', 'code': 'A2-ii'},
    'A2-iii': {'category': 'Informal Tax', 'sub_type': 'Funeral contribution or harambee', 'code': 'A2-iii'},
    'A2-iv': {'category': 'Informal Tax', 'sub_type': 'Medical emergency harambee', 'code': 'A2-iv'},
    'A2-v': {'category': 'Personal-Loan', 'sub_type': "Loan I'm giving to friend", 'code': 'A2-v'},
    'A2-vi': {'category': 'Personal-Loan', 'sub_type': 'Loan repayment', 'code': 'A2-vi'},
    'A2-vii': {'category': 'Food', 'sub_type': 'Food supplier', 'code': 'A2-vii'},
    'A2-viii': {'category': 'Transport', 'sub_type': 'Transport provider', 'code': 'A2-viii'},
    'A2-ix': {'category': 'Other', 'sub_type': 'Other payment to friend', 'code': 'A2-ix'},
    'A3-i': {'category': 'Family Support', 'sub_type': 'Regular monthly support', 'code': 'A3-i'},
    'A3-ii': {'category': 'Informal Tax', 'sub_type': 'One-time emergency help', 'code': 'A3-ii'},
    'A3-iii': {'category': 'Family Support', 'sub_type': 'School fees or education expense', 'code': 'A3-iii'},
    'A3-iv': {'category': 'Informal Tax', 'sub_type': 'Wedding contribution or harambee', 'code': 'A3-iv'},
    'A3-v': {'category': 'Informal Tax', 'sub_type': 'Funeral contribution or harambee', 'code': 'A3-v'},
    'A3-vi': {'category': 'Personal-Loan', 'sub_type': "Loan I'm giving to family member", 'code': 'A3-vi'},
    'A3-vii': {'category': 'Personal-Loan', 'sub_type': 'Loan repayment', 'code': 'A3-vii'},
    'A3-viii': {'category': 'Family Support', 'sub_type': 'Other family-related', 'code': 'A3-viii'},
    'A3-ix': {'category': 'Chama', 'sub_type': 'Group contribution', 'code': 'A3-ix'},
    'A3-x': {'category': 'Informal Tax', 'sub_type': 'Wedding contribution or harambee', 'code': 'A3-x'},
    'A3-xi': {'category': 'Informal Tax', 'sub_type': 'Funeral contribution or harambee', 'code': 'A3-xi'},
    'A3-xii': {'category': 'Informal Tax', 'sub_type': 'Medical emergency harambee', 'code': 'A3-xii'},
    'A3-xiii': {'category': 'Personal-Loan', 'sub_type': "Loan I'm giving to friend", 'code': 'A3-xiii'},
    'A3-xiv': {'category': 'Personal-Loan', 'sub_type': 'Loan repayment', 'code': 'A3-xiv'},
    'A3-xv': {'category': 'Food', 'sub_type': 'Food supplier', 'code': 'A3-xv'},
    'A3-xvi': {'category': 'Transport', 'sub_type': 'Transport provider', 'code': 'A3-xvi'},
    'A3-xvii': {'category': 'Other', 'sub_type': 'Other payment to friend or unknown person', 'code': 'A3-xvii'},
    'B1': {'category': 'Food', 'sub_type': 'Food service or product', 'code': 'B1'},
    'B2': {'category': 'Transport', 'sub_type': 'Transport service or product', 'code': 'B2'},
    'B3': {'category': 'Utilities', 'sub_type': 'Utilities service or product', 'code': 'B3'},
    'B4': {'category': 'Entertainment', 'sub_type': 'Entertainment service or product', 'code': 'B4'},
    'B5': {'category': 'Airtime', 'sub_type': 'Airtime or mobile credit', 'code': 'B5'},
    'B6': {'category': 'Personal-Loan', 'sub_type': 'Insurance or loan repayment', 'code': 'B6'},
    'B7': {'category': 'Business', 'sub_type': 'Business expense', 'code': 'B7'},
    'B8': {'category': 'Informal Tax', 'sub_type': 'Healthcare or medical expense', 'code': 'B8'},
    'B9': {'category': 'Other', 'sub_type': 'Other service or product', 'code': 'B9'},
    'B10': {'category': 'Inventories and Supplies', 'sub_type': 'Inventories and Supplies', 'code': 'B10'},
    'C2': {'category': 'Other', 'sub_type': 'Staying in M-Pesa', 'code': 'C2'},
}

FINAL_CATEGORY_MAP_UPPER = {key.upper(): value for key, value in FINAL_CATEGORY_MAP.items()}

QUESTION_ROUTE = {
    '1': {'A': '2A', 'B': '2B', 'C': '3'},
    '2A': {'A1': '3A', 'A2': '3B', 'A3': '3C', 'A4': '2B'},
    '2B': None,
    '3': {'C1': 'C1', 'C2': 'C2'},
    'C1': {'A': '2A', 'B': '2B'},
    '3A': None,
    '3B': None,
    '3C': None,
}


def _wrap_result(final_data):
    return {
        'category': final_data['category'],
        'sub_type': final_data['sub_type'],
        'code': final_data['code'],
        'confidence': 1.0,
        'requires_user_confirmation': True,
    }


def get_disambiguation_questions(transaction, node_code='1'):
    if node_code in QUESTION_NODES:
        return QUESTION_NODES[node_code].to_dict()
    return QUESTION_NODES['1'].to_dict()


def process_answer(previous_level, user_answer):
    if previous_level is None:
        previous_level = '1'

    normalized_level = str(previous_level).strip().upper()
    choice = str(user_answer).strip().upper()

    if normalized_level not in QUESTION_ROUTE:
        return _resolve_final_choice(choice)

    route = QUESTION_ROUTE[normalized_level]
    if route is None:
        return _resolve_final_choice(choice)

    choice_key = choice.upper()
    next_node = route.get(choice_key) or route.get(choice)
    if next_node is None:
        return _resolve_final_choice(choice)

    if next_node in QUESTION_NODES:
        return QUESTION_NODES[next_node].to_dict()

    return _resolve_final_choice(next_node)


def _resolve_final_choice(choice):
    if choice in FINAL_CATEGORY_MAP:
        return _wrap_result(FINAL_CATEGORY_MAP[choice])
    upper_choice = choice.upper()
    if upper_choice in FINAL_CATEGORY_MAP_UPPER:
        return _wrap_result(FINAL_CATEGORY_MAP_UPPER[upper_choice])
    return None
