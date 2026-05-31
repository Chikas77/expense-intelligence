"""
Test the complete categorization flow:
Parse transaction → Ask question → Get answer → Final category
"""

import unittest
from parser import parse_mpesa_sms, categorize_transaction_kenya, categorize_transaction_flow
from categorization_questions import get_disambiguation_questions, process_answer


def run_question_flow(transaction, answers):
    question = get_disambiguation_questions(transaction)
    for answer in answers:
        question_level = question.get('question_level')
        if not question_level:
            raise ValueError('Missing question level for current question')

        result = process_answer(question_level, answer)
        if result is None:
            raise AssertionError(f'No result for question_level={question_level}, answer={answer}')

        if 'category' in result:
            return result

        question = result

    raise AssertionError('Flow did not complete with a final category')


class CompleteFlowTest(unittest.TestCase):
    def test_obvious_airtime(self):
        message = 'You bought Ksh 200 airtime. Your M-Pesa balance is Ksh 24,800'
        transaction = parse_mpesa_sms(message)

        self.assertIsNotNone(transaction, 'Transaction should parse successfully')
        self.assertEqual(transaction.category, 'airtime')

        auto_category = categorize_transaction_kenya(transaction)
        self.assertEqual(auto_category.lower(), 'airtime')

    def test_uncertain_person_transfer(self):
        message = 'You have sent Ksh 5,000 to JANE WANJIRU. Your M-Pesa balance is Ksh 25,000'
        transaction = parse_mpesa_sms(message)

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.category, 'transfer')

        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        self.assertTrue(needs_input)
        self.assertEqual(question['question_level'], '1')

        result = run_question_flow(transaction, ['A', 'A1', 'A1-i'])
        self.assertEqual(result['category'], 'Family Support')
        self.assertEqual(result['sub_type'], 'Regular monthly support')
        self.assertEqual(result['code'], 'A1-i')
        self.assertEqual(result['confidence'], 1.0)

    def test_wedding_contribution(self):
        message = 'You sent Ksh 5,000 for WEDDING HARAMBEE. Balance Ksh 30,000'
        transaction = parse_mpesa_sms(message)

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.category, 'transfer')

        result = run_question_flow(transaction, ['A', 'A1', 'A1-iv'])
        self.assertEqual(result['category'], 'Informal Tax')
        self.assertEqual(result['code'], 'A1-iv')

    def test_chama_contribution(self):
        message = 'Sent Ksh 2,000 to RUTH. Balance Ksh 28,000'
        transaction = parse_mpesa_sms(message)

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.category, 'transfer')

        result = run_question_flow(transaction, ['A', 'A2', 'A2-i'])
        self.assertEqual(result['category'], 'Chama')
        self.assertEqual(result['code'], 'A2-i')

    def test_unsure_branch(self):
        message = 'You have sent Ksh 3,500. Your M-Pesa balance is Ksh 22,000'
        transaction = parse_mpesa_sms(message)

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.category, 'transfer')

        result = run_question_flow(transaction, ['C', 'C1', 'B4'])
        self.assertEqual(result['category'], 'Entertainment')
        self.assertEqual(result['sub_type'], 'Entertainment service or product')
        self.assertEqual(result['code'], 'B4')


if __name__ == '__main__':
    unittest.main()
