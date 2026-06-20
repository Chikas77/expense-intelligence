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
    return {
        'description': transaction.description,
        'amount': transaction.amount,
        'category': transaction.category,
        'balance': transaction.balance,
    }


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
    <html>
    <head>
        <meta charset="utf-8">
        <title>M-Pesa Upload</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 24px; max-width: 900px; }
            textarea { width: 100%; min-height: 140px; padding: 12px; font-size: 15px; margin-bottom: 16px; }
            button { font-size: 15px; padding: 10px 18px; margin-right: 10px; }
            .message { margin: 14px 0; color: #b00020; }
            .result { margin-top: 18px; padding: 16px; background: #eef9f2; border: 1px solid #b8e4c5; }
            #categorization-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.45); align-items: center; justify-content: center; }
            .modal-content { background: #fff; border-radius: 8px; max-width: 720px; width: 100%; padding: 22px; box-shadow: 0 18px 40px rgba(0,0,0,0.18); }
            .candidate-card { border: 1px solid #ddd; padding: 12px; border-radius: 8px; margin-bottom: 10px; background: #fafafa; }
            .candidate-card.selected { border-color: #2E75B6; background: #eef4ff; }
            .candidate-card h4 { margin: 0 0 6px 0; font-size: 15px; }
            .candidate-card p { margin: 5px 0; }
            #options-container label { display: block; margin: 10px 0; cursor: pointer; }
            #options-container input { margin-right: 10px; }
            .button-row { margin-top: 20px; display: flex; gap: 12px; }
        </style>
    </head>
    <body>
        <h1>M-Pesa Upload</h1>
        <p>Paste an M-Pesa SMS and answer the follow-up questions to classify the transaction.</p>

        <textarea id="sms-text" placeholder="Paste M-Pesa SMS here"></textarea>
        <br>
        <button id="start-btn" type="button">Start Categorization</button>
        <button id="upload-pdf-btn" type="button">Preview PDF Text</button>
        <input id="pdf-file" type="file" accept="application/pdf" style="display:block; margin-top:12px;" />
        <div id="message" class="message"></div>
        <div id="pdf-preview" class="result" style="display: none; white-space: pre-wrap;">
            <h3>PDF Text Preview</h3>
            <div id="pdf-raw-text" style="white-space: pre-wrap; max-height: 240px; overflow: auto; background: #fff; border: 1px solid #ccc; padding: 12px; margin-bottom: 12px;"></div>
            <div id="pdf-candidates" style="margin-bottom: 12px;"></div>
            <div style="display:flex; gap:10px; align-items:center; margin-top:8px; flex-wrap: wrap;">
                <button id="confirm-pdf-btn" type="button" style="display: none;">Confirm Candidate and Categorize</button>
                <button id="import-all-btn" type="button" style="display: none;">Import All Parsed Transactions</button>
                <button id="finalize-batch-btn" type="button" style="display: none;">Finalize Statement Import</button>
                <button id="upload-another-btn" type="button" style="display: none;">Upload Another PDF</button>
            </div>
            <div id="pdf-batch-review" style="display:none; margin-top:16px;"></div>
        </div>
        <div id="result" class="result" style="display: none;"></div>

        <div id="categorization-modal">
            <div class="modal-content">
                <h3 id="question-text"></h3>
                <div id="options-container"></div>
                <div id="answer-trail" style="font-size: 0.95em; color: #555; margin-top: 12px;"></div>
                <div class="button-row">
                    <button id="back-btn" type="button">← Back</button>
                    <button id="submit-answer-btn" type="button">Next</button>
                </div>
            </div>
        </div>

        <script>
            let currentSms = '';
            let currentEndpoint = '/categorize-with-questions';
            let currentRequestMode = 'json';
            let nextQuestionLevel = null;
            let currentQuestion = null;
            let currentTransactionLabel = '';
            let currentTransactionAmount = null;
            let isLoading = false;
            let questionStack = [];
            let answerPath = [];
            let batchTransactions = [];
            let currentBatchIndex = -1;
            let inBatchMode = false;

            document.getElementById('start-btn').addEventListener('click', startCategorization);
            document.getElementById('upload-pdf-btn').addEventListener('click', startPdfCategorization);
            document.getElementById('submit-answer-btn').addEventListener('click', submitAnswer);
            document.getElementById('back-btn').addEventListener('click', goBack);
            document.getElementById('confirm-pdf-btn').addEventListener('click', confirmPdfCandidate);
            document.getElementById('import-all-btn').addEventListener('click', importAllPdfTransactions);
            document.getElementById('finalize-batch-btn').addEventListener('click', finalizeBatchImport);
            document.getElementById('upload-another-btn').addEventListener('click', uploadAnother);

            let currentPdfCandidates = [];
            let currentPdfCandidate = null;
            let currentBatchTransactions = [];
            let currentBatchNeedsReview = false;

            function startCategorization() {
                const sms = document.getElementById('sms-text').value.trim();
                const pdfFile = document.getElementById('pdf-file') && document.getElementById('pdf-file').files[0];
                // If no SMS provided but a PDF is selected or we have PDF candidates, run PDF batch import
                if (!sms) {
                    if (pdfFile) {
                        // Directly import PDF so Start works immediately without Preview
                        importAllPdfTransactions();
                        return;
                    }
                    if (Array.isArray(currentPdfCandidates) && currentPdfCandidates.length > 0) {
                        importAllPdfTransactions();
                        return;
                    }
                    showMessage('Please enter an M-Pesa SMS message.');
                    return;
                }
                hidePdfPreview();
                inBatchMode = true;
                batchTransactions = [];
                currentBatchIndex = -1;
                currentEndpoint = '/parse-mpesa-messages';
                currentRequestMode = 'json';
                currentSms = sms;
                nextQuestionLevel = null;
                currentQuestion = null;
                currentTransactionLabel = '';
                currentTransactionAmount = null;
                questionStack = [];
                answerPath = [];
                document.getElementById('result').style.display = 'none';
                showMessage('');
                fetchQuestion({ mpesa_text: currentSms }, currentEndpoint, false, handleBatchParseResponse);
            }

            function startPdfCategorization() {
                const pdfFile = document.getElementById('pdf-file').files[0];
                if (!pdfFile) {
                    showMessage('Please select a PDF file to upload.');
                    return;
                }
                hidePdfPreview();
                currentEndpoint = '/preview-pdf';
                currentRequestMode = 'form';
                nextQuestionLevel = null;
                currentQuestion = null;
                currentTransactionLabel = '';
                currentTransactionAmount = null;
                questionStack = [];
                answerPath = [];
                document.getElementById('result').style.display = 'none';
                showMessage('');

                const formData = new FormData();
                formData.append('pdf_file', pdfFile);
                fetchQuestion(formData, currentEndpoint, true, handlePdfPreviewResponse);
            }

            function fetchQuestion(payload, endpoint = '/categorize-with-questions', isFormData = false, responseHandler = handleCategorizationResponse) {
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

            function handleCategorizationResponse(data) {
                if (data.needs_user_input) {
                    currentTransactionLabel = data.transaction && data.transaction.description ? data.transaction.description : '';
                    if (!data.question || !data.next_question_level) {
                        showMessage('Server returned incomplete question data.');
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

                if (inBatchMode && currentBatchIndex >= 0) {
                    const currentTx = batchTransactions[currentBatchIndex];
                    if (currentTx) {
                        currentTx.category = data.final_category || currentTx.category;
                        currentTx.sub_type = data.sub_type || currentTx.sub_type;
                        currentTx.answer_path = data.answer_path || [];
                        currentTx.needs_review = false;
                        currentTx.reviewed = true;
                    }
                    currentBatchIndex = findNextReviewIndex(currentBatchIndex + 1);
                    if (currentBatchIndex >= 0) {
                        startBatchQuestion(currentBatchIndex);
                        return;
                    }
                    inBatchMode = false;
                    hideModal();
                    hidePdfPreview();
                    showResultBatch(batchTransactions);
                    return;
                }

                hideModal();
                hidePdfPreview();
                showResult(data);
            }

            function handlePdfPreviewResponse(data) {
                if (!data.success) {
                    showMessage(data.error || 'PDF preview failed');
                    return;
                }
                showPdfPreview(data);
            }

            function showPdfPreview(data) {
                const preview = document.getElementById('pdf-preview');
                const rawText = document.getElementById('pdf-raw-text');
                const candidateContainer = document.getElementById('pdf-candidates');
                const confirmButton = document.getElementById('confirm-pdf-btn');
                const importAllButton = document.getElementById('import-all-btn');
                const finalizeBatchButton = document.getElementById('finalize-batch-btn');
                const batchReview = document.getElementById('pdf-batch-review');

                // STRICT TABLE-ONLY PREVIEW: show only formatted table preview.
                // If no table, show a rendered page image preview (OCR-capable) when available.
                if (data && data.has_table) {
                    rawText.textContent = data.table_preview || 'No table preview available.';
                } else if (data && data.standardized_text) {
                    // Show cleaned OCR text preview when available
                    rawText.textContent = data.standardized_text || 'No OCR text available.';
                } else if (data && data.has_image_preview && data.page_image_preview) {
                    // Insert or replace an <img> for the PNG preview
                    let img = document.getElementById('pdf-page-preview-img');
                    if (!img) {
                        img = document.createElement('img');
                        img.id = 'pdf-page-preview-img';
                        img.style.maxWidth = '100%';
                        rawText.innerHTML = '';
                        rawText.appendChild(img);
                    }
                    img.src = 'data:image/png;base64,' + data.page_image_preview;
                } else {
                    rawText.textContent = 'No table found in PDF (strict table-only preview).';
                }
                candidateContainer.innerHTML = '';
                batchReview.innerHTML = '';
                batchReview.style.display = 'none';
                finalizeBatchButton.style.display = 'none';
                currentBatchTransactions = [];
                // Candidates only from table extraction (if any)
                currentPdfCandidates = Array.isArray(data.candidates) ? data.candidates : [];
                currentPdfCandidate = null;
                if (!data.has_table) {
                    candidateContainer.innerHTML = '<p>No table found — preview is table-only.</p>';
                    confirmButton.style.display = 'none';
                    importAllButton.style.display = 'none';
                    document.getElementById('upload-another-btn').style.display = 'inline-block';
                } else if (currentPdfCandidates.length === 0) {
                    candidateContainer.innerHTML = '<p>Table found but no parseable M-Pesa rows were detected.</p>';
                    confirmButton.style.display = 'none';
                    importAllButton.style.display = 'inline-block';
                    document.getElementById('upload-another-btn').style.display = 'inline-block';
                } else {
                    currentPdfCandidates.forEach((candidate, index) => {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'candidate-card';
                        wrapper.innerHTML = `
                            <label style="display:block; cursor:pointer;">
                                <input type="radio" name="pdf-candidate" value="${index}"> 
                                <strong>${candidate.parseable ? '✔️' : '❌'}</strong> ${candidate.text}
                            </label>
                        `;
                        candidateContainer.appendChild(wrapper);
                    });
                    confirmButton.style.display = 'inline-block';
                    importAllButton.style.display = 'inline-block';
                    document.getElementById('upload-another-btn').style.display = 'inline-block';

                    const firstInput = candidateContainer.querySelector('input[name="pdf-candidate"]');
                    if (firstInput) {
                        firstInput.checked = true;
                        const parentCard = firstInput.closest('.candidate-card');
                        if (parentCard) {
                            parentCard.classList.add('selected');
                            parentCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                    }

                    candidateContainer.querySelectorAll('input[name="pdf-candidate"]').forEach(input => {
                        input.addEventListener('change', () => {
                            candidateContainer.querySelectorAll('.candidate-card').forEach(card => {
                                card.classList.remove('selected');
                            });
                            const selectedCard = input.closest('.candidate-card');
                            if (selectedCard) {
                                selectedCard.classList.add('selected');
                            }
                        });
                    });
                }

                preview.style.display = 'block';
                showMessage(data.message || 'PDF extracted. Please review the text and choose a candidate.');
            }

            function hidePdfPreview() {
                const preview = document.getElementById('pdf-preview');
                const rawText = document.getElementById('pdf-raw-text');
                const candidateContainer = document.getElementById('pdf-candidates');
                const confirmButton = document.getElementById('confirm-pdf-btn');
                const importAllButton = document.getElementById('import-all-btn');
                const finalizeBatchButton = document.getElementById('finalize-batch-btn');
                const batchReview = document.getElementById('pdf-batch-review');

                preview.style.display = 'none';
                rawText.textContent = '';
                candidateContainer.innerHTML = '';
                batchReview.innerHTML = '';
                confirmButton.style.display = 'none';
                importAllButton.style.display = 'none';
                finalizeBatchButton.style.display = 'none';
                currentPdfCandidates = [];
                currentPdfCandidate = null;
                currentBatchTransactions = [];
            }

            function confirmPdfCandidate() {
                const selected = document.querySelector('input[name="pdf-candidate"]:checked');
                if (!selected) {
                    showMessage('Please select a candidate line from the PDF preview.');
                    return;
                }
                const index = Number(selected.value);
                const candidate = currentPdfCandidates[index];
                if (!candidate) {
                    showMessage('Selected candidate is invalid.');
                    return;
                }
                hidePdfPreview();
                document.getElementById('result').style.display = 'none';
                currentSms = candidate.text;
                currentEndpoint = '/categorize-with-questions';
                currentRequestMode = 'json';
                nextQuestionLevel = null;
                currentQuestion = null;
                currentTransactionLabel = '';
                currentTransactionAmount = null;
                questionStack = [];
                answerPath = [];
                fetchQuestion({ sms_message: currentSms, answer_path: answerPath }, currentEndpoint, false);
            }

            function uploadAnother() {
                const fileInput = document.getElementById('pdf-file');
                if (fileInput) {
                    try { fileInput.value = ''; } catch (e) { /* some browsers restrict clearing file inputs, ignore */ }
                }
                hidePdfPreview();
                showMessage('You can upload another PDF now.');
            }

            function importAllPdfTransactions() {
                const pdfFile = document.getElementById('pdf-file').files[0];
                if (!pdfFile) {
                    showMessage('Please select a PDF file to upload first.');
                    return;
                }
                setLoading(true);
                const formData = new FormData();
                formData.append('pdf_file', pdfFile);
                fetch('/import-pdf-statement', {
                    method: 'POST',
                    body: formData,
                })
                .then(async response => {
                    const data = await response.json();
                    if (!response.ok) {
                        throw new Error(data.error || 'Batch import failed');
                    }
                    return data;
                })
                .then(handleBatchImportResponse)
                .catch(err => showMessage(err.message || 'Unexpected error during batch import'))
                .finally(() => setLoading(false));
            }

            function handleBatchImportResponse(data) {
                if (!data.success) {
                    showMessage(data.error || 'Unable to import PDF statement');
                    return;
                }
                currentBatchTransactions = Array.isArray(data.transactions) ? data.transactions : [];
                currentBatchNeedsReview = currentBatchTransactions.some(tx => tx.needs_review);
                showBatchReview(data);
            }

            function showResultBatch(transactions) {
                const result = document.getElementById('result');
                const lines = ['<strong>Batch review complete:</strong>'];
                transactions.forEach((tx, index) => {
                    let status = '';
                    if (tx.dropped) {
                        status = 'Dropped — Cash inflow (not an expense)';
                    } else if (tx.needs_review) {
                        status = 'Needs review';
                    } else {
                        status = `Recorded as ${tx.category}${tx.sub_type ? ` (${tx.sub_type})` : ''}`;
                    }
                    lines.push(`<strong>Transaction ${index + 1}:</strong> ${tx.description} — Ksh ${Number(tx.amount).toLocaleString()} — ${status}`);
                });
                result.innerHTML = lines.join('<br>');
                result.style.display = 'block';
            }

            function findNextReviewIndex(startIndex) {
                for (let i = startIndex; i < batchTransactions.length; i += 1) {
                    if (batchTransactions[i].needs_review) {
                        return i;
                    }
                }
                return -1;
            }

            function startBatchQuestion(index) {
                const tx = batchTransactions[index];
                if (!tx) {
                    return;
                }
                currentBatchIndex = index;
                currentSms = tx.raw_message;
                currentEndpoint = '/categorize-with-questions';
                currentRequestMode = 'json';
                nextQuestionLevel = null;
                currentQuestion = null;
                currentTransactionLabel = tx.description || '';
                currentTransactionAmount = tx.amount !== undefined ? Number(tx.amount) : null;
                questionStack = [];
                answerPath = [];
                document.getElementById('result').style.display = 'none';
                if (tx.question) {
                    currentQuestion = tx.question;
                    nextQuestionLevel = tx.question.question_level;
                    showQuestion(tx.question);
                } else {
                    fetchQuestion({ sms_message: currentSms, answer_path: [] }, currentEndpoint, false);
                }
            }

            function showBatchParseSummary(transactions) {
                const result = document.getElementById('result');
                const lines = ['<strong>Parsed M-Pesa transactions:</strong>'];
                transactions.forEach((tx, index) => {
                    let status = '';
                    if (tx.dropped) {
                        status = 'Dropped — Cash inflow (not an expense)';
                    } else if (tx.needs_review) {
                        status = 'Needs review';
                    } else {
                        status = `Recorded as ${tx.category}${tx.sub_type ? ` (${tx.sub_type})` : ''}`;
                    }
                    lines.push(`<strong>${index + 1}.</strong> ${tx.description} — Ksh ${Number(tx.amount).toLocaleString()} — ${status}`);
                });
                result.innerHTML = lines.join('<br>');
                result.style.display = 'block';
            }

            function handleBatchParseResponse(data) {
                if (!data.transactions || !Array.isArray(data.transactions)) {
                    showMessage('Unable to parse M-Pesa messages.');
                    return;
                }
                batchTransactions = data.transactions;
                showBatchParseSummary(batchTransactions);
                if (data.first_uncertain_index !== null && data.first_uncertain_index !== undefined) {
                    startBatchQuestion(data.first_uncertain_index);
                } else {
                    inBatchMode = false;
                    showMessage('All transactions were categorized automatically.');
                }
            }

            function showBatchReview(data) {
                const batchReview = document.getElementById('pdf-batch-review');
                batchReview.innerHTML = '';
                batchReview.style.display = 'block';

                const title = document.createElement('h3');
                title.textContent = data.message || 'Review parsed transactions';
                batchReview.appendChild(title);

                const list = document.createElement('div');
                currentBatchTransactions.forEach((tx, index) => {
                    const card = document.createElement('div');
                    card.className = 'candidate-card';
                    if (index === 0) {
                        card.classList.add('selected');
                    }
                    let status = '';
                    if (tx.dropped) {
                        status = 'Dropped — Cash inflow (not an expense)';
                    } else if (tx.needs_review) {
                        status = 'Needs review';
                    } else {
                        status = `Recorded as ${tx.category}${tx.sub_type ? ` (${tx.sub_type})` : ''}`;
                    }
                    card.innerHTML = `
                        <h4>Transaction ${index + 1}</h4>
                        <p><strong>Amount:</strong> Ksh ${tx.amount.toLocaleString()}</p>
                        <p><strong>Description:</strong> ${tx.description}</p>
                        <p><strong>Status:</strong> ${status}</p>
                        <p><strong>Candidate line:</strong> ${tx.candidate_text || ''}</p>
                    `;
                    list.appendChild(card);
                });
                batchReview.appendChild(list);
                const finalizeButton = document.getElementById('finalize-batch-btn');
                finalizeButton.style.display = 'inline-block';
                const firstCard = list.querySelector('.candidate-card');
                if (firstCard) {
                    firstCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }

            function finalizeBatchImport() {
                if (!currentBatchTransactions.length) {
                    showMessage('No transactions are available to finalize.');
                    return;
                }
                const payload = { transactions: currentBatchTransactions };
                setLoading(true);
                fetch('/finalize-pdf-batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                })
                .then(async response => {
                    const data = await response.json();
                    if (!response.ok) {
                        throw new Error(data.error || 'Unable to finalize statement import');
                    }
                    return data;
                })
                .then(result => {
                    hidePdfPreview();
                    showResult(result);
                    if (result.alert) {
                        showMessage(result.alert);
                    }
                })
                .catch(err => showMessage(err.message || 'Unexpected error while finalizing'))
                .finally(() => setLoading(false));
            }

            function formatKsh(value) {
                if (value === null || value === undefined || value === '') {
                    return '';
                }
                return `Ksh ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }

            function showQuestion(questionData) {
                const amountLabel = currentTransactionAmount !== null ? ` (${formatKsh(currentTransactionAmount)})` : '';
                const label = currentTransactionLabel ? ` for "${currentTransactionLabel}"${amountLabel}` : amountLabel;
                document.getElementById('question-text').textContent = (questionData.question || 'Choose an option below:') + label;
                const container = document.getElementById('options-container');
                container.innerHTML = '';

                (questionData.options || []).forEach(opt => {
                    const label = document.createElement('label');
                    label.innerHTML = `\n                        <input type="radio" name="answer" value="${opt.code}">\n                        ${opt.label}\n                    `;
                    container.appendChild(label);
                });

                updateAnswerTrail();
                document.getElementById('categorization-modal').style.display = 'flex';
                setLoading(false);
            }

            function submitAnswer() {
                const selected = document.querySelector('input[name="answer"]:checked');
                if (!selected) {
                    showMessage('Please choose an answer before continuing.');
                    return;
                }
                if (!nextQuestionLevel) {
                    showMessage('Missing question state. Please restart categorization.');
                    return;
                }
                if (currentQuestion) {
                    questionStack.push({ question: currentQuestion, answer: selected.value });
                }
                answerPath.push(selected.value);
                showMessage('');

                if (currentRequestMode === 'form') {
                    const pdfFile = document.getElementById('pdf-file').files[0];
                    const formData = new FormData();
                    if (pdfFile) {
                        formData.append('pdf_file', pdfFile);
                    }
                    formData.append('question_level', nextQuestionLevel);
                    formData.append('user_answer', selected.value);
                    formData.append('answer_path', JSON.stringify(answerPath));
                    fetchQuestion(formData, currentEndpoint, true);
                    return;
                }

                fetchQuestion({
                    sms_message: currentSms,
                    question_level: nextQuestionLevel,
                    user_answer: selected.value,
                    answer_path: answerPath,
                }, currentEndpoint, false);
            }

            function goBack() {
                if (questionStack.length === 0) {
                    hideModal();
                    showMessage('Question entry canceled. Edit the SMS or start again.');
                    return;
                }

                const previous = questionStack.pop();
                answerPath.pop();
                currentQuestion = previous.question;
                nextQuestionLevel = previous.question.question_level;
                showQuestion(currentQuestion);

                const selectedInput = document.querySelector(`input[name="answer"][value="${previous.answer}"]`);
                if (selectedInput) {
                    selectedInput.checked = true;
                }
            }

            function updateAnswerTrail() {
                const trail = document.getElementById('answer-trail');
                if (answerPath.length === 0) {
                    trail.textContent = '';
                    return;
                }
                trail.textContent = 'Previous answers: ' + answerPath.join(' → ');
            }

            function showResult(data) {
                const result = document.getElementById('result');
                const lines = [];
                if (data.final_category) {
                    lines.push(`<strong>Category:</strong> ${data.final_category}`);
                }
                if (data.sub_type) {
                    lines.push(`<strong>Sub-type:</strong> ${data.sub_type}`);
                }
                if (data.answer_path && data.answer_path.length) {
                    lines.push(`<strong>Answer path:</strong> ${data.answer_path.join(' → ')}`);
                }
                if (data.transaction) {
                    lines.push(`<strong>Description:</strong> ${data.transaction.description}`);
                    if (data.transaction.amount !== undefined) {
                        lines.push(`<strong>Amount:</strong> Ksh ${Number(data.transaction.amount).toLocaleString()}`);
                    }
                    if (data.transaction.balance !== undefined) {
                        lines.push(`<strong>Balance:</strong> Ksh ${Number(data.transaction.balance).toLocaleString()}`);
                    }
                }
                if (data.confidence !== undefined) {
                    lines.push(`<strong>Confidence:</strong> ${data.confidence}`);
                }
                if (data.summary && Array.isArray(data.summary)) {
                    lines.push('<strong>Batch summary:</strong>');
                    data.summary.forEach(item => {
                        lines.push(item);
                    });
                    if (data.total_spending) {
                        lines.push(`<strong>Total spending:</strong> ${data.total_spending}`);
                    }
                }
                result.innerHTML = lines.join('<br>');
                result.style.display = 'block';
            }

            function hideModal() {
                document.getElementById('categorization-modal').style.display = 'none';
            }

            function showMessage(text) {
                document.getElementById('message').textContent = text || '';
            }

            function setLoading(enabled) {
                isLoading = enabled;
                document.getElementById('start-btn').disabled = enabled;
                document.getElementById('submit-answer-btn').disabled = enabled;
            }
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
        return _api_error('Unable to parse M-Pesa SMS', 400)

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
    first_uncertain_index = None
    for index, raw in enumerate(raw_messages):
        transaction = parse_mpesa_sms(raw)
        if transaction is None:
            continue
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        # If parser detected an incoming/credit, mark as dropped (cash inflow) and skip questions
        dropped = (transaction.category == 'inflow')
        if dropped:
            needs_input = False
            if first_uncertain_index is None:
                # treat as not uncertain but still record position
                pass
        if needs_input and first_uncertain_index is None:
            first_uncertain_index = len(transactions)
        transactions.append({
            'transaction_code': transaction.transaction_code,
            'description': transaction.description,
            'amount': transaction.amount,
            'balance': transaction.balance,
            'raw_message': raw,
            'category': None if dropped else (category if not needs_input else None),
            'sub_type': None if dropped else (sub_type if not needs_input else None),
            'needs_review': needs_input,
            'question': question if needs_input else None,
            'dropped': bool(dropped),
            'dropped_reason': 'Cash inflow (not an expense)' if dropped else None,
        })

    if not transactions:
        return _api_error('No valid M-Pesa messages found.', 400)

    return _api_success(
        data={
            'transactions': transactions,
            'first_uncertain_index': first_uncertain_index,
        },
        message='Parsed M-Pesa transactions successfully',
    )


@app.route('/import-pdf-statement', methods=['POST'])
def import_pdf_statement():
    pdf_file = request.files.get('pdf_file')
    if pdf_file is None:
        return _api_error('pdf_file is required', 400)

    pdf_bytes = pdf_file.read()
    if not pdf_bytes:
        return _api_error('Uploaded PDF is empty', 400)

    transactions = parse_mpesa_pdf_all(pdf_bytes)
    if not transactions:
        return _api_error('No valid M-Pesa transactions were found in the PDF', 400)

    items = []
    for transaction in transactions:
        category, sub_type, needs_input, question = categorize_transaction_flow(transaction)
        items.append({
            'description': transaction.description,
            'amount': transaction.amount,
            'balance': transaction.balance,
            'candidate_text': getattr(transaction, 'candidate_text', None),
            'category': category if not needs_input else None,
            'needs_review': bool(needs_input),
            'sub_type': sub_type,
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

    spending_by_category = {}
    total_spending = 0.0
    for tx in transactions:
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
        message='Batch statement import completed. Review the category breakdown below.',
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
