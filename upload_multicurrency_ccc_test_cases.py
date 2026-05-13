"""
Multi-Currency Corporate Credit Card — QA Test Cases
Enhancement ID: 40047  |  Tester: Kunal Joshi
Before running: pip install requests python-dotenv
Usage: python upload_multicurrency_ccc_test_cases.py
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
ENHANCEMENT_ID    = 40047
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
    ('MC-001', 'MC-001 | Register a Single-Currency EUR card successfully', 1, 'FM logged in; card provider = HSBC', "1. Open Credit Card wizard.\n2. Select claimant.\n3. Choose 'Single-Currency Card'.\n4. Set currency = EUR.\n5. Enter provider = HSBC, last 4 digits.\n6. Save.", 'Card saved with card_currency=EUR, is_multi_currency=FALSE. EUR badge displayed in card list.'),
    ('MC-002', 'MC-002 | Register a Multi-Currency card (Equals Money) — no currency field shown', 1, 'FM logged in; provider = Equals Money', "1. Open wizard.\n2. Select claimant.\n3. Choose 'Multi-Currency Card'.\n4. Confirm no currency selector shown.\n5. Enter provider + last 4 digits.\n6. Save.", "Card saved with is_multi_currency=TRUE, card_currency=NULL. 'Multi-Currency' badge shown. Message: 'Currency will be read from each CSV row'."),
    ('MC-003', 'MC-003 | Block duplicate card number for same claimant', 1, 'Card ****1234 from Equals Money already registered for claimant', '1. Attempt to register same provider + last 4 digits for same claimant.\n2. Click Save.', "Error: 'A card from this provider ending in 1234 already exists.' Registration blocked."),
    ('MC-004', 'MC-004 | Block card type/currency change after transactions exist', 1, 'EUR single-currency card with at least 1 imported transaction', '1. Open card edit.\n2. Attempt to change currency from EUR to USD.\n3. Click Save.', "Error: 'Currency cannot be changed — transactions exist.' Save blocked."),
    ('MC-005', 'MC-005 | Import EUR CSV against EUR card — happy path with conversion', 1, 'EUR card registered; EUR→GBP rate 0.8571 set for 10-Mar-2026; 5-row CSV ready', '1. Select EUR card in import wizard.\n2. Upload EUR CSV.\n3. Map columns.\n4. Review preview.\n5. Confirm import.', 'All 5 transactions stored: original_currency=EUR, original_amount locked. Converted GBP amounts = original × 0.8571 rounded to 2dp. Rate source recorded.'),
    ('MC-006', 'MC-006 | Block import when no exchange rate exists — never default to 1.0', 1, 'USD card registered; NO USD→GBP rate configured', '1. Select USD card.\n2. Upload USD CSV.\n3. Proceed to preview.', "Every row flagged. Message: 'No exchange rate for USD→GBP.' Import blocked. System does NOT default to 1.0. Manual rate entry or admin setup required."),
    ('MC-007', 'MC-007 | Reject rows where CSV currency column mismatches card currency', 1, "EUR card registered; CSV has currency column; rows 6-7 show 'USD'", '1. Upload CSV with currency column.\n2. Map currency column.\n3. System validates each row.', "Rows 6 & 7 rejected: 'currency USD does not match card currency EUR'. Other EUR rows proceed normally."),
    ('MC-008', 'MC-008 | Import mixed-currency CSV against multi-currency card — happy path', 1, 'Equals Money ****1234 registered; EUR/USD/GBP/JPY rates all configured; 12-row mixed CSV', '1. Select multi-currency card.\n2. Upload mixed CSV.\n3. Map columns including currency.\n4. Review preview.\n5. Confirm.', 'Each row stored with its own currency. GBP rows: rate=1.0. EUR/USD/JPY rows: correctly converted. Per-currency summary shown in preview header.'),
    ('MC-009', 'MC-009 | Block import when multi-currency card CSV has no currency column', 1, 'Multi-currency card; CSV has only Date, Merchant, Amount columns', '1. Select multi-currency card.\n2. Upload CSV without currency column.\n3. Reach mapping step.', "Import blocked: 'This is a multi-currency card. Your CSV must include a currency column.' System never defaults to home currency."),
    ('MC-010', "MC-010 | Reject invalid currency codes in CSV (e.g. 'Euro' instead of 'EUR')", 1, "Multi-currency card; CSV row 3 has 'Euro' in currency column", '1. Upload CSV.\n2. Map currency column.\n3. System validates each row.', "Row 3 rejected: 'Euro is not a valid code. Did you mean EUR?' Other valid rows shown in preview."),
    ('MC-011', 'MC-011 | Correct rounding: €412.50 × 0.8571 = £353.55 (not £353.56)', 1, 'EUR card; rate = 0.8571; transaction = €412.50', '1. Import €412.50 transaction with rate 0.8571.\n2. Check converted_amount in system.', '412.50 × 0.8571 = 353.55375 → stored as £353.55 (third decimal is 3, rounds down). Exchange rate shown as 0.8571.'),
    ('MC-012', 'MC-012 | Policy check uses converted GBP amount — not original foreign amount', 1, 'Hotel policy limit = £200; EUR card; transaction = €280 (converted £239.99)', '1. Import €280 hotel transaction.\n2. View transaction in approver panel.', "Red 'OVER LIMIT' badge shown. 'Exceeds by £39.99.' Policy checked against £239.99 (GBP), not €280."),
    ('MC-013', 'MC-013 | Claimant dashboard shows GBP primary with original currency in brackets', 1, 'EUR transaction £353.55 (€412.50) submitted', '1. Log in as Claimant.\n2. View My Expenses list.\n3. Locate the EUR transaction.', "Row shows '£353.55' as primary amount. '(€412.50 EUR)' displayed below in smaller text. GBP-only transactions show no brackets."),
    ('MC-014', 'MC-014 | GL posting reference field includes original currency and rate', 1, 'EUR transaction £353.55 posted to GL', '1. Finance Manager views GL posting preview.\n2. Inspect reference column for EUR transaction.', "Reference field shows: 'CCC-8823 | €412.50 EUR @ 0.8571'. GBP-only transactions show: 'CCC-4471' (no currency annotation)."),
    ('MC-015', 'MC-015 | Existing cards and transactions backfilled correctly after migration', 1, 'Pre-migration data with UK claimants (home currency GBP) in database', '1. Run migration script.\n2. Query all existing cards: check card_currency and is_multi_currency.\n3. Query all existing transactions: check original_amount, converted_amount, exchange_rate, rate_source.', "All existing cards: card_currency=GBP, is_multi_currency=FALSE. All existing transactions: original_amount=converted_amount, exchange_rate=1.0, rate_source='MIGRATION'. No data deleted."),
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
