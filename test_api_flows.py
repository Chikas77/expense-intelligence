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

    def test_upload_file_size_exceeds_limit(self):
        large_bytes = b'0' * (11 * 1024 * 1024)
        data = {'pdf_file': (io.BytesIO(large_bytes), 'large_statement.pdf')}
        response = self.client.post('/preview-pdf', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 413)
        json_data = response.get_json()
        self.assertFalse(json_data['success'])
        self.assertIn('File size exceeds the 10MB upload limit', json_data['error'])

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

    def test_parse_mpesa_messages_handles_messy_multi_message_paste(self):
        from parser import parse_mpesa_messages

        sample = (
            'UF6AR6NMGC Confirmed. Ksh50.00 paid to SIMON KIHARA NJOROGE. on 6/6/26 at 12:19 PM.New M-PESA balance is Ksh546.37. '
            'Transaction cost, Ksh0.00. Amount you can transact within the day is 497,560.00. '
            'Download My OneApp on https://saf.cx/lPKcC '
            '\n'
            'UF6AR6NPU4 Confirmed. Ksh160.00 sent to Equity Paybill Account for account 487321 on 6/6/26 at 12:12 PM '
            'New M-PESA balance is Ksh596.37. Transaction cost, Ksh5.00.Amount you can transact within the day is 497,610.00. '
            'Download My OneApp on https://saf.cx/kWQpy'
        )

        transactions = parse_mpesa_messages(sample)
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].transaction_code, 'UF6AR6NMGC')
        self.assertAlmostEqual(transactions[0].amount, 50.00)
        self.assertAlmostEqual(transactions[0].balance, 546.37)
        self.assertIn('SIMON KIHARA NJOROGE', transactions[0].description)

        self.assertEqual(transactions[1].transaction_code, 'UF6AR6NPU4')
        self.assertAlmostEqual(transactions[1].amount, 160.00)
        self.assertAlmostEqual(transactions[1].balance, 596.37)
        self.assertIn('Equity Paybill', transactions[1].description)

    def test_parse_mpesa_messages_handles_lowercase_confirmed_and_new_balance(self):
        from parser import parse_mpesa_messages

        sample = (
            'UF1AR625M4 confirmed.You bought Ksh110.00 of airtime for 0790777315 on 1/6/26 at 9:45 AM.New  balance is Ksh4,983.37. '
            'Transaction cost, Ksh0.00. Amount you can transact within the day is 499,875.00.You can now access M-PESA via *334#'
        )

        transactions = parse_mpesa_messages(sample)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].transaction_code, 'UF1AR625M4')
        self.assertAlmostEqual(transactions[0].amount, 110.00)
        self.assertAlmostEqual(transactions[0].balance, 4983.37)
        self.assertEqual(transactions[0].category, 'airtime')
        self.assertIn('airtime', transactions[0].description.lower())

    def test_parse_mpesa_messages_endpoint_returns_multiple_transactions(self):
        payload = {
            'mpesa_text': (
                'UF6AR6NMGC Confirmed. Ksh50.00 paid to SIMON KIHARA NJOROGE. on 6/6/26 at 12:19 PM.New M-PESA balance is Ksh546.37. '
                'Transaction cost, Ksh0.00. Amount you can transact within the day is 497,560.00. '
                'Download My OneApp on https://saf.cx/lPKcUF6AR6NPU4 Confirmed. Ksh160.00 sent to Equity Paybill Account for account 487321 on 6/6/26 at 12:12 PM '
                'New M-PESA balance is Ksh596.37. Transaction cost, Ksh5.00.Amount you can transact within the day is 497,610.00. '
                'Download My OneApp on https://saf.cx/kWQpyUF6AR6NHMJ Confirmed. Ksh140.00 sent to JOSEPH  NYAMBUTU on 6/6/26 at 11:48 AM. '
                'New M-PESA balance is Ksh761.37. Transaction cost, Ksh7.00. Amount you can transact within the day is 497,770.00. '
                'Download My OneApp on https://saf.cx/kWQpy'
            )
        }
        response = self.client.post('/parse-mpesa-messages', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(len(json_data['transactions']), 3)
        self.assertEqual(json_data['transactions'][0]['transaction_code'], 'UF6AR6NMGC')
        self.assertEqual(json_data['transactions'][1]['amount'], 160.0)
        self.assertIn('Equity Paybill', json_data['transactions'][1]['description'])
        self.assertEqual(json_data['transactions'][2]['transaction_code'], 'UF6AR6NHMJ')
        self.assertEqual(json_data['transactions'][2]['amount'], 140.0)
        self.assertIn('JOSEPH', json_data['transactions'][2]['description'])

    @patch('parser.pypdf.PdfReader')
    def test_preview_pdf_password_required(self, mock_pdf_reader_cls):
        mock_reader = mock_pdf_reader_cls.return_value
        mock_reader.is_encrypted = True
        
        data = {'pdf_file': (io.BytesIO(b'encryptedpdf'), 'statement.pdf')}
        response = self.client.post('/preview-pdf', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 401)
        json_data = response.get_json()
        self.assertEqual(json_data['error'], 'password_required')

    @patch('parser.pypdf.PdfReader')
    def test_preview_pdf_invalid_password(self, mock_pdf_reader_cls):
        mock_reader = mock_pdf_reader_cls.return_value
        mock_reader.is_encrypted = True
        mock_reader.decrypt.return_value = 0
        
        data = {
            'pdf_file': (io.BytesIO(b'encryptedpdf'), 'statement.pdf'),
            'password': 'wrong_password'
        }
        response = self.client.post('/preview-pdf', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 401)
        json_data = response.get_json()
        self.assertEqual(json_data['error'], 'invalid_password')
        mock_reader.decrypt.assert_called_with('wrong_password')

    @patch('parser.pypdf.PdfReader')
    def test_import_pdf_password_required(self, mock_pdf_reader_cls):
        mock_reader = mock_pdf_reader_cls.return_value
        mock_reader.is_encrypted = True
        
        data = {'pdf_file': (io.BytesIO(b'encryptedpdf'), 'statement.pdf')}
        response = self.client.post('/import-pdf-statement', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 401)
        json_data = response.get_json()
        self.assertEqual(json_data['error'], 'password_required')

    @patch('parser.pypdf.PdfReader')
    def test_import_pdf_invalid_password(self, mock_pdf_reader_cls):
        mock_reader = mock_pdf_reader_cls.return_value
        mock_reader.is_encrypted = True
        mock_reader.decrypt.return_value = 0
        
        data = {
            'pdf_file': (io.BytesIO(b'encryptedpdf'), 'statement.pdf'),
            'password': 'wrong_password'
        }
        response = self.client.post('/import-pdf-statement', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 401)
        json_data = response.get_json()
        self.assertEqual(json_data['error'], 'invalid_password')
        mock_reader.decrypt.assert_called_with('wrong_password')


if __name__ == '__main__':
    unittest.main()
