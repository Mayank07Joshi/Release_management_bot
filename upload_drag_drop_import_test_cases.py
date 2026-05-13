"""
Credit Card Drag & Drop Import (incl. PDF) — QA Test Cases
Enhancement ID: 39516  |  Tester: Kunal Joshi
Before running: pip install requests python-dotenv
Usage: python upload_drag_drop_import_test_cases.py
"""

import requests, json, base64, html, sys, time, re, os
from dotenv import load_dotenv
load_dotenv()

def _auth_header(pat):
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def build_steps_xml(steps_text, expected_text):
    lines = [l.strip() for l in steps_text.strip().split("\n") if l.strip()]
    steps = [re.sub(r"^\d+[\.)\s]\s*", "", l).strip() for l in lines]
    steps = [s for s in steps if s] or [steps_text.strip() or "Execute test"]
    parts = [f'<steps id="0" last="{len(steps)}">']
    for i, action in enumerate(steps, start=1):
        esc_a = html.escape(action)
        is_last = (i == len(steps))
        esc_e = html.escape(expected_text) if is_last and expected_text else ""
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

def create_test_case(title, priority, steps_xml, precondition,
                     base_url, project, enhancement_id, iteration_path,
                     function_value, function_field_ref, patch_headers, tester_name):
    url = f"{base_url}/{project}/_apis/wit/workitems/$Test%20Case?api-version=7.0"
    enh_url = f"{base_url}/_apis/wit/workitems/{enhancement_id}"
    payload = [
        {"op": "add", "path": "/fields/System.Title",                   "value": title},
        {"op": "add", "path": "/fields/System.AreaPath",                "value": project},
        {"op": "add", "path": "/fields/System.IterationPath",           "value": iteration_path},
        {"op": "add", "path": "/fields/Custom.Area",                    "value": "Web"},
        {"op": "add", "path": "/fields/Custom.Automation",              "value": "To be automated"},
        {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": priority},
        {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps",       "value": steps_xml},
        {"op": "add", "path": f"/fields/{function_field_ref}",          "value": function_value},
        {"op": "add", "path": "/relations/-",
         "value": {"rel": "Microsoft.VSTS.Common.TestedBy-Reverse",
                   "url": enh_url,
                   "attributes": {"comment": f"Written by {tester_name}"}}},
    ]
    if precondition:
        payload.append({"op": "add", "path": "/fields/Microsoft.VSTS.TCM.LocalDataSource", "value": precondition})
    r = requests.post(url, headers=patch_headers, data=json.dumps(payload))
    if r.status_code not in (200, 201):
        print(f"  FAILED '{title[:60]}': {r.status_code} {r.text[:300]}")
        return None
    return r.json()["id"]


PAT               = os.environ.get("AZURE_DEVOPS_PAT", "")
ORG               = "expenseondemand"
PROJECT           = "Solo Expenses"
ENHANCEMENT_ID    = 39516
FUNCTION_VALUE    = "Credit Card"
ITERATION_PATH    = r"Solo Expenses\2026\Iteration 2026 04-April"
TESTER_NAME       = "Kunal Joshi"
DISCOVER_MODE     = False
FUNCTION_FIELD_REF = "Custom.function"
BASE_URL          = f"https://dev.azure.com/{ORG}"

HEADERS       = _auth_header(PAT)
PATCH_HEADERS = {**_auth_header(PAT), "Content-Type": "application/json-patch+json"}

def discover_fields():
    url = f"{BASE_URL}/{PROJECT}/_apis/wit/workitemtypes/Test%20Case/fields?api-version=7.0"
    r = requests.get(url, headers=HEADERS); r.raise_for_status()
    for f in r.json().get("value", []):
        name = f.get("name","").lower(); ref = f.get("referenceName","").lower()
        if any(k in name or k in ref for k in ("function","automat","area")):
            print(f"  {f['name']:40s}  {f['referenceName']}")

TEST_CASES = [
    ('DD-001', 'DD-001 | Drag and drop valid CSV from desktop — import completes within 3 seconds', 1, 'FM logged in; Credit Card Dashboard open; valid CSV with reference numbers ready', '1. Drag CSV file from desktop.\n2. Drop anywhere on dashboard.\n3. Observe dialog (Screen 24/25).\n4. Monitor import progress.', "Dialog opens. File uploads. Countdown counter shown (e.g. 50→0). 'All transactions imported' message at end. Import completes ≤3 seconds. Transaction list populates live."),
    ('DD-002', 'DD-002 | Drag and drop text-based PDF — transactions extracted and imported', 1, 'FM logged in; text-layer PDF statement ready (Amex, 25 rows)', "1. Drag PDF to dashboard.\n2. Drop on screen.\n3. Observe 'Scanning Document' state (Screen 26).", "'Scanning Document — Extracting spend details from your statement' shown. AI extraction runs. 25 transactions imported within 5 seconds. ≥98% field accuracy."),
    ('DD-003', 'DD-003 | Drag and drop scanned PDF — OCR engine triggered, ≥95% accuracy', 1, 'FM logged in; scanned image PDF (HDFC, 20 rows, 300dpi)', '1. Drag scanned PDF.\n2. Drop on dashboard.\n3. Monitor OCR processing.', "OCR engine invoked. 'Our AI is analysing your statement' shown. ≥95% transactions correctly extracted. Import completes ≤6 seconds."),
    ('DD-004', 'DD-004 | Reject unsupported file type (.txt) with clear error message', 1, 'FM on dashboard', '1. Drag a .txt file to dashboard.\n2. Drop on screen.', "File rejected immediately. Error: 'Unsupported file format. Accepted formats: PDF, CSV, XLS, XLSX.' No import starts. No data stored."),
    ('DD-005', 'DD-005 | Block re-import of identical file using hash code — duplicate alert shown', 1, 'CSV already imported once; hash stored in database', '1. Drag and drop the same CSV file again.\n2. Observe alert.', "Alert shown: 'This file was imported on <date>, with <n> transactions, and cannot be imported again.' Import blocked. No duplicate transactions created."),
    ('DD-006', "DD-006 | Transactions missing reference number shown in 'Not Imported' panel", 1, 'CSV with 30 rows; 5 rows have blank reference number field', "1. Drag and drop CSV.\n2. Monitor import progress panel (Screen 3/4).\n3. Click 'Missing Reference Number' hyperlink.", "25 transactions imported. 'Not Imported — Missing Reference Number: 5' shown with hyperlink. Clicking opens panel (Screen 6) listing the 5 transactions with details."),
    ('DD-007', 'DD-007 | Close (X) during import — dashboard shows in-progress bar with View Import Status', 2, '50-row CSV import in progress', '1. Start import.\n2. While importing, click ✕ close icon on panel (Screen 35).\n3. Observe dashboard.', "Panel closes. Dashboard shows progress bar (Screen 36): Total count, Imported count, Remaining count. 'View Import Status' button present. Clicking reopens import summary panel."),
    ('DD-008', 'DD-008 | FM can download the original imported file after import completes', 1, 'PDF import completed successfully', "1. Complete PDF import.\n2. Close summary panel.\n3. View transaction list (Screen 7).\n4. Click 'Download the Original File' button.", 'Original PDF downloaded (not re-exported CSV). File matches the original uploaded file. Format preserved: PDF→PDF, CSV→CSV.'),
    ('DD-009', 'DD-009 | Two imports on same date filterable separately by time', 1, 'File_A (50 rows) imported at 10:00; File_B (60 rows) imported at 14:30 — both on 3rd November', "1. Import both files on same date.\n2. Open Import Date filter (Screen 8).\n3. Select '3rd Nov 10:00'.\n4. Select '3rd Nov 14:30'.", 'Filter shows two separate timestamps. Selecting 10:00 shows only 50 transactions. Selecting 14:30 shows only 60. Batches never merged into single 110-row list.'),
    ('DD-010', 'DD-010 | Statement date extracted and shown for FM confirmation — cannot proceed without confirming', 1, 'PDF with detectable statement date: 14 March 2026', '1. Drop PDF.\n2. Observe dialog (Screen 41).\n3. Attempt to proceed without clicking either button.', "Dialog: 'Confirm Statement Date — 14 March 2026'. Buttons: 'No, amend it' | 'Yes, Confirm'. Cannot proceed past this dialog. Hard gate enforced."),
    ('DD-011', "DD-011 | System never defaults to today's date when statement date not found in file", 1, 'PDF with no detectable statement date', '1. Drop PDF with no date.\n2. Observe date dialog (Screen 46).', "Dialog: 'Statement Date Not Detected — Please select a date to continue.' Date field is EMPTY. No Cancel button. No pre-filled date. FM must manually select date before import proceeds."),
    ('DD-012', 'DD-012 | FM can amend extracted date using calendar and Reset to Original', 2, 'Statement date dialog showing extracted date: 14 March 2026', "1. Click 'No, amend it'.\n2. Calendar opens (Screen 43).\n3. Select 31 March 2026.\n4. Click 'Save Date'.\n5. Click 'Reset to Original'.", "Date changed to 31 March. Save Date button enables. Success message shown (Screen 45). Clicking 'Reset to Original' reverts calendar back to 14 March."),
    ('DD-013', 'DD-013 | Majority negative transactions — classification panel shown, Negative=Expenses pre-selected', 1, 'Statement with 35 negative, 15 positive transactions', '1. Drop statement.\n2. Confirm statement date.\n3. Observe classification panel (Screen 50).', "Panel shown: 'How should we read your statement?' Smart Detection message. Option 'Negative Values = Money Out (Expenses)' pre-selected. Checkbox 'Remember this choice'. Buttons: 'Review Manually' | 'Confirm & Continue'."),
    ('DD-014', 'DD-014 | All same-sign transactions — classification panel NOT shown, all imported as Expenses', 1, 'Statement with 50 all-negative transactions', '1. Drop statement.\n2. Confirm date.\n3. Observe whether panel appears.', 'Classification panel NOT displayed. All 50 transactions automatically imported as Expenses. No user action required.'),
    ('DD-015', "DD-015 | 'Remember this choice' saves per-card preference — panel suppressed on next import", 1, 'Classification panel showing for Amex ****4821', "1. Tick 'Remember this choice for Amex ****4821'.\n2. Select 'Negative=Expenses'.\n3. Click Confirm.\n4. Import second statement for same card.", 'Second import: classification panel NOT shown. Negative=Expenses applied automatically. Preference is card-specific — other cards still prompt.'),
    ('DD-016', 'DD-016 | Exported pending transactions CSV includes STATUS column', 1, 'Pending transactions with statuses: Pending, Approved, Rejected', '1. Navigate to pending transactions (Screen 9).\n2. Export all pending transactions.\n3. Open downloaded file.', 'Exported file contains STATUS column (Screen 11). Each row shows correct status. Column was previously missing (UC2 fix).'),
    ('DD-017', 'DD-017 | View All Pending Transactions shows company breakdown panel', 2, 'Multi-company feature active; transactions across Alpha Ltd (30), Beta Ltd (20), No Company (5)', "1. Navigate to Credit Card Dashboard (Screen 12).\n2. Click 'View All Pending Transactions' button.\n3. Observe panel.", "Panel opens (Screen 13) with two columns: Company Name | Transactions Count. 'No Company Assigned' at top. View button per company. Clicking View opens filtered transactions for that company."),
    ('DD-018', 'DD-018 | Step 5 added to credit card wizard — Xero mapping type selection', 2, 'Xero integration enabled; completing credit card wizard Step 4', "1. Complete Step 4 of credit card wizard.\n2. Navigate to Step 5.\n3. Observe options (Screen 63/64).\n4. Select 'By Employee'.\n5. Save.", "Step 5 'Select Mapping Type for Xero' visible only when Xero enabled. Three options: By Company (default), By Employee, By Company & Employee. Selected option displayed in wizard summary and drives Step 13 Xero mapping flow."),
]


def main():
    if DISCOVER_MODE:
        discover_fields(); sys.exit(0)
    print(f"Uploading {len(TEST_CASES)} test cases → Enhancement {ENHANCEMENT_ID} | Tester: {TESTER_NAME}\n")
    created, failed = [], []
    for tc_id, title, priority, precondition, steps, expected in TEST_CASES:
        wi_id = create_test_case(
            title, priority, build_steps_xml(steps, expected), precondition,
            BASE_URL, PROJECT, ENHANCEMENT_ID, ITERATION_PATH,
            FUNCTION_VALUE, FUNCTION_FIELD_REF, PATCH_HEADERS, TESTER_NAME
        )
        if wi_id:
            print(f"  \u2713  [{wi_id}]  {tc_id} - {title[:70]}")
            created.append((tc_id, wi_id))
        else:
            print(f"  \u2717 FAILED  {tc_id}")
            failed.append(tc_id)
        time.sleep(0.3)
    print("\n" + "-"*60)
    print(f"Done.  Created: {len(created)}   Failed: {len(failed)}")
    if failed: print(f"Failed: {', '.join(failed)}")

if __name__ == "__main__":
    main()
