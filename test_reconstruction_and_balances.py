import unittest
from datetime import datetime
from parser import get_clean_recipient_name, Transaction
from app import process_and_deduplicate_transactions, app
import json

class ReconstructionAndBalancesTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_clean_recipient_name(self):
        # 1. Paybill pattern
        desc_1 = "Pay Bill to 400222 - Equity Paybill Account Acc. 1234"
        self.assertEqual(get_clean_recipient_name(desc_1), "Equity Paybill Account")

        # 2. Merchant Payment pattern
        desc_2 = "Merchant Payment to 4012345 - DORCAS WAMBUI 2"
        self.assertEqual(get_clean_recipient_name(desc_2), "DORCAS WAMBUI 2")

        # 3. Small Business pattern
        desc_3 = "Customer Payment to Small Business to - +254712345678 WINLEX"
        self.assertEqual(get_clean_recipient_name(desc_3), "WINLEX")

        # 4. Fuliza prefix cleaning patterns
        desc_4 = "Fuliza Manal Capitol Hill"
        self.assertEqual(get_clean_recipient_name(desc_4), "Manal Capitol Hill")

        desc_5 = "Customer Send Money to Micro SME Business with Fuliza MPesa to - +254712345678 WINLEX"
        self.assertEqual(get_clean_recipient_name(desc_5), "WINLEX")

        desc_6 = "Fuliza M-Pesa to - +254712345678 JOHN DOE"
        self.assertEqual(get_clean_recipient_name(desc_6), "JOHN DOE")

    def test_deduplication_and_negative_balances(self):
        # Setup sequence of transactions
        # Outflow larger than balance should cause balance to go negative
        tx1 = Transaction(amount=5000, description="Inflow", category="inflow", balance=2000, timestamp=datetime(2026, 6, 1, 10, 0, 0), transaction_code="TX001")
        tx2 = Transaction(amount=5000, description="Inflow", category="inflow", balance=2000, timestamp=datetime(2026, 6, 1, 10, 0, 0), transaction_code="TX001") # Exact duplicate
        tx3 = Transaction(amount=3000, description="Outflow 1", category="expense", balance=2000, timestamp=datetime(2026, 6, 1, 11, 0, 0), transaction_code="TX002") # Balance becomes -1000
        tx4 = Transaction(amount=2000, description="Outflow 2", category="expense", balance=2000, timestamp=datetime(2026, 6, 1, 12, 0, 0), transaction_code="TX003") # Balance becomes -3000

        txs = [tx1, tx2, tx3, tx4]
        processed = process_and_deduplicate_transactions(txs)

        # Should deduplicate tx2 (exact composite key duplicate of tx1)
        self.assertEqual(len(processed), 3)

        # Chronological order verified
        self.assertEqual(processed[0].transaction_code, "TX001")
        self.assertEqual(processed[1].transaction_code, "TX002")
        self.assertEqual(processed[2].transaction_code, "TX003")

        # Balance calculations (inflows add, outflows subtract)
        self.assertEqual(processed[0].balance, 2000.0) # Starting balance
        self.assertEqual(processed[1].balance, -1000.0) # 2000 - 3000
        self.assertEqual(processed[2].balance, -3000.0) # -1000 - 2000

    def test_reconstruct_transaction_api_fallback(self):
        # Call categorise API with non-SMS description but with full transaction details
        payload = {
            "sms_message": "DORCAS WAMBUI 2",
            "amount": 1500.0,
            "description": "Merchant Payment to 4012345 - DORCAS WAMBUI 2",
            "balance": -500.0,
            "category": "expense",
            "transaction_code": "TX999",
            "answer_path": []
        }
        response = self.client.post('/categorize-with-questions', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertTrue(json_data['data']['needs_user_input'])
        self.assertEqual(json_data['data']['next_question_level'], '2B') # Start Node for merchant payment should be 2B
        self.assertEqual(json_data['data']['transaction']['transaction_code'], 'TX999')
        self.assertEqual(json_data['data']['transaction']['balance'], -500.0)

    def test_import_pdf_statement_with_filename(self):
        payload = {
            "filename": "temp_statement_3888.pdf"
        }
        response = self.client.post('/import-pdf-statement', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertGreater(len(json_data['data']['transactions']), 0)

    def test_preview_pdf_candidates_fields(self):
        from parser import extract_mpesa_pdf_candidates
        with open("temp_statement_3888.pdf", "rb") as f:
            pdf_bytes = f.read()
        res = extract_mpesa_pdf_candidates(pdf_bytes)
        self.assertIn('parseable', res)
        self.assertGreater(len(res['parseable']), 0)
        first_candidate = res['parseable'][0]
        self.assertIn('balance', first_candidate)
        self.assertIn('category', first_candidate)
        self.assertIn('transaction_code', first_candidate)

    def test_overdraft_cascading_balance_and_sorting(self):
        # 1. Inflow of 1000.0, followed by repayment of 400.0 (simultaneous)
        tx_repayment = Transaction(amount=400.0, description="OD Loan Repayment to 3201003", category="expense", balance=600.0, timestamp=datetime(2026, 6, 1, 10, 0, 0), transaction_code="TX_REP")
        tx_inflow = Transaction(amount=1000.0, description="Funds received from Swalehe", category="inflow", balance=1000.0, timestamp=datetime(2026, 6, 1, 10, 0, 0), transaction_code="TX_INF")
        
        # Simulating that inflow was parsed before repayment (lower orig_idx, printed above)
        tx_inflow.orig_idx = 0
        tx_repayment.orig_idx = 1
        
        # Starting with negative balance (overdraft)
        tx_initial = Transaction(amount=100.0, description="Outflow causing overdraft", category="expense", balance=0.0, timestamp=datetime(2026, 6, 1, 9, 0, 0), transaction_code="TX_INIT")
        tx_initial.orig_idx = 2
        tx_initial.balance = -100.0 # Set negative manually for start
        
        processed = process_and_deduplicate_transactions([tx_initial, tx_repayment, tx_inflow])
        
        # Verify chronological sorting order: Initial -> Inflow -> Repayment
        self.assertEqual(processed[0].transaction_code, "TX_INIT")
        self.assertEqual(processed[1].transaction_code, "TX_INF")
        self.assertEqual(processed[2].transaction_code, "TX_REP")
        
        # Verify cascading balances:
        # Initial: -100.0
        # Inflow: since prior was <= 0, resets to inflow amount = 1000.0
        # Repayment: 1000.0 - 400.0 = 600.0
        self.assertEqual(processed[0].balance, -100.0)
        self.assertEqual(processed[1].balance, 1000.0)
        self.assertEqual(processed[2].balance, 600.0)

if __name__ == '__main__':
    unittest.main()
