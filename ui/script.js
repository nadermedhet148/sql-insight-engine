// Configuration
const API_BASE_URL = 'http://localhost:8001';

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
    document.getElementById('onboarding').style.display = 'none';
    document.getElementById('queryInterface').style.display = 'block';
    document.getElementById('currentAccount').textContent = userData.accountId;
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

            tabs.forEach(t => t.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(`${tabName}-tab`).classList.add('active');
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

                const errorMsg = statusData.result?.error_message || statusData.message || 'Query processing failed';
                displayError(errorMsg, statusData.result?.call_stack);
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
        'generate_query': 'step2Load',
        'execute_query': 'step3Load',
        'format_result': 'step4Load'
    };

    callStack.forEach(step => {
        const elementId = stepMapping[step.step_name];
        if (elementId && step.status === 'success') {
            const element = document.getElementById(elementId);
            if (element) {
                element.classList.add('completed');
                element.classList.add('active'); // Keep it visible
            }
        }
    });
}


function displayResults(data) {
    // Display formatted response
    document.getElementById('formattedResponse').innerHTML = formatMarkdown(data.formatted_response);

    // Display reasoning - now includes call stack
    let reasoningText = '';

    if (data.call_stack && data.call_stack.length > 0) {
        reasoningText = '';
        data.call_stack.forEach((step, index) => {
            const stepTitle = step.step_name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
            reasoningText += `【 STEP ${index + 1}: ${stepTitle} 】\n`;
            reasoningText += `❯ Status: ${step.status.toUpperCase()}\n`;
            if (step.duration_ms != null) {
                reasoningText += `❯ Duration: ${step.duration_ms.toFixed(2)}ms\n`;
            }

            // Render Metadata based on step type
            if (step.metadata) {
                const meta = step.metadata;

                if (meta.prompt) {
                    reasoningText += `\n--- LLM PROMPT ---\n${meta.prompt}\n`;
                }

                if (meta.llm_reasoning) {
                    reasoningText += `\n--- LLM REASONING ---\n${meta.llm_reasoning}\n`;
                }

                if (meta.tools_used && meta.tools_used.length > 0) {
                    reasoningText += `\n--- TOOLS USED ---\n`;
                    meta.tools_used.forEach(tool => {
                        reasoningText += `  • ${tool.tool}(${JSON.stringify(tool.args)})\n`;
                    });
                }

                if (meta.available_tables) {
                    reasoningText += `\n--- TABLES FOUND ---\n${meta.available_tables.join(', ')}\n`;
                }

                if (meta.sql) {
                    reasoningText += `\n--- SQL EXECUTED ---\n${meta.sql}\n`;
                }

                if (meta.usage) {
                    reasoningText += `\n--- TOKEN USAGE ---\n`;
                    reasoningText += `  • Prompt: ${meta.usage.prompt_token_count}\n`;
                    reasoningText += `  • Response: ${meta.usage.candidates_token_count}\n`;
                    reasoningText += `  • Total: ${meta.usage.total_token_count}\n`;
                }
            }
            reasoningText += '\n' + '='.repeat(40) + '\n\n';
        });

        if (data.total_duration_ms) {
            reasoningText += `TOTAL EXECUTION TIME: ${data.total_duration_ms.toFixed(2)}ms\n`;
        }
    } else if (data.reasoning) {
        reasoningText = data.reasoning;
    } else {
        reasoningText = 'No reasoning available';
    }

    document.getElementById('reasoningContent').textContent = reasoningText;

    // Display SQL query
    document.getElementById('sqlQuery').textContent = data.generated_sql || 'No SQL query generated';

    // Display raw results
    const rawResultsDiv = document.getElementById('rawResults');
    if (data.raw_results) {
        rawResultsDiv.innerHTML = formatMarkdownTable(data.raw_results);
    } else {
        rawResultsDiv.textContent = 'No raw results available';
    }

    // Show results
    document.getElementById('results').style.display = 'block';

    // Scroll to results
    document.getElementById('results').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function displayError(message, callStack = null) {
    let errorText = message;

    if (callStack && callStack.length > 0) {
        errorText += '\n\n=== Call Stack ===\n';
        callStack.forEach((step, index) => {
            errorText += `\n${index + 1}. ${step.step_name} - ${step.status}`;
            if (step.duration_ms) {
                errorText += ` (${step.duration_ms.toFixed(2)}ms)`;
            }
        });
    }

    document.getElementById('errorMessage').textContent = errorText;
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
