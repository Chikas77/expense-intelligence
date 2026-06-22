import json
from flask import Flask, request, jsonify
from datetime import datetime
from parser import (
    extract_mpesa_pdf_candidates,
    parse_mpesa_pdf,
    parse_mpesa_pdf_all,
    parse_mpesa_sms,
    parse_mpesa_messages,
    split_mpesa_messages,
    categorize_transaction_flow,
    Transaction,
)
from categorization_questions import process_answer

app = Flask(__name__)


def _build_transaction_payload(transaction):
    ts_str = transaction.timestamp.strftime('%Y-%m-%d %H:%M:%S') if transaction.timestamp else ''
    return {
        'transaction_code': transaction.transaction_code,
        'description': transaction.description,
        'amount': transaction.amount,
        'category': transaction.category,
        'balance': transaction.balance,
        'timestamp': ts_str,
        'clean_name': getattr(transaction, 'clean_name', ''),
        'is_inflow': getattr(transaction, 'is_inflow', False),
        'is_repayment': getattr(transaction, 'is_repayment', False),
    }


def process_and_deduplicate_transactions(transactions):
    if not transactions:
        return []

    # Custom sort key to handle simultaneous transactions chronologically
    def get_sort_key(tx):
        ts = tx.timestamp or datetime.min
        is_inflow = tx.category == 'inflow' or getattr(tx, 'is_inflow', False)
        desc = (tx.description or '').lower()
        is_charge = any(k in desc for k in ['charge', 'fee', 'transaction cost'])
        
        if is_inflow:
            priority = 1
        elif is_charge:
            priority = 3
        else:
            priority = 2
            
        orig = -getattr(tx, 'orig_idx', 0)
        return (ts, priority, orig)

    transactions = sorted(transactions, key=get_sort_key)

    seen = set()
    deduped = []
    for tx in transactions:
        tx_code = tx.transaction_code or ''
        amt = tx.amount
        ts_str = tx.timestamp.strftime('%Y-%m-%d %H:%M:%S') if tx.timestamp else ''
        key = (tx_code, amt, ts_str)
        if key not in seen:
            seen.add(key)
            deduped.append(tx)

    # Recompute running balance forward
    if deduped:
        running_balance = deduped[0].balance
        for i in range(1, len(deduped)):
            tx = deduped[i]
            is_inflow = tx.category == 'inflow' or getattr(tx, 'is_inflow', False)
            
            old_bal = running_balance
            if is_inflow:
                # If prior balance was negative or zero (overdraft state), reset running balance to this inflow amount
                if old_bal <= 0.0:
                    running_balance = tx.amount
                else:
                    running_balance += tx.amount
            else:
                # Both normal outflows and loan repayments decrease the running balance
                running_balance -= tx.amount
            tx.balance = running_balance

    return deduped


def _api_success(data=None, message=None, status_code=200, **extra):
    payload = {'success': True}
    if message is not None:
        payload['message'] = message
    if data is not None:
        payload['data'] = data
        if isinstance(data, dict):
            payload.update(data)
    payload.update(extra)
    return jsonify(payload), status_code


def _api_error(message, status_code=400, details=None, **extra):
    payload = {'success': False, 'error': message}
    if details is not None:
        payload['details'] = details
    payload.update(extra)
    return jsonify(payload), status_code


def _compute_next_question_level(question):
    if not isinstance(question, dict):
        return None
    question_level = question.get('question_level')
    if question_level:
        return str(question_level)
    level = question.get('level')
    if level == 1:
        return '1'
    options = question.get('options') or []
    if not options:
        return str(level)
    prefix = str(options[0].get('code', ''))[:1]
    return f"{level}{prefix}"


def _parse_answer_path_from_request():
    answer_path = []
    if request.content_type and request.content_type.startswith('application/json'):
        data = request.get_json(silent=True) or {}
        answer_path = data.get('answer_path', [])
    else:
        answer_path = request.form.getlist('answer_path')
        if not answer_path:
            raw = request.form.get('answer_path', '')
            try:
                answer_path = json.loads(raw) if raw else []
            except Exception:
                answer_path = [item.strip() for item in raw.split(',') if item.strip()]

    return answer_path if isinstance(answer_path, list) else []


@app.route('/')
def home():
    return "Expense Intelligence - Coming Soon"

@app.route('/pages-detailed')
def show_pages_detailed():
    """
    Show detailed information about all routes
    """
    
    routes_info = []
    
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        
        url = str(rule)
        methods = ','.join(sorted(rule.methods - {'OPTIONS', 'HEAD'}))
        endpoint = rule.endpoint
        
        # Get function docstring
        func = app.view_functions.get(endpoint)
        docstring = func.__doc__ if func else "No description"
        
        routes_info.append({
            'url': url,
            'methods': methods,
            'endpoint': endpoint,
            'docstring': docstring,
            'function': func.__name__ if func else 'Unknown'
        })
    
    routes_info.sort(key=lambda x: x['url'])
    
    routes_html = ""
    for i, route in enumerate(routes_info, 1):
        routes_html += f"""
        <div class="route-card">
            <div class="route-number">{i}</div>
            <div class="route-details">
                <h3>
                    <a href="{route['url']}">{route['url']}</a>
                </h3>
                <p class="endpoint"><strong>Endpoint:</strong> {route['endpoint']}</p>
                <p class="function"><strong>Function:</strong> {route['function']}</p>
                <p class="methods"><strong>Methods:</strong> {route['methods']}</p>
                <p class="docstring"><strong>Description:</strong> {route['docstring']}</p>
            </div>
        </div>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>📖 Detailed Page Info</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: #f5f5f5;
                padding: 20px;
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            h1 {{
                color: #333;
                margin-bottom: 20px;
            }}
            .route-card {{
                background: white;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 8px;
                border-left: 4px solid #667eea;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                display: flex;
                gap: 20px;
            }}
            .route-number {{
                background: #667eea;
                color: white;
                width: 50px;
                height: 50px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 20px;
            }}
            .route-details {{
                flex: 1;
            }}
            .route-details h3 {{
                margin: 0 0 10px 0;
            }}
            .route-details a {{
                color: #667eea;
                text-decoration: none;
                font-weight: 600;
            }}
            .route-details p {{
                margin: 5px 0;
                font-size: 14px;
                color: #666;
            }}
            .endpoint, .function, .methods {{
                color: #999;
                font-size: 13px;
            }}
            .docstring {{
                color: #333;
                font-style: italic;
                margin-top: 10px !important;
            }}
            a {{
                color: #667eea;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📖 Detailed Page Information ({len(routes_info)} pages)</h1>
            {routes_html}
            <p style="text-align: center; margin-top: 40px;">
                <a href="/pages">← Back to Simple View</a> | 
                <a href="/">Home</a>
            </p>
        </div>
    </body>
    </html>
    """

@app.route('/upload')
def upload():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Expense Intelligence - M-Pesa Upload</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        :root {
            --bg-main: #090d16;
            --bg-card: #111827;
            --bg-card-hover: #1f2937;
            --border-color: #374151;
            --text-primary: #f9fafb;
            --text-secondary: #9ca3af;
            --primary: #4f46e5;
            --primary-hover: #4338ca;
            --primary-light: rgba(79, 70, 229, 0.1);
            --success: #10b981;
            --success-light: rgba(16, 185, 129, 0.1);
            --danger: #ef4444;
            --danger-light: rgba(239, 68, 68, 0.1);
            --warning: #f59e0b;
            --warning-light: rgba(245, 158, 11, 0.1);
            --purple: #8b5cf6;
            --purple-light: rgba(139, 92, 246, 0.1);
        }

        * {
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg-main);
            color: var(--text-primary);
            margin: 0;
            padding: 0;
            min-height: 100vh;
        }

        /* Nav Bar */
        .navbar {
            background: rgba(17, 24, 39, 0.8);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .nav-container {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 2rem;
        }
        .nav-logo {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-primary);
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .nav-links {
            display: flex;
            gap: 1.5rem;
        }
        .nav-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 500;
            font-size: 0.9rem;
            transition: color 0.2s;
        }
        .nav-link:hover, .nav-link.active {
            color: var(--text-primary);
        }

        /* Container */
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 2rem;
        }

        /* Header */
        .header {
            margin-bottom: 2.5rem;
            text-align: center;
        }
        .header h1 {
            font-size: 2.5rem;
            font-weight: 800;
            margin: 0 0 0.5rem 0;
            background: linear-gradient(to right, #818cf8, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header p {
            color: var(--text-secondary);
            font-size: 1.1rem;
            margin: 0;
        }

        /* Grid */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 380px 1fr;
            gap: 2rem;
        }
        @media (max-width: 900px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Cards */
        .panel-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.75rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        /* Tabs */
        .tab-buttons {
            display: flex;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 1.5rem;
            gap: 1rem;
        }
        .tab-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            padding: 0.5rem 0.25rem 0.75rem 0.25rem;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: color 0.2s, border-color 0.2s;
        }
        .tab-btn:hover {
            color: var(--text-primary);
        }
        .tab-btn.active {
            color: #818cf8;
            border-bottom-color: #818cf8;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }

        /* Inputs */
        textarea {
            width: 100%;
            min-height: 150px;
            background: var(--bg-main);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            padding: 0.75rem;
            font-family: inherit;
            font-size: 0.95rem;
            resize: vertical;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        textarea:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.25);
        }

        /* File Upload */
        .file-dropzone {
            border: 2px dashed var(--border-color);
            border-radius: 12px;
            padding: 2rem 1rem;
            text-align: center;
            cursor: pointer;
            background: rgba(17, 24, 39, 0.3);
            margin-bottom: 1rem;
            position: relative;
            transition: border-color 0.2s, background-color 0.2s;
        }
        .file-dropzone:hover {
            border-color: var(--primary);
            background: rgba(79, 70, 229, 0.05);
        }
        .file-dropzone input {
            position: absolute;
            inset: 0;
            opacity: 0;
            cursor: pointer;
        }
        .file-dropzone svg {
            width: 48px;
            height: 48px;
            color: var(--text-secondary);
            margin-bottom: 0.75rem;
        }
        .file-info {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        .file-info strong {
            color: var(--text-primary);
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            background: var(--primary);
            color: #fff;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            gap: 0.5rem;
            transition: background-color 0.2s, opacity 0.2s;
        }
        .btn:hover:not(:disabled) {
            background: var(--primary-hover);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        .btn-outline {
            background: none;
            border: 1px solid var(--border-color);
            color: var(--text-primary);
        }
        .btn-outline:hover:not(:disabled) {
            background: var(--bg-card-hover);
        }
        .btn-danger {
            background: var(--danger);
        }
        .btn-danger:hover:not(:disabled) {
            background: #dc2626;
        }
        .btn-sm {
            padding: 0.4rem 0.8rem;
            font-size: 0.8rem;
            border-radius: 6px;
            width: auto;
        }

        /* Message */
        .message-area {
            margin-top: 1rem;
            font-size: 0.9rem;
            color: var(--warning);
            text-align: center;
            min-height: 20px;
            word-break: break-word;
        }

        /* Workspace Placeholders */
        .placeholder-view {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 5rem 2rem;
            text-align: center;
            color: var(--text-secondary);
        }
        .placeholder-view svg {
            width: 64px;
            height: 64px;
            color: var(--border-color);
            margin-bottom: 1.5rem;
        }

        /* Stats Row */
        .stats-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat-card {
            background: rgba(17, 24, 39, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1rem;
        }
        .stat-card .label {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.25rem;
        }
        .stat-card .value {
            font-size: 1.4rem;
            font-weight: 700;
        }

        /* Transaction List */
        .batch-container {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        .batch-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.75rem;
        }
        .batch-header h2 {
            font-size: 1.25rem;
            margin: 0;
            font-weight: 700;
        }

        .table-responsive {
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            background: rgba(17, 24, 39, 0.2);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }
        th {
            background: rgba(17, 24, 39, 0.6);
            color: var(--text-secondary);
            font-weight: 600;
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }
        td {
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }
        tr:last-child td {
            border-bottom: none;
        }
        tr:hover td {
            background: var(--bg-card-hover);
        }

        .recipient-cell {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            max-width: 250px;
        }
        .recipient-cell .clean-name {
            font-weight: 600;
            color: var(--text-primary);
        }
        .recipient-cell .raw-desc {
            font-size: 0.75rem;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Badges */
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.5rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: capitalize;
        }
        .badge-warning {
            background: var(--warning-light);
            color: var(--warning);
        }
        .badge-success {
            background: var(--success-light);
            color: var(--success);
        }
        .badge-danger {
            background: var(--danger-light);
            color: var(--danger);
        }
        .badge-purple {
            background: var(--purple-light);
            color: var(--purple);
        }
        .badge-gray {
            background: rgba(156, 163, 175, 0.1);
            color: var(--text-secondary);
        }

        .amount-val {
            font-weight: 600;
        }
        .amount-inflow {
            color: var(--success);
        }
        .amount-outflow {
            color: var(--text-primary);
        }

        .balance-val {
            font-size: 0.85rem;
        }
        .balance-negative {
            color: var(--danger);
            font-weight: 500;
        }

        /* PDF Preview Specific Section */
        .pdf-preview-box {
            background: rgba(17, 24, 39, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
        }
        .pdf-preview-box h3 {
            margin: 0 0 0.75rem 0;
            font-size: 1.1rem;
        }
        .raw-text-scroll {
            background: var(--bg-main);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            max-height: 250px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.85rem;
            white-space: pre-wrap;
            color: var(--text-secondary);
        }

        /* Modal Overlay */
        #categorization-modal {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(9, 13, 22, 0.75);
            backdrop-filter: blur(8px);
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-content {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            max-width: 550px;
            width: 90%;
            max-height: 85vh;
            overflow: hidden;
            padding: 2.25rem;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        .modal-header h3 {
            margin: 0;
            font-size: 1.3rem;
            font-weight: 700;
            line-height: 1.4;
        }
        .options-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            overflow-y: auto;
            padding-right: 0.5rem;
        }
        /* Premium Scrollbar for options list */
        .options-list::-webkit-scrollbar {
            width: 6px;
        }
        .options-list::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.03);
            border-radius: 3px;
        }
        .options-list::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 3px;
        }
        .options-list::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.3);
        }
        .choice-card {
            display: flex;
            align-items: center;
            gap: 1rem;
            background: rgba(17, 24, 39, 0.4);
            border: 1px solid var(--border-color);
            padding: 1rem;
            border-radius: 10px;
            cursor: pointer;
            transition: border-color 0.2s, background-color 0.2s;
        }
        .choice-card:hover {
            border-color: var(--primary);
            background: var(--bg-card-hover);
        }
        .choice-card input[type="radio"] {
            width: 18px;
            height: 18px;
            accent-color: var(--primary);
            cursor: pointer;
        }
        .choice-card.selected {
            border-color: #818cf8;
            background: rgba(79, 70, 229, 0.08);
        }
        .answer-trail {
            font-size: 0.8rem;
            color: var(--text-secondary);
            background: rgba(17, 24, 39, 0.5);
            padding: 0.5rem 0.75rem;
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }
        .modal-footer {
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
            margin-top: 0.5rem;
        }
        .modal-footer .btn {
            width: auto;
        }

        /* Result View */
        .result-view {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }
        .summary-card {
            background: rgba(16, 185, 129, 0.05);
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 12px;
            padding: 1.5rem;
        }
        .summary-title {
            color: var(--success);
            font-size: 1.2rem;
            font-weight: 700;
            margin-top: 0;
            margin-bottom: 0.75rem;
        }
        .category-breakdown {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            margin-top: 1rem;
        }
        .breakdown-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .breakdown-bar-container {
            width: 100%;
            height: 6px;
            background: var(--border-color);
            border-radius: 3px;
            margin-top: 0.25rem;
            overflow: hidden;
        }
        .breakdown-bar {
            height: 100%;
            background: var(--primary);
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <!-- Navbar -->
    <nav class="navbar">
        <div class="nav-container">
            <a href="/upload" class="nav-logo">📊 Expense Intelligence</a>
            <div class="nav-links">
                <a href="/upload" class="nav-link active">Upload & Categorize</a>
                <a href="/predict" class="nav-link">Prediction Wizard</a>
                <a href="/pages-detailed" class="nav-link">API Registry</a>
            </div>
        </div>
    </nav>

    <div class="container">
        <!-- Header -->
        <header class="header">
            <h1>M-Pesa Transaction Intelligence</h1>
            <p>Paste SMS messages or import M-Pesa PDF statements to clean, sort, and categorize your cash outflow.</p>
        </header>

        <div class="dashboard-grid">
            <!-- Left Panel (Inputs) -->
            <div class="panel-card" style="height: fit-content;">
                <div class="tab-buttons">
                    <button id="tab-sms-btn" class="tab-btn active" onclick="switchTab('sms')">Paste SMS</button>
                    <button id="tab-pdf-btn" class="tab-btn" onclick="switchTab('pdf')">Upload PDF Statement</button>
                </div>

                <!-- SMS Tab -->
                <div id="tab-sms" class="tab-content active">
                    <textarea id="sms-text" placeholder="Paste raw M-Pesa SMS messages here (you can paste multiple messages stacked together)..." oninput="toggleSmsClear()"></textarea>
                    <div style="margin-top: -0.5rem; margin-bottom: 1.25rem; text-align: right;">
                        <button id="clear-sms-btn" type="button" class="btn btn-outline btn-sm" style="display:none;" onclick="clearSmsInput()">Clear SMS</button>
                    </div>
                    <button id="start-btn" type="button" class="btn" onclick="startCategorization()">
                        <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
                        Categorize SMS Batch
                    </button>
                </div>

                <!-- PDF Tab -->
                <div id="tab-pdf" class="tab-content">
                    <div class="file-dropzone">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
                        <div class="file-info" id="file-dropzone-text">
                            <strong>Choose PDF file</strong> or drag it here <br>
                            <span style="font-size: 0.8rem; color: var(--text-secondary);">M-Pesa Statement PDF</span>
                        </div>
                        <input id="pdf-file" type="file" accept="application/pdf" onchange="handlePdfSelected()" />
                    </div>

                    <div style="display:flex; gap:10px; margin-bottom: 1.25rem; justify-content: flex-end;">
                        <button id="clear-pdf-btn" type="button" class="btn btn-outline btn-danger btn-sm" style="display:none;" onclick="clearPdfInput()">Remove PDF</button>
                    </div>

                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                        <button id="upload-pdf-btn" type="button" class="btn btn-outline" onclick="startPdfCategorization()">
                            Preview PDF Contents
                        </button>
                        <button id="import-all-btn" type="button" class="btn" onclick="importAllPdfTransactions()">
                            Import PDF Statement
                        </button>
                    </div>
                </div>

                <div id="message" class="message-area"></div>
            </div>

            <!-- Right Panel (Workspace & Results) -->
            <div class="panel-card" style="min-height: 480px; position: relative;">
                <!-- Placeholder View -->
                <div id="placeholder-view" class="placeholder-view">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                    <h3>No Transactions Loaded</h3>
                    <p>Pasted SMS messages or imported PDF tables will display here for cleaning, sorting, and categorization.</p>
                </div>

                <!-- PDF Text Preview Box -->
                <div id="pdf-preview-section" style="display: none; height: 100%;">
                    <div class="pdf-preview-box">
                        <h3>PDF Table Preview</h3>
                        <div id="pdf-raw-text" class="raw-text-scroll"></div>
                    </div>
                    <div style="display: flex; gap: 1rem; align-items: center; margin-top: 1rem;">
                        <button id="confirm-pdf-btn" type="button" class="btn" style="display:none;" onclick="confirmPdfCandidate()">Categorize Candidate Line</button>
                        <button id="upload-another-btn" type="button" class="btn btn-outline" onclick="clearPdfInput()">Clear and Upload Another</button>
                    </div>
                    <div id="pdf-candidates" style="margin-top: 1.5rem;"></div>
                </div>

                <!-- Parsed Batch review Workspace -->
                <div id="batch-workspace" style="display: none;">
                    <div class="batch-container">
                        <div class="batch-header">
                            <h2 id="batch-title">Parsed Transactions</h2>
                            <div style="display: flex; gap: 0.75rem;">
                               <button id="start-review-btn" class="btn btn-sm" onclick="startBatchReview()">Start Review Wizard</button>
                                <button id="finalize-batch-btn" class="btn btn-sm btn-success" onclick="finalizeBatchImport()">Finalize Import</button>
                            </div>
                        </div>

                        <!-- Stats summary -->
                        <div class="stats-row">
                            <div class="stat-card">
                                <div class="label">Total Records</div>
                                <div id="stat-total" class="value">0</div>
                            </div>
                            <div class="stat-card">
                                <div class="label">Categorized</div>
                                <div id="stat-categorized" class="value" style="color: var(--success);">0</div>
                            </div>
                            <div class="stat-card">
                                <div class="label">Needs Review</div>
                                <div id="stat-review" class="value" style="color: var(--warning);">0</div>
                            </div>
                            <div class="stat-card">
                                <div class="label">Inflow (Dropped)</div>
                                <div id="stat-dropped" class="value" style="color: var(--text-secondary);">0</div>
                            </div>
                        </div>

                        <!-- Table -->
                        <div class="table-responsive">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="width: 40px;">#</th>
                                        <th style="width: 100px;">Receipt Code</th>
                                        <th style="width: 140px;">Timestamp</th>
                                        <th>Recipient / Description</th>
                                        <th style="text-align: right; width: 100px;">Amount</th>
                                        <th style="text-align: right; width: 110px;">Wallet Balance</th>
                                        <th style="width: 150px;">Category</th>
                                        <th style="text-align: center; width: 100px;">Action</th>
                                    </tr>
                                </thead>
                                <tbody id="transactions-tbody">
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Final Analysis Results View -->
                <div id="result-view" class="result-view" style="display: none;">
                    <div class="summary-card">
                        <h3 class="summary-title">Import Summary Successful!</h3>
                        <div id="result-total-spending" style="font-size: 1.4rem; font-weight: 700; margin-bottom: 1.5rem;">Total Outflow: Ksh 0.00</div>
                        
                        <div style="font-weight: 600; font-size: 0.95rem; margin-bottom: 0.75rem; color: var(--text-secondary);">Spending by Category:</div>
                        <div id="result-categories" class="category-breakdown">
                        </div>
                    </div>
                    <button class="btn btn-outline" onclick="resetWorkspace()">Reset and Import Another</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Categorization Modal Dialog -->
    <div id="categorization-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="question-text">Is this transaction money going TO a person or FOR a service/product?</h3>
            </div>
            
            <div id="options-container" class="options-list">
            </div>
            
            <div id="answer-trail" class="answer-trail"></div>
            
            <div class="modal-footer">
                <button id="back-btn" type="button" class="btn btn-outline" onclick="goBack()">← Back</button>
                <button id="submit-answer-btn" type="button" class="btn" onclick="submitAnswer()">Next</button>
            </div>
        </div>
    </div>

    <script>
        let batchTransactions = [];
        let currentBatchIndex = -1;
        let inBatchMode = false;
        let isAutoAdvancing = false;
        let chamaManualCounts = {};
        
        let questionStack = [];
        let answerPath = [];
        let currentSms = '';
        let currentTransactionLabel = '';
        let currentTransactionAmount = null;
        let nextQuestionLevel = null;
        let currentQuestion = null;
        let currentRequestMode = 'json';
        let currentEndpoint = '/categorize-with-questions';

        // Tabs Toggle
        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            document.getElementById(`tab-${tab}-btn`).classList.add('active');
            document.getElementById(`tab-${tab}`).classList.add('active');
        }

        // SMS input toggling
        function toggleSmsClear() {
            const val = document.getElementById('sms-text').value.trim();
            document.getElementById('clear-sms-btn').style.display = val ? 'inline-block' : 'none';
        }
        function clearSmsInput() {
            document.getElementById('sms-text').value = '';
            toggleSmsClear();
        }

        // PDF file selection
        function handlePdfSelected() {
            const fileInput = document.getElementById('pdf-file');
            const clearBtn = document.getElementById('clear-pdf-btn');
            const dropzoneText = document.getElementById('file-dropzone-text');
            
            if (fileInput.files.length > 0) {
                const file = fileInput.files[0];
                dropzoneText.innerHTML = `<strong>Selected Statement:</strong><br>${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
                clearBtn.style.display = 'inline-block';
            } else {
                dropzoneText.innerHTML = `<strong>Choose PDF file</strong> or drag it here <br><span style="font-size: 0.8rem; color: var(--text-secondary);">M-Pesa Statement PDF</span>`;
                clearBtn.style.display = 'none';
            }
        }
        function clearPdfInput() {
            document.getElementById('pdf-file').value = '';
            document.getElementById('clear-pdf-btn').style.display = 'none';
            document.getElementById('file-dropzone-text').innerHTML = `<strong>Choose PDF file</strong> or drag it here <br><span style="font-size: 0.8rem; color: var(--text-secondary);">M-Pesa Statement PDF</span>`;
            resetWorkspace();
        }

        // Reset workspace to clean layout
        function resetWorkspace() {
            document.getElementById('placeholder-view').style.display = 'flex';
            document.getElementById('pdf-preview-section').style.display = 'none';
            document.getElementById('batch-workspace').style.display = 'none';
            document.getElementById('result-view').style.display = 'none';
            showMessage('');
            batchTransactions = [];
            currentBatchIndex = -1;
            inBatchMode = false;
            isAutoAdvancing = false;
            chamaManualCounts = {};
        }

        function showMessage(text) {
            document.getElementById('message').textContent = text || '';
        }

        function setLoading(enabled) {
            const startBtn = document.getElementById('start-btn');
            const uploadBtn = document.getElementById('upload-pdf-btn');
            const importBtn = document.getElementById('import-all-btn');
            const submitBtn = document.getElementById('submit-answer-btn');
            
            if (startBtn) startBtn.disabled = enabled;
            if (uploadBtn) uploadBtn.disabled = enabled;
            if (importBtn) importBtn.disabled = enabled;
            if (submitBtn) submitBtn.disabled = enabled;
        }

        // API Fetch helper
        function fetchQuestion(payload, endpoint, isFormData, responseHandler) {
            setLoading(true);
            const fetchOptions = {
                method: 'POST',
                body: isFormData ? payload : JSON.stringify(payload),
            };
            if (!isFormData) {
                fetchOptions.headers = { 'Content-Type': 'application/json' };
            }

            fetch(endpoint, fetchOptions)
            .then(async response => {
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Server error');
                }
                return data;
            })
            .then(responseHandler)
            .catch(error => showMessage(error.message || 'Unexpected error'))
            .finally(() => setLoading(false));
        }

        // --- SMS Import Flow ---
        function startCategorization() {
            const sms = document.getElementById('sms-text').value.trim();
            if (!sms) {
                showMessage('Please paste one or more M-Pesa SMS messages first.');
                return;
            }
            resetWorkspace();
            fetchQuestion({ mpesa_text: sms }, '/parse-mpesa-messages', false, handleBatchParseResponse);
        }

        function handleBatchParseResponse(data) {
            if (!data.transactions || !Array.isArray(data.transactions)) {
                showMessage(data.error || 'Unable to parse M-Pesa SMS messages.');
                return;
            }
            
            batchTransactions = data.transactions;
            setupBatchWorkspace();
        }

        // --- PDF Preview & Import Flow ---
        function startPdfCategorization() {
            const pdfFile = document.getElementById('pdf-file').files[0];
            if (!pdfFile) {
                showMessage('Please select a PDF statement file first.');
                return;
            }
            resetWorkspace();
            
            const formData = new FormData();
            formData.append('pdf_file', pdfFile);
            fetchQuestion(formData, '/preview-pdf', true, handlePdfPreviewResponse);
        }

        function handlePdfPreviewResponse(data) {
            if (!data.success) {
                showMessage(data.error || 'PDF text extraction failed.');
                return;
            }
            
            document.getElementById('placeholder-view').style.display = 'none';
            document.getElementById('pdf-preview-section').style.display = 'block';
            
            const rawTextDiv = document.getElementById('pdf-raw-text');
            const candidateContainer = document.getElementById('pdf-candidates');
            const confirmBtn = document.getElementById('confirm-pdf-btn');

            if (data.has_table) {
                rawTextDiv.textContent = data.table_preview || 'No tables extracted.';
            } else {
                rawTextDiv.textContent = data.raw_text || 'No readable text extracted.';
            }

            candidateContainer.innerHTML = '';
            if (data.candidates && data.candidates.length > 0) {
                let html = '<h3>Extracted SMS-style Candidates (Select one to classify):</h3>';
                data.candidates.forEach((cand, idx) => {
                    html += `
                        <div class="choice-card" onclick="selectPdfCandidate(${idx}, this)">
                            <input type="radio" name="pdf-candidate-radio" id="cand-${idx}" value="${idx}">
                            <label style="cursor:pointer; width:100%; display:block;">
                                <strong>Ksh ${Number(cand.amount).toLocaleString()}</strong> — ${cand.description}
                            </label>
                        </div>
                    `;
                });
                candidateContainer.innerHTML = html;
                confirmBtn.style.display = 'inline-block';
            } else {
                candidateContainer.innerHTML = '<p style="color: var(--text-secondary);">No SMS-style transaction lines detected inside the text blocks.</p>';
                confirmBtn.style.display = 'none';
            }
            
            showMessage('PDF preview successfully loaded.');
        }

        let selectedPdfCandidateIdx = -1;
        function selectPdfCandidate(idx, element) {
            selectedPdfCandidateIdx = idx;
            document.querySelectorAll('#pdf-candidates .choice-card').forEach(c => c.classList.remove('selected'));
            element.classList.add('selected');
            const radio = element.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
        }

        function confirmPdfCandidate() {
            if (selectedPdfCandidateIdx < 0) {
                showMessage('Please select an extracted candidate transaction first.');
                return;
            }
            // Trigger single SMS question wizard for the selected candidate
            const fileInput = document.getElementById('pdf-file');
            const formData = new FormData();
            if (fileInput.files[0]) {
                formData.append('pdf_file', fileInput.files[0]);
            }
            
            resetWorkspace();
            currentEndpoint = '/categorize-with-questions-file';
            currentRequestMode = 'form';
            questionStack = [];
            answerPath = [];
            
            fetchQuestion(formData, currentEndpoint, true, handleCategorizationResponse);
        }

        function importAllPdfTransactions() {
            const pdfFile = document.getElementById('pdf-file').files[0];
            if (!pdfFile) {
                showMessage('Please select a PDF statement file first.');
                return;
            }
            resetWorkspace();
            
            const formData = new FormData();
            formData.append('pdf_file', pdfFile);
            setLoading(true);
            
            fetch('/import-pdf-statement', {
                method: 'POST',
                body: formData
            })
            .then(async response => {
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Statement parsing failed.');
                }
                return data;
            })
            .then(data => {
                batchTransactions = data.transactions || [];
                setupBatchWorkspace();
                showMessage(data.message || 'Import successful.');
            })
            .catch(err => showMessage(err.message || 'Error occurred during PDF statement import.'))
            .finally(() => setLoading(false));
        }

        // --- Workspace Rendering ---
        function setupBatchWorkspace() {
            document.getElementById('placeholder-view').style.display = 'none';
            document.getElementById('pdf-preview-section').style.display = 'none';
            document.getElementById('result-view').style.display = 'none';
            document.getElementById('batch-workspace').style.display = 'block';
            
            renderTransactionsTable();
            updateStatsSummary();
        }

        function updateStatsSummary() {
            const total = batchTransactions.length;
            const dropped = batchTransactions.filter(tx => tx.dropped).length;
            const review = batchTransactions.filter(tx => tx.needs_review && !tx.dropped).length;
            const categorized = total - dropped - review;
            
            document.getElementById('stat-total').textContent = total;
            document.getElementById('stat-dropped').textContent = dropped;
            document.getElementById('stat-review').textContent = review;
            document.getElementById('stat-categorized').textContent = categorized;

            // Update Start Review button label/display
            const reviewBtn = document.getElementById('start-review-btn');
            if (review === 0) {
                reviewBtn.textContent = 'All Categorized';
                reviewBtn.disabled = true;
            } else {
                reviewBtn.textContent = `Review Pending (${review})`;
                reviewBtn.disabled = false;
            }
        }

        function renderTransactionsTable() {
            const tbody = document.getElementById('transactions-tbody');
            tbody.innerHTML = '';
            
            if (batchTransactions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-secondary);">No transactions available in this batch.</td></tr>';
                return;
            }

            batchTransactions.forEach((tx, idx) => {
                const row = document.createElement('tr');
                if (tx.dropped) {
                    row.style.opacity = '0.65';
                }
                
                // Formats
                const isCredited = (tx.category === 'inflow' || (tx.dropped && !tx.is_repayment));
                const amtFormatted = (isCredited ? '+' : '-') + `Ksh ${Number(tx.amount).toLocaleString(undefined, {minimumFractionDigits:2})}`;
                const balNum = Number(tx.balance);
                const isBalNeg = balNum < 0;
                const balFormatted = (isBalNeg ? '-' : '') + `Ksh ${Math.abs(balNum).toLocaleString(undefined, {minimumFractionDigits:2})}`;
                
                let categoryBadge = '';
                if (tx.dropped) {
                    categoryBadge = `<span class="badge badge-gray">${tx.dropped_reason || 'Inflow (Dropped)'}</span>`;
                } else if (tx.needs_review) {
                    categoryBadge = `<span class="badge badge-warning">Needs Review</span>`;
                } else if (tx.is_propagated) {
                    categoryBadge = `<span class="badge badge-purple">${tx.category} [Auto]</span>`;
                } else {
                    categoryBadge = `<span class="badge badge-success">${tx.category}</span>`;
                }

                let actionHtml = '';
                if (tx.dropped) {
                    actionHtml = '<span style="color:var(--text-secondary); font-size:0.8rem;">Skipped</span>';
                } else if (tx.needs_review) {
                    actionHtml = `<button class="btn btn-sm" onclick="reviewSingleTransaction(${idx})">Review</button>`;
                } else {
                    actionHtml = `<span style="color:var(--success); font-weight:bold;">✓</span>`;
                }

                row.innerHTML = `
                    <td>${idx + 1}</td>
                    <td><code style="color:#818cf8; font-weight:600;">${tx.transaction_code || '—'}</code></td>
                    <td style="font-size:0.8rem; color:var(--text-secondary);">${tx.timestamp || '—'}</td>
                    <td>
                        <div class="recipient-cell">
                            <span class="clean-name">${tx.clean_name || 'Personal Transfer'}</span>
                            <span class="raw-desc" title="${tx.description}">${tx.description}</span>
                        </div>
                    </td>
                    <td style="text-align: right;" class="amount-val ${isCredited ? 'amount-inflow' : 'amount-outflow'}">${amtFormatted}</td>
                    <td style="text-align: right;" class="balance-val ${isBalNeg ? 'balance-negative' : ''}">${balFormatted}</td>
                    <td>${categoryBadge}</td>
                    <td style="text-align: center;">${actionHtml}</td>
                `;
                tbody.appendChild(row);
            });
        }

        // --- Categorization Wizard Modal Flow ---
        function findNextReviewIndex(startIndex) {
            for (let i = startIndex; i < batchTransactions.length; i++) {
                if (batchTransactions[i].needs_review && !batchTransactions[i].dropped) {
                    return i;
                }
            }
            return -1;
        }

        function startBatchReview() {
            const nextIdx = findNextReviewIndex(0);
            if (nextIdx >= 0) {
                isAutoAdvancing = true;
                inBatchMode = true;
                startReviewForIndex(nextIdx);
            }
        }

        function reviewSingleTransaction(idx) {
            isAutoAdvancing = false;
            inBatchMode = true;
            startReviewForIndex(idx);
        }

        function startReviewForIndex(idx) {
            currentBatchIndex = idx;
            const tx = batchTransactions[idx];
            
            currentSms = tx.raw_message || tx.description;
            currentTransactionLabel = tx.description;
            currentTransactionAmount = Number(tx.amount);
            
            questionStack = [];
            answerPath = [];
            nextQuestionLevel = null;
            currentQuestion = null;
            
            // If the transaction payload already has preloaded question metadata (from backend rules)
            if (tx.question) {
                currentQuestion = tx.question;
                nextQuestionLevel = tx.question.question_level;
                showQuestion(tx.question);
            } else {
                // Fetch first question node
                currentEndpoint = '/categorize-with-questions';
                currentRequestMode = 'json';
                fetchQuestion({
                    sms_message: currentSms,
                    amount: tx.amount,
                    description: tx.description,
                    balance: tx.balance,
                    category: tx.category,
                    transaction_code: tx.transaction_code,
                    answer_path: []
                }, currentEndpoint, false, handleCategorizationResponse);
            }
        }

        function showQuestion(questionData) {
            const labelNode = document.getElementById('question-text');
            const amtStr = `Ksh ${currentTransactionAmount.toLocaleString(undefined, {minimumFractionDigits:2})}`;
            
            labelNode.innerHTML = `
                <div style="font-size:0.8rem; text-transform:uppercase; color:var(--purple); font-weight:700; margin-bottom:0.25rem;">
                    Categorizing Outflow of ${amtStr}
                </div>
                <div style="font-size:0.9rem; color:var(--text-secondary); margin-bottom:0.5rem; font-style:italic;">
                    "${currentTransactionLabel}"
                </div>
                <div>${questionData.question}</div>
            `;

            const container = document.getElementById('options-container');
            container.innerHTML = '';
            
            (questionData.options || []).forEach((opt, idx) => {
                const card = document.createElement('div');
                card.className = 'choice-card';
                card.onclick = () => selectOption(opt.code, card);
                card.innerHTML = `
                    <input type="radio" name="answer-radio" id="opt-${opt.code}" value="${opt.code}">
                    <span style="font-weight:500;">${opt.label}</span>
                `;
                container.appendChild(card);
            });

            updateAnswerTrail();
            document.getElementById('categorization-modal').style.display = 'flex';
            setLoading(false);
        }

        let selectedOptionCode = null;
        function selectOption(code, element) {
            selectedOptionCode = code;
            document.querySelectorAll('#options-container .choice-card').forEach(c => c.classList.remove('selected'));
            element.classList.add('selected');
            const radio = element.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
        }

        function submitAnswer() {
            if (!selectedOptionCode) {
                showMessage('Please pick an option to proceed.');
                return;
            }
            if (!nextQuestionLevel) {
                showMessage('Question flow corrupted. Resetting...');
                hideModal();
                return;
            }

            if (currentQuestion) {
                questionStack.push({ question: currentQuestion, answer: selectedOptionCode });
            }
            answerPath.push(selectedOptionCode);
            const ans = selectedOptionCode;
            selectedOptionCode = null; // Reset selection
            
            showMessage('');
            const tx = batchTransactions[currentBatchIndex] || {};
            fetchQuestion({
                sms_message: currentSms,
                amount: tx.amount,
                description: tx.description,
                balance: tx.balance,
                category: tx.category,
                transaction_code: tx.transaction_code,
                question_level: nextQuestionLevel,
                user_answer: ans,
                answer_path: answerPath
            }, '/categorize-with-questions', false, handleCategorizationResponse);
        }

        function goBack() {
            if (questionStack.length === 0) {
                hideModal();
                showMessage('Wizard canceled.');
                return;
            }
            
            const prev = questionStack.pop();
            answerPath.pop();
            currentQuestion = prev.question;
            nextQuestionLevel = prev.question.question_level;
            
            showQuestion(currentQuestion);
            const savedAns = prev.answer;
            setTimeout(() => {
                const card = Array.from(document.querySelectorAll('#options-container .choice-card')).find(c => {
                    const r = c.querySelector('input[type="radio"]');
                    return r && r.value === savedAns;
                });
                if (card) selectOption(savedAns, card);
            }, 50);
        }

        function updateAnswerTrail() {
            const trail = document.getElementById('answer-trail');
            if (answerPath.length === 0) {
                trail.style.display = 'none';
            } else {
                trail.style.display = 'block';
                trail.textContent = 'Wizard Path: ' + answerPath.join(' → ');
            }
        }

        function hideModal() {
            document.getElementById('categorization-modal').style.display = 'none';
        }

        function isOneTimeCategory(category, subType) {
            const oneTimeSubTypes = [
                "Loan repayment",
                "Loan I'm giving to family member",
                "Loan I'm giving to friend",
                "Wedding contribution or harambee",
                "Funeral contribution or harambee",
                "Medical emergency harambee",
                "One-time emergency help",
                "School fees or education expense",
                "Insurance or loan repayment"
            ];
            const oneTimeCategories = ['Personal-Loan'];
            return oneTimeCategories.includes(category) || oneTimeSubTypes.includes(subType);
        }

        function propagateCategory(cleanName, category, subType, answerPath) {
            if (!cleanName) return;
            
            if (isOneTimeCategory(category, subType)) {
                return;
            }
            
            let count = 0;
            batchTransactions.forEach(tx => {
                if (tx.clean_name === cleanName && tx.needs_review && !tx.dropped && !tx.is_inflow) {
                    tx.category = category;
                    tx.sub_type = subType;
                    tx.answer_path = answerPath;
                    tx.needs_review = false;
                    tx.reviewed = true;
                    tx.is_propagated = true; // Mark as auto-propagated
                    count++;
                }
            });
            
            if (count > 0) {
                showMessage(`Auto-propagated category "${category}" to ${count} matching transaction(s) for "${cleanName}".`);
            }
        }

        function handleCategorizationResponse(data) {
            if (data.needs_user_input) {
                if (!data.question || !data.next_question_level) {
                    showMessage('Server returned incomplete question metadata.');
                    return;
                }
                nextQuestionLevel = data.next_question_level;
                currentQuestion = data.question;
                currentTransactionLabel = data.transaction && data.transaction.description ? data.transaction.description : '';
                currentTransactionAmount = data.transaction && data.transaction.amount !== undefined ? Number(data.transaction.amount) : null;
                answerPath = Array.isArray(data.answer_path) ? data.answer_path.slice() : answerPath;
                showQuestion(data.question);
                return;
            }

            // Finished categorization for the active item!
            hideModal();
            const finalCat = data.final_category;
            const finalSub = data.sub_type;
            const finalPath = data.answer_path;

            // If we are in a batch workspace:
            if (inBatchMode && currentBatchIndex >= 0) {
                const currentTx = batchTransactions[currentBatchIndex];
                if (currentTx) {
                    currentTx.category = finalCat;
                    currentTx.sub_type = finalSub;
                    currentTx.answer_path = finalPath;
                    currentTx.needs_review = false;
                    currentTx.reviewed = true;
                    
                    let shouldPropagate = true;
                    if (finalCat === 'Chama') {
                        const cleanName = currentTx.clean_name;
                        chamaManualCounts[cleanName] = (chamaManualCounts[cleanName] || 0) + 1;
                        if (chamaManualCounts[cleanName] < 3) {
                            shouldPropagate = false;
                            showMessage(`Chama category applied to "${cleanName}". Review it ${3 - chamaManualCounts[cleanName]} more time(s) to trigger auto-propagation.`);
                        }
                    }

                    if (shouldPropagate) {
                        // Trigger Batch Auto-Propagation across identical Clean Names!
                        propagateCategory(currentTx.clean_name, finalCat, finalSub, finalPath);
                    }
                }

                // Render live changes to the workspace
                renderTransactionsTable();
                updateStatsSummary();

                if (isAutoAdvancing) {
                    // Check if there are further pending transactions
                    const nextIdx = findNextReviewIndex(currentBatchIndex + 1);
                    if (nextIdx >= 0) {
                        startReviewForIndex(nextIdx);
                        return;
                    }
                    isAutoAdvancing = false;
                    showMessage('Batch review complete! You can now finalize the import.');
                } else {
                    showMessage(`Transaction categorized under "${finalCat}".`);
                }
                return;
            }

            // Single transaction standalone categorization response
            showResult(data);
        }

        function showResult(data) {
            const placeholder = document.getElementById('placeholder-view');
            const resultPanel = document.getElementById('result-view');
            
            placeholder.style.display = 'none';
            document.getElementById('pdf-preview-section').style.display = 'none';
            document.getElementById('batch-workspace').style.display = 'none';
            resultPanel.style.display = 'block';

            document.getElementById('result-total-spending').textContent = `Total Spend: Ksh ${Number(data.transaction.amount).toLocaleString(undefined, {minimumFractionDigits:2})}`;
            
            const catContainer = document.getElementById('result-categories');
            catContainer.innerHTML = `
                <div class="breakdown-row" style="font-weight:600;">
                    <span>${data.final_category} ${data.sub_type ? `(${data.sub_type})` : ''}</span>
                    <span>100%</span>
                </div>
                <div class="breakdown-bar-container">
                    <div class="breakdown-bar" style="width: 100%;"></div>
                </div>
            `;
        }

        // --- Finalize Batch Import ---
        function finalizeBatchImport() {
            const hasPending = batchTransactions.some(tx => tx.needs_review && !tx.dropped);
            if (hasPending) {
                showMessage('Please review and resolve all pending transactions before finalizing.');
                return;
            }

            setLoading(true);
            fetch('/finalize-pdf-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ transactions: batchTransactions })
            })
            .then(async response => {
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Finalization failed.');
                }
                return data;
            })
            .then(data => {
                // Transition to final result summary card
                document.getElementById('batch-workspace').style.display = 'none';
                const resultPanel = document.getElementById('result-view');
                resultPanel.style.display = 'block';

                document.getElementById('result-total-spending').textContent = `Total Outflow: ${data.total_spending}`;
                
                const catContainer = document.getElementById('result-categories');
                catContainer.innerHTML = '';

                if (Array.isArray(data.summary)) {
                    // Calculate total numeric spending to draw ratios
                    let totalVal = 0;
                    const parsedCategories = data.summary.map(str => {
                        const parts = str.split(': Ksh ');
                        const catName = parts[0];
                        const catVal = parseFloat(parts[1].replace(/,/g, ''));
                        totalVal += catVal;
                        return { name: catName, value: catVal, original: str };
                    });

                    parsedCategories.forEach(cat => {
                        const pct = totalVal > 0 ? ((cat.value / totalVal) * 100).toFixed(0) : 0;
                        const row = document.createElement('div');
                        row.style.marginBottom = '1rem';
                        row.innerHTML = `
                            <div class="breakdown-row" style="font-size:0.9rem;">
                                <span style="font-weight:600;">${cat.name}</span>
                                <span style="color:var(--text-secondary);">Ksh ${cat.value.toLocaleString(undefined, {minimumFractionDigits:0})} (${pct}%)</span>
                            </div>
                            <div class="breakdown-bar-container">
                                <div class="breakdown-bar" style="width: ${pct}%;"></div>
                            </div>
                        `;
                        catContainer.appendChild(row);
                    });
                }
                
                showMessage(data.message || 'Batch import finalized.');
            })
            .catch(err => showMessage(err.message || 'Error finalize.'))
            .finally(() => setLoading(false));
        }

        window.addEventListener('DOMContentLoaded', () => {
            const urlParams = new URLSearchParams(window.location.search);
            const fileParam = urlParams.get('file');
            if (fileParam) {
                resetWorkspace();
                setLoading(true);
                showMessage('Auto-loading statement file...');
                fetch('/import-pdf-statement', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: fileParam })
                })
                .then(async response => {
                    const data = await response.json();
                    if (!response.ok) {
                        throw new Error(data.error || 'Auto-load failed.');
                    }
                    return data;
                })
                .then(data => {
                    batchTransactions = data.transactions || [];
                    setupBatchWorkspace();
                    showMessage(data.message || 'Auto-loaded statement successfully.');
                })
                .catch(err => showMessage(err.message || 'Error auto-loading statement.'))
                .finally(() => setLoading(false));
            }
        });
    </script>
</body>
</html>
"""


@app.route('/predict')
def predict():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Predict Cash Flow</title>
    </head>
    <body>
        <h1>Cash Flow Prediction</h1>
        
        <form method="POST" action="/calculate">
            <label>Monthly Salary (Ksh):</label><br>
            <input type="number" name="salary" required><br><br>
            
            <label>Current M-Pesa Balance (Ksh):</label><br>
            <input type="number" name="balance" required><br><br>
            
            <label>Last 30 Days Spending (Ksh):</label><br>
            <input type="number" name="spending" required><br><br>
            
            <label>Salary Day (1-31):</label><br>
            <input type="number" name="salary_day" min="1" max="31" required><br><br>
            
            <button type="submit">Predict</button>
        </form>
    </body>
    </html>
    """


def calculate_spending_by_category(transactions):
    totals = {}
    for tx in transactions:
        key = (tx.category or 'Other')
        totals[key] = totals.get(key, 0) + float(tx.amount or 0)
    return totals


def calculate_last_30_days_spending(transactions):
    # For now, we treat provided transactions as within the last 30 days.
    return sum(float(tx.amount or 0) for tx in transactions)


@app.route('/upload-mpesa', methods=['GET', 'POST'])
def upload_mpesa():
    if request.method == 'POST':
        mpesa_text = request.form.get('mpesa_messages', '')
        try:
            salary = float(request.form.get('salary', 0) or 0)
        except Exception:
            salary = 0.0
        try:
            salary_day = int(request.form.get('salary_day', 1) or 1)
        except Exception:
            salary_day = 1

        transactions = parse_mpesa_messages(mpesa_text)

        if not transactions:
            return "No valid M-Pesa messages found."

        obvious_transactions = []
        uncertain_transactions = []
        for transaction in transactions:
            # Use categorize_transaction_flow to determine if user input is needed
            category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
            if not needs_input and category is not None:
                # assign final category for the obvious ones
                transaction.category = category
                obvious_transactions.append(transaction)
            else:
                uncertain_transactions.append(transaction)

        if not uncertain_transactions:
            return show_analysis_results(obvious_transactions, salary, salary_day)

        return show_categorization_form(obvious_transactions, uncertain_transactions, salary, salary_day)

    # GET request - show upload form
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Upload M-Pesa Messages</title>
        <style>
            body { font-family: Arial; padding: 20px; }
            textarea { width: 100%; height: 200px; }
            button { padding: 10px 20px; background: #2E75B6; color: white; }
        </style>
    </head>
    <body>
        <h1>Upload M-Pesa Messages</h1>

        <form method="POST">
            <label>Paste M-Pesa SMS (one per line):</label><br>
            <textarea name="mpesa_messages" required></textarea><br><br>

            <label>Salary:</label>
            <input type="number" name="salary" required><br><br>

            <label>Salary Day:</label>
            <input type="number" name="salary_day" min="1" max="31" required><br><br>

            <button type="submit">Analyze</button>
        </form>
    </body>
    </html>
    """


def show_analysis_results(transactions, salary, salary_day):
    spending_by_category = calculate_spending_by_category(transactions)
    total_spending = calculate_last_30_days_spending(transactions)
    current_balance = transactions[-1].balance if transactions else 0

    daily_burn_rate = total_spending / 30 if total_spending else 0
    days_remaining = current_balance / daily_burn_rate if daily_burn_rate > 0 else 999

    today = datetime.now().day
    if today <= salary_day:
        days_until_salary = salary_day - today
    else:
        days_until_salary = (30 - today) + salary_day

    if days_remaining < days_until_salary:
        status = "⚠️ AT RISK"
        depletion_day = today + int(days_remaining)
        message = f"Funds tight by Day {depletion_day}"
    else:
        status = "✅ ON TRACK"
        message = "You'll make it to salary day"

    category_breakdown = ""
    for category, amount in sorted(spending_by_category.items(), key=lambda x: x[1], reverse=True):
        category_breakdown += f"<tr><td>{category}</td><td>Ksh {amount:,.0f}</td></tr>"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>M-Pesa Analysis</title>
        <style>
            body {{ font-family: Arial; padding: 40px; }}
            .status {{ font-size: 32px; margin: 20px 0; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        </style>
    </head>
    <body>
        <h1>Your M-Pesa Analysis</h1>
        <div class="status">{status}</div>
        <div>{message}</div>
        
        <h2>Spending by Category</h2>
        <table>
            <tr><th>Category</th><th>Amount</th></tr>
            {category_breakdown}
            <tr><td><strong>Total</strong></td><td><strong>Ksh {total_spending:,.0f}</strong></td></tr>
        </table>
        
        <a href="/upload-mpesa">← Upload Again</a>
    </body>
    </html>
    """


def show_categorization_form(obvious_transactions, uncertain_transactions, salary, salary_day):
    uncertain_html = ""
    for i, transaction in enumerate(uncertain_transactions):
        uncertain_html += f"""
        <div class=\"transaction-item\">
            <p><strong>Sent Ksh {transaction.amount:,.0f}</strong> — <strong>{transaction.description}</strong></p>
            <input type=\"hidden\" name=\"transaction_{i}_amount\" value=\"{transaction.amount}\">
            <input type=\"hidden\" name=\"transaction_{i}_description\" value=\"{transaction.description}\">
            <label>Category:</label>
            <select name=\"transaction_{i}_category\" required>
                <option value=\"\">-- Choose --</option>
                <option value=\"Family Support\">Family Support</option>
                <option value=\"Informal Tax\">Informal Tax (Wedding/Funeral/Medical)</option>
                <option value=\"Chama\">Chama (Group)</option>
                <option value=\"Food\">Food</option>
                <option value=\"Transport\">Transport</option>
                <option value=\"Utilities\">Utilities</option>
                <option value=\"Entertainment\">Entertainment</option>
                <option value=\"Other\">Other</option>
            </select>
            <br><br>
        </div>
        """

    # Serialize obvious (auto-categorized) transactions as hidden fields
    obvious_html = ""
    for j, transaction in enumerate(obvious_transactions):
        obvious_html += f"""
            <input type=\"hidden\" name=\"obvious_{j}_amount\" value=\"{transaction.amount}\">
            <input type=\"hidden\" name=\"obvious_{j}_description\" value=\"{transaction.description}\">
            <input type=\"hidden\" name=\"obvious_{j}_category\" value=\"{transaction.category}\">
            <input type=\"hidden\" name=\"obvious_{j}_balance\" value=\"{transaction.balance}\">
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Confirm Categories</title>
        <style>
            body {{ font-family: Arial; padding: 40px; }}
            .transaction-item {{ border: 1px solid #ddd; padding: 20px; margin: 20px 0; }}
            select {{ padding: 8px; width: 300px; }}
            button {{ padding: 10px 20px; background: #2E75B6; color: white; }}
        </style>
    </head>
    <body>
        <h1>Confirm Transaction Categories</h1>
        <p>We found {len(uncertain_transactions)} transactions that need your input:</p>
        
        <form method=\"POST\" action=\"/finalize-categorization\">
            {uncertain_html}
            {obvious_html}
            <input type=\"hidden\" name=\"salary\" value=\"{salary}\">
            <input type=\"hidden\" name=\"salary_day\" value=\"{salary_day}\">
            <button type=\"submit\">Confirm & Analyze</button>
        </form>
    </body>
    </html>
    """


@app.route('/finalize-categorization', methods=['POST'])
def finalize_categorization():
    form = request.form
    try:
        salary = float(form.get('salary', 0) or 0)
    except Exception:
        salary = 0.0
    try:
        salary_day = int(form.get('salary_day', 1) or 1)
    except Exception:
        salary_day = 1

    # Reconstruct user-labeled transactions
    all_transactions = []
    i = 0
    while True:
        key_amount = f'transaction_{i}_amount'
        key_desc = f'transaction_{i}_description'
        key_cat = f'transaction_{i}_category'
        if key_amount not in form:
            break
        amount = float(form.get(key_amount) or 0)
        desc = form.get(key_desc) or ''
        cat = form.get(key_cat) or 'Other'
        all_transactions.append(Transaction(amount=amount, description=desc, category=cat, balance=0, timestamp=datetime.now()))
        i += 1

    # Reconstruct obvious (auto-categorized) transactions from hidden fields
    j = 0
    while True:
        key_amount = f'obvious_{j}_amount'
        key_desc = f'obvious_{j}_description'
        key_cat = f'obvious_{j}_category'
        key_bal = f'obvious_{j}_balance'
        if key_amount not in form:
            break
        amount = float(form.get(key_amount) or 0)
        desc = form.get(key_desc) or ''
        cat = form.get(key_cat) or 'Other'
        bal = float(form.get(key_bal) or 0)
        all_transactions.append(Transaction(amount=amount, description=desc, category=cat, balance=bal, timestamp=datetime.now()))
        j += 1

    return show_analysis_results(all_transactions, salary, salary_day)


@app.route('/calculate', methods=['POST'])
def calculate():
    salary = float(request.form['salary'])
    balance = float(request.form['balance'])
    spending_30_days = float(request.form['spending'])
    salary_day = int(request.form['salary_day'])
    daily_burn_rate = spending_30_days / 30
    days_remaining = balance / daily_burn_rate if daily_burn_rate > 0 else 999
    today = datetime.now().day
    if today <= salary_day:
        days_until_salary = salary_day - today
    else:
        days_until_salary = (30 - today) + salary_day
    if days_remaining < days_until_salary:
        depletion_day = today + int(days_remaining)
        shortfall_days = days_until_salary - days_remaining
        shortfall_amount = shortfall_days * daily_burn_rate
        status = "⚠️ AT RISK"
        message = f"Funds will be tight by Day {depletion_day}"
        details = f"You'll run out {int(shortfall_days)} days before salary. Gap: Ksh {shortfall_amount:,.0f}"
    else:
        buffer = balance - (daily_burn_rate * days_until_salary)
        status = "✅ ON TRACK"
        message = f"You'll make it to salary day"
        details = f"Projected buffer: Ksh {buffer:,.0f}"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Prediction Result</title>
        <style>
            body {{ font-family: Arial; padding: 40px; }}
            .status {{ font-size: 32px; margin: 20px 0; }}
            .message {{ font-size: 24px; color: #333; }}
            .details {{ font-size: 18px; color: #666; margin: 20px 0; }}
            .data {{ background: #f5f5f5; padding: 20px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <h1>Your Prediction</h1>
        
        <div class="status">{status}</div>
        <div class="message">{message}</div>
        <div class="details">{details}</div>
        
        <div class="data">
            <strong>Your Numbers:</strong><br>
            Salary: Ksh {salary:,.0f}<br>
            Current Balance: Ksh {balance:,.0f}<br>
            Daily Burn Rate: Ksh {daily_burn_rate:,.0f}<br>
            Days Until Salary: {days_until_salary}<br>
        </div>
        
        <a href="/predict">← Calculate Again</a>
    </body>
    </html>
    """


@app.route('/categorize-with-questions', methods=['POST'])
def categorize_with_questions():
    """Multi-step categorization API.

    Request body examples:

    1) First request - get the first question:
       {
           "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000."
       }

    2) Next request - answer level 1:
       {
           "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000.",
           "question_level": "1",
           "user_answer": "A"
       }

    3) Later request - continue the flow:
       {
           "sms_message": "...",
           "question_level": "2A",
           "user_answer": "A1"
       }

    Response payload structure:

    - When user input is still needed:
      {
          "success": true,
          "needs_user_input": true,
          "question": { ... },
          "next_question_level": "2A",
          "transaction": { ... }
      }

    - When a final category is reached:
      {
          "success": true,
          "needs_user_input": false,
          "final_category": "Family Support",
          "sub_type": "Regular monthly support",
          "confidence": 1.0,
          "transaction": { ... }
      }

    - On error:
      {
          "success": false,
          "error": "..."
      }
    """
    request_data = request.get_json(force=True, silent=True) or {}
    sms_message = request_data.get('sms_message')
    question_level = request_data.get('question_level')
    user_answer = request_data.get('user_answer')
    answer_path = request_data.get('answer_path', [])

    if not sms_message or not isinstance(sms_message, str) or not sms_message.strip():
        return _api_error('sms_message is required', 400)

    if not isinstance(answer_path, list):
        return _api_error('answer_path must be a list of answer codes', 400)
    if any(not isinstance(item, str) for item in answer_path):
        return _api_error('answer_path entries must be strings', 400)

    sms_message = sms_message.strip()
    transaction = parse_mpesa_sms(sms_message)
    if transaction is None:
        try:
            amount = float(request_data.get('amount') or 0.0)
            balance = float(request_data.get('balance') or 0.0)
            description = request_data.get('description') or sms_message
            category = request_data.get('category') or 'expense'
            code = request_data.get('transaction_code')
            transaction = Transaction(
                amount=amount,
                description=description,
                category=category,
                balance=balance,
                timestamp=datetime.now(),
                transaction_code=code
            )
        except Exception as e:
            return _api_error(f'Unable to parse M-Pesa SMS or reconstruct transaction: {str(e)}', 400)

    transaction_payload = _build_transaction_payload(transaction)

    if question_level is None:
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        if not needs_input:
            payload = {
                'needs_user_input': False,
                'final_category': category,
                'sub_type': sub_type,
                'transaction': transaction_payload,
                'answer_path': [],
            }
            return _api_success(data=payload, message='Transaction categorized automatically')
        payload = {
            'needs_user_input': True,
            'question': question,
            'next_question_level': question.get('question_level'),
            'transaction': transaction_payload,
            'answer_path': [],
        }
        return _api_success(data=payload, message='Additional user input required')

    if not user_answer or not isinstance(user_answer, str):
        return _api_error('user_answer is required when question_level is provided', 400)

    question_level = str(question_level).strip()
    current_answer = user_answer.strip()
    result = process_answer(question_level, current_answer)
    if result is None:
        return _api_error('Invalid question_level or user_answer combination', 400)

    next_answer_path = answer_path + [current_answer]

    if 'category' in result:
        payload = {
            'needs_user_input': False,
            'final_category': result['category'],
            'sub_type': result.get('sub_type'),
            'confidence': result.get('confidence', 1.0),
            'transaction': transaction_payload,
            'answer_path': next_answer_path,
        }
        return _api_success(data=payload, message='Transaction categorized')

    next_question_level = _compute_next_question_level(result)
    payload = {
        'needs_user_input': True,
        'question': result,
        'next_question_level': next_question_level,
        'transaction': transaction_payload,
        'answer_path': next_answer_path,
    }
    return _api_success(data=payload, message='Next question required')


@app.route('/preview-pdf', methods=['POST'])
def preview_pdf():
    pdf_file = request.files.get('pdf_file')
    if pdf_file is None:
        return _api_error('pdf_file is required', 400)

    pdf_bytes = pdf_file.read()
    if not pdf_bytes:
        return _api_error('Uploaded PDF is empty', 400)

    try:
        preview = extract_mpesa_pdf_candidates(pdf_bytes)
    except RuntimeError as exc:
        return _api_error(str(exc), 500)

    data = {
        'raw_text': preview['raw_text'],
        'candidates': preview['parseable'],
        'has_table': preview.get('has_table', False),
        'table_preview': preview.get('table_preview', ''),
    }
    if not preview['candidates']:
        data['candidates'] = []
        return _api_success(data=data, message='No M-Pesa-style lines were found in the PDF. Please confirm the upload.')

    return _api_success(data=data, message='PDF text extracted. Choose the most likely M-Pesa transaction line.')


@app.route('/parse-mpesa-messages', methods=['POST'])
def parse_mpesa_messages_endpoint():
    request_data = request.get_json(force=True, silent=True) or {}
    mpesa_text = request_data.get('mpesa_text')
    if not mpesa_text or not isinstance(mpesa_text, str) or not mpesa_text.strip():
        return _api_error('mpesa_text is required', 400)

    raw_messages = split_mpesa_messages(mpesa_text)
    transactions = []
    for raw in raw_messages:
        transaction = parse_mpesa_sms(raw)
        if transaction is not None:
            transactions.append(transaction)

    # Sort, deduplicate, and calculate negative running balance
    transactions = process_and_deduplicate_transactions(transactions)

    items = []
    first_uncertain_index = None
    for transaction in transactions:
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        is_repayment = getattr(transaction, 'is_repayment', False)
        # If parser detected an incoming/credit, mark as dropped and skip questions
        dropped = (transaction.category == 'inflow' or getattr(transaction, 'is_inflow', False))
        if dropped or is_repayment:
            needs_input = False
            
        if needs_input and first_uncertain_index is None:
            first_uncertain_index = len(items)

        ts_str = transaction.timestamp.strftime('%Y-%m-%d %H:%M:%S') if transaction.timestamp else ''
        
        items.append({
            'transaction_code': transaction.transaction_code,
            'description': transaction.description,
            'amount': transaction.amount,
            'balance': transaction.balance,
            'timestamp': ts_str,
            'clean_name': getattr(transaction, 'clean_name', ''),
            'raw_message': getattr(transaction, 'candidate_text', transaction.description),
            'category': None if dropped else (category if not needs_input else None),
            'sub_type': None if dropped else (sub_type if not needs_input else None),
            'needs_review': needs_input,
            'question': question if needs_input else None,
            'dropped': bool(dropped),
            'dropped_reason': 'Cash inflow (not an expense)' if dropped else None,
            'is_inflow': getattr(transaction, 'is_inflow', False),
            'is_repayment': is_repayment,
        })

    if not items:
        return _api_error('No valid M-Pesa messages found.', 400)

    return _api_success(
        data={
            'transactions': items,
            'first_uncertain_index': first_uncertain_index,
        },
        message='Parsed M-Pesa transactions successfully',
    )


@app.route('/import-pdf-statement', methods=['POST'])
def import_pdf_statement():
    filename = None
    pdf_file = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        filename = data.get('filename')
    else:
        pdf_file = request.files.get('pdf_file')
        filename = request.form.get('filename')

    if not pdf_file and filename:
        import os
        safe_name = os.path.basename(filename)
        try:
            with open(safe_name, 'rb') as f:
                pdf_bytes = f.read()
        except Exception as e:
            return _api_error(f'Failed to read local PDF file: {str(e)}', 400)
    elif pdf_file:
        pdf_bytes = pdf_file.read()
    else:
        return _api_error('pdf_file is required', 400)

    if not pdf_bytes:
        return _api_error('Uploaded PDF is empty', 400)

    transactions = parse_mpesa_pdf_all(pdf_bytes)
    if not transactions:
        return _api_error('No valid M-Pesa transactions were found in the PDF', 400)

    # Sort, deduplicate, and calculate negative running balance
    transactions = process_and_deduplicate_transactions(transactions)

    items = []
    for transaction in transactions:
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        is_repayment = getattr(transaction, 'is_repayment', False)
        dropped = (transaction.category == 'inflow' or getattr(transaction, 'is_inflow', False))
        if dropped or is_repayment:
            needs_input = False

        ts_str = transaction.timestamp.strftime('%Y-%m-%d %H:%M:%S') if transaction.timestamp else ''

        items.append({
            'transaction_code': transaction.transaction_code,
            'description': transaction.description,
            'amount': transaction.amount,
            'balance': transaction.balance,
            'timestamp': ts_str,
            'clean_name': getattr(transaction, 'clean_name', ''),
            'candidate_text': getattr(transaction, 'candidate_text', None),
            'category': None if dropped else (category if not needs_input else None),
            'sub_type': None if dropped else (sub_type if not needs_input else None),
            'needs_review': not dropped and bool(needs_input),
            'question': question if (needs_input and not dropped) else None,
            'dropped': bool(dropped),
            'dropped_reason': 'Cash inflow (not an expense)' if dropped else None,
            'is_inflow': getattr(transaction, 'is_inflow', False),
            'is_repayment': is_repayment,
        })

    return _api_success(
        data={
            'transactions': items,
            'transaction_count': len(items),
        },
        message=f'Found {len(items)} M-Pesa transactions in the PDF. Review before finalizing.',
    )


@app.route('/finalize-pdf-batch', methods=['POST'])
def finalize_pdf_batch():
    request_data = request.get_json(force=True, silent=True) or {}
    transactions = request_data.get('transactions', [])
    if not isinstance(transactions, list) or not transactions:
        return _api_error('No batch transactions provided', 400)

    # Chronologically sort incoming transactions in finalize
    transactions = sorted(transactions, key=lambda x: x.get('timestamp') or '')

    # Deduplicate in finalize to be doubly safe
    seen = set()
    deduped = []
    for tx in transactions:
        tx_code = tx.get('transaction_code') or ''
        amt = float(tx.get('amount') or 0)
        ts_str = tx.get('timestamp') or ''
        key = (tx_code, amt, ts_str)
        if key not in seen:
            seen.add(key)
            deduped.append(tx)

    spending_by_category = {}
    total_spending = 0.0
    for tx in deduped:
        if tx.get('dropped'):
            continue
        try:
            amount = float(tx.get('amount', 0) or 0)
        except Exception:
            amount = 0.0
        category = tx.get('category') or 'Needs review'
        spending_by_category[category] = spending_by_category.get(category, 0) + amount
        total_spending += amount

    summary_lines = [f"{category}: Ksh {amount:,.0f}" for category, amount in sorted(spending_by_category.items(), key=lambda x: x[1], reverse=True)]
    return _api_success(
        data={
            'summary': summary_lines,
            'total_spending': f"Ksh {total_spending:,.0f}",
        },
        message='Batch import completed. Review the category breakdown below.',
    )


@app.route('/categorize-with-questions-file', methods=['POST'])
def categorize_with_questions_file():
    pdf_file = request.files.get('pdf_file')
    sms_message = request.form.get('sms_message')
    question_level = request.form.get('question_level')
    user_answer = request.form.get('user_answer')
    answer_path = _parse_answer_path_from_request()

    if not pdf_file and not sms_message:
        return _api_error('A PDF file or sms_message is required', 400)

    if pdf_file:
        pdf_bytes = pdf_file.read()
        transaction = parse_mpesa_pdf(pdf_bytes)
        if transaction is None:
            return _api_error('Unable to extract M-Pesa text from PDF. Ensure the PDF contains readable M-Pesa SMS content.', 400)
    else:
        sms_message = sms_message.strip()
        transaction = parse_mpesa_sms(sms_message)
        if transaction is None:
            return _api_error('Unable to parse M-Pesa SMS', 400)

    transaction_payload = _build_transaction_payload(transaction)

    if question_level is None:
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        if not needs_input:
            return _api_success(
                data={
                    'needs_user_input': False,
                    'final_category': category,
                    'sub_type': sub_type,
                    'transaction': transaction_payload,
                    'answer_path': answer_path,
                },
                message='Transaction categorized automatically',
            )
        return _api_success(
            data={
                'needs_user_input': True,
                'question': question,
                'next_question_level': question.get('question_level'),
                'transaction': transaction_payload,
                'answer_path': answer_path,
            },
            message='Additional user input required',
        )

    if not user_answer:
        return _api_error('user_answer is required when question_level is provided', 400)

    question_level = str(question_level).strip()
    current_answer = user_answer.strip()
    result = process_answer(question_level, current_answer)
    if result is None:
        return _api_error('Invalid question_level or user_answer combination', 400)

    next_answer_path = answer_path + [current_answer]
    if 'category' in result:
        payload = {
            'needs_user_input': False,
            'final_category': result['category'],
            'sub_type': result.get('sub_type'),
            'confidence': result.get('confidence', 1.0),
            'transaction': transaction_payload,
            'answer_path': next_answer_path,
        }
        return _api_success(data=payload, message='Transaction categorized')

    next_question_level = _compute_next_question_level(result)
    payload = {
        'needs_user_input': True,
        'question': result,
        'next_question_level': next_question_level,
        'transaction': transaction_payload,
        'answer_path': next_answer_path,
    }
    return _api_success(data=payload, message='Next question required')


if __name__ == '__main__':
    app.run(debug=True)
