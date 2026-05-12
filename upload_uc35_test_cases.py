"""
UC35 – Add Notes During Receipt Capture (Cash & Credit Card)
VSTS Test Case Uploader  |  Enhancement: 38187
==============================================================
Uploads test cases to Azure DevOps.
Before running: pip install requests
Usage: python upload_uc35_test_cases.py
"""

import requests, json, base64, html, sys, time, re, os
from dotenv import load_dotenv
load_dotenv()

# ── CONFIG ─────────────────────────────────────────────────────────────
PAT               = os.environ.get("ADO_PAT", "")
ORG               = "expenseondemand"
PROJECT           = "Solo Expenses"
ENHANCEMENT_ID    = 38187
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
                   "attributes": {"comment": "UC35 - Add Notes During Receipt Capture"}}},
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

PRE_MOB = (
    "Precondition: User is logged into EOD mobile app (iOS or Android) as a Claimant. "
    "The UC35 Notes feature has been deployed. CCC subscription is active and Corporate Credit Card is assigned to the user."
)
PRE_WEB = (
    "Precondition: User is logged into EOD web application as a Claimant. "
    "The UC35 Notes feature has been deployed."
)

TEST_CASES = [

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — RECEIPT PREVIEW SCREEN (NOTES FIELD UI)
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-001",
        "TC-UC35-001 | Notes/Justification field is displayed on Receipt Preview screen after capture",
        PRE_MOB,
        "1. Tap 'Capture Receipt' from the home screen.\n"
        "2. Select 'Cash/Personal Credit/Debit Card Transaction'.\n"
        "3. Capture a receipt image.\n"
        "4. Observe the Receipt Preview screen.",
        "A multi-line Notes/Justification input field is displayed on the Receipt Preview screen, placed below the extracted fields and above the action buttons. Placeholder text reads: 'Add justification (e.g., client lunch, travel expense)'."
    ),

    (
        "TC-UC35-002",
        "TC-UC35-002 | Notes field allows multi-line text input up to 200 characters",
        PRE_MOB,
        "1. Capture a receipt and land on the Receipt Preview screen.\n"
        "2. Tap on the Notes/Justification field.\n"
        "3. Type exactly 200 characters of text.\n"
        "4. Attempt to type a 201st character.",
        "The field accepts up to 200 characters. The 201st character is not accepted. The field supports multi-line input. Character limit is enforced without crashing the app."
    ),

    (
        "TC-UC35-003",
        "TC-UC35-003 | Notes field is optional — Save & Scan works without entering notes",
        PRE_MOB,
        "1. Capture a receipt and land on the Receipt Preview screen.\n"
        "2. Leave the Notes/Justification field empty.\n"
        "3. Tap 'Save & Scan'.",
        "The receipt is saved and scanned successfully without any error. An incomplete cash expense is created. The app navigates to the Incomplete Cash Expense List. Notes field being empty does not block the flow."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — CASH: SINGLE EXPENSE → SAVE & SCAN FLOW
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-004",
        "TC-UC35-004 | Cash single expense — notes saved and mapped to expense via Save & Scan",
        PRE_MOB,
        "1. Capture a Cash receipt and land on the Receipt Preview screen.\n"
        "2. Enter notes: 'Client lunch with John — project Alpha'.\n"
        "3. Tap 'Save & Scan'.\n"
        "4. Navigate to Incomplete Cash Expense List.\n"
        "5. Open the newly created expense.",
        "Receipt is saved. The incomplete cash expense is created. The notes 'Client lunch with John — project Alpha' are mapped directly to the expense. When the expense form is opened, the Notes/Justification field is pre-populated with the entered notes."
    ),

    (
        "TC-UC35-005",
        "TC-UC35-005 | Cash single expense — notes pre-populated on Expense Form via Create Expense",
        PRE_MOB,
        "1. Capture a Cash receipt and land on the Receipt Preview screen.\n"
        "2. Enter notes: 'Travel expense — client visit'.\n"
        "3. Tap 'Create Expense'.\n"
        "4. Observe the Expense Form screen.",
        "The Expense Form screen opens with the receipt image attached and auto-filled fields. The Notes/Justification field is pre-populated with 'Travel expense — client visit'. The user can edit or extend the notes before submitting."
    ),

    (
        "TC-UC35-006",
        "TC-UC35-006 | Cash single expense — notes persist when scanned values are Confirmed",
        PRE_MOB,
        "1. Capture a Cash receipt, enter notes: 'Office supplies — Q2 budget'.\n"
        "2. Tap 'Save & Scan' and navigate to Incomplete Cash Expense List.\n"
        "3. Open the expense.\n"
        "4. Click 'Confirm Scanned Values'.\n"
        "5. Observe the Expense Form.",
        "After confirming scanned values, the Expense Form opens. The Notes field is still pre-populated with 'Office supplies — Q2 budget'. Notes are not cleared when scanned values are confirmed."
    ),

    (
        "TC-UC35-007",
        "TC-UC35-007 | Cash single expense — notes persist when scanned values are Discarded",
        PRE_MOB,
        "1. Capture a Cash receipt, enter notes: 'Team dinner — project kickoff'.\n"
        "2. Tap 'Save & Scan' and navigate to Incomplete Cash Expense List.\n"
        "3. Open the expense.\n"
        "4. Click 'Discard Scanned Values'.\n"
        "5. Observe the Expense Form.",
        "The Expense Form opens with blank scanned fields (as expected after discard). However, the Notes field is still pre-populated with 'Team dinner — project kickoff'. Notes are not cleared when scanned values are discarded."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — CASH: MULTIPLE EXPENSES → SAVE & SCAN FLOW
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-008",
        "TC-UC35-008 | Cash multiple expenses — each receipt has its own individual notes",
        PRE_MOB,
        "1. Capture a Cash receipt (Receipt 1) and land on Receipt Preview.\n"
        "2. Enter notes: 'Receipt 1 — taxi fare'.\n"
        "3. Tap 'Save & Scan'. Camera reopens.\n"
        "4. Capture Receipt 2 and land on Receipt Preview.\n"
        "5. Enter notes: 'Receipt 2 — hotel stay'.\n"
        "6. Tap 'Save & Scan'.\n"
        "7. Navigate to Incomplete Cash Expense List and open each expense.",
        "Each expense has its own distinct notes: Expense 1 shows 'Receipt 1 — taxi fare', Expense 2 shows 'Receipt 2 — hotel stay'. Notes are not shared or overwritten between receipts."
    ),

    (
        "TC-UC35-009",
        "TC-UC35-009 | Cash multiple expenses — notes field shown independently for each receipt preview",
        PRE_MOB,
        "1. Capture a Cash receipt in 'Multiple Expenses' mode.\n"
        "2. Observe Receipt Preview screen for the first receipt.\n"
        "3. Enter notes and tap 'Save & Scan'. Camera reopens.\n"
        "4. Capture a second receipt.\n"
        "5. Observe Receipt Preview screen for the second receipt.",
        "Each time the Receipt Preview screen appears for a new capture, the Notes field is blank (not pre-filled from the previous receipt). Each receipt's notes are stored independently."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — CCC: SINGLE RECEIPT → SAVE & SCAN FLOW
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-010",
        "TC-UC35-010 | CCC single receipt — only Save & Scan button shown, Create Expense absent",
        PRE_MOB,
        "1. Tap 'Capture Receipt'.\n"
        "2. Select 'Corporate Credit Card Transaction'.\n"
        "3. Capture a receipt and land on Receipt Preview.",
        "The Receipt Preview screen shows the Notes/Justification field. At the bottom, only one full-width button 'Save & Scan' is displayed. The 'Create Expense' button is NOT present for CCC receipts."
    ),

    (
        "TC-UC35-011",
        "TC-UC35-011 | CCC single receipt — notes stored at receipt level after Save & Scan",
        PRE_MOB,
        "1. Capture a CCC receipt and land on Receipt Preview.\n"
        "2. Enter notes: 'Corporate card — client entertainment'.\n"
        "3. Tap 'Save & Scan'.\n"
        "4. Navigate to Incomplete Corporate CC Receipts list.",
        "The CCC receipt is saved. No expense is created. The notes 'Corporate card — client entertainment' are stored at the receipt level. The receipt appears in the Incomplete CC Receipts list."
    ),

    (
        "TC-UC35-012",
        "TC-UC35-012 | CCC receipt — notes mapped to transaction upon auto-matching",
        PRE_MOB,
        "1. Capture a CCC receipt with notes: 'Q2 travel — Singapore trip'.\n"
        "2. Tap 'Save & Scan'. Receipt saved in CC Receipts list.\n"
        "3. Wait for the system to auto-match the receipt to a CCC transaction.\n"
        "4. Navigate to Incomplete Corporate CC Transactions.\n"
        "5. Open the matched transaction.",
        "The matched CCC transaction's Notes/Justification field is pre-populated with 'Q2 travel — Singapore trip'. Notes from the receipt are transferred to the transaction upon auto-matching."
    ),

    (
        "TC-UC35-013",
        "TC-UC35-013 | CCC receipt — notes mapped to transaction upon manual attachment",
        PRE_MOB,
        "1. Capture a CCC receipt with notes: 'Manual attach test — conference fee'.\n"
        "2. Tap 'Save & Scan'. Receipt saved.\n"
        "3. Navigate to an unmatched CCC transaction and manually attach the receipt.\n"
        "4. Open the transaction after attachment.",
        "After manual attachment, the transaction's Notes/Justification field is pre-populated with 'Manual attach test — conference fee'. Notes from the receipt are correctly transferred on manual attachment."
    ),

    (
        "TC-UC35-014",
        "TC-UC35-014 | CCC multiple receipts — notes stored per receipt and mapped to respective transactions",
        PRE_MOB,
        "1. Capture CCC Receipt 1, enter notes: 'CCC Receipt 1 — flight ticket'.\n"
        "2. Tap 'Save & Scan'. Camera reopens.\n"
        "3. Capture CCC Receipt 2, enter notes: 'CCC Receipt 2 — airport lounge'.\n"
        "4. Tap 'Save & Scan'.\n"
        "5. Allow system to auto-match both receipts to their respective transactions.\n"
        "6. Open each matched transaction.",
        "Transaction 1 shows notes 'CCC Receipt 1 — flight ticket'. Transaction 2 shows notes 'CCC Receipt 2 — airport lounge'. Notes are not mixed between transactions."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MOBILE — EXPENSE LIST: ADD / EDIT NOTES FROM LIST
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-015",
        "TC-UC35-015 | Expense card shows '+ Add Notes' button when no notes exist",
        PRE_MOB,
        "1. Create an incomplete cash expense without adding any notes during capture.\n"
        "2. Navigate to Incomplete Cash Expense List.\n"
        "3. Observe the expense card.",
        "The expense card displays a clickable '+ Add Notes' button styled as a light blue bar, placed below item details and above the amount. No notes text is shown."
    ),

    (
        "TC-UC35-016",
        "TC-UC35-016 | Tapping '+ Add Notes' opens bottom sheet modal with correct UI",
        PRE_MOB,
        "1. Navigate to Incomplete Cash Expense List.\n"
        "2. Tap '+ Add Notes' on an expense card without notes.",
        "A bottom sheet modal slides up from the bottom. It contains: Title 'Add Notes', informational message 'Saved notes will be auto-added on justification notes in the expense form', a multi-line input field labelled 'Justification / Notes', and a 'Save Notes' button at the bottom."
    ),

    (
        "TC-UC35-017",
        "TC-UC35-017 | Notes saved from list replaces '+ Add Notes' with preview text and Edit option",
        PRE_MOB,
        "1. Navigate to Incomplete Cash Expense List.\n"
        "2. Tap '+ Add Notes' on an expense card.\n"
        "3. Enter notes: 'This expense was made for client meeting'.\n"
        "4. Tap 'Save Notes'.\n"
        "5. Observe the expense card.",
        "The bottom sheet closes. The '+ Add Notes' button is replaced with a notes preview showing 'Notes: This expense was made for client meeting...' and an 'Edit' option on the right side."
    ),

    (
        "TC-UC35-018",
        "TC-UC35-018 | Notes limit of 200 characters enforced in bottom sheet modal",
        PRE_MOB,
        "1. Tap '+ Add Notes' on an expense card.\n"
        "2. In the bottom sheet, type exactly 200 characters.\n"
        "3. Attempt to type a 201st character.\n"
        "4. Tap 'Save Notes'.",
        "The field accepts up to 200 characters and rejects the 201st. Save Notes saves successfully. The 200-character limit applies consistently in the bottom sheet modal."
    ),

    (
        "TC-UC35-019",
        "TC-UC35-019 | 'Save Notes' button is disabled when no changes have been made during Edit",
        PRE_MOB,
        "1. Navigate to an expense card that already has notes.\n"
        "2. Tap 'Edit' on the notes preview.\n"
        "3. Observe the 'Save Notes' button without making any changes.",
        "The bottom sheet opens with notes pre-filled. The 'Save Notes' button is displayed as disabled (greyed out) since no changes have been made. Tapping it has no effect."
    ),

    (
        "TC-UC35-020",
        "TC-UC35-020 | Editing existing notes updates the preview on the expense card",
        PRE_MOB,
        "1. Navigate to an expense card with existing notes: 'Old note text'.\n"
        "2. Tap 'Edit'.\n"
        "3. Clear the text and enter: 'Updated note text'.\n"
        "4. Tap 'Save Notes'.\n"
        "5. Observe the expense card.",
        "'Save Notes' becomes active after editing. After saving, the notes preview on the expense card updates to 'Notes: Updated note text...'. The old notes text is no longer shown."
    ),

    (
        "TC-UC35-021",
        "TC-UC35-021 | Notes added from list are pre-populated in Expense Form when expense is opened",
        PRE_MOB,
        "1. Add notes 'Added from list screen' to an expense card via '+ Add Notes'.\n"
        "2. Tap on the expense card to open the Expense Form.",
        "The Expense Form opens with the Notes/Justification field pre-populated with 'Added from list screen'. Notes added from the list screen are reflected correctly in the form."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # WEB FLOW
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-022",
        "TC-UC35-022 | Web — Justification Notes column shown on Incomplete Cash Expense grid",
        PRE_WEB,
        "1. Log into EOD web application.\n"
        "2. Navigate to Expense List.\n"
        "3. Open Incomplete Cash Receipts/Expenses list.\n"
        "4. Observe the grid columns.",
        "A 'Justification Notes' column is visible in the Incomplete Cash Expenses grid. If a note exists for an expense, it is displayed in this column. The column is present across all incomplete expense list filters."
    ),

    (
        "TC-UC35-023",
        "TC-UC35-023 | Web — Notes added on mobile are visible in the web grid and receipt preview",
        PRE_WEB,
        "1. On mobile, capture a Cash receipt and add notes: 'Mobile note — web sync test'.\n"
        "2. Save & Scan the receipt.\n"
        "3. On web, navigate to Incomplete Cash Expenses.\n"
        "4. Locate the expense in the grid.\n"
        "5. Open the CCC/Emailed Receipt preview.",
        "The 'Justification Notes' column in the web grid shows 'Mobile note — web sync test'. The Notes section in the receipt preview on web also displays the same note. Notes sync correctly from mobile to web."
    ),

    (
        "TC-UC35-024",
        "TC-UC35-024 | Web — Notes can be added/edited directly on web for CCC and Emailed receipts",
        PRE_WEB,
        "1. On web, navigate to Incomplete Corporate CC Receipts or Emailed Receipts.\n"
        "2. Open a receipt that has no notes.\n"
        "3. Find the Notes section in the receipt preview.\n"
        "4. Enter notes: 'Web note — added directly'.\n"
        "5. Save the notes.\n"
        "6. Reload the page and re-open the receipt.",
        "The Notes section is present in the CCC/Emailed receipt preview on web. Notes can be entered and saved directly. After reload, the saved notes 'Web note — added directly' persist."
    ),

    (
        "TC-UC35-025",
        "TC-UC35-025 | Web — Notes added on web are visible on mobile",
        PRE_WEB,
        "1. On web, open an expense and add notes: 'Web note — cross platform sync'.\n"
        "2. Save.\n"
        "3. On mobile, navigate to the same expense in Incomplete Cash Expense List.\n"
        "4. Observe the expense card and open the Expense Form.",
        "The mobile expense card shows the notes preview 'Notes: Web note — cross platform sync...'. Opening the Expense Form shows the notes pre-populated. Notes sync correctly from web to mobile."
    ),

    (
        "TC-UC35-026",
        "TC-UC35-026 | Web — CCC receipt notes copied to transaction on acceptance",
        PRE_WEB,
        "1. On web, navigate to a CCC receipt that has notes: 'CCC note — acceptance test'.\n"
        "2. The receipt is matched (auto or manually) to a CCC transaction.\n"
        "3. Open the matched CCC transaction.\n"
        "4. Click 'Accept Receipt'.\n"
        "5. Observe the transaction's Notes/Justification field.",
        "After accepting the receipt, the transaction's Notes/Justification field is populated with 'CCC note — acceptance test'. Notes from the receipt are copied to the transaction upon acceptance on web."
    ),

    (
        "TC-UC35-027",
        "TC-UC35-027 | Web — Emailed receipt notes copied to CCC transaction on acceptance",
        PRE_WEB,
        "1. On web, ensure an emailed receipt has notes: 'Emailed receipt — acceptance note'.\n"
        "2. Match the emailed receipt to a CCC transaction.\n"
        "3. Open the CCC transaction and click 'Accept Receipt'.\n"
        "4. Observe the Notes field on the transaction.",
        "The CCC transaction's Notes field is populated with 'Emailed receipt — acceptance note' after accepting the emailed receipt. Notes flow correctly from emailed receipts to transactions."
    ),

    (
        "TC-UC35-028",
        "TC-UC35-028 | Web — Cash expense notes reflected in Expense Form regardless of scan action",
        PRE_WEB,
        "1. On web, open an incomplete cash expense that has notes: 'Cash note — scan test'.\n"
        "2. Confirm scanned values and observe the Expense Form.\n"
        "3. Repeat: open a second expense with same note and Discard scanned values.\n"
        "4. Observe the Expense Form in both cases.",
        "In both cases (Confirm and Discard scanned values), the Expense Form's Notes/Justification field is pre-populated with 'Cash note — scan test'. Notes are not cleared by either scan action on web."
    ),

    # ═══════════════════════════════════════════════════════════════════
    # NEGATIVE TEST CASES
    # ═══════════════════════════════════════════════════════════════════

    (
        "TC-UC35-NEG-001",
        "TC-UC35-NEG-001 | Notes from one receipt are not overwritten by another receipt's notes",
        PRE_MOB,
        "1. Capture Cash Receipt 1, enter notes: 'Note A'.\n"
        "2. Tap Save & Scan.\n"
        "3. Capture Cash Receipt 2, enter notes: 'Note B'.\n"
        "4. Tap Save & Scan.\n"
        "5. Open Expense 1 in the list.",
        "Expense 1 retains 'Note A'. Expense 2 retains 'Note B'. No overwriting occurs between receipts captured in the same session."
    ),

    (
        "TC-UC35-NEG-002",
        "TC-UC35-NEG-002 | Notes exceeding 200 characters are rejected",
        PRE_MOB,
        "1. Open the Add Notes bottom sheet modal on any expense.\n"
        "2. Paste a 250-character string into the notes field.\n"
        "3. Tap 'Save Notes'.",
        "The field rejects or truncates input beyond 200 characters. If the user attempts to paste text exceeding the limit, only 200 characters are retained. An appropriate indicator (e.g., character count) is shown."
    ),

    (
        "TC-UC35-NEG-003",
        "TC-UC35-NEG-003 | CCC receipt — Create Expense button is absent on Receipt Preview",
        PRE_MOB,
        "1. Capture a CCC receipt.\n"
        "2. Observe the Receipt Preview screen action buttons.",
        "Only the 'Save & Scan' button (full width) is displayed at the bottom of the Receipt Preview screen for CCC receipts. The 'Create Expense' button is absent. This ensures CCC receipts cannot be directly converted to expenses from the capture flow."
    ),

    (
        "TC-UC35-NEG-004",
        "TC-UC35-NEG-004 | Notes not lost if user navigates back and returns to Receipt Preview",
        PRE_MOB,
        "1. Capture a receipt and land on Receipt Preview.\n"
        "2. Enter notes: 'Notes before going back'.\n"
        "3. Tap the Back button — a confirmation pop-up appears.\n"
        "4. Select 'Continue Setup' / cancel to stay on the screen.\n"
        "5. Observe the Notes field.",
        "After cancelling the back navigation, the user returns to the Receipt Preview screen with the Notes field still populated with 'Notes before going back'. Notes are not wiped on a cancelled back action."
    ),

    (
        "TC-UC35-NEG-005",
        "TC-UC35-NEG-005 | Notes column on web does not display for non-incomplete expense lists",
        PRE_WEB,
        "1. On web, navigate to 'Pending with Approver' expense list.\n"
        "2. Observe the column headers in the grid.",
        "The 'Justification Notes' column behaviour follows the existing implementation for Pending/Approved expense lists. Notes entered during capture are visible within the expense detail, but the grid-level Notes column is specifically present in incomplete expense lists as per the spec."
    ),

    (
        "TC-UC35-NEG-006",
        "TC-UC35-NEG-006 | CCC notes are NOT copied to transaction if receipt is discarded",
        PRE_MOB,
        "1. Capture a CCC receipt with notes: 'Discard test note'.\n"
        "2. Save & Scan the receipt.\n"
        "3. On the matched CCC transaction, click 'Discard & Try Later'.\n"
        "4. Observe the transaction's notes after discarding.",
        "After clicking 'Discard & Try Later', no notes from the receipt are populated in the transaction. Notes are only copied to the transaction when the receipt is accepted, not discarded."
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
