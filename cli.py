from parser import parse_mpesa_sms, categorize_transaction_flow


def prompt(message, default=None):
    if default:
        prompt_text = f"{message} [{default}] "
    else:
        prompt_text = f"{message} "
    value = input(prompt_text).strip()
    return value or default


def show_question(question):
    print()
    print(question['question'])
    for option in question['options']:
        print(f"  {option['code']}: {option['label']}")
    print()


def find_valid_answer(question, raw_answer):
    normalized = raw_answer.strip()
    valid_codes = {option['code'] for option in question['options']}
    if normalized in valid_codes:
        return normalized
    return None


def run_cli():
    print('Expense Intelligence CLI - M-Pesa SMS Categorization')
    print('Enter the full text of an M-Pesa SMS to classify. Press Ctrl+C to exit.')

    while True:
        try:
            sms_message = input('\nM-Pesa SMS: ').strip()
        except (KeyboardInterrupt, EOFError):
            print('\nExiting.')
            return

        if not sms_message:
            print('Please enter a non-empty SMS message.')
            continue

        transaction = parse_mpesa_sms(sms_message)
        if transaction is None:
            print('Error: Could not parse the M-Pesa SMS. Make sure it contains Ksh amounts and balance text.')
            continue

        previous_level = None
        category = None
        sub_type = None
        needs_input = False
        question = None

        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)

        while needs_input:
            show_question(question)

            answer = None
            while answer is None:
                raw_answer = input('Choose an option code: ').strip()
                answer = find_valid_answer(question, raw_answer)
                if answer is None:
                    print('Invalid answer. Enter one of:', ', '.join(opt['code'] for opt in question['options']))

            if previous_level is None:
                previous_level = str(question['level'])
            else:
                previous_level = f"{question['level']}{answer[0]}"

            category, sub_type, needs_input, question = categorize_transaction_flow(
                transaction,
                previous_level=previous_level,
                user_answer=answer,
            )

        print('\nFinal categorization:')
        print(f"  Category: {category}")
        if sub_type:
            print(f"  Sub-type: {sub_type}")
        print(f"  Parsed description: {transaction.description}")

        again = prompt('Classify another SMS? (y/n)', 'y')
        if again.lower() not in {'y', 'yes'}:
            print('Goodbye.')
            return


if __name__ == '__main__':
    run_cli()
