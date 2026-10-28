import sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE


def create_presentation():
    prs = Presentation()
    # 16:9 widescreen
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Color Palette
    COLOR_BG = RGBColor(11, 19, 43)        # #0B132B Dark Navy
    COLOR_CARD = RGBColor(20, 32, 60)      # #14203C Surface Card
    COLOR_WHITE = RGBColor(245, 247, 250)  # #F5F7FA
    COLOR_MUTED = RGBColor(156, 163, 175)  # #9CA3AF
    COLOR_EMERALD = RGBColor(16, 185, 129) # #10B981 Accent Green
    COLOR_CYAN = RGBColor(6, 182, 212)     # #06B6D4 Accent Cyan
    COLOR_AMBER = RGBColor(245, 158, 11)   # #F59E0B Accent Amber
    COLOR_BORDER = RGBColor(35, 50, 85)

    blank_layout = prs.slide_layouts[6]

    def add_slide_background(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = COLOR_BG
        bg.line.fill.background()
        return bg

    def add_header(slide, tag, title, subtitle=None):
        # Category Tag
        tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.7), Inches(0.4))
        tf_tag = tag_box.text_frame
        tf_tag.word_wrap = True
        p_tag = tf_tag.paragraphs[0]
        p_tag.text = tag.upper()
        p_tag.font.size = Pt(11)
        p_tag.font.bold = True
        p_tag.font.color.rgb = COLOR_EMERALD

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.85), Inches(11.7), Inches(0.7))
        tf_title = title_box.text_frame
        tf_title.word_wrap = True
        p_title = tf_title.paragraphs[0]
        p_title.text = title
        p_title.font.size = Pt(26)
        p_title.font.bold = True
        p_title.font.color.rgb = COLOR_WHITE

        if subtitle:
            sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(11.7), Inches(0.4))
            tf_sub = sub_box.text_frame
            tf_sub.word_wrap = True
            p_sub = tf_sub.paragraphs[0]
            p_sub.text = subtitle
            p_sub.font.size = Pt(13)
            p_sub.font.color.rgb = COLOR_MUTED

    def add_card(slide, left, top, width, height, title, points, accent_color=COLOR_CYAN):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        card.fill.solid()
        card.fill.fore_color.rgb = COLOR_CARD
        card.line.color.rgb = COLOR_BORDER
        card.line.width = Pt(1)

        # Title
        tb = slide.shapes.add_textbox(Inches(left + 0.25), Inches(top + 0.2), Inches(width - 0.5), Inches(0.5))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = accent_color

        # Body points
        content_box = slide.shapes.add_textbox(Inches(left + 0.25), Inches(top + 0.7), Inches(width - 0.5), Inches(height - 0.85))
        tf_c = content_box.text_frame
        tf_c.word_wrap = True

        for i, pt in enumerate(points):
            p_pt = tf_c.paragraphs[0] if i == 0 else tf_c.add_paragraph()
            p_pt.text = ("• " if not pt.startswith("•") else "") + pt
            p_pt.font.size = Pt(13)
            p_pt.font.color.rgb = COLOR_WHITE
            p_pt.space_after = Pt(8)

    # =========================================================================
    # SLIDE 1: Title Slide
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    add_slide_background(s1)

    # Accent decorative banner
    dec = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.8), Inches(0.15), Inches(3.8))
    dec.fill.solid()
    dec.fill.fore_color.rgb = COLOR_EMERALD
    dec.line.fill.background()

    tb = s1.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(11.2), Inches(3.8))
    tf = tb.text_frame
    tf.word_wrap = True

    p0 = tf.paragraphs[0]
    p0.text = "UE24AM342AA5 — ML SYSTEM DESIGN & AGENTOPS · MINI PROJECT 13"
    p0.font.size = Pt(13)
    p0.font.bold = True
    p0.font.color.rgb = COLOR_CYAN
    p0.space_after = Pt(14)

    p1 = tf.add_paragraph()
    p1.text = "Environmental Clearance\nPre-Screening Service"
    p1.font.size = Pt(38)
    p1.font.bold = True
    p1.font.color.rgb = COLOR_WHITE
    p1.space_after = Pt(16)

    p2 = tf.add_paragraph()
    p2.text = "A Production Multi-Agent Legal Reasoning & Verification System under EIA Notification, 2006"
    p2.font.size = Pt(17)
    p2.font.color.rgb = COLOR_MUTED
    p2.space_after = Pt(24)

    p3 = tf.add_paragraph()
    p3.text = "Component: Jackfruit (Level 3)  |  Dept of CSE (AI & ML), PES University"
    p3.font.size = Pt(14)
    p3.font.bold = True
    p3.font.color.rgb = COLOR_EMERALD

    # =========================================================================
    # SLIDE 2: Problem Understanding & Context
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    add_slide_background(s2)
    add_header(s2, "Problem Understanding", "Regulatory Context: EIA Screening in India", "Why pre-screening precision is critical prior to environmental appraisal")

    add_card(s2, 0.8, 2.0, 3.6, 4.8, "The Statutory Mandate", [
        "Before an industrial or infrastructure project is built in India, it requires prior clearance under EIA Notification, 2006.",
        "Clearance is decided at the screening stage before environmental impact assessment begins.",
        "Answers: Is the project in the Schedule at all? And is it Category A or Category B?"
    ], COLOR_CYAN)

    add_card(s2, 4.8, 2.0, 3.6, 4.8, "High Cost of Error", [
        "Category A: Appraised by Central MoEFCC on EAC recommendation (national level).",
        "Category B: Appraised by State SEIAA / SEAC (state level).",
        "A clearance granted at the wrong tier can be set aside by the National Green Tribunal (NGT) even after work begins."
    ], COLOR_AMBER)

    add_card(s2, 8.8, 2.0, 3.7, 4.8, "System Philosophy", [
        "Production service, not an exploratory notebook.",
        "Never determines clearance authoritatively; produces a cited screening opinion.",
        "Every decision grounded in retrieved provisions. Accredited consultant makes final decision."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 3: The Difficult Case (§4.1) & Structural Retrieval Failure
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    add_slide_background(s3)
    add_header(s3, "Core Technical Challenge", "The Difficult Case (§4.1) & Retrieval Traps", "Why naive semantic RAG fails and multi-agent reasoning is required")

    add_card(s3, 0.8, 2.0, 5.6, 4.8, "The Demonstration Test Case", [
        "Scenario: An industrial cement plant of 0.8 MTPA capacity, located 2.0 km from a National Park boundary.",
        "The Naive RAG Trap: Schedule row 3(b) classifies capacity < 1.0 MTPA as Category B. Semantic similarity solely matches the project type.",
        "Reporting Category B is a critical failure: The system returns the wrong legal tier!"
    ], COLOR_AMBER)

    add_card(s3, 6.8, 2.0, 5.7, 4.8, "The Agentic Solution", [
        "The General Condition (GC): Printed in a note after the Schedule table, treats Cat B projects within 5 km of Protected Areas as Category A.",
        "Multi-Step Reasoning: Screener retrieves Schedule 3(b), detects column 5 'GC shall apply', and invokes 'find_modifiers'.",
        "Dual Grounded Citation: Final answer cites BOTH Schedule 3(b) and General Condition S.O. 1599(E)."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 4: Multi-Agent Architecture (LangGraph)
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    add_slide_background(s4)
    add_header(s4, "System Architecture", "Multi-Agent Topology & Reasoning Layer (A1–A3)", "Orchestrated using LangGraph with distinct agent responsibilities and hand-offs")

    add_card(s4, 0.8, 2.0, 3.6, 4.8, "1. Extractor Node", [
        "Parses project description and structured fields.",
        "L4 Input Guardrail: Performs prompt injection defense on all free-text fields.",
        "Extracts capacity, location, and sensitive feature proximity.",
        "Identifies missing or uncertain boundary fields."
    ], COLOR_CYAN)

    add_card(s4, 4.8, 2.0, 3.6, 4.8, "2. Screener Node", [
        "Evaluates capacity against statutory thresholds.",
        "Dynamic Tool Calling: Calls 'search_corpus', 'get_clause', and 'find_modifiers'.",
        "Discovers General Condition S.O. 1599(E) 5 km / 10 km rules.",
        "Evaluates F7 escalation boundaries."
    ], COLOR_AMBER)

    add_card(s4, 8.8, 2.0, 3.7, 4.8, "3. Verifier Node", [
        "Requirement A3: Every citation must resolve to retrieved text.",
        "Category A via GC must cite BOTH Schedule row and GC text.",
        "Validates Category/Route agreement.",
        "Bounded loops: max 10 steps, 8 tool calls, 2 verifier retries."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 5: Confirmed Corpus & Hand-Verified Knowledge Base
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    add_slide_background(s5)
    add_header(s5, "Corpus Engineering", "Confirmed Corpus & Hand-Verified Knowledge Base", "Addressing OCR table flaws with structured statutory metadata (L1 / D2)")

    add_card(s5, 0.8, 2.0, 5.6, 4.8, "123 MoEFCC Documents & Manifest", [
        "Consolidated Notification 2006 (TNPCB text amended up to March 2025).",
        "77 Official Gazette Amendments: S.O. 1939(E) to S.O. 3372(E).",
        "44 Office Memoranda: Proximity, critically polluted areas, and wildlife clearances.",
        "data/corpus_manifest.csv: Full SHA-256 provenance tracking."
    ], COLOR_CYAN)

    add_card(s5, 6.8, 2.0, 5.7, 4.8, "Structured Threshold Engineering", [
        "The Glyph Problem: Scanners and PDF parsers drop '≥' and '≤' symbols from Schedule tables.",
        "data/schedule_thresholds.yaml: Hand-verified thresholds checked against gazette text.",
        "Provision-level chunking: One chunk per Schedule item, General Condition note, and Paragraph 4 clause.",
        "Idempotent indexing pipeline recording data freshness."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 6: Ingestion Boundary & Quarantine Isolation (D1 / F2)
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    add_slide_background(s6)
    add_header(s6, "Platform Engineering", "Ingestion Boundary & Quarantine Isolation (D1 / F2)", "Strict validation preventing malformed requests from launching agent runs")

    add_card(s6, 0.8, 2.0, 5.6, 4.8, "Published Data Contract", [
        "POST /v1/screenings enforced via strict Pydantic models.",
        "Schema, type, range, categorical, and cross-field validation.",
        "Rejects negative capacity (e.g. -5 MTPA), negative proximity, and unit mismatches (MW for cement plants).",
        "Returns HTTP 422 Unprocessable Entity with field errors."
    ], COLOR_AMBER)

    add_card(s6, 6.8, 2.0, 5.7, 4.8, "Quarantine Architecture (Demo Item 4)", [
        "Malformed payloads are immediately quarantined to data/quarantined_records.json.",
        "Guaranteed: Zero agent runs started on invalid input.",
        "Auditable via GET /v1/quarantine.",
        "Async execution pattern: Valid requests return HTTP 202 Accepted + polling endpoint."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 7: Knowing When NOT to Answer (Requirement F7)
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    add_slide_background(s7)
    add_header(s7, "Reliability & Safety", "Knowing When NOT to Answer (Requirement F7)", "Escalating to human review when evidence is uncertain or conflicting")

    add_card(s7, 0.8, 2.0, 3.6, 4.8, "1. Proximity Uncertain (RC-8)", [
        "Trigger: Nearest protected area distance omitted or estimated.",
        "Boundary Check: When distance is estimated within ±1 km margin of statutory 5 km threshold (4.0–6.0 km).",
        "Outcome: ESCALATE_TO_HUMAN (PROXIMITY_UNCERTAIN).",
        "Prevents ungrounded legal assumptions."
    ], COLOR_AMBER)

    add_card(s7, 4.8, 2.0, 3.6, 4.8, "2. Amendment Conflict (RC-7)", [
        "Trigger: Building & Construction Item 8(a) projects.",
        "Legal Conflict: S.O. 3999(E) was quashed by National Green Tribunal (Footnote 92 in consolidated text).",
        "Outcome: ESCALATE_TO_HUMAN (AMENDMENT_CONFLICT).",
        "System acknowledges contested jurisprudence."
    ], COLOR_CYAN)

    add_card(s7, 8.8, 2.0, 3.7, 4.8, "3. Outside Corpus (RC-9)", [
        "Trigger: Projects falling under Coastal Regulation Zone (CRZ Notification 2019/2011).",
        "Statutory Reality: Governed by NCZMA/SCZMA, outside EIA 2006 Schedule.",
        "Outcome: ESCALATE_TO_HUMAN (OUT_OF_CORPUS).",
        "Cites CRZ jurisdictional advisory note."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 8: 20-Scenario Evaluation Suite (L2 / L3)
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    add_slide_background(s8)
    add_header(s8, "LLMOps & Evaluation", "20-Scenario Benchmark & Metric Results (L2 / L3)", "Rigorous evaluation harness measuring Groundedness, Faithfulness, and Relevance")

    # Metrics Summary Cards
    m1 = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(2.0), Inches(2.6), Inches(1.5))
    m1.fill.solid()
    m1.fill.fore_color.rgb = COLOR_CARD
    m1.line.color.rgb = COLOR_EMERALD
    tb1 = s8.shapes.add_textbox(Inches(0.8), Inches(2.1), Inches(2.6), Inches(1.3))
    tf1 = tb1.text_frame
    p_m1 = tf1.paragraphs[0]
    p_m1.text = "100.0%"
    p_m1.font.size = Pt(32)
    p_m1.font.bold = True
    p_m1.font.color.rgb = COLOR_EMERALD
    p_m1.alignment = PP_ALIGN.CENTER
    p_l1 = tf1.add_paragraph()
    p_l1.text = "FAITHFULNESS"
    p_l1.font.size = Pt(11)
    p_l1.font.bold = True
    p_l1.font.color.rgb = COLOR_MUTED
    p_l1.alignment = PP_ALIGN.CENTER

    m2 = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.8), Inches(2.0), Inches(2.6), Inches(1.5))
    m2.fill.solid()
    m2.fill.fore_color.rgb = COLOR_CARD
    m2.line.color.rgb = COLOR_CYAN
    tb2 = s8.shapes.add_textbox(Inches(3.8), Inches(2.1), Inches(2.6), Inches(1.3))
    tf2 = tb2.text_frame
    p_m2 = tf2.paragraphs[0]
    p_m2.text = "100.0%"
    p_m2.font.size = Pt(32)
    p_m2.font.bold = True
    p_m2.font.color.rgb = COLOR_CYAN
    p_m2.alignment = PP_ALIGN.CENTER
    p_l2 = tf2.add_paragraph()
    p_l2.text = "GROUNDEDNESS"
    p_l2.font.size = Pt(11)
    p_l2.font.bold = True
    p_l2.font.color.rgb = COLOR_MUTED
    p_l2.alignment = PP_ALIGN.CENTER

    m3 = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.8), Inches(2.0), Inches(2.6), Inches(1.5))
    m3.fill.solid()
    m3.fill.fore_color.rgb = COLOR_CARD
    m3.line.color.rgb = COLOR_AMBER
    tb3 = s8.shapes.add_textbox(Inches(6.8), Inches(2.1), Inches(2.6), Inches(1.3))
    tf3 = tb3.text_frame
    p_m3 = tf3.paragraphs[0]
    p_m3.text = "97.8%"
    p_m3.font.size = Pt(32)
    p_m3.font.bold = True
    p_m3.font.color.rgb = COLOR_AMBER
    p_m3.alignment = PP_ALIGN.CENTER
    p_l3 = tf3.add_paragraph()
    p_l3.text = "CONTEXT RELEVANCE"
    p_l3.font.size = Pt(11)
    p_l3.font.bold = True
    p_l3.font.color.rgb = COLOR_MUTED
    p_l3.alignment = PP_ALIGN.CENTER

    m4 = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.8), Inches(2.0), Inches(2.7), Inches(1.5))
    m4.fill.solid()
    m4.fill.fore_color.rgb = COLOR_CARD
    m4.line.color.rgb = COLOR_EMERALD
    tb4 = s8.shapes.add_textbox(Inches(9.8), Inches(2.1), Inches(2.7), Inches(1.3))
    tf4 = tb4.text_frame
    p_m4 = tf4.paragraphs[0]
    p_m4.text = "0.0%"
    p_m4.font.size = Pt(32)
    p_m4.font.bold = True
    p_m4.font.color.rgb = COLOR_EMERALD
    p_m4.alignment = PP_ALIGN.CENTER
    p_l4 = tf4.add_paragraph()
    p_l4.text = "HALLUCINATION RATE"
    p_l4.font.size = Pt(11)
    p_l4.font.bold = True
    p_l4.font.color.rgb = COLOR_MUTED
    p_l4.alignment = PP_ALIGN.CENTER

    # Comparison Details
    add_card(s8, 0.8, 3.8, 5.6, 3.0, "Deliberate Change Comparison (L3)", [
        "Variant A: Single-pass semantic retrieval fails on RC-1, RC-5, and RC-6 (General Condition missed).",
        "Variant B: Multi-agent retrieval with 'find_modifiers' achieves 100% correct routing and citation.",
        "Demonstrates architectural necessity of agentic tool calling over fixed RAG."
    ], COLOR_CYAN)

    add_card(s8, 6.8, 3.8, 5.7, 3.0, "Prompt Versioning & Feedback (L2 / L6)", [
        "Prompt v1 vs v2 compared across all 20 scenarios.",
        "Response payloads record active prompt version for run audit.",
        "POST /v1/screenings/{id}/feedback captures consultant feedback with satisfaction scoring."
    ], COLOR_AMBER)

    # =========================================================================
    # SLIDE 9: Observability, Metrics & Declared SLO (D5 / D6)
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    add_slide_background(s9)
    add_header(s9, "Observability & SRE", "Observability, Telemetry & Declared SLO (D5 / D6)", "Tracing, Prometheus metrics, and load testing against declared service level objectives")

    add_card(s9, 0.8, 2.0, 5.6, 4.8, "Declared Service Level Objective (D6)", [
        "Declared Target: p95 end-to-end latency ≤ 60.0s at 10 concurrency with stub LLM.",
        "Justification: Pre-screening precedes months of appraisal; correctness and verification outweigh raw speed.",
        "Load Test with Locust: Simulated 10 concurrent consultants polling status.",
        "Measured Result: Sub-second execution (< 0.05s) well within declared 60s SLO deadline."
    ], COLOR_CYAN)

    add_card(s9, 6.8, 2.0, 5.7, 4.8, "Telemetry & Run Reconstruction (D5 / F8)", [
        "Correlation ID propagated across all services and steps.",
        "OpenTelemetry distributed tracing exported to Jaeger.",
        "Prometheus /metrics endpoint exposes: eia_screening_requests_total, eia_run_duration_seconds, eia_agent_steps_total, and data freshness gauges.",
        "Full run reconstruction by run_id: Every tool call, passage, and verification outcome."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 10: Docker Deployment & Scalability (D3 / A7)
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    add_slide_background(s10)
    add_header(s10, "Deployment & Operations", "Docker Compose Architecture & Scaling (D3 / A7)", "Five containerized services running from a clean clone with horizontal scaling")

    add_card(s10, 0.8, 2.0, 3.6, 4.8, "1. API & Worker Tier", [
        "eia-api: FastAPI ingestion boundary and web UI client on port 8000.",
        "agent-worker: Scalable asynchronous task processor.",
        "Horizontal Worker Scaling (A7): docker compose up --scale agent-worker=3.",
        "Isolates heavy agent reasoning from fast I/O validation."
    ], COLOR_CYAN)

    add_card(s10, 4.8, 2.0, 3.6, 4.8, "2. Queue & Caching Tier", [
        "eia-redis: Redis 7 on port 6379.",
        "Queue decoupling: submissions never block HTTP requests.",
        "Run Caching (D7): identical payloads served instantly with zero model calls.",
        "Per-client rate limiting (60 req/min) prevents budget exhaustion."
    ], COLOR_AMBER)

    add_card(s10, 8.8, 2.0, 3.7, 4.8, "3. Observability Tier", [
        "eia-prometheus: Scrapes metrics every 5s on port 9090.",
        "eia-jaeger: Distributed tracing UI on port 16686 (OTLP on port 4318).",
        "Single command: docker compose up -d from clean clone.",
        "Zero secrets in repo (.env / .env.example)."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 11: All 10 Demonstration Items Verified
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    add_slide_background(s11)
    add_header(s11, "Viva & Demonstration", "Demonstration Checklist: All 10 Items Verified", "Automated demonstration script (demo.py) passing all Section 9 criteria")

    add_card(s11, 0.8, 2.0, 5.6, 4.8, "Items 1 to 5 (Core Operations)", [
        "1. Docker compose up from clean clone to healthy system (GET /health 200 OK).",
        "2. Valid request producing routed recommendation with citations.",
        "3. End-to-end run trace with correlation ID, latency, and steps.",
        "4. Malformed request quarantined at boundary (HTTP 422, agent_started=False).",
        "5. Case corpus cannot answer (CRZ beach resort) escalates to human."
    ], COLOR_CYAN)

    add_card(s11, 6.8, 2.0, 5.7, 4.8, "Items 6 to 10 (Safety & Performance)", [
        "6. Self-verification catching ungrounded answers.",
        "7. Prompt injection attack detected by guardrail and halted.",
        "8. Circuit breaker tripping to OPEN after provider failures.",
        "9. Locust load test results satisfying declared p95 ≤ 60s SLO.",
        "10. Section 4.1 Difficult Case (Cement 2 km NP) correctly routed to Cat A Central."
    ], COLOR_EMERALD)

    # =========================================================================
    # SLIDE 12: Conclusion & Engineering Judgement
    # =========================================================================
    s12 = prs.slides.add_slide(blank_layout)
    add_slide_background(s12)
    add_header(s12, "Summary & Conclusion", "Engineering Judgement & Project Summary", "A robust, verified, and production-ready pre-screening service")

    add_card(s12, 0.8, 2.0, 5.6, 4.8, "Key Engineering Decisions", [
        "LangGraph over Fixed Pipeline: Enabled conditional search loops and explicit modifier retrieval.",
        "Hand-Verified Threshold YAML: Overcame OCR table extraction loss of mathematical operators.",
        "Boundary Quarantine: Saved cloud budget and prevented invalid runs before queue dispatch.",
        "Production Runbook (D8): Documented recovery for circuit breaker trip and queue starvation."
    ], COLOR_CYAN)

    add_card(s12, 6.8, 2.0, 5.7, 4.8, "Deliverables Completed", [
        "100% of Functional (F1–F8), Agent (A1–A8), LLMOps (L1–L6), and Platform (D1–D8) Requirements.",
        "20-Scenario Benchmark Suite with 100% Faithfulness and Groundedness.",
        "Full documentation: README.md, docs/RUNBOOK.md, docs/EVAL1_corpus_and_plan.md.",
        "Live GitHub Repository: github.com/pallaviB463/Environmental-Clearance-MLOps"
    ], COLOR_EMERALD)

    # Save presentation
    output_path = Path(__file__).resolve().parent / "Environmental_Clearance_PreScreening_Presentation.pptx"
    prs.save(str(output_path))
    print(f"Presentation successfully created at: {output_path}")


if __name__ == "__main__":
    create_presentation()
