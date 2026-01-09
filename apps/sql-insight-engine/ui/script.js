// Configuration
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8005'
    : `${window.location.protocol}//${window.location.hostname}:8005`;

console.log('Using API Base URL:', API_BASE_URL);

// State
let currentStep = 1;
let userData = {
    userId: null,
    accountId: null,
    dbConfig: null,
    uploadedDocs: 0
};
let selectedFiles = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Check if user is already set up
    const storedUser = localStorage.getItem('sql_insight_user');
    if (storedUser) {
        userData = JSON.parse(storedUser);
        showQueryInterface();
    }

    // Setup file upload
    setupFileUpload();

    // Setup query interface
    setupQueryInterface();
});

// ================== WIZARD FUNCTIONS ==================

async function createAccount() {
    const accountId = document.getElementById('accountId').value.trim();

    if (!accountId) {
        alert('Please enter an account ID');
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/users/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_id: accountId })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to create account');
        }

        userData.userId = data.id;
        userData.accountId = data.account_id;

        nextStep();
    } catch (error) {
        alert(`Error creating account: ${error.message}`);
    }
}

async function configureDatabase() {
    const dbConfig = {
        host: document.getElementById('dbHost').value.trim(),
        port: parseInt(document.getElementById('dbPort').value),
        db_name: document.getElementById('dbName').value.trim(),
        username: document.getElementById('dbUsername').value.trim(),
        password: document.getElementById('dbPassword').value.trim()
    };

    if (!dbConfig.host || !dbConfig.db_name || !dbConfig.username) {
        alert('Please fill in all required database fields');
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/users/${userData.userId}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dbConfig)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to configure database');
        }

        userData.dbConfig = dbConfig;

        nextStep();
    } catch (error) {
        alert(`Error configuring database: ${error.message}`);
    }
}

async function uploadDocuments() {
    if (selectedFiles.length === 0) {
        alert('Please select at least one file to upload');
        return;
    }

    try {
        for (const file of selectedFiles) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('account_id', userData.accountId);

            const response = await fetch(`${API_BASE_URL}/knowledgebase/`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Failed to upload ${file.name}`);
            }
        }

        userData.uploadedDocs = selectedFiles.length;
        selectedFiles = [];

        nextStep();
    } catch (error) {
        alert(`Error uploading documents: ${error.message}`);
    }
}

function skipDocuments() {
    nextStep();
}

function startQuerying() {
    // Save user data to localStorage
    localStorage.setItem('sql_insight_user', JSON.stringify(userData));

    // Update summary
    document.getElementById('summaryAccountId').textContent = userData.accountId;
    document.getElementById('summaryDatabase').textContent = `${userData.dbConfig.db_name} @ ${userData.dbConfig.host}`;
    document.getElementById('summaryDocs').textContent = `${userData.uploadedDocs} uploaded`;

    showQueryInterface();
}

function logout() {
    if (confirm('Are you sure you want to switch accounts? This will clear your current session.')) {
        localStorage.removeItem('sql_insight_user');
        location.reload();
    }
}

function setupFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const uploadedFilesDiv = document.getElementById('uploadedFiles');

    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--primary)';
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = 'var(--border-color)';
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--border-color)';
        const files = Array.from(e.dataTransfer.files);
        handleFiles(files);
    });

    fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        handleFiles(files);
    });

    function handleFiles(files) {
        files.forEach(file => {
            if (!selectedFiles.find(f => f.name === file.name)) {
                selectedFiles.push(file);
                addFileToList(file);
            }
        });
    }

    function addFileToList(file) {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        fileItem.innerHTML = `
            <svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <div class="file-info">
                <div class="file-name">${file.name}</div>
                <div class="file-size">${formatFileSize(file.size)}</div>
            </div>
            <button class="file-remove" onclick="removeFile('${file.name}')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        `;
        uploadedFilesDiv.appendChild(fileItem);
    }
}

function removeFile(fileName) {
    selectedFiles = selectedFiles.filter(f => f.name !== fileName);
    const uploadedFilesDiv = document.getElementById('uploadedFiles');
    const fileItems = uploadedFilesDiv.querySelectorAll('.file-item');
    fileItems.forEach(item => {
        if (item.querySelector('.file-name').textContent === fileName) {
            item.remove();
        }
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// ================== WIZARD NAVIGATION ==================

function nextStep() {
    // Mark current step as completed
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.add('completed');
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.remove('active');

    // Hide current content
    document.getElementById(`step${currentStep}`).classList.remove('active');

    // Move to next step
    currentStep++;

    // Show next step
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.add('active');
    document.getElementById(`step${currentStep}`).classList.add('active');

    // Update summary on final step
    if (currentStep === 4) {
        document.getElementById('summaryAccountId').textContent = userData.accountId;
        document.getElementById('summaryDatabase').textContent = `${userData.dbConfig.db_name} @ ${userData.dbConfig.host}`;
        document.getElementById('summaryDocs').textContent = `${userData.uploadedDocs} uploaded`;
    }
}

function previousStep() {
    // Hide current content
    document.getElementById(`step${currentStep}`).classList.remove('active');
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.remove('active');

    // Move to previous step
    currentStep--;

    // Show previous step
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.remove('completed');
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.add('active');
    document.getElementById(`step${currentStep}`).classList.add('active');
}

function showQueryInterface() {
    const onboarding = document.getElementById('onboarding');
    const kbInterface = document.getElementById('knowledgeBaseInterface');
    const queryInterface = document.getElementById('queryInterface');
    const appNav = document.getElementById('appNav');
    
    if (onboarding) onboarding.style.display = 'none';
    if (kbInterface) kbInterface.style.display = 'none';
    if (queryInterface) queryInterface.style.display = 'block';
    
    // Show Nav and update state
    if (appNav && userData && userData.accountId) {
        appNav.style.display = 'flex';
        document.getElementById('navAccountName').textContent = userData.accountId;
        
        const navSql = document.getElementById('navSql');
        const navKb = document.getElementById('navKb');
        if (navSql) navSql.classList.add('active');
        if (navKb) navKb.classList.remove('active');
    }
}

// ================== QUERY INTERFACE ==================

function setupQueryInterface() {
    const queryInput = document.getElementById('queryInput');
    const submitBtn = document.getElementById('submitBtn');
    const copySqlBtn = document.getElementById('copySqlBtn');

    // Example chips
    const chips = document.querySelectorAll('.chip');
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            const query = chip.getAttribute('data-query');
            queryInput.value = query;
            queryInput.focus();
        });
    });

    // Tab functionality
    const tabs = document.querySelectorAll('.tab');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.getAttribute('data-tab');
            // Only handle non-KB tabs here or check context
            if (!tab.closest('.kb-container')) {
                 tabs.forEach(t => {
                     if (!t.closest('.kb-container')) t.classList.remove('active');
                 });
                 tabPanes.forEach(p => p.classList.remove('active'));
    
                 tab.classList.add('active');
                 const targetPane = document.getElementById(`${tabName}-tab`);
                 if (targetPane) targetPane.classList.add('active');
            }
        });
    });

    // Copy SQL button
    if (copySqlBtn) {
        copySqlBtn.addEventListener('click', async () => {
            const sql = document.getElementById('sqlQuery').textContent;
            try {
                await navigator.clipboard.writeText(sql);
                const originalHTML = copySqlBtn.innerHTML;
                copySqlBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    Copied!
                `;
                setTimeout(() => {
                    copySqlBtn.innerHTML = originalHTML;
                }, 2000);
            } catch (err) {
                console.error('Failed to copy:', err);
            }
        });
    }

    // Submit query
    if (submitBtn) {
        submitBtn.addEventListener('click', submitQuery);
    }

    if (queryInput) {
        queryInput.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') {
                submitQuery();
            }
        });
    }
}

async function submitQuery() {
    const queryInput = document.getElementById('queryInput');
    const question = queryInput.value.trim();

    if (!question) {
        return;
    }

    if (!userData.userId) {
        alert('Please complete the setup wizard first');
        return;
    }

    const loadingState = document.getElementById('loadingState');
    const results = document.getElementById('results');
    const errorState = document.getElementById('errorState');
    const submitBtn = document.getElementById('submitBtn');

    // Hide previous results/errors
    results.style.display = 'none';
    errorState.style.display = 'none';

    // Show loading state
    loadingState.style.display = 'block';
    submitBtn.disabled = true;

    // Reset loading steps visually
    ['step1Load', 'step2Load', 'step3Load', 'step4Load'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove('active', 'completed');
        }
    });

    try {
        // Call async endpoint
        const response = await fetch(`${API_BASE_URL}/users/${userData.userId}/query/async`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to submit query');
        }

        // Got saga_id, now poll for results
        const sagaId = data.saga_id;
        console.log(`Query submitted. Saga ID: ${sagaId}`);
        console.log(`Polling for results...`);

        // Poll for results
        await pollForResults(sagaId);

    } catch (error) {
        loadingState.style.display = 'none';
        submitBtn.disabled = false;
        displayError(`Failed to submit query: ${error.message}`);
    }
}

async function pollForResults(sagaId, maxAttempts = 60) {
    const loadingState = document.getElementById('loadingState');
    const submitBtn = document.getElementById('submitBtn');

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        try {
            // Wait before polling (except first attempt)
            if (attempt > 0) {
                await new Promise(resolve => setTimeout(resolve, 1000)); // Poll every 1 second
            }

            const response = await fetch(`${API_BASE_URL}/users/${userData.userId}/query/status/${sagaId}`);
            const statusData = await response.json();

            console.log(`Poll attempt ${attempt + 1}: status = ${statusData.status}`);

            // Update progress steps if call stack is available
            if (statusData.result && statusData.result.call_stack) {
                updateLoadingProgress(statusData.result.call_stack);
            }

            if (statusData.status === 'completed') {
                // Query completed successfully
                loadingState.style.display = 'none';
                submitBtn.disabled = false;

                if (statusData.result && statusData.result.success) {
                    displayResults(statusData.result);
                } else {
                    displayError('Query completed but no results available');
                }
                return;
            } else if (statusData.status === 'error') {
                // Query failed
                loadingState.style.display = 'none';
                submitBtn.disabled = false;

                if (statusData.result && statusData.result.is_irrelevant) {
                    displayResults(statusData.result);
                } else {
                    const errorMsg = statusData.result?.formatted_response || statusData.result?.error_message || statusData.message || 'Query processing failed';
                    displayError(errorMsg, statusData.result?.call_stack);
                }
                return;
            }

            // Still pending, continue polling
        } catch (error) {
            console.error(`Polling error: ${error.message}`);
        }
    }

    // Timeout
    loadingState.style.display = 'none';
    submitBtn.disabled = false;
    displayError('Query processing timeout. Please try again.');
}

function updateLoadingProgress(callStack) {
    const stepMapping = {
        'check_knowledge_base': 'step1Load',
        'check_tables': 'step1Load',
        'relevance_check': 'step1Load',
        'generate_query': 'step2Load',
        'generate_query_agentic': 'step2Load',
        'execute_query': 'step3Load',
        'execute_query_agentic': 'step3Load',
        'format_result': 'step4Load',
        'format_result_agentic': 'step4Load'
    };

    callStack.forEach(step => {
        const elementId = stepMapping[step.step_name];
        if (elementId) {
            const element = document.getElementById(elementId);
            if (element) {
                if (step.status === 'success') {
                    element.classList.add('completed');
                    element.classList.add('active');
                } else if (step.status === 'error' || step.status === 'failed') {
                    element.classList.add('active');
                    element.classList.remove('completed');
                    // Add an error style if we had one, but visually keeping it active is enough for now
                }
            }
        }
    });
}

function renderCallStack(callStack) {
    if (!callStack || callStack.length === 0) return '<div class="text-muted">No processing data available</div>';

    return callStack
        .filter(step => step.status !== 'pending' && step.step_name !== 'init') // Filter empty/pending steps
        .map((step, index) => {
            const stepTitle = step.step_name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
            const badgeClass = step.status === 'success' ? 'badge-success' : (step.status === 'error' || step.status === 'failed' ? 'badge-error' : 'badge-info');
            const duration = step.duration_ms ? `${step.duration_ms.toFixed(0)}ms` : '';

            let metadataHtml = '';
            if (step.metadata) {
                const m = step.metadata;

                if (m.prompt) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                            Initial Prompt
                        </div>
                        <div class="meta-content">${m.prompt}</div>
                    </div>`;
                }

                if (m.llm_reasoning || m.reasoning) {
                    const reasoning = m.llm_reasoning || m.reasoning;
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>
                            AI Reasoning
                        </div>
                        <div class="meta-content meta-content-rich">${reasoning}</div>
                    </div>`;
                }

                if (m.tools_used && m.tools_used.length > 0) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>
                            Tools Called
                        </div>
                        <div class="tool-list">
                            ${m.tools_used.map(t => `
                                <div class="tool-item ${t.status === 'error' ? 'tool-error' : ''}">
                                    <div class="tool-header">
                                        <div class="tool-name">${t.tool}</div>
                                        ${t.duration_ms ? `<div class="tool-duration">${t.duration_ms.toFixed(0)}ms</div>` : ''}
                                    </div>
                                    <div class="tool-args">${JSON.stringify(t.args)}</div>
                                    ${t.response ? `
                                        <div class="tool-response">
                                            <strong>Response:</strong> ${typeof t.response === 'string' ? t.response : JSON.stringify(t.response)}
                                        </div>` : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>`;
                }

                if (m.available_tables) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h18v18H3z"></path><path d="M21 9H3"></path><path d="M21 15H3"></path><path d="M9 3v18"></path><path d="M15 3v18"></path></svg>
                            Database Discovery
                        </div>
                        <div class="meta-content">Found Tables: ${m.available_tables.join(', ')}</div>
                    </div>`;
                }

                if (m.sql) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
                            SQL Executed
                        </div>
                        <div class="meta-content">${m.sql}</div>
                    </div>`;
                }

                if (m.usage) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20"></path><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
                            Token Usage
                        </div>
                        <div class="meta-content">Prompt: ${m.usage.prompt_token_count} | Response: ${m.usage.candidates_token_count} | Total: ${m.usage.total_token_count}</div>
                    </div>`;
                }

                if (m.reason) {
                    metadataHtml += `
                    <div class="meta-section">
                        <div class="meta-label">Status Details</div>
                        <div class="meta-content">${m.reason}</div>
                    </div>`;
                }
            }

            return `
            <div class="stack-item ${index === callStack.length - 1 ? 'open' : ''}" id="stack-item-${index}">
                <div class="stack-header" onclick="toggleStackItem(${index})">
                    <div class="stack-icon">${index + 1}</div>
                    <div class="stack-title-group">
                        <div class="stack-subtitle">STEP ${index + 1}</div>
                        <div class="stack-title">${stepTitle}</div>
                    </div>
                    <span class="stack-badge ${badgeClass}">${step.status}</span>
                    <div class="stack-duration">${duration}</div>
                    <svg class="stack-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </div>
                <div class="stack-body">
                    <div class="stack-metadata">
                        ${metadataHtml || '<div class="text-muted">No additional metadata for this step</div>'}
                    </div>
                </div>
            </div>
        `;
        }).join('');
}

function toggleStackItem(index) {
    const item = document.getElementById(`stack-item-${index}`);
    if (item) {
        item.classList.toggle('open');
    }
}


function displayResults(data) {
    const tabs = document.querySelector('.tabs');
    const reasoningTab = document.querySelector('.tab[data-tab="reasoning"]');
    const sqlTab = document.querySelector('.tab[data-tab="sql"]');
    const rawTab = document.querySelector('.tab[data-tab="raw"]');

    // Display total metrics
    const totalTimeEl = document.getElementById('totalTime');
    const totalTokensEl = document.getElementById('totalTokens');
    if (totalTimeEl) totalTimeEl.textContent = data.total_duration_ms ? `${data.total_duration_ms.toFixed(0)}ms` : '0ms';
    if (totalTokensEl) totalTokensEl.textContent = data.total_tokens || '0';

    // Display reasoning if available
    const reasoningArea = document.getElementById('sagaReasoning');
    const reasoningContent = document.getElementById('sagaReasoningContent');
    if (data.reasoning && reasoningContent) {
        reasoningContent.innerHTML = `
            <div class="reasoning-summary">
                <div class="reasoning-badge">AI INSIGHT</div>
                <div class="reasoning-text">${data.reasoning}</div>
            </div>
        `;
        reasoningArea.style.display = 'block';
    } else if (reasoningArea) {
        // Still show area if metrics are available, but hide the content part
        reasoningArea.style.display = 'block';
        if (reasoningContent) reasoningContent.innerHTML = '';
    }

    // Display formatted response
    document.getElementById('formattedResponse').innerHTML = formatMarkdown(data.formatted_response);

    if (data.is_irrelevant) {
        // Hide technical tabs for irrelevant questions
        if (reasoningTab) reasoningTab.style.display = 'none';
        if (sqlTab) sqlTab.style.display = 'none';
        if (rawTab) rawTab.style.display = 'none';

        // Ensure Answer tab is active
        document.querySelector('.tab[data-tab="answer"]').click();
    } else {
        // Show technical tabs for valid queries
        if (reasoningTab) reasoningTab.style.display = 'block';
        if (sqlTab) sqlTab.style.display = 'block';
        if (rawTab) rawTab.style.display = 'block';

        // Render call stack as HTML
        const reasoningContent = document.getElementById('reasoningContent');
        reasoningContent.innerHTML = renderCallStack(data.call_stack);

        // Display SQL query
        document.getElementById('sqlQuery').textContent = data.generated_sql || 'No SQL query generated';

        // Display raw results
        const rawResultsDiv = document.getElementById('rawResults');
        if (data.raw_results) {
            rawResultsDiv.innerHTML = formatMarkdownTable(data.raw_results);
        } else {
            rawResultsDiv.textContent = 'No raw results available';
        }
    }

    // Show results
    document.getElementById('results').style.display = 'block';

    // Scroll to results
    document.getElementById('results').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function displayError(message, callStack = null) {
    document.getElementById('errorMessage').textContent = message;

    // Also show call stack in reasoning tab even on error
    if (callStack) {
        document.getElementById('reasoningContent').innerHTML = renderCallStack(callStack);
        document.getElementById('results').style.display = 'block';
        // Select reasoning tab automatically on error to show where it failed
        document.querySelector('.tab[data-tab="reasoning"]').click();
    }

    document.getElementById('errorState').style.display = 'block';
    document.getElementById('errorState').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function formatMarkdown(text) {
    if (!text) return '';

    let formatted = text;

    // Bold text
    formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Bullet lists
    formatted = formatted.replace(/^\*\s+(.+)$/gm, '<div style="margin: 0.5rem 0; padding-left: 1.5rem;">• $1</div>');

    // Line breaks
    formatted = formatted.replace(/\n/g, '<br>');

    // Numbers with dollar signs
    formatted = formatted.replace(/\$([0-9,]+\.?[0-9]*)/g, '<span style="color: var(--success); font-weight: 600;">$$$1</span>');

    // Numbered lists
    formatted = formatted.replace(/(\d+)\.\s+(.+?)(<br>|$)/g, '<div style="margin: 0.5rem 0;"><span style="color: var(--primary); font-weight: 600; margin-right: 0.5rem;">$1.</span>$2</div>');

    return formatted;
}

function formatMarkdownTable(markdown) {
    if (!markdown) return '';

    const lines = markdown.trim().split('\n');
    if (lines.length < 2) {
        return `<pre>${markdown}</pre>`;
    }

    // Check if it's a markdown table
    if (!lines[0].includes('|') || !lines[1].includes('---')) {
        return `<pre>${markdown}</pre>`;
    }

    let html = '<table style="width: 100%; border-collapse: collapse; margin-top: 1rem;">';

    // Header
    const headers = lines[0].split('|').map(h => h.trim()).filter(h => h);
    html += '<thead><tr>';
    headers.forEach(header => {
        html += `<th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--border-color); color: var(--primary); font-weight: 600;">${header}</th>`;
    });
    html += '</tr></thead>';

    // Body
    html += '<tbody>';
    for (let i = 2; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line || line.startsWith('*...')) {
            if (line.startsWith('*...')) {
                html += `<tr><td colspan="${headers.length}" style="padding: 0.75rem; text-align: center; color: var(--text-muted); font-style: italic;">${line}</td></tr>`;
            }
            continue;
        }

        const cells = line.split('|').map(c => c.trim()).filter(c => c);
        html += '<tr>';
        cells.forEach(cell => {
            html += `<td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); color: var(--text-secondary);">${cell}</td>`;
        });
        html += '</tr>';
    }
    html += '</tbody>';
    html += '</table>';

    return html;
}

console.log('SQL Insight Engine UI loaded successfully!');
console.log(`API URL: ${API_BASE_URL}`);

// KB State
let kbSelectedFiles = [];

// ================== KNOWLEDGE BASE FUNCTIONS ==================

function showKnowledgeBase() {
    console.log("showKnowledgeBase called");
    if (!userData || !userData.accountId) {
        alert("Please log in or create an account first.");
        return;
    }

    const queryInterface = document.getElementById('queryInterface');
    const kbInterface = document.getElementById('knowledgeBaseInterface');
    const appNav = document.getElementById('appNav');
    
    if (queryInterface) queryInterface.style.display = 'none';
    if (kbInterface) kbInterface.style.display = 'block';
    
    // Show Nav and update state
    if (appNav) {
        appNav.style.display = 'flex';
         document.getElementById('navAccountName').textContent = userData.accountId;
         
         const navSql = document.getElementById('navSql');
         const navKb = document.getElementById('navKb');
         if (navSql) navSql.classList.remove('active');
         if (navKb) navKb.classList.add('active');
    }
    
    // Default to chat tab using robust call
    switchKbTab('chat');
}

function switchKbTab(tabName) {
    console.log(`switchKbTab called with ${tabName}`);
    const chatView = document.getElementById('kbChatView');
    const manageView = document.getElementById('kbManageView');
    
    // Use more specific selector to avoid conflict with other tabs
    const tabs = document.querySelectorAll('.kb-container .tabs .tab');
    
    if (!chatView || !manageView) {
        console.error("KB Views not found");
        return;
    }
    
    if (tabName === 'chat') {
        chatView.style.display = 'block';
        manageView.style.display = 'none';
        
        if (tabs.length >= 2) {
            tabs[0].classList.add('active');
            tabs[1].classList.remove('active');
        }
    } else {
        chatView.style.display = 'none';
        manageView.style.display = 'block';
        
        if (tabs.length >= 2) {
            tabs[0].classList.remove('active');
            tabs[1].classList.add('active');
        }
        
        // Load documents when switching to manage tab
        loadDocuments();
        // Setup file upload only if element exists and hasn't been blocked
        setTimeout(setupKbFileUpload, 100); 
    }
}

async function loadDocuments() {
    const listContainer = document.getElementById('docList');
    listContainer.innerHTML = '<div class="text-muted">Loading documents...</div>';
    
    try {
        const response = await fetch(`${API_BASE_URL}/knowledgebase/files?account_id=${userData.accountId}`);
        if (!response.ok) throw new Error("Failed to load documents");
        
        const files = await response.json();
        
        if (files.length === 0) {
            listContainer.innerHTML = '<div class="text-muted">No documents uploaded.</div>';
            return;
        }
        
        let html = '<table class="doc-table" style="width:100%; border-collapse: collapse;">';
        html += '<thead><tr><th style="text-align:left; padding:8px;">Name</th><th style="text-align:left; padding:8px;">Size</th><th style="padding:8px;">Action</th></tr></thead><tbody>';
        
        files.forEach(file => {
            html += `
                <tr style="border-bottom: 1px solid var(--border-color);">
                    <td style="padding: 12px 8px;">${file.filename}</td>
                    <td style="padding: 12px 8px;">${formatFileSize(file.size)}</td>
                    <td style="padding: 12px 8px; text-align: center;">
                        <button class="btn-danger-sm" onclick="deleteDocument('${file.filename}')" style="background:none; border:none; color: var(--error); cursor: pointer;">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        </button>
                    </td>
                </tr>
            `;
        });
        
        html += '</tbody></table>';
        listContainer.innerHTML = html;
        
    } catch (error) {
        listContainer.innerHTML = `<div class="error-text">Error loading documents: ${error.message}</div>`;
    }
}

async function deleteDocument(filename) {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/knowledgebase/?account_id=${userData.accountId}&filename=${filename}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error("Failed to delete document");
        
        loadDocuments(); // Reload list
        
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

function setupKbFileUpload() {
    const uploadArea = document.getElementById('kbUploadArea');
    const fileInput = document.getElementById('kbFileInput');
    const uploadedFilesDiv = document.getElementById('kbUploadedFiles');
    
    // Prevent multiple listeners if called multiple times
    // We'll just clone and replace to strip listeners
    
    const newUploadArea = uploadArea.cloneNode(true);
    uploadArea.parentNode.replaceChild(newUploadArea, uploadArea);
    
    const newFileInput = fileInput.cloneNode(true);
    fileInput.parentNode.replaceChild(newFileInput, fileInput);
    
    newUploadArea.addEventListener('click', () => newFileInput.click());
    
    newUploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        newUploadArea.style.borderColor = 'var(--primary)';
    });
    
    newUploadArea.addEventListener('dragleave', () => {
        newUploadArea.style.borderColor = 'var(--border-color)';
    });
    
    newUploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        newUploadArea.style.borderColor = 'var(--border-color)';
        const files = Array.from(e.dataTransfer.files);
        handleKbFiles(files);
    });
    
    newFileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        handleKbFiles(files);
    });
    
    function handleKbFiles(files) {
        files.forEach(file => {
            if (!kbSelectedFiles.find(f => f.name === file.name)) {
                kbSelectedFiles.push(file);
                renderKbFileList();
            }
        });
    }
}

function renderKbFileList() {
    const div = document.getElementById('kbUploadedFiles');
    div.innerHTML = '';
    
    kbSelectedFiles.forEach(file => {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.innerHTML = `
            <span>${file.name} (${formatFileSize(file.size)})</span>
            <span style="color: var(--error); cursor: pointer;" onclick="removeKbFile('${file.name}')">✕</span>
        `;
        div.appendChild(item);
    });
}

function removeKbFile(name) {
    kbSelectedFiles = kbSelectedFiles.filter(f => f.name !== name);
    renderKbFileList();
}

async function uploadKbDocuments() {
    if (kbSelectedFiles.length === 0) {
        alert("Please select files first.");
        return;
    }
    
    const btn = document.querySelector('#kbManageView .btn-primary');
    const originalText = btn.textContent;
    btn.textContent = "Uploading...";
    btn.disabled = true;
    
    try {
        for (const file of kbSelectedFiles) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('account_id', userData.accountId);

            const response = await fetch(`${API_BASE_URL}/knowledgebase/`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error(`Failed to upload ${file.name}`);
        }
        
        kbSelectedFiles = [];
        renderKbFileList();
        loadDocuments();
        alert("Upload complete!");
        
    } catch (e) {
        alert(`Error: ${e.message}`);
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

async function submitRagQuery() {
    const input = document.getElementById('kbQueryInput');
    const question = input.value.trim();
    if (!question) return;
    
    const loading = document.getElementById('kbLoading');
    const resultDiv = document.getElementById('kbResult');
    const answerDiv = document.getElementById('kbAnswerContent');
    const sourcesDiv = document.getElementById('kbSources');
    const btn = document.getElementById('kbSubmitBtn');
    
    loading.style.display = 'block';
    resultDiv.style.display = 'none';
    btn.disabled = true;
    
    try {
        const response = await fetch(`${API_BASE_URL}/knowledgebase/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_id: userData.accountId,
                query: question
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) throw new Error(data.detail || "Error asking question");
        
        answerDiv.innerHTML = formatMarkdown(data.answer);
        
        // Render sources
        if (data.context && data.context.length > 0) {
            sourcesDiv.innerHTML = data.context.map((ctx, i) => `
                <div class="source-item">
                    <div style="font-weight: 600; margin-bottom: 0.25rem; color: var(--primary-light);">Source Chunk ${i+1}</div>
                    <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; line-height: 1.5; color: var(--text-secondary);">${ctx.substring(0, 300)}...</div>
                </div>
            `).join('');
            document.querySelector('.sources-section').style.display = 'block';
        } else {
             document.querySelector('.sources-section').style.display = 'none';
        }
        
        resultDiv.style.display = 'block';
        
    } catch (e) {
        alert(`Error: ${e.message}`);
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
    }
}

// Attach to window for onclick access
window.showKnowledgeBase = showKnowledgeBase;
window.switchKbTab = switchKbTab;
window.deleteDocument = deleteDocument;
window.uploadKbDocuments = uploadKbDocuments;
window.removeKbFile = removeKbFile;
window.submitRagQuery = submitRagQuery;
