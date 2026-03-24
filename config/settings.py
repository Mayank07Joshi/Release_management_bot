"""Application settings and constants"""


from datetime import date


ANALYSIS_START_DATE = date(2025, 1, 1)

# Chart colors
COLOR_SCHEMES = {
    'bugs': 'Reds',
    'qa': 'Blues',
    'team': 'Greens',
    'area': 'Plasma',
    'function': 'Viridis'
}

# Chart heights
CHART_HEIGHTS = {
    'donut': 400,
    'bar': 350,
    'function': 400
}

# Display limits
TOP_N_FUNCTIONS = 10
TOP_N_AREAS = 8
RECENT_DAYS = 30
RECENT_ITEMS_COUNT = 15

# Azure DevOps Configuration
ADO_ORG = "expenseondemand"
ADO_PROJECT = "Solo%20Expenses"
ADO_BASE_URL = f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_workitems/edit/"

# CSV filename
DATA_FILE = 'data-1773128446057.csv'
