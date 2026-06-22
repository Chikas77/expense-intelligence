
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
                const isCredited = (tx.category === 'inflow' || tx.dropped);
                const amtFormatted = (isCredited ? '+' : '-') + `Ksh ${Number(tx.amount).toLocaleString(undefined, {minimumFractionDigits:2})}`;
                const balNum = Number(tx.balance);
                const isBalNeg = balNum < 0;
                const balFormatted = (isBalNeg ? '-' : '') + `Ksh ${Math.abs(balNum).toLocaleString(undefined, {minimumFractionDigits:2})}`;
                
                let categoryBadge = '';
                if (tx.dropped) {
                    categoryBadge = `<span class="badge badge-gray">Inflow (Dropped)</span>`;
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
                'Loan repayment',
                'Loan I\'m giving to family member',
                'Loan I\'m giving to friend',
                'Wedding contribution or harambee',
                'Funeral contribution or harambee',
                'Medical emergency harambee',
                'One-time emergency help',
                'School fees or education expense',
                'Insurance or loan repayment'
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
    