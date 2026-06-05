"""
generate_docs.py
Generates two Word documents:
  1. tech_brief.docx      — 1-pager system tech brief
  2. validation_questions.docx — validator questionnaire
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import datetime


# ── Helpers ────────────────────────────────────────────────────────────────────

def set_cell_bg(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def heading(doc, text, level=1, color="1f3864", size=14, bold=True, space_before=10):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(*bytes.fromhex(color))
    return p


def body(doc, text, size=10, space_before=0, space_after=4, italic=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.italic = italic
    return p


def bullet(doc, text, size=10):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(size)
    return p


def divider(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "2c3e50")
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p


# ══════════════════════════════════════════════════════════════════════════════
# 1. TECH BRIEF
# ══════════════════════════════════════════════════════════════════════════════

def build_tech_brief():
    doc = Document()

    # Page margins (narrow for 1-pager)
    for section in doc.sections:
        section.top_margin    = Cm(1.8)
        section.bottom_margin = Cm(1.8)
        section.left_margin   = Cm(2.2)
        section.right_margin  = Cm(2.2)

    # ── Title block ────────────────────────────────────────────────────────────
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.paragraph_format.space_after = Pt(2)
    r = t.add_run("TECHNICAL BRIEF")
    r.bold = True; r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x9c, 0xa3, 0xaf)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(2)
    tr = title.add_run(
        "Evaluating the Performance of Gated Recurrent Units\n"
        "for Multi-Parameter Weather Forecasting"
    )
    tr.bold = True; tr.font.size = Pt(15)
    tr.font.color.rgb = RGBColor(0x1f, 0x38, 0x64)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(6)
    sr = sub.add_run(
        "University of the Cordilleras  ·  College of CITCS  ·  "
        "B.S. Computer Science\n"
        "Castro, E. M.  ·  Millan, D. J. S.  ·  Mondoñedo, J. E."
    )
    sr.font.size = Pt(9)
    sr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    divider(doc)

    # ── Two-column layout via table ────────────────────────────────────────────
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.columns[0].width = Cm(8.8)
    tbl.columns[1].width = Cm(7.8)
    left  = tbl.rows[0].cells[0]
    right = tbl.rows[0].cells[1]

    # Remove table borders
    for cell in [left, right]:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "none")
            tcBorders.append(el)
        tcPr.append(tcBorders)

    # ── LEFT COLUMN ────────────────────────────────────────────────────────────
    def lh(text, **kw):
        p = left.add_paragraph()
        p.paragraph_format.space_before = Pt(kw.get("sb", 8))
        p.paragraph_format.space_after  = Pt(2)
        r = p.add_run(text)
        r.bold = True; r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0x1f, 0x38, 0x64)
        return p

    def lb(text):
        p = left.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(3)
        r = p.add_run(text)
        r.font.size = Pt(9.5)
        return p

    def lbul(text):
        p = left.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(1)
        r = p.add_run(text)
        r.font.size = Pt(9.5)
        return p

    lh("Overview", sb=0)
    lb(
        "This system is a web-based platform that fetches real daily weather data "
        "from Meteostat and benchmarks five machine learning models — GRU, LSTM, "
        "SimpleRNN, Linear Regression, and ARIMA — for multi-variable weather "
        "forecasting across two Philippine stations: Baguio City and Manila."
    )

    lh("Problem Statement")
    lb(
        "Weather forecasting in the Philippines relies on general-purpose models "
        "not specifically benchmarked against local station data. This study "
        "evaluates whether GRU, a modern recurrent architecture, outperforms "
        "traditional and alternative deep learning approaches for four key "
        "meteorological variables."
    )

    lh("Target Variables")
    for v in [
        "Precipitation (prcp) — daily rainfall in mm",
        "Temperature (temp)   — average daily temperature in °C",
        "Wind Speed (wspd)    — average daily wind speed in km/h",
        "Pressure (pres)      — mean sea-level pressure in hPa",
    ]:
        lbul(v)

    lh("Stations Covered")
    lbul("Baguio City  (Meteostat Station ID: 98328)")
    lbul("Manila           (Meteostat Station ID: 98425)")

    lh("Data Source & Period")
    lb("Meteostat Open Weather API  ·  January 1, 2020 — Present (dynamic)")

    # ── RIGHT COLUMN ───────────────────────────────────────────────────────────
    def rh(text, sb=8):
        p = right.add_paragraph()
        p.paragraph_format.space_before = Pt(sb)
        p.paragraph_format.space_after  = Pt(2)
        r = p.add_run(text)
        r.bold = True; r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0x1f, 0x38, 0x64)
        return p

    def rb(text):
        p = right.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(3)
        r = p.add_run(text)
        r.font.size = Pt(9.5)
        return p

    def rbul(text):
        p = right.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(1)
        r = p.add_run(text)
        r.font.size = Pt(9.5)
        return p

    rh("Models Compared", sb=0)
    for m in [
        "GRU            — 3-layer Bidirectional, hidden=256",
        "LSTM          — 3-layer Bidirectional, hidden=256",
        "SimpleRNN  — 3-layer Unidirectional, hidden=256",
        "Linear Regression  — flattened-sequence multivariate",
        "ARIMA        — auto_arima (AIC, stepwise, seasonal=False)",
    ]:
        rbul(m)

    rh("Evaluation Metrics")
    for m in [
        "Accuracy (%)  =  100 − MAPE",
        "Mean Squared Error (MSE)",
        "Mean Absolute Error (MAE)",
        "Coefficient of Determination (R²)",
    ]:
        rbul(m)

    rh("Technology Stack")
    stack_rows = [
        ("Language",   "Python 3.10+"),
        ("Deep Learning", "PyTorch 2.x (CUDA / MPS / CPU)"),
        ("ARIMA",      "pmdarima (auto_arima)"),
        ("Data",       "Meteostat API"),
        ("Preprocessing", "scikit-learn, pandas, NumPy"),
        ("Web UI",     "Streamlit"),
        ("Plots",      "Matplotlib"),
    ]
    stbl = right.add_table(rows=len(stack_rows), cols=2)
    stbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, (k, v) in enumerate(stack_rows):
        c0, c1 = stbl.rows[i].cells
        c0.width = Cm(3.0); c1.width = Cm(4.6)
        bg = "eaf0fb" if i % 2 == 0 else "ffffff"
        set_cell_bg(c0, bg); set_cell_bg(c1, bg)
        p0 = c0.paragraphs[0]; p1 = c1.paragraphs[0]
        r0 = p0.add_run(k);   r0.bold = True;  r0.font.size = Pt(8.5)
        r1 = p1.add_run(v);   r1.font.size = Pt(8.5)

    rh("Live Demo")
    p = right.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    p.add_run("🔗 ").font.size = Pt(9.5)
    link_run = p.add_run(
        "thesis-gru-evaluation-in-weather-forecasting.streamlit.app"
    )
    link_run.font.size = Pt(8.5)
    link_run.font.color.rgb = RGBColor(0x1f, 0x77, 0xb4)
    link_run.underline = True

    rh("Source Code")
    p2 = right.add_paragraph()
    p2.paragraph_format.space_after = Pt(2)
    p2.add_run("🔗 ").font.size = Pt(9.5)
    gr = p2.add_run(
        "github.com/EzekelCastro/Thesis-GRU-Evaluation-in-Weather-Forecasting"
    )
    gr.font.size = Pt(8.5)
    gr.font.color.rgb = RGBColor(0x1f, 0x77, 0xb4)
    gr.underline = True

    divider(doc)

    foot = doc.add_paragraph()
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    foot.paragraph_format.space_before = Pt(4)
    fr = foot.add_run(
        f"University of the Cordilleras  ·  Baguio City, Benguet, Philippines  ·  {datetime.date.today().year}"
    )
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor(0x9c, 0xa3, 0xaf)

    doc.save("tech_brief.docx")
    print("Saved: tech_brief.docx")


# ══════════════════════════════════════════════════════════════════════════════
# 2. VALIDATION QUESTIONNAIRE
# ══════════════════════════════════════════════════════════════════════════════

def build_validation():
    doc = Document()

    for section in doc.sections:
        section.top_margin    = Cm(2.2)
        section.bottom_margin = Cm(2.2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # Title
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.paragraph_format.space_after = Pt(2)
    t.add_run("SYSTEM VALIDATION QUESTIONNAIRE").bold = True
    t.runs[0].font.size = Pt(13)
    t.runs[0].font.color.rgb = RGBColor(0x1f, 0x38, 0x64)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(4)
    sr = sub.add_run(
        "GRU Evaluation in Multi-Parameter Weather Forecasting System\n"
        "University of the Cordilleras  ·  B.S. Computer Science"
    )
    sr.font.size = Pt(9.5)
    sr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    divider(doc)

    # Instructions
    inst = doc.add_paragraph()
    inst.paragraph_format.space_before = Pt(6)
    inst.paragraph_format.space_after  = Pt(6)
    ir = inst.add_run(
        "Instructions:  Please rate each statement using the scale below. "
        "Write the number that best reflects your evaluation in the 'Rating' column. "
        "Additional comments are welcome in the 'Remarks' column."
    )
    ir.font.size = Pt(9.5)
    ir.italic = True

    # Scale legend
    scale_tbl = doc.add_table(rows=2, cols=5)
    scale_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["5 — Strongly Agree", "4 — Agree", "3 — Neutral",
               "2 — Disagree", "1 — Strongly Disagree"]
    colors  = ["1f3864",             "2980b9",    "7f8c8d",
               "e67e22",             "c0392b"]
    for j, (h, c) in enumerate(zip(headers, colors)):
        cell = scale_tbl.rows[0].cells[j]
        set_cell_bg(cell, c)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h)
        r.bold = True; r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0xff, 0xff, 0xff)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # ── Question sections ──────────────────────────────────────────────────────
    sections_data = [
        (
            "A.  Usability",
            "1f3864",
            [
                "The system interface is clean and easy to navigate.",
                "The sidebar controls (date range, station, model selection) are intuitive and easy to understand.",
                "The labels, axis titles, and chart legends are clear and informative.",
                "The system provides sufficient feedback during long-running operations (e.g., progress bar, status messages).",
                "I was able to run the analysis and interpret the results without needing external assistance.",
                "The tabs (Predictions, Metrics, Download) are logically organized and easy to switch between.",
                "The download feature works as expected and produces a usable output.",
            ],
        ),
        (
            "B.  System Performance",
            "1a5276",
            [
                "The system loads and responds within a reasonable time frame.",
                "The progress bar accurately reflects the training progress.",
                "The system handles multiple models and stations without crashing or freezing.",
                "The system works consistently across multiple runs with the same settings.",
                "Error messages or warnings, if any, are understandable and helpful.",
            ],
        ),
        (
            "C.  Accuracy & Reliability of Results",
            "145a32",
            [
                "The prediction plots clearly show the difference between actual and predicted values.",
                "The metrics (MSE, MAE, R², Accuracy) are presented in a way that allows meaningful comparison across models.",
                "The bar charts in the Metrics tab effectively visualize model performance differences.",
                "The 'Best Model per Variable' summary table is helpful for drawing conclusions.",
                "The results appear consistent and trustworthy based on the data presented.",
            ],
        ),
        (
            "D.  Relevance & Completeness",
            "4a235a",
            [
                "The choice of weather variables (Precipitation, Temperature, Wind Speed, Pressure) is appropriate for the study.",
                "The selection of stations (Baguio City and Manila) is relevant to the Philippine context.",
                "The five models compared (GRU, LSTM, SimpleRNN, Linear Regression, ARIMA) represent a sufficient range for benchmarking.",
                "The evaluation metrics used are appropriate for assessing forecasting model performance.",
                "The system as a whole addresses the research objectives of the study.",
            ],
        ),
        (
            "E.  Overall Assessment",
            "2c3e50",
            [
                "The system is suitable as a tool for evaluating weather forecasting models in an academic context.",
                "I would recommend this system as a reference for similar comparative studies.",
                "Overall, I am satisfied with the quality and functionality of this system.",
            ],
        ),
    ]

    for sec_title, color_hex, questions in sections_data:
        # Section heading
        sh = doc.add_paragraph()
        sh.paragraph_format.space_before = Pt(10)
        sh.paragraph_format.space_after  = Pt(4)
        r = sh.add_run(sec_title)
        r.bold = True; r.font.size = Pt(11)
        c = bytes.fromhex(color_hex)
        r.font.color.rgb = RGBColor(c[0], c[1], c[2])

        # Question table
        qtbl = doc.add_table(rows=1 + len(questions), cols=3)
        qtbl.style = "Table Grid"
        qtbl.alignment = WD_TABLE_ALIGNMENT.CENTER

        # Set column widths
        qtbl.columns[0].width = Cm(0.8)
        qtbl.columns[1].width = Cm(10.5)
        qtbl.columns[2].width = Cm(2.5)

        # Header row
        hdr_cells = qtbl.rows[0].cells
        hdr_labels = ["No.", "Statement", "Rating (1–5)"]
        for j, lbl in enumerate(hdr_labels):
            set_cell_bg(hdr_cells[j], color_hex)
            p = hdr_cells[j].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(lbl)
            r.bold = True; r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0xff, 0xff, 0xff)

        # Question rows
        for i, q in enumerate(questions):
            row = qtbl.rows[i + 1]
            bg = "eaf0fb" if i % 2 == 0 else "ffffff"

            # No.
            set_cell_bg(row.cells[0], bg)
            p0 = row.cells[0].paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r0 = p0.add_run(str(i + 1))
            r0.font.size = Pt(9)

            # Statement
            set_cell_bg(row.cells[1], bg)
            p1 = row.cells[1].paragraphs[0]
            r1 = p1.add_run(q)
            r1.font.size = Pt(9.5)

            # Rating box
            set_cell_bg(row.cells[2], bg)
            row.cells[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # Open-ended section
    divider(doc)
    oe = doc.add_paragraph()
    oe.paragraph_format.space_before = Pt(8)
    oer = oe.add_run("F.  Open-Ended Feedback")
    oer.bold = True; oer.font.size = Pt(11)
    oer.font.color.rgb = RGBColor(0x2c, 0x3e, 0x50)

    open_qs = [
        "What aspect of the system do you find most useful or well-implemented?",
        "What aspect of the system needs the most improvement?",
        "Do you have any suggestions for additional features or changes to the current design?",
        "Any other comments, observations, or recommendations?",
    ]
    for q in open_qs:
        pq = doc.add_paragraph()
        pq.paragraph_format.space_before = Pt(8)
        pq.paragraph_format.space_after  = Pt(0)
        rq = pq.add_run(q)
        rq.bold = True; rq.font.size = Pt(9.5)
        # Answer lines
        for _ in range(2):
            pl = doc.add_paragraph()
            pl.paragraph_format.space_before = Pt(2)
            pl.paragraph_format.space_after  = Pt(0)
            pPr = pl._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "4")
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), "aaaaaa")
            pBdr.append(bottom)
            pPr.append(pBdr)

    # Signature block
    divider(doc)
    sig = doc.add_paragraph()
    sig.paragraph_format.space_before = Pt(10)
    sig.paragraph_format.space_after  = Pt(0)
    sig.add_run("Validator's Name: ").bold = True
    sig.runs[0].font.size = Pt(9.5)
    sig.add_run("_" * 35 + "      ")
    sig.add_run("Signature: ").bold = True
    sig.runs[-1].font.size = Pt(9.5)
    sig.add_run("_" * 25)

    sig2 = doc.add_paragraph()
    sig2.paragraph_format.space_before = Pt(6)
    sig2.add_run("Position / Expertise: ").bold = True
    sig2.runs[0].font.size = Pt(9.5)
    sig2.add_run("_" * 30 + "      ")
    sig2.add_run("Date: ").bold = True
    sig2.runs[-1].font.size = Pt(9.5)
    sig2.add_run("_" * 20)

    doc.save("validation_questions.docx")
    print("Saved: validation_questions.docx")


if __name__ == "__main__":
    build_tech_brief()
    build_validation()
    print("\nDone.")
