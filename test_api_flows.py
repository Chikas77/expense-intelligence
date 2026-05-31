import io
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from app import app
from parser import Transaction


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_upload_mpesa_direct_analysis(self):
        payload = {
            'mpesa_messages': 'You bought Ksh 200 airtime. Your M-Pesa balance is Ksh 24,800\nPaid Ksh 150 to matatu. Your M-Pesa balance is Ksh 24,650',
            'salary': '50000',
            'salary_day': '25',
        }
        response = self.client.post('/upload-mpesa', data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Your M-Pesa Analysis', response.data)
        self.assertIn(b'Spending by Category', response.data)

    def test_upload_mpesa_uncertain_results_in_review_form(self):
        payload = {
            'mpesa_messages': 'You have sent Ksh 5,000 to JANE. Your M-Pesa balance is Ksh 24,800',
            'salary': '50000',
            'salary_day': '25',
        }
        response = self.client.post('/upload-mpesa', data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Confirm Transaction Categories', response.data)
        self.assertIn(b'transaction_0_amount', response.data)

    @patch('app.extract_mpesa_pdf_candidates')
    def test_preview_pdf_endpoint_returns_candidates(self, mock_extract):
        mock_extract.return_value = {
            'raw_text': 'Sample M-Pesa text',
            'candidates': ['Sent Ksh 500 to JOHN. Balance Ksh 10,000'],
            'parseable': [{'text': 'Sent Ksh 500 to JOHN. Balance Ksh 10,000', 'parseable': True, 'description': 'Sent to JOHN', 'amount': 500}],
        }
        data = {'pdf_file': (io.BytesIO(b'fakepdf'), 'statement.pdf')}
        response = self.client.post('/preview-pdf', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['raw_text'], 'Sample M-Pesa text')
        self.assertEqual(len(json_data['candidates']), 1)
        self.assertEqual(json_data['candidates'][0]['parseable'], True)

    @patch('app.parse_mpesa_pdf_all')
    def test_import_pdf_statement_endpoint_returns_parsed_transactions(self, mock_parse_all):
        mock_parse_all.return_value = [
            Transaction(amount=500, description='Sent to JOHN', category='transfer', balance=10000, timestamp=datetime.now()),
            Transaction(amount=120, description='Bought airtime', category='airtime', balance=9880, timestamp=datetime.now()),
        ]
        data = {'pdf_file': (io.BytesIO(b'fakepdf'), 'statement.pdf')}
        response = self.client.post('/import-pdf-statement', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(len(json_data['transactions']), 2)
        self.assertIn('Review before finalizing', json_data['message'])

    def test_finalize_pdf_batch_endpoint_returns_summary(self):
        payload = {
            'transactions': [
                {'amount': 500, 'category': 'Transport'},
                {'amount': 120, 'category': 'Airtime'},
                {'amount': 200, 'category': 'Transport'},
            ]
        }
        response = self.client.post('/finalize-pdf-batch', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertIn('summary', json_data)
        self.assertIn('Transport: Ksh 700', json_data['summary'])
        self.assertIn('Airtime: Ksh 120', json_data['summary'])
        self.assertEqual(json_data['total_spending'], 'Ksh 820')

    @patch('parser._extract_text_from_pdf_bytes')
    def test_parse_mpesa_pdf_all_returns_transactions(self, mock_extract):
        mock_extract.return_value = 'Sent Ksh 500 to JOHN. Your M-Pesa balance is Ksh 10,000\nYou bought Ksh 300 airtime. Your M-Pesa balance is Ksh 9,700'
        from parser import parse_mpesa_pdf_all

        transactions = parse_mpesa_pdf_all(b'fakepdf')
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].amount, 500)
        self.assertEqual(transactions[1].category, 'airtime')


if __name__ == '__main__':
    unittest.main()
