"""
UC42 - Show Expenses Older Than 180 Days on Mobile
VSTS Test Case Uploader
Uploads 26 test cases linked to enhancement 38833.
Before running: pip install requests
Usage: python upload_uc42_test_cases.py
"""
import requests, json, base64, html, sys, time, re, os

PAT               = os.environ.get("ADO_PAT", "")
ORG               = "expenseondemand"
PROJECT           = "Solo Expenses"
ENHANCEMENT_ID    = 38833
FUNCTION_VALUE    = "Projects & Budget"
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
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    for f in r.json().get("value", []):
        name = f.get("name","").lower()
        ref  = f.get("referenceName","").lower()
        if any(k in name or k in ref for k in ("function","automat","area")):
            print(f"  {f['name']:40s}  {f['referenceName']}")

def build_steps_xml(steps_text, expected_text):
    lines = [l.strip() for l in steps_text.strip().split("\n") if l.strip()]
    steps = [re.sub(r"^\d+[\.)\s]\s*", "", l).strip() for l in lines]
    steps = [s for s in steps if s]
    parts = [f'<steps id="0" last="{len(steps)}">']
    for i, action in enumerate(steps, start=1):
        esc_a  = html.escape(action)
        is_last = (i == len(steps))
        esc_e   = html.escape(expected_text) if is_last else ""
        etag    = f"&lt;P&gt;{esc_e}&lt;/P&gt;" if esc_e else ""
        stype   = "ValidateStep" if esc_e else "ActionStep"
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
                   "attributes": {"comment": "UC42 - Show expenses older than 180 days on mobile"}}},
    ]
    if precondition:
        payload.append({"op": "add",
                        "path": "/fields/Microsoft.VSTS.TCM.LocalDataSource",
                        "value": precondition})
    r = requests.post(url, headers=PATCH_HEADERS, data=json.dumps(payload))
    if r.status_code not in (200, 201):
        print(f"  FAILED '{title[:60]}': {r.status_code} {r.text[:300]}")
        return None
    return r.json()["id"]

TEST_CASES = [
    ('TC-UC42-001', 'TC-UC42-001 | Expense list displays all history without 180-day cutoff', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has at least 5 expenses older than 180 days in Incomplete Cash Expenses.', "1. Log in to EOD mobile app.\n2. Navigate to Expense List.\n3. Tap 'Incomplete Cash Receipts/Expenses'.\n4. Scroll through the list.", 'All expenses — including those older than 180 days — are visible. No expenses are hidden or truncated based on date. The count matches the Quick Actions count.'),
    ('TC-UC42-002', 'TC-UC42-002 | Quick Actions count matches Expense List landing page count', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has expenses older than 180 days in Rejected and Incomplete Cash categories.', "1. Log in to EOD mobile app.\n2. Note the count shown in Quick Actions for 'Incomplete Cash Expenses'.\n3. Navigate to Expense List.\n4. Note the count shown on the landing page for the same category.\n5. Tap the category and count the visible items (including paginated ones).", 'Quick Actions count = Expense List landing page count = Total items in the category list (across all pages). There is zero discrepancy between any of the three counts.'),
    ('TC-UC42-003', 'TC-UC42-003 | Expense List landing page count matches category list count', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has more than 10 expenses spanning different date ranges including items older than 1 year.', "1. Navigate to the Expense List landing page.\n2. Note the count displayed for 'Pending with Approver'.\n3. Tap 'Pending with Approver'.\n4. Scroll through all pages using 'Load More'.\n5. Count all visible items.", 'The total number of items paginated through equals the count displayed on the landing page. No items are missing.'),
    ('TC-UC42-004', 'TC-UC42-004 | Cursor-based pagination loads 10 items per page', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 25+ incomplete cash expenses.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Observe the initial list load.\n3. Tap 'Load More' at the bottom.", "Initial load shows exactly 10 items. After tapping 'Load More', the next 10 items are appended. The 'Load More' button disappears when no further items exist (nextCursor is null)."),
    ('TC-UC42-005', "TC-UC42-005 | 'Load More' button appears and disappears correctly", 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has exactly 15 incomplete CC receipts.', "1. Navigate to 'Incomplete Corporate Credit Card Receipts'.\n2. Observe the 'Load More' button after initial load of 10 items.\n3. Tap 'Load More'.\n4. Observe the button after the remaining 5 items load.", "After initial load: 'Load More' is visible. After tapping and loading all 15 items: 'Load More' button is hidden/removed since there are no further items."),
    ('TC-UC42-006', 'TC-UC42-006 | Old expense (>180 days) can be opened and viewed', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has a rejected expense that is 200 days old.', "1. Navigate to 'Rejected' in the Expense List.\n2. Scroll to find an expense older than 180 days.\n3. Tap on the expense.", 'The expense opens fully. All details (date, amount, supplier, category, rejection reason) are visible and correct. No error or empty screen is shown.'),
    ('TC-UC42-007', 'TC-UC42-007 | Old expense can be edited and resubmitted from mobile', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has an incomplete cash expense that is 250 days old.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Open an expense older than 180 days.\n3. Edit the category field.\n4. Submit the expense.", 'Expense opens and is editable. Changes can be saved. Expense can be submitted without requiring the user to switch to web. The submission is successful.'),
    ('TC-UC42-008', "TC-UC42-008 | 'Last 180 days' banner is removed from the expense list", 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed.', '1. Navigate to any expense category list (e.g., Incomplete Cash Expenses).\n2. Observe the top of the screen.', "The 'Default Filter: Last 180 days' banner is no longer displayed. No text on the screen implies a date limitation exists."),
    ('TC-UC42-009', 'TC-UC42-009 | All 9 expense category lists display full history', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has at least 1 expense older than 180 days in each of the 9 categories.', '1. Navigate to each of the 9 expense categories in sequence:\n   - Emailed Receipts\n   - Incomplete Cash Receipts/Expenses\n   - Incomplete CC Receipts\n   - Incomplete CC Transactions\n   - Rejected\n   - Pending with Approver\n   - Pending with Finance Approver\n   - Pending Passed for Payment\n   - Passed for Payment\n2. For each, verify that expenses older than 180 days are visible.', 'For all 9 categories, expenses older than 180 days appear in the list. No category retains the 180-day cutoff.'),
    ('TC-UC42-010', 'TC-UC42-010 | Sorting works correctly across full expense history', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 30+ incomplete cash expenses spanning 2 years.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Apply 'Sort by Date' (descending).\n3. Verify the order of the first 10 items.\n4. Load more pages and verify continued sort order.", 'Items are sorted in correct descending date order across all pages. The sort is consistent — no item appears out of sequence when paginating.'),
    ('TC-UC42-011', "TC-UC42-011 | Date range filter includes 'All Time' option", 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed.', "1. Navigate to 'Rejected' in the Expense List.\n2. Open the filter/date range options.\n3. Select 'All Time'.", "An 'All Time' date range option is available. Selecting it shows all rejected expenses regardless of age. The count matches the landing page count."),
    ('TC-UC42-012', 'TC-UC42-012 | Search finds expenses older than 180 days', "User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has an expense with supplier 'OldCafé' that is 300 days old.", "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Use the search/filter to search for 'OldCafé'.\n3. Observe results.", "The old expense for 'OldCafé' (300 days old) appears in the search results. Search is not limited to the last 180 days."),
    ('TC-UC42-013', 'TC-UC42-013 | Infinite scroll / Load More works on low-bandwidth connection', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. Device is on a 3G network. User has 50+ expenses in Passed for Payment.', "1. Set device to 3G or slow network.\n2. Navigate to 'Passed for Payment'.\n3. Scroll to the bottom and tap 'Load More'.\n4. Observe load time and result.", 'Next 10 items load within 1–2 seconds. The app does not crash, freeze, or show an error. A loading indicator is displayed while fetching. Data appears correctly after load.'),
    ('TC-UC42-014', 'TC-UC42-014 | iOS and Android display identical counts and items', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. The same user account is tested on both iOS and Android devices.', '1. Log in on iOS device — note Quick Actions count and list count for each category.\n2. Log in on the same account on Android — note the same counts.\n3. Open a specific old expense on both platforms.', 'Counts are identical on iOS and Android. The same expenses are visible on both platforms. There is no platform-specific 180-day restriction on either.'),
    ('TC-UC42-015', 'TC-UC42-015 | Pop-up for items older than 180 days no longer appears', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has expenses older than 180 days.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Navigate to any screen that previously showed the '180 days' pop-up message.", "The pop-up message 'There are X of Y items which are older than 180 days. These cannot be viewed on mobile.' is no longer displayed anywhere in the app."),
    ('TC-UC42-NEG-001', 'TC-UC42-NEG-001 | Count mismatch does not occur after full data load', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 77 incomplete cash expenses spanning 3 years.', "1. Note count in Quick Actions for 'Incomplete Cash Expenses' (e.g. 77).\n2. Navigate to Expense List landing page and note the count.\n3. Navigate into 'Incomplete Cash Expenses'.\n4. Paginate through all pages using 'Load More'.\n5. Total up all loaded items.", 'All three counts are identical (77). The previous mismatch (Quick Actions 77 vs list showing 16) no longer occurs.'),
    ('TC-UC42-NEG-002', 'TC-UC42-NEG-002 | Expenses are not duplicated across pagination pages', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has exactly 25 incomplete cash expenses.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Record the IDs/details of all 10 items on the first page.\n3. Tap 'Load More' — record items on page 2 (next 10).\n4. Tap 'Load More' again — record items on page 3 (last 5).\n5. Check for duplicates across all three pages.", 'No expense appears on more than one page. Total count across all pages equals 25. Cursor-based pagination ensures consistency — no duplicates, no gaps.'),
    ('TC-UC42-NEG-003', 'TC-UC42-NEG-003 | No regression in expenses submitted less than 180 days ago', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has expenses from today, 30 days ago, and 200 days ago.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Verify that recent expenses (today, 30 days ago) still appear.\n3. Verify that old expenses (200 days ago) also appear.", 'Both recent and old expenses are visible. Removing the 180-day filter does not affect recent expenses — they are still shown correctly.'),
    ('TC-UC42-NEG-004', 'TC-UC42-NEG-004 | API payload remains under 100KB per page request', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. Network monitoring is enabled on the device.', "1. Navigate to any expense category with 50+ items.\n2. Monitor the API response for each 'Load More' request using network tools or Charles Proxy.", 'Each API response payload is under 100KB. Response time for each page load is under 1 second on a standard mobile connection (4G or above).'),
    ('TC-UC42-NEG-005', 'TC-UC42-NEG-005 | App does not crash or freeze when loading large history', "User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 200+ expenses in 'Passed for Payment'.", "1. Navigate to 'Passed for Payment'.\n2. Continuously tap 'Load More' 20 times.\n3. Scroll rapidly through the full list.", 'App remains stable throughout. No crashes, freezing, or ANR (Application Not Responding) dialogs occur. Scrolling is smooth with no jank.'),
    ('TC-UC42-NEG-006', 'TC-UC42-NEG-006 | Expenses from other users are not shown', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. Two different users exist in the same subscription with old expenses.', "1. Log in as User A.\n2. Navigate to 'Incomplete Cash Receipts/Expenses'.\n3. Load all pages.\n4. Verify all visible expenses belong only to User A.", "Only User A's expenses are visible. No expenses belonging to User B (or any other user) are displayed, even when the full history is loaded."),
    ('TC-UC42-PERF-001', 'TC-UC42-PERF-001 | Initial page load completes within 1–2 seconds', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 100+ expenses in the Rejected category. Device is on a 4G network.', "1. Navigate to 'Rejected' in the Expense List.\n2. Measure the time from tap to first 10 items being visible.", 'First 10 items are displayed within 1–2 seconds of navigating into the category. A loading indicator is shown until data is ready.'),
    ('TC-UC42-PERF-002', "TC-UC42-PERF-002 | 'Load More' fetch completes within 0.5–1 second", 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has 50+ expenses in Incomplete Cash. Device is on a 4G network.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. After initial load, tap 'Load More'.\n3. Measure the time from tap to next 10 items appearing.", "Next 10 items load and are visible within 0.5–1 second of tapping 'Load More'."),
    ('TC-UC42-CON-001', 'TC-UC42-CON-001 | Mobile and web display identical counts for all 9 categories', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. The same user account is active on both web and mobile.', '1. Log in on mobile — record expense counts for all 9 categories.\n2. Log in on web — record expense counts for all 9 categories.\n3. Compare counts.', 'All 9 category counts are identical between mobile and web. Mobile no longer shows fewer items due to the 180-day filter.'),
    ('TC-UC42-CON-002', 'TC-UC42-CON-002 | Pulling to refresh reloads full list correctly', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed.', "1. Navigate to 'Pending with Approver' in the Expense List.\n2. Load several pages.\n3. Perform a pull-to-refresh gesture.", 'The list resets to the first 10 items. Counts remain accurate. No stale data or duplication appears after refresh.'),
    ('TC-UC42-CON-003', 'TC-UC42-CON-003 | Back navigation does not lose pagination state', 'User is logged into EOD mobile app (iOS or Android). The user has expenses spanning more than 180 days across multiple categories. The 180-day filter removal has been deployed. User has loaded 3 pages of Incomplete Cash Expenses.', "1. Navigate to 'Incomplete Cash Receipts/Expenses'.\n2. Load 3 pages using 'Load More'.\n3. Tap on an expense to open it.\n4. Tap the back button.", 'The user returns to the expense list in the same position (30 items still visible). Scroll position is maintained. No data is lost or reset.'),
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
            print(f"  \u2713  [{wi_id}]  {tc_id} - {title[:70]}")
            created.append((tc_id, wi_id))
        else:
            print(f"  \u2717 FAILED  {tc_id}")
            failed.append(tc_id)
        time.sleep(0.3)
    print(f"\n" + "-"*60)
    print(f"Done.  Created: {len(created)}   Failed: {len(failed)}")
    if failed:
        print(f"Failed: {', '.join(failed)}")

if __name__ == "__main__":
    main()
