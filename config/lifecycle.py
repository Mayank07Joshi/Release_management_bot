"""
Product Delivery Lifecycle — Gate → Phase → Step hierarchy.

Sourced from: Product_Delivery_Lifecycle_Flowchart.html

Structure
---------
6 Gates  →  14 Phases  →  70 Steps

Rules
-----
  Phase complete   = ALL steps in that phase checked
  Gate complete    = ALL phases in that gate complete
  Lifecycle done   = ALL 6 gates complete

Keys
----
  gate_key   : "g1" … "g6"
  phase_key  : "p1" … "p14"
  step_key   : "p{phase_num}_s{step_num:02d}"  e.g. "p1_s01", "p11_s09"
"""

from __future__ import annotations

LIFECYCLE: list[dict] = [
    # ── Gate 1: DoR Gate ─────────────────────────────────────────────────────
    {
        "key":   "g1",
        "label": "DoR Gate",
        "desc":  "Definition of Ready — story fully defined before design begins",
        "color": "#818cf8",
        "phases": [
            {
                "key":   "p1",
                "label": "User Story & Requirements Definition",
                "steps": [
                    {"key": "p1_s01", "label": "Clear problem statement & job-to-be-done defined"},
                    {"key": "p1_s02", "label": "User personas & business context documented"},
                    {"key": "p1_s03", "label": "Acceptance criteria written (Given / When / Then)"},
                    {"key": "p1_s04", "label": "Happy path + edge cases + error states covered"},
                    {"key": "p1_s05", "label": "In-scope & out-of-scope sections defined"},
                    {"key": "p1_s06", "label": "Dependencies & integrations identified"},
                    {"key": "p1_s07", "label": "NFRs: performance, security, compliance, compatibility"},
                    {"key": "p1_s08", "label": "Input/output data definitions & API contracts (draft)"},
                    {"key": "p1_s09", "label": "Success metrics / KPIs defined"},
                    {"key": "p1_s10", "label": "QA(s) assigned early — Shift Left Testing"},
                    {"key": "p1_s11", "label": "Mobile: platform-specific behavior (iOS vs Android) stated"},
                    {"key": "p1_s12", "label": "Mobile: offline support, analytics tracking requirements"},
                ],
            },
        ],
    },

    # ── Gate 2: Design Freeze Gate ───────────────────────────────────────────
    {
        "key":   "g2",
        "label": "Design Freeze Gate",
        "desc":  "High-fidelity designs signed off and frozen for development",
        "color": "#c084fc",
        "phases": [
            {
                "key":   "p2",
                "label": "Design — Requirements Gathering & Research",
                "steps": [
                    {"key": "p2_s01", "label": "Understand target users (personas, roles)"},
                    {"key": "p2_s02", "label": "Identify areas the new requirement will impact"},
                    {"key": "p2_s03", "label": "Define user problems being solved"},
                    {"key": "p2_s04", "label": "Competitive research & R&D conducted (Designer & Akarsh)"},
                    {"key": "p2_s05", "label": "Low-fidelity wireframes created"},
                    {"key": "p2_s06", "label": "Wireframes align with design system"},
                ],
            },
            {
                "key":   "p3",
                "label": "Design — Review, Sign-offs & Freeze",
                "steps": [
                    {"key": "p3_s01", "label": "Internal Design Discussion — review wireframes for feedback"},
                    {"key": "p3_s02", "label": "High-fidelity UI designs created from approved wireframes"},
                    {"key": "p3_s03", "label": "Internal Design Sign-off — follows design system standards"},
                    {"key": "p3_s04", "label": "First Design Sign-off by User Story Owner / Sunil"},
                    {"key": "p3_s05", "label": "Playback Session with Sunil, QA & Dev Team — address implementation challenges"},
                    {"key": "p3_s06", "label": "Final Design Sign-off by Management Team"},
                    {"key": "p3_s07", "label": "Design Freeze — no further modifications allowed"},
                    {"key": "p3_s08", "label": "Figma link shared with Story Owner & Developers"},
                    {"key": "p3_s09", "label": "Icons, images & assets provided in required resolutions"},
                ],
            },
        ],
    },

    # ── Gate 3: Story Freeze Gate ────────────────────────────────────────────
    {
        "key":   "g3",
        "label": "Story Freeze Gate",
        "desc":  "Story understood, feasibility confirmed, estimation complete",
        "color": "#34d399",
        "phases": [
            {
                "key":   "p4",
                "label": "Playback — Understanding Validation",
                "steps": [
                    {"key": "p4_s01", "label": "Team restates requirements & expected outcomes"},
                    {"key": "p4_s02", "label": "Confirm technical feasibility"},
                    {"key": "p4_s03", "label": "Identify risks & dependencies"},
                    {"key": "p4_s04", "label": "Update story with clarifications"},
                    {"key": "p4_s05", "label": "Create flowchart of the functionality"},
                    {"key": "p4_s06", "label": "QA: feedback documented via VSTS tickets to story owner"},
                    {"key": "p4_s07", "label": "Designs updated with any new changes"},
                    {"key": "p4_s08", "label": "Mobile: internal team discussion pre-playback"},
                    {"key": "p4_s09", "label": "Mobile: flow designs & Low-Level Document prepared"},
                    {"key": "p4_s10", "label": "Story freezes after all changes verified"},
                ],
            },
            {
                "key":   "p5",
                "label": "Estimation Phase",
                "steps": [
                    {"key": "p5_s01", "label": "Developers provide effort estimation"},
                    {"key": "p5_s02", "label": "Discuss technical complexity, testing effort & dependencies"},
                    {"key": "p5_s03", "label": "Analyse and build logical framework / LLD"},
                    {"key": "p5_s04", "label": "Record estimation in standard Estimation Sheet"},
                    {"key": "p5_s05", "label": "Define estimated completion timeline"},
                    {"key": "p5_s06", "label": "Mobile: get approval from Arjan & Sunita"},
                    {"key": "p5_s07", "label": "Create tasks in VSTS related to all story tasks"},
                ],
            },
        ],
    },

    # ── Gate 4: Dev Complete Gate ────────────────────────────────────────────
    {
        "key":   "g4",
        "label": "Dev Complete Gate",
        "desc":  "Development finished, self-verified, and handed over to QA",
        "color": "#60a5fa",
        "phases": [
            {
                "key":   "p6",
                "label": "Development Phase",
                "steps": [
                    {"key": "p6_s01", "label": "Get all required HTML from Design Team"},
                    {"key": "p6_s02", "label": "Check API requirement doc from Mobile for their needs"},
                    {"key": "p6_s03", "label": "Code development initiated"},
                    {"key": "p6_s04", "label": "Conduct regular internal syncs for progress"},
                    {"key": "p6_s05", "label": "Perform unit testing"},
                    {"key": "p6_s06", "label": "Integrate with dependent modules"},
                    {"key": "p6_s07", "label": "Begin parallel integration & testing"},
                    {"key": "p6_s08", "label": "Mobile: API endpoints defined & documented"},
                    {"key": "p6_s09", "label": "Mobile: request/response formats shared"},
                    {"key": "p6_s10", "label": "Mobile: auth & error handling mechanisms described"},
                    {"key": "p6_s11", "label": "Mobile: mock data / Postman collections available"},
                    {"key": "p6_s12", "label": "Mobile: impact analysis of code changes"},
                    {"key": "p6_s13", "label": "Track continuous progress"},
                ],
            },
            {
                "key":   "p7",
                "label": "Progress Demo & Feedback Loop",
                "steps": [
                    {"key": "p7_s01", "label": "Present current working version to stakeholders"},
                    {"key": "p7_s02", "label": "Capture stakeholder feedback"},
                    {"key": "p7_s03", "label": "Document required changes or improvements"},
                    {"key": "p7_s04", "label": "Update acceptance criteria if needed"},
                    {"key": "p7_s05", "label": "Rework (if any) completed and retested"},
                ],
            },
            {
                "key":   "p8",
                "label": "Development Complete / Code Freeze",
                "steps": [
                    {"key": "p8_s01", "label": "Code finalized and stable"},
                    {"key": "p8_s02", "label": "Unit testing completed"},
                    {"key": "p8_s03", "label": "Developer self-verification done"},
                    {"key": "p8_s04", "label": "Supporting / technical documentation provided"},
                    {"key": "p8_s05", "label": "Internal handover to QA"},
                ],
            },
        ],
    },

    # ── Gate 5: QA Gate ──────────────────────────────────────────────────────
    {
        "key":   "g5",
        "label": "QA Gate",
        "desc":  "Test cases written, demo validated, three-environment testing complete",
        "color": "#fb923c",
        "phases": [
            {
                "key":   "p9",
                "label": "QA — Test Case Development",
                "steps": [
                    {"key": "p9_s01", "label": "Story version frozen before creating test cases"},
                    {"key": "p9_s02", "label": "Test cases written at granular level (each step highlighted)"},
                    {"key": "p9_s03", "label": "Functional & non-functional test cases for all enhancements"},
                    {"key": "p9_s04", "label": "Screen verification, text verification, performance test cases"},
                    {"key": "p9_s05", "label": "Peer review by assigned QAs"},
                    {"key": "p9_s06", "label": "Test cases finalized into manual & automation suites"},
                ],
            },
            {
                "key":   "p10",
                "label": "QA — Demo Validation",
                "steps": [
                    {"key": "p10_s01", "label": "Ticket well documented with all related discussions"},
                    {"key": "p10_s02", "label": "All screens in user story are up to date"},
                    {"key": "p10_s03", "label": "No open comments on user story"},
                    {"key": "p10_s04", "label": "All positive cases covered"},
                    {"key": "p10_s05", "label": "No open bugs against the user story"},
                    {"key": "p10_s06", "label": "Strings reviewed with @Sunita"},
                ],
            },
            {
                "key":   "p11",
                "label": "QA Testing — DEV → QA → Production Environments",
                "steps": [
                    {"key": "p11_s01", "label": "DEV ENV: test enhancements (per test cases) + bugs"},
                    {"key": "p11_s02", "label": "DEV ENV: impact area testing, sanity >98%, no P1 issues"},
                    {"key": "p11_s03", "label": "QA ENV: end-to-end use case testing, aim for prod-ready build"},
                    {"key": "p11_s04", "label": "QA ENV: upgrade testing on mobile, notification testing"},
                    {"key": "p11_s05", "label": "QA ENV: Apple-ready & Android-ready build tests"},
                    {"key": "p11_s06", "label": "QA ENV: sanity >98%, no P1 issues"},
                    {"key": "p11_s07", "label": "PROD ENV: upgrade testing, notification testing, new subscriber testing"},
                    {"key": "p11_s08", "label": "PROD ENV: verification of enhancements & watch-list items"},
                    {"key": "p11_s09", "label": "PROD ENV: sanity >98%, no P1 issues"},
                ],
            },
        ],
    },

    # ── Gate 6: Ship Gate ────────────────────────────────────────────────────
    {
        "key":   "g6",
        "label": "Ship Gate",
        "desc":  "Business sign-off obtained, deployed, knowledge transferred",
        "color": "#f87171",
        "phases": [
            {
                "key":   "p12",
                "label": "Final Demo & Business Sign-Off",
                "steps": [
                    {"key": "p12_s01", "label": "Final demo scheduled with stakeholders"},
                    {"key": "p12_s02", "label": "Demonstrate all acceptance criteria"},
                    {"key": "p12_s03", "label": "Address final queries or minor issues"},
                    {"key": "p12_s04", "label": "Obtain formal sign-off"},
                    {"key": "p12_s05", "label": "Update final documentation"},
                    {"key": "p12_s06", "label": "Design-Dev sign-off (designer verifies implementation)"},
                ],
            },
            {
                "key":   "p13",
                "label": "Deployment & Build Submission",
                "steps": [
                    {"key": "p13_s01", "label": "Release notes prepared"},
                    {"key": "p13_s02", "label": "Deployment log created"},
                    {"key": "p13_s03", "label": "Web deployment executed"},
                    {"key": "p13_s04", "label": "Mobile: update release notes for stores"},
                    {"key": "p13_s05", "label": "Mobile: upload builds to Play Store & App Store"},
                    {"key": "p13_s06", "label": "Mobile: publish builds & run upgrade scripts"},
                    {"key": "p13_s07", "label": "Play Store / App Store images updated"},
                    {"key": "p13_s08", "label": "Closure on all release items with remarks"},
                ],
            },
            {
                "key":   "p14",
                "label": "Knowledge Transfer (KT)",
                "steps": [
                    {"key": "p14_s01", "label": "KT sessions scheduled with all relevant team members"},
                    {"key": "p14_s02", "label": "Functionality walkthrough completed"},
                    {"key": "p14_s03", "label": "Technical implementation details shared"},
                    {"key": "p14_s04", "label": "Process details & decisions documented"},
                    {"key": "p14_s05", "label": "Team capability built, risks reduced"},
                ],
            },
        ],
    },
]


# ── Lookup / aggregate helpers ─────────────────────────────────────────────────

def _build_step_index() -> dict[str, tuple[str, str]]:
    """Returns {step_key: (gate_key, phase_key)} for O(1) lookups."""
    idx: dict[str, tuple[str, str]] = {}
    for gate in LIFECYCLE:
        for phase in gate["phases"]:
            for step in phase["steps"]:
                idx[step["key"]] = (gate["key"], phase["key"])
    return idx


def _build_step_label_index() -> dict[str, str]:
    """Returns {step_key: step_label}."""
    return {
        step["key"]: step["label"]
        for gate in LIFECYCLE
        for phase in gate["phases"]
        for step in phase["steps"]
    }


STEP_INDEX:       dict[str, tuple[str, str]] = _build_step_index()
STEP_LABELS:      dict[str, str]             = _build_step_label_index()

PHASE_STEP_COUNT: dict[str, int] = {
    phase["key"]: len(phase["steps"])
    for gate in LIFECYCLE
    for phase in gate["phases"]
}

GATE_STEP_COUNT: dict[str, int] = {
    gate["key"]: sum(len(p["steps"]) for p in gate["phases"])
    for gate in LIFECYCLE
}

TOTAL_STEPS: int = sum(GATE_STEP_COUNT.values())
