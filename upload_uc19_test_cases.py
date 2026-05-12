"""
UC19 – Internal Improvement: Save & Scan (VSTS: 37047)
VSTS Test Case Uploader  |  Enhancement: 37047
==============================================================
Problem: When a claimant captures a receipt on mobile, uses "Save & Scan",
then selects "Discard Values" on mobile — the web platform still shows the
scanned values (Amount, Date, Supplier) because the server auto-fills the form
and does not honour the discard action.

Solution: Show the same scan-summary (Use Scanned Values / Discard Values) on
web for receipts captured & scanned on mobile. Discard must clear server-side
values too.

Before running: pip install requests
Usage: python upload_uc19_test_cases.py
"""

import requests, json, base64, html, sys, time, re, os

# ── CONFIG ─────────────────────────────────────────────────────────────
PAT               = os.environ.get("ADO_PAT", "")
ORG               = "expenseondemand"
PROJECT           = "Solo Expenses"
ENHANCEMENT_ID    = 37047
FUNCTION_VALUE    = "Create Expense"
ITERATION_PATH    = r"Solo Expenses\2026\Iteration 2026 04-April"
CUSTOM_AREA       = "Web"
CUSTOM_AUTOMATION = "To be automated"
PRIORITY          = 2
DISCOVER_MODE     = False
FUNCTION_FIELD_REF = "Custom.function"

BASE_URL = f"https://dev.azure.com/{ORG}"

def _auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

HEADERS       = _auth_header(PAT)
PATCH_HEADERS = {**_auth_header(PAT), "Content-Type": "application/json-patch+json"}

def discover_function_field():
    url = f"{BASE_URL}/{PROJECT}/_apis/wit/workitemtypes/Test%20Case/fields?api-version=7.0"
    r = requests.get(url, headers=HEADERS); r.raise_for_status()
    for f in r.json().get("value", []):
        name = f.get("name","").lower(); ref = f.get("referenceName","").lower()
        if any(k in name or k in ref for k in ("function","automat","area")):
            print(f"  {f['name']:40s}  {f['referenceName']}")

def build_steps_xml(steps_text, expected_text):
    lines = [l.strip() for l in steps_text.strip().split("\n") if l.strip()]
    steps = [re.sub(r"^\d+[\.\)\s]\s*", "", l).strip() for l in lines]
    steps = [s for s in steps if s]
    parts = [f'<steps id="0" last="{len(steps)}">']
    for i, action in enumerate(steps, start=1):
        esc_a = html.escape(action)
        is_last = (i == len(steps))
        esc_e = html.escape(expected_text) if is_last else ""
        etag  = f"&lt;P&gt;{esc_e}&lt;/P&gt;" if esc_e else ""
        stype = "ValidateStep" if esc_e else "ActionStep"
        parts.append(
            f'<step id="{i}" type="{stype}">'
            f'<parameterizedString isformatted="true">&lt;P&gt;{esc_a}&lt;/P&gt;</parameterizedString>'
            f'<parameterizedString isformatted="true">{etag}</parameterizedString>'
            f'<description/></step>'
        )
    parts.append("</steps>")
    return "".join(parts)

def create_test_case(title, steps_xml, precondition=None):
    url = f"{BASE_URL}/{PROJECT}/_apis/wit/workitems/$Test%20Case?api-version=7.0"
    enh_url = f"{BASE_URL}/_apis/wit/workitems/{ENHANCEMENT_ID}"
    payload = [
        {"op": "add", "path": "/fields/System.Title",                   "value": title},
        {"op": "add", "path": "/fields/System.AreaPath",                "value": PROJECT},
        {"op": "add", "path": "/fields/System.IterationPath",           "value": ITERATION_PATH},
        {"op": "add", "path": "/fields/Custom.Area",                    "value": CUSTOM_AREA},
        {"op": "add", "path": "/fields/Custom.Automation",              "value": CUSTOM_AUTOMATION},
        {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": PRIORITY},
        {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps",       "value": steps_xml},
        {"op": "add", "path": f"/fields/{FUNCTION_FIELD_REF}",          "value": FUNCTION_VALUE},
        {"op": "add", "path": "/relations/-",
         "value": {"rel": "Microsoft.VSTS.Common.TestedBy-Reverse",
                   "url": enh_url,
                   "attributes": {"comment": "UC19 - Save & Scan: Discard Values alignment between mobile and web"}}},
    ]
    if precondition:
        payload.append({"op": "add", "path": "/fields/Microsoft.VSTS.TCM.LocalDataSource", "value": precondition})
    r = requests.post(url, headers=PATCH_HEADERS, data=json.dumps(payload))
    if r.status_code not in (200, 201):
        print(f"  FAILED '{title[:60]}': {r.status_code} {r.text[:300]}")
        return None
    return r.json()["id"]


# ── TEST CASE DATA ──────────────────────────────────────────────────────
# Format: (tc_id, title, precondition, steps, expected_result)

PRE = (
    "Precondition: Claimant is logged into EOD on both mobile (iOS or Android) and web. "
    "A receipt has been captured on mobile using 'Capture Receipt -> Save & Scan'. "
    "The receipt has been successfully scanned by the server and scanned values (Amount, Date, Supplier) are available. "
    "UC19 fix has been deployed."
)

TEST_CASES = [

    # ═══════════════════════════════════════════════════════════════════
    # WEB — SCAN SUMMARY DISPLAY
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-001",
        "TC-UC19-001 | Web shows scan summary screen before populating expense form for mobile Save & Scan receipts",
        PRE,
        "1. On mobile, capture a Cash receipt and tap 'Save & Scan'. Receipt is scanned in background.\n"
        "2. On web, navigate to Incomplete Cash Expenses.\n"
        "3. Open the expense created from the mobile Save & Scan receipt.",
        "The web displays a scan summary screen showing the scanned values (Amount, Date, Supplier) before opening the expense form. The claimant is presented with 'Use Scanned Values' and 'Discard Values' options — matching the mobile experience."
    ),

    (
        "TC-UC19-002",
        "TC-UC19-002 | Scan summary displays correct scanned values from the mobile-captured receipt",
        PRE,
        "1. On mobile, capture a receipt showing: Amount=£45.00, Date=10/04/2026, Supplier='Costa Coffee'. Tap 'Save & Scan'.\n"
        "2. On web, open the corresponding expense from Incomplete Cash Expenses.\n"
        "3. Observe the scan summary screen.",
        "The scan summary on web correctly displays: Amount = £45.00, Date = 10/04/2026, Supplier = 'Costa Coffee'. The values match what the server scanned from the mobile-captured receipt."
    ),

    (
        "TC-UC19-003",
        "TC-UC19-003 | Web scan summary is NOT shown for receipts uploaded directly on web",
        PRE,
        "1. On web, create a new expense and upload a receipt directly (not via mobile Save & Scan).\n"
        "2. Observe the flow after the receipt is scanned.",
        "The scan summary / Use-Discard choice is not shown for receipts uploaded directly on web. The existing web scan flow (Confirm / Discard Scanned Values) applies only to receipts that came through mobile Save & Scan. No regression in the standard web upload flow."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # WEB — USE SCANNED VALUES
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-004",
        "TC-UC19-004 | Selecting 'Use Scanned Values' on web populates expense form with scanned data",
        PRE,
        "1. On web, open the expense from a mobile Save & Scan receipt.\n"
        "2. The scan summary screen is displayed with scanned values.\n"
        "3. Click 'Use Scanned Values'.",
        "The expense form opens with all scanned fields pre-populated: Amount, Date, Supplier (and any other scanned fields). The claimant can review, edit remaining fields, and submit."
    ),

    (
        "TC-UC19-005",
        "TC-UC19-005 | Scanned values populated on web via 'Use Scanned Values' are editable",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Use Scanned Values'.\n"
        "2. On the expense form, modify the Amount field.\n"
        "3. Modify the Supplier field.\n"
        "4. Save the expense.",
        "All pre-populated fields are editable. Changes to Amount and Supplier are saved correctly. The expense form does not lock the scanned values."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # WEB — DISCARD VALUES (CORE BUG FIX)
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-006",
        "TC-UC19-006 | Selecting 'Discard Values' on web clears all scanned fields in the expense form",
        PRE,
        "1. On web, open the expense from a mobile Save & Scan receipt.\n"
        "2. The scan summary screen is displayed.\n"
        "3. Click 'Discard Values'.\n"
        "4. Observe the expense form.",
        "The expense form opens with all scanned fields (Amount, Date, Supplier, etc.) cleared and blank. No scanned values are pre-populated. The claimant must fill in the form manually."
    ),

    (
        "TC-UC19-007",
        "TC-UC19-007 | Server-side scanned values do not persist after 'Discard Values' on web",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Discard Values'.\n"
        "2. Leave the expense form without saving.\n"
        "3. Re-open the same expense from the Incomplete Cash Expenses list.",
        "On re-opening, the expense form is still blank (no scanned values). The server-side pre-filled values are permanently cleared/ignored after the discard action. Values do not reappear on subsequent opens."
    ),

    (
        "TC-UC19-008",
        "TC-UC19-008 | Receipt image remains attached after 'Discard Values' on web",
        PRE,
        "1. On web, open a mobile Save & Scan expense.\n"
        "2. Click 'Discard Values' on the scan summary.\n"
        "3. Observe the expense form.",
        "The receipt image remains attached to the expense form after discarding scanned values. Only the extracted text fields (Amount, Date, Supplier) are cleared — the receipt itself is not removed."
    ),

    (
        "TC-UC19-009",
        "TC-UC19-009 | Expense can be submitted manually after 'Discard Values' on web",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Discard Values'.\n"
        "2. Manually fill in Amount, Date, Category, and Supplier on the blank expense form.\n"
        "3. Submit the expense.",
        "The expense is submitted successfully with the manually entered values. No scanned data interferes. The submission flow works correctly after a discard action."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — DISCARD VALUES (EXISTING BEHAVIOUR REGRESSION CHECK)
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-010",
        "TC-UC19-010 | Discard Values on mobile clears scanned fields on mobile expense form",
        PRE,
        "1. On mobile, capture a receipt and tap 'Save & Scan'.\n"
        "2. Navigate to Incomplete Cash Expenses and open the expense.\n"
        "3. The scan summary is displayed.\n"
        "4. Tap 'Discard Values'.\n"
        "5. Observe the expense form on mobile.",
        "The mobile expense form opens blank — all scanned fields are cleared. This is the existing mobile behaviour and must not be regressed by the UC19 fix."
    ),

    (
        "TC-UC19-011",
        "TC-UC19-011 | Discard Values on mobile — fields remain blank when expense is reopened on mobile",
        PRE,
        "1. On mobile, discard scanned values for an expense.\n"
        "2. Navigate away without saving.\n"
        "3. Re-open the same expense from the Incomplete Cash list.",
        "The expense form remains blank on re-open. Scanned values do not reappear. The discard action is honoured persistently on mobile."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # CROSS-PLATFORM CONSISTENCY
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-012",
        "TC-UC19-012 | Discard on mobile — opening same expense on web shows blank form",
        PRE,
        "1. On mobile, open a mobile Save & Scan expense and tap 'Discard Values'.\n"
        "2. On web, navigate to Incomplete Cash Expenses and open the same expense.",
        "The web expense form is also blank — no scanned values are shown. The discard action taken on mobile is reflected on web. The server clears values regardless of which platform initiated the discard."
    ),

    (
        "TC-UC19-013",
        "TC-UC19-013 | Discard on web — opening same expense on mobile shows blank form",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Discard Values'.\n"
        "2. On mobile, navigate to Incomplete Cash Expenses and open the same expense.",
        "The mobile expense form is also blank — no scanned values are shown. The discard action taken on web is reflected on mobile. Both platforms honour the server-side clear."
    ),

    (
        "TC-UC19-014",
        "TC-UC19-014 | Use Scanned Values on web — same values visible on mobile",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Use Scanned Values'.\n"
        "2. On mobile, navigate to Incomplete Cash Expenses and open the same expense.",
        "The mobile expense form displays the same scanned values (Amount, Date, Supplier) as confirmed on web. Both platforms show consistent data after 'Use Scanned Values'."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # NEGATIVE TEST CASES
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC19-NEG-001",
        "TC-UC19-NEG-001 | Scanned values do NOT persist on web after Discard (core bug regression test)",
        PRE,
        "1. On mobile, capture a receipt (Amount=£120, Supplier='Tesco', Date=01/05/2026). Tap 'Save & Scan'.\n"
        "2. On mobile, open the expense and tap 'Discard Values'.\n"
        "3. On web, open the same expense.\n"
        "4. Observe the expense form fields.",
        "Amount, Supplier, and Date fields on the web expense form are ALL blank. None of the scanned values (£120, 'Tesco', 01/05/2026) appear. This directly validates the bug fix — server-side values are cleared after discard."
    ),

    (
        "TC-UC19-NEG-002",
        "TC-UC19-NEG-002 | Scan summary not shown on web if receipt was not scanned (no server scan data)",
        PRE,
        "1. On mobile, capture a receipt using 'Save & Scan' but the server scan fails (e.g., poor image quality — no data returned).\n"
        "2. On web, open the resulting expense from Incomplete Cash Expenses.",
        "The scan summary / Use-Discard screen is NOT displayed since there are no scanned values to present. The web opens directly to a blank expense form. No error or empty scan summary is shown."
    ),

    (
        "TC-UC19-NEG-003",
        "TC-UC19-NEG-003 | Scan summary on web not shown for receipts added via 'Create Expense' camera flow",
        PRE,
        "1. On mobile, create an expense using 'Create Expense' > camera (not Save & Scan).\n"
        "2. On web, open the same expense.",
        "The scan summary / Use-Discard screen is not displayed on web. Receipts captured via 'Create Expense' on mobile follow the standard scan confirmation flow, not the Save & Scan flow introduced in UC19."
    ),

    (
        "TC-UC19-NEG-004",
        "TC-UC19-NEG-004 | Selecting 'Discard Values' on web does not delete the expense itself",
        PRE,
        "1. On web, open a mobile Save & Scan expense.\n"
        "2. Click 'Discard Values' on the scan summary.\n"
        "3. Navigate back to Incomplete Cash Expenses list.",
        "The expense still exists in the Incomplete Cash Expenses list. 'Discard Values' only clears the scanned field values — it does not delete the expense or its receipt."
    ),

    (
        "TC-UC19-NEG-005",
        "TC-UC19-NEG-005 | Once 'Use Scanned Values' confirmed on web, re-opening expense shows populated form — no scan summary shown again",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Use Scanned Values'.\n"
        "2. Navigate away without saving.\n"
        "3. Re-open the same expense from the list.",
        "The expense form opens directly with the scanned values pre-populated. The scan summary / Use-Discard screen is NOT shown again. The 'Use Scanned Values' choice is remembered — the claimant is not asked to choose again."
    ),

    (
        "TC-UC19-NEG-006",
        "TC-UC19-NEG-006 | Once 'Discard Values' confirmed on web, re-opening expense shows blank form — no scan summary shown again",
        PRE,
        "1. On web, open a mobile Save & Scan expense and click 'Discard Values'.\n"
        "2. Navigate away without saving.\n"
        "3. Re-open the same expense from the list.",
        "The expense form opens blank. The scan summary / Use-Discard screen is NOT shown again. The 'Discard Values' choice is remembered — the claimant is not prompted to choose again on subsequent opens."
    ),

]


def main():
    if DISCOVER_MODE:
        discover_function_field()
        sys.exit(0)
    print(f"Uploading {len(TEST_CASES)} test cases linked to enhancement {ENHANCEMENT_ID} ...\n")
    created, failed = [], []
    for tc_id, title, precondition, steps, expected in TEST_CASES:
        steps_xml = build_steps_xml(steps, expected)
        wi_id = create_test_case(title, steps_xml, precondition)
        if wi_id:
            print(f"  \u2713  [{wi_id}]  {tc_id} - {title[:72]}")
            created.append((tc_id, wi_id))
        else:
            print(f"  \u2717 FAILED  {tc_id}")
            failed.append(tc_id)
        time.sleep(0.3)
    print(f"\n" + "-" * 60)
    print(f"Done.  Created: {len(created)}   Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
