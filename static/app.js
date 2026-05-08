/* GradeThis — frontend logic */
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────
  let selectedFile = null;
  let activeInputTab = 'file';

  // ── Element refs ────────────────────────────────────────────────────────
  const uploadSection   = document.getElementById('upload-section');
  const loadingSection  = document.getElementById('loading-section');
  const errorBanner     = document.getElementById('error-banner');
  const errorText       = document.getElementById('error-text');
  const resultsSection  = document.getElementById('results-section');

  const dropzone        = document.getElementById('dropzone');
  const fileInput       = document.getElementById('file-input');
  const browseBtn       = document.getElementById('browse-btn');
  const fileSelected    = document.getElementById('file-selected');
  const fileNameDisplay = document.getElementById('file-name-display');
  const removeFileBtn   = document.getElementById('remove-file');

  const analyzeBtn      = document.getElementById('analyze-btn');
  const analyzeAnotherBtn = document.getElementById('analyze-another-btn');

  // ── Input tabs ──────────────────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      activeInputTab = btn.dataset.tab;
      document.getElementById(`panel-${activeInputTab}`).classList.add('active');
      hideError();
    });
  });

  // ── Result tabs ─────────────────────────────────────────────────────────
  document.querySelectorAll('.result-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.result-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.result-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`result-panel-${btn.dataset.resultTab}`).classList.add('active');
    });
  });

  // ── File drag & drop ────────────────────────────────────────────────────
  dropzone.addEventListener('click', (e) => {
    if (e.target !== browseBtn) fileInput.click();
  });
  browseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  ['dragenter', 'dragover'].forEach(evt => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(evt => {
    dropzone.addEventListener(evt, () => dropzone.classList.remove('drag-over'));
  });
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files.length) handleFileSelect(files[0]);
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) handleFileSelect(fileInput.files[0]);
  });

  removeFileBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearFile();
  });

  function handleFileSelect(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['pdf', 'docx', 'doc'].includes(ext)) {
      showError('Unsupported file type. Please upload a PDF or Word document (.pdf, .docx).');
      return;
    }
    if (file.size > 16 * 1024 * 1024) {
      showError('File is too large. Maximum size is 16 MB.');
      return;
    }
    selectedFile = file;
    fileNameDisplay.textContent = file.name;
    dropzone.hidden = true;
    fileSelected.hidden = false;
    hideError();
  }

  function clearFile() {
    selectedFile = null;
    fileInput.value = '';
    dropzone.hidden = false;
    fileSelected.hidden = true;
  }

  // ── Analyze ──────────────────────────────────────────────────────────────
  analyzeBtn.addEventListener('click', submitAnalysis);

  async function submitAnalysis() {
    hideError();

    const formData = new FormData();
    formData.append('input_type', activeInputTab);
    formData.append('student_name', document.getElementById('student-name').value.trim());
    formData.append('assignment_title', document.getElementById('assignment-title').value.trim());
    formData.append('assignment_context', document.getElementById('assignment-context').value.trim());

    if (activeInputTab === 'file') {
      if (!selectedFile) { showError('Please select a file to upload.'); return; }
      formData.append('file', selectedFile);
    } else if (activeInputTab === 'gdocs') {
      const url = document.getElementById('gdocs-url').value.trim();
      if (!url) { showError('Please enter a Google Docs URL.'); return; }
      formData.append('gdocs_url', url);
    } else {
      const text = document.getElementById('paste-text').value.trim();
      if (!text) { showError('Please paste the paper text before analyzing.'); return; }
      formData.append('paste_text', text);
    }

    uploadSection.hidden = true;
    loadingSection.hidden = false;
    resultsSection.hidden = true;
    analyzeBtn.disabled = true;

    const loadingMessages = [
      'Extracting paper text…',
      'Reading the paper…',
      'Checking for AI patterns…',
      'Evaluating clinical accuracy…',
      'Generating grade and feedback…',
    ];
    let msgIdx = 0;
    const msgEl = document.getElementById('loading-msg');
    const msgInterval = setInterval(() => {
      msgIdx = (msgIdx + 1) % loadingMessages.length;
      msgEl.textContent = loadingMessages[msgIdx];
    }, 4500);

    try {
      const resp = await fetch('/analyze', { method: 'POST', body: formData });
      const data = await resp.json();
      clearInterval(msgInterval);

      if (!resp.ok || data.error) {
        throw new Error(data.error || 'Analysis failed. Please try again.');
      }

      loadingSection.hidden = true;
      renderResults(data);
      resultsSection.hidden = false;

    } catch (err) {
      clearInterval(msgInterval);
      loadingSection.hidden = true;
      uploadSection.hidden = false;
      showError(err.message || 'Unexpected error. Please try again.');
    } finally {
      analyzeBtn.disabled = false;
    }
  }

  // ── Render results ────────────────────────────────────────────────────────
  function renderResults(data) {
    const { ai_detection: ai, summary, grade, word_count, student_name, assignment_title } = data;

    // Header
    const titleParts = [];
    if (student_name)     titleParts.push(student_name);
    if (assignment_title) titleParts.push(assignment_title);
    document.getElementById('results-title').textContent =
      titleParts.length ? `Results — ${titleParts.join(' · ')}` : 'Analysis Results';
    document.getElementById('results-subtitle').textContent =
      `${(word_count || 0).toLocaleString()} words analyzed`;

    // ── Stats row ──
    // Grade stat
    const letterEl = document.getElementById('stat-letter');
    letterEl.textContent = grade.letter_grade;
    letterEl.style.color = gradeColor(grade.letter_grade);
    document.getElementById('stat-pct').textContent = `${grade.percentage}%`;

    // AI stat
    const aiLikelihood = document.getElementById('stat-ai-likelihood');
    aiLikelihood.textContent = ai.likelihood;
    aiLikelihood.style.color = aiColor(ai.score);
    document.getElementById('stat-ai-score').textContent = `${ai.score}% likelihood`;

    // Words
    document.getElementById('stat-words').textContent = (word_count || 0).toLocaleString();

    // ── Summary tab ──
    document.getElementById('full-summary').textContent = summary.full_summary;
    document.getElementById('conclusion-text').textContent = summary.conclusion;
    const kpList = document.getElementById('key-points');
    kpList.innerHTML = '';
    (summary.key_points || []).forEach(pt => {
      const li = document.createElement('li');
      li.textContent = pt;
      kpList.appendChild(li);
    });

    // ── AI Detection tab ──
    const score = ai.score || 0;
    const meterFill = document.getElementById('ai-meter-fill');
    meterFill.style.width = `${score}%`;
    meterFill.style.setProperty('--pct', score);

    const badge = document.getElementById('ai-badge');
    badge.textContent = ai.likelihood;
    badge.className = 'meter-badge ' + aiLikelihoodClass(ai.likelihood);

    const confChip = document.getElementById('ai-confidence-chip');
    confChip.textContent = `Confidence: ${ai.confidence}`;
    confChip.className = 'meta-chip ' + (ai.confidence || '').toLowerCase();

    document.getElementById('ai-score-chip').textContent = `Score: ${score}/100`;
    document.getElementById('ai-explanation').textContent = ai.explanation;

    const indList = document.getElementById('ai-indicators');
    indList.innerHTML = '';
    (ai.indicators || []).forEach(ind => {
      const li = document.createElement('li');
      li.textContent = ind;
      indList.appendChild(li);
    });

    // ── Grade tab ──
    const gradeCircle = document.getElementById('grade-circle');
    gradeCircle.className = 'grade-circle ' + gradeCSSClass(grade.letter_grade);
    document.getElementById('grade-circle-letter').textContent = grade.letter_grade;
    document.getElementById('grade-pct-big').textContent = `${grade.percentage}%`;

    const criteriaMap = {
      clinical_accuracy:  'Clinical Accuracy & Evidence-Based Practice',
      critical_analysis:  'Critical Analysis & Nursing Application',
      organization:       'Organization & Logical Flow',
      sources_citations:  'Scholarly Sources & Citations',
      writing_quality:    'Writing Quality & Professionalism',
    };

    const critList = document.getElementById('criteria-list');
    critList.innerHTML = '';
    Object.entries(criteriaMap).forEach(([key, label]) => {
      const crit = (grade.criteria || {})[key];
      if (!crit) return;
      const pct = Math.round((crit.score / crit.max) * 100);
      const div = document.createElement('div');
      div.className = 'criterion';
      div.innerHTML = `
        <div class="crit-header">
          <span class="crit-name">${label}</span>
          <span class="crit-score">${crit.score}/${crit.max}</span>
        </div>
        <div class="crit-bar-track">
          <div class="crit-bar-fill" style="width:${pct}%; background:${criterionColor(pct)}"></div>
        </div>
        <p class="crit-feedback">${crit.feedback}</p>
      `;
      critList.appendChild(div);
    });

    const strengthsList = document.getElementById('strengths-list');
    strengthsList.innerHTML = '';
    (grade.strengths || []).forEach(s => {
      const li = document.createElement('li');
      li.textContent = s;
      strengthsList.appendChild(li);
    });

    const improvsList = document.getElementById('improvements-list');
    improvsList.innerHTML = '';
    (grade.improvements || []).forEach(s => {
      const li = document.createElement('li');
      li.textContent = s;
      improvsList.appendChild(li);
    });

    document.getElementById('overall-feedback').textContent = grade.overall_feedback;

    // Reset result tabs to Summary
    document.querySelectorAll('.result-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.result-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('[data-result-tab="summary"]').classList.add('active');
    document.getElementById('result-panel-summary').classList.add('active');

    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── Analyze another ───────────────────────────────────────────────────────
  analyzeAnotherBtn.addEventListener('click', () => {
    clearFile();
    document.getElementById('gdocs-url').value = '';
    document.getElementById('paste-text').value = '';
    document.getElementById('student-name').value = '';
    document.getElementById('assignment-title').value = '';
    document.getElementById('assignment-context').value = '';
    resultsSection.hidden = true;
    uploadSection.hidden = false;
    hideError();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  function showError(msg) {
    errorText.textContent = msg;
    errorBanner.hidden = false;
    errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function hideError() { errorBanner.hidden = true; }

  function gradeColor(letter) {
    if (letter.startsWith('A')) return '#16a34a';
    if (letter.startsWith('B')) return '#0ea5e9';
    if (letter.startsWith('C')) return '#d97706';
    if (letter.startsWith('D')) return '#f97316';
    return '#dc2626';
  }

  function gradeCSSClass(letter) {
    if (letter.startsWith('A')) return 'grade-a';
    if (letter.startsWith('B')) return 'grade-b';
    if (letter.startsWith('C')) return 'grade-c';
    if (letter.startsWith('D')) return 'grade-d';
    return 'grade-f';
  }

  function aiColor(score) {
    if (score < 30) return '#16a34a';
    if (score < 60) return '#d97706';
    return '#dc2626';
  }

  function aiLikelihoodClass(likelihood) {
    const l = (likelihood || '').toLowerCase();
    if (l.includes('very unlikely')) return 'badge-very-unlikely';
    if (l.includes('possibly'))      return 'badge-possibly';
    if (l.includes('very likely'))   return 'badge-very-likely';
    if (l.includes('likely'))        return 'badge-likely';
    return 'badge-very-unlikely';
  }

  function criterionColor(pct) {
    if (pct >= 85) return '#16a34a';
    if (pct >= 70) return '#0ea5e9';
    if (pct >= 55) return '#d97706';
    return '#dc2626';
  }
})();
