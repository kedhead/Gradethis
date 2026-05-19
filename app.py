import os
import re
import json
import tempfile
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import pdfplumber
from docx import Document
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc"}

MAX_TEXT_LENGTH = 25000  # ~15k words, covers most student papers

# PHI scrubbing — applied before text reaches the Claude API
_PHI_PATTERNS = [
    # Social Security Numbers: 123-45-6789 or 123 45 6789
    (re.compile(r'\b\d{3}[-\s]\d{2}[-\s]\d{4}\b'), '[SSN REDACTED]'),
    # US phone numbers in common formats
    (re.compile(r'\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'), '[PHONE REDACTED]'),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), '[EMAIL REDACTED]'),
    # Medical Record Numbers / Patient IDs
    (re.compile(r'\b(MRN|Medical\s+Record(?:\s+Number)?|Patient\s+ID|Chart\s+#?)\s*[:#]?\s*\d+\b', re.IGNORECASE),
     r'\1 [ID REDACTED]'),
    # Date of birth when explicitly labeled
    (re.compile(r'\b(DOB|Date\s+of\s+Birth|D\.O\.B\.?)\s*[:#]?\s*\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b', re.IGNORECASE),
     '[DOB REDACTED]'),
    # Patient name when preceded by an explicit label ("Patient: Jane Doe", "Patient Name: Jane Doe")
    (re.compile(r'\b(Patient\s*(?:Name\s*)?[:#]\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)'), r'\1[NAME REDACTED]'),
]


def scrub_phi(text):
    for pattern, replacement in _PHI_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


DEFAULT_RUBRIC = [
    {"name": "Clinical Accuracy & Evidence-Based Practice", "max": 25},
    {"name": "Critical Analysis & Nursing Application", "max": 25},
    {"name": "Organization & Logical Flow", "max": 20},
    {"name": "Scholarly Sources & Citations", "max": 15},
    {"name": "Writing Quality & Professionalism", "max": 15},
]


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def extract_text_from_docx(file_path):
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text_from_google_docs(url):
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError("Invalid Google Docs URL. Please check the link and try again.")
    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    resp = requests.get(export_url, timeout=30)
    if resp.status_code == 403:
        raise ValueError(
            "This Google Doc is not publicly accessible. Please change sharing to "
            '"Anyone with the link can view" and try again.'
        )
    resp.raise_for_status()
    return resp.text.strip()


def analyze_paper_with_claude(text, student_name="", assignment_title="", assignment_context="", rubric=None):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured. Please add it to your .env file.")

    if not rubric:
        rubric = DEFAULT_RUBRIC

    client = anthropic.Anthropic(api_key=api_key)

    # Scrub PHI before the text leaves the server
    text = scrub_phi(text)

    # Truncate very long papers to avoid excessive cost while still covering the full work
    truncated = text[:MAX_TEXT_LENGTH]
    truncation_note = (
        f"\n[Note: Paper was truncated to first {MAX_TEXT_LENGTH} characters for analysis.]"
        if len(text) > MAX_TEXT_LENGTH
        else ""
    )

    assignment_info = f"Assignment: {assignment_title}" if assignment_title else "Assignment: Not specified"
    context_info = (
        f"Assignment context/instructions: {assignment_context}"
        if assignment_context
        else "Assignment context: General pediatric nursing paper"
    )

    # Build dynamic criteria block — use the exact criterion name as the JSON key
    crit_lines = []
    for item in rubric:
        ex_score = round(item["max"] * 0.85)
        crit_lines.append(
            f'      "{item["name"]}": {{"score": {ex_score}, "max": {item["max"]}, "feedback": "Specific feedback on this criterion..."}}'
        )
    criteria_block = ",\n".join(crit_lines)

    total_pts = sum(item["max"] for item in rubric)
    rubric_rules = "\n".join(
        f'- Criterion "{item["name"]}": score must be integer 0-{item["max"]}'
        for item in rubric
    )

    prompt = f"""You are an expert academic evaluator for a pediatrics nursing program at the university level. Analyze the following student paper thoroughly and return ONLY valid JSON — no markdown, no extra text, just the JSON object.

{assignment_info}
{context_info}
{truncation_note}

--- PAPER CONTENT ---
{truncated}
--- END PAPER ---

Return this exact JSON structure (fill in all fields):

{{
  "ai_detection": {{
    "likelihood": "Very Unlikely",
    "score": 5,
    "confidence": "Medium",
    "indicators": ["Example indicator 1", "Example indicator 2"],
    "explanation": "Detailed explanation of findings..."
  }},
  "summary": {{
    "main_topic": "1-2 sentence description of the main topic",
    "key_points": ["Key point 1", "Key point 2", "Key point 3"],
    "conclusion": "Brief summary of the paper's conclusion",
    "full_summary": "Comprehensive 3-5 sentence summary of the entire paper"
  }},
  "grade": {{
    "letter_grade": "B+",
    "percentage": 87,
    "criteria": {{
{criteria_block}
    }},
    "strengths": ["Strength 1", "Strength 2", "Strength 3"],
    "improvements": ["Area for improvement 1", "Area for improvement 2"],
    "overall_feedback": "A comprehensive paragraph providing overall feedback on the paper, suitable for sharing directly with the student."
  }},
  "clinical_completeness": {{
    "condition_identified": "The specific pediatric condition or clinical topic this paper is about",
    "completeness_score": 72,
    "completeness_label": "Adequate",
    "checklist": [
      {{
        "category": "Assessment & Diagnosis",
        "items": [
          {{"element": "Clinical signs and symptoms", "present": true, "note": "Specific note about what was/wasn't covered"}},
          {{"element": "Diagnostic workup (labs, imaging, cultures)", "present": false, "note": "Specific note"}},
          {{"element": "Vital sign monitoring and interpretation", "present": true, "note": "Specific note"}}
        ]
      }},
      {{
        "category": "Treatment & Pharmacology",
        "items": [
          {{"element": "First-line medication(s) with dosing context", "present": true, "note": "Specific note"}},
          {{"element": "Supportive therapies (oxygen, IV fluids, etc.)", "present": false, "note": "Specific note"}},
          {{"element": "Pediatric-specific dosing or safety considerations", "present": false, "note": "Specific note"}}
        ]
      }},
      {{
        "category": "Nursing Interventions",
        "items": [
          {{"element": "Evidence-based nursing actions for this condition", "present": true, "note": "Specific note"}},
          {{"element": "Monitoring parameters and frequency", "present": false, "note": "Specific note"}},
          {{"element": "Escalation criteria / when to call provider", "present": false, "note": "Specific note"}}
        ]
      }},
      {{
        "category": "Patient & Family Education",
        "items": [
          {{"element": "Medication teaching", "present": false, "note": "Specific note"}},
          {{"element": "Home care instructions / follow-up", "present": true, "note": "Specific note"}},
          {{"element": "Return precautions / warning signs", "present": false, "note": "Specific note"}}
        ]
      }}
    ],
    "clinical_concerns": [
      "Describe any specific clinical content that is factually wrong, irrelevant to this diagnosis, or potentially dangerous if applied — be direct and specific, e.g. 'Student recommends insulin administration which has no role in pneumonia management'"
    ],
    "critical_omissions": [
      "List the most important clinical elements that are completely absent and would be expected in any competent paper on this topic"
    ],
    "summary": "2-3 sentence overall assessment of clinical completeness and accuracy."
  }},
  "currency_check": {{
    "overall_currency": "Current",
    "currency_score": 88,
    "outdated_items": [
      {{
        "claim": "Exact quote or close paraphrase of what the student wrote",
        "issue": "Why this is outdated — which guideline or study it conflicts with and when it was superseded",
        "current_guidance": "What the current evidence-based recommendation actually says, citing the specific guideline or organization if possible (e.g. AAP 2023, PALS 2020, WHO 2022)",
        "severity": "High"
      }}
    ],
    "outdated_citations": [
      "Description of any references cited by the student that are outdated given more recent evidence — e.g. 'Cites a 2004 study on antibiotic dosing; AAP revised these recommendations in 2021'"
    ],
    "confirmed_current": [
      "Specific things the student correctly stated that align with current guidelines — e.g. 'Correctly recommends amoxicillin as first-line per AAP 2023 CAP guidelines'"
    ],
    "knowledge_cutoff_note": "This currency check reflects medical guidelines and evidence available up to the AI knowledge cutoff. Very recent guideline updates may not be captured. Always verify critical recommendations against live sources such as AAP, CDC, UpToDate, or Cochrane.",
    "summary": "2-3 sentence assessment of how current the paper's medical information is and what the most important currency issues are."
  }}
}}

Rules for each field:
- ai_detection.likelihood: MUST be one of exactly: "Very Unlikely", "Possibly AI-Generated", "Likely AI-Generated", "Very Likely AI-Generated"
- ai_detection.score: integer 0-100 (0=clearly human, 100=clearly AI)
- ai_detection.confidence: MUST be one of: "Low", "Medium", "High"
- ai_detection.indicators: list 2-5 specific textual observations (both human and AI signals)
- grade.letter_grade: MUST be one of: "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"
- grade.percentage: integer 0-100, must match letter_grade (A=93+, A-=90-92, B+=87-89, B=83-86, B-=80-82, C+=77-79, C=73-76, C-=70-72, D+=67-69, D=63-66, D-=60-62, F=<60)
- grade.criteria: use EXACTLY these criterion names as JSON keys (case-sensitive): {', '.join(f'"{item["name"]}"' for item in rubric)}
{rubric_rules}
- All criterion scores must sum to approximately match percentage × {total_pts} / 100 (within 1 point)
- Be specific and actionable in all feedback fields
- For AI detection: be nuanced — clear, polished writing alone is not evidence of AI; look for uniform sentence rhythm, lack of personal clinical insight, generic transitions, absence of specific patient/case references, and overly hedged or perfectly balanced arguments
- clinical_completeness.completeness_label: MUST be one of: "Excellent", "Strong", "Adequate", "Weak", "Incomplete"
- clinical_completeness.completeness_score: integer 0-100 reflecting how completely the paper covers clinically expected content for this diagnosis
- clinical_completeness checklist: tailor ALL items specifically to the condition identified — do not use generic items; each element should name what is expected for THIS diagnosis in a pediatric nursing context
- clinical_completeness.clinical_concerns: if there is nothing wrong or irrelevant, return an empty array []
- clinical_completeness.critical_omissions: list only truly critical gaps, not minor ones; if paper is comprehensive return []
- Be direct and frank about clinical_concerns — if a student wrote something dangerous or nonsensical, say so clearly
- currency_check.overall_currency: MUST be one of: "Current", "Mostly Current", "Some Outdated Content", "Significantly Outdated"
- currency_check.currency_score: integer 0-100 (100 = fully current; 0 = dangerously out of date)
- currency_check.outdated_items.severity: MUST be one of: "High", "Medium", "Low"
  - High = clinically significant error that could affect patient safety if applied
  - Medium = deviates from current guidelines but not immediately dangerous
  - Low = minor currency issue (e.g. older terminology, slightly dated reference)
- currency_check.outdated_items: be specific — name the exact claim, explain WHY it's outdated, and state the current recommendation with the authoritative source
- currency_check.outdated_citations: flag references older than ~10 years IF newer evidence exists that changes the recommendation; don't flag old citations that are still valid
- currency_check.confirmed_current: list 2-5 specific things the student got right per current standards — this is important for balance
- If all content appears current, outdated_items and outdated_citations should be empty arrays []
- Focus on pediatric-specific currency: AAP guidelines, PALS protocols, CDC vaccine schedules, WHO pediatric recommendations, and recent RCTs/meta-analyses in pediatric nursing
- Do NOT flag content as outdated just because it's older — only flag it if the recommendation has actually changed"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip any accidental markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        student_name = request.form.get("student_name", "").strip()
        assignment_title = request.form.get("assignment_title", "").strip()
        assignment_context = request.form.get("assignment_context", "").strip()
        rubric_name = request.form.get("rubric_name", "Custom Rubric").strip()
        input_type = request.form.get("input_type", "file")
        text = ""

        # Parse rubric from form data
        rubric = None
        rubric_json = request.form.get("rubric", "").strip()
        if rubric_json:
            try:
                rubric = json.loads(rubric_json)
                if not isinstance(rubric, list) or not rubric:
                    rubric = None
            except (json.JSONDecodeError, ValueError):
                rubric = None

        if input_type == "file":
            if "file" not in request.files:
                return jsonify({"error": "No file uploaded."}), 400
            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "No file selected."}), 400
            if not allowed_file(f.filename):
                return jsonify({"error": "Unsupported file type. Please upload a PDF or Word document (.pdf, .docx)."}), 400

            filename = secure_filename(f.filename)
            ext = filename.rsplit(".", 1)[1].lower()

            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                f.save(tmp.name)
                tmp_path = tmp.name

            try:
                if ext == "pdf":
                    text = extract_text_from_pdf(tmp_path)
                else:
                    text = extract_text_from_docx(tmp_path)
            finally:
                os.unlink(tmp_path)

        elif input_type == "gdocs":
            url = request.form.get("gdocs_url", "").strip()
            if not url:
                return jsonify({"error": "Please enter a Google Docs URL."}), 400
            text = extract_text_from_google_docs(url)

        elif input_type == "text":
            text = request.form.get("paste_text", "").strip()
            if not text:
                return jsonify({"error": "Please paste the paper text before analyzing."}), 400

        else:
            return jsonify({"error": "Invalid input type."}), 400

        if not text or len(text.strip()) < 100:
            return jsonify({"error": "The paper appears to be empty or too short to analyze (minimum ~100 characters)."}), 400

        result = analyze_paper_with_claude(text, student_name, assignment_title, assignment_context, rubric)
        result["word_count"] = len(text.split())
        result["student_name"] = student_name
        result["assignment_title"] = assignment_title
        result["rubric_name"] = rubric_name
        return jsonify(result)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except json.JSONDecodeError:
        return jsonify({"error": "Unexpected response from AI. Please try again."}), 500
    except Exception as e:
        app.logger.error(f"Analysis error: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
