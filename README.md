# GradeThis — Pediatric Nursing Paper Analyzer

A web app for nursing educators to analyze student papers: AI detection, automatic summary, and rubric-based grading.

## Features

- **File upload** — PDF and Word (.docx) documents
- **Google Docs** — paste a public share link
- **Paste text** — directly paste paper content
- **AI Detection** — likelihood score with explanation and key indicators
- **Paper Summary** — topic, key points, conclusion
- **Grade & Feedback** — letter grade + rubric breakdown across 5 criteria:
  - Clinical Accuracy & Evidence-Based Practice (25%)
  - Critical Analysis & Nursing Application (25%)
  - Organization & Logical Flow (20%)
  - Scholarly Sources & Citations (15%)
  - Writing Quality & Professionalism (15%)
- **Print** — results are print-friendly

---

## Quick Start (Local)

### 1. Clone and set up
```bash
git clone <repo-url>
cd Gradethis
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add your API key
```bash
cp .env.example .env
# Edit .env and paste your Anthropic API key
```
Get a key at [console.anthropic.com](https://console.anthropic.com).

### 3. Run
```bash
python app.py
```
Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## Deploy to Vercel

### 1. Install the Vercel CLI
```bash
npm i -g vercel
```

### 2. Add your API key as a secret
```bash
vercel secrets add anthropic_api_key your_api_key_here
```

### 3. Deploy
```bash
vercel --prod
```

> **Note:** Vercel's hobby plan has a 4.5 MB request body limit. Most student papers are well under this. For larger files, use the Google Docs link or paste text options.

---

## Notes

- AI detection is advisory only. No student should face academic consequences based solely on this score.
- Papers are not stored — each analysis is processed in memory and discarded.
- Requires an active internet connection to call the Anthropic API.
