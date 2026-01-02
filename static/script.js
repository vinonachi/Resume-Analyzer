let currentResumeId = null;
let selectedFile = null;

        const fileInput = document.getElementById('fileInput');
        const uploadSection = document.getElementById('uploadSection');
        const selectedFileDiv = document.getElementById('selectedFile');
        const uploadBtn = document.getElementById('uploadBtn');
        const statusMessage = document.getElementById('statusMessage');
        const loader = document.getElementById('loader');
        const generateSection = document.getElementById('generateSection');
        const generateBtn = document.getElementById('generateBtn');
        const questionsSection = document.getElementById('questionsSection');
        const questionsList = document.getElementById('questionsList');
        const questionCount = document.getElementById('questionCount');
        const resetBtn = document.getElementById('resetBtn');

        // File selection
        fileInput.addEventListener('change', (e) => {
            selectedFile = e.target.files[0];
            if (selectedFile) {
                selectedFileDiv.textContent = `Selected: ${selectedFile.name}`;
                selectedFileDiv.classList.add('show');
                uploadBtn.disabled = false;
            }
        });

        // Drag and drop
        uploadSection.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadSection.classList.add('dragover');
        });

        uploadSection.addEventListener('dragleave', () => {
            uploadSection.classList.remove('dragover');
        });

        uploadSection.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadSection.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                selectedFile = files[0];
                selectedFileDiv.textContent = `Selected: ${selectedFile.name}`;
                selectedFileDiv.classList.add('show');
                uploadBtn.disabled = false;
            }
        });

        // Upload resume
        uploadBtn.addEventListener('click', async () => {
            if (!selectedFile) return;

            const formData = new FormData();
            formData.append('file', selectedFile);

            uploadBtn.disabled = true;
            loader.classList.add('show');
            showStatus('Uploading resume...', 'processing');

            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();

                if (response.ok) {
                    currentResumeId = data.resume_id;
                    showStatus('Resume uploaded! Processing...', 'processing');
                    checkProcessingStatus(currentResumeId);
                } else {
                    showStatus(`Error: ${data.error}`, 'error');
                    uploadBtn.disabled = false;
                    loader.classList.remove('show');
                }
            } catch (error) {
                showStatus(`Upload failed: ${error.message}`, 'error');
                uploadBtn.disabled = false;
                loader.classList.remove('show');
            }
        });

        // Check processing status
        async function checkProcessingStatus(resumeId) {
            const maxAttempts = 60;
            let attempts = 0;

            const interval = setInterval(async () => {
                try {
                    const response = await fetch(`/status/${resumeId}`);
                    const data = await response.json();

                    if (data.status === 'done') {
                        clearInterval(interval);
                        loader.classList.remove('show');
                        showStatus('✅ Resume processed successfully!', 'success');
                        generateSection.classList.add('show');
                        resetBtn.style.display = 'block';
                    } else if (data.status.startsWith('error')) {
                        clearInterval(interval);
                        loader.classList.remove('show');
                        showStatus(`❌ Processing error: ${data.status}`, 'error');
                        uploadBtn.disabled = false;
                    } else if (attempts >= maxAttempts) {
                        clearInterval(interval);
                        loader.classList.remove('show');
                        showStatus('⏱️ Processing timeout. Please try again.', 'error');
                        uploadBtn.disabled = false;
                    }

                    attempts++;
                } catch (error) {
                    clearInterval(interval);
                    loader.classList.remove('show');
                    showStatus(`Status check failed: ${error.message}`, 'error');
                }
            }, 2000);
        }

        // Generate questions
        generateBtn.addEventListener('click', async () => {
            if (!currentResumeId) return;

            const count = parseInt(questionCount.value);
            if (count < 1 || count > 20) {
                showStatus('Please enter a number between 1 and 20', 'error');
                return;
            }

            generateBtn.disabled = true;
            loader.classList.add('show');
            showStatus('Generating questions...', 'processing');
            questionsList.innerHTML = '';
            questionsSection.classList.remove('show');

            try {
                const response = await fetch('/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        resume_id: currentResumeId,
                        count: count
                    })
                });

                const data = await response.json();

                if (response.ok && data.questions) {
                    loader.classList.remove('show');
                    statusMessage.classList.remove('show');
                    displayQuestions(data.questions);
                    generateBtn.disabled = false;
                } else {
                    showStatus(`Error: ${data.error || 'Failed to generate questions'}`, 'error');
                    loader.classList.remove('show');
                    generateBtn.disabled = false;
                }
            } catch (error) {
                showStatus(`Generation failed: ${error.message}`, 'error');
                loader.classList.remove('show');
                generateBtn.disabled = false;
            }
        });

        // Display questions
        function displayQuestions(questions) {
            questionsList.innerHTML = '';
            questions.forEach((q, index) => {
                const card = document.createElement('div');
                card.className = 'question-card';
                card.style.animationDelay = `${index * 0.1}s`;

                const difficultyClass = `difficulty-${q.difficulty}`;

                card.innerHTML = `
                    <div class="question-header">
                        <span class="question-type">${q.type || 'general'}</span>
                        <span class="question-difficulty ${difficultyClass}">${q.difficulty || 'medium'}</span>
                    </div>
                    <div class="question-text">
                        <strong>Q${index + 1}:</strong> ${q.question}
                    </div>
                `;

                questionsList.appendChild(card);
            });

            questionsSection.classList.add('show');
        }

        // Show status message
        function showStatus(message, type) {
            statusMessage.textContent = message;
            statusMessage.className = `status ${type} show`;
        }

        // Reset button
        resetBtn.addEventListener('click', () => {
            location.reload();
        });