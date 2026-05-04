import sys; sys.path.insert(0, '.')
from data.loader import load_data
import pandas as pd

df = load_data()
bugs = df[df['work_item_type'].isin(['Bug','Bug_UI','Bug_Text'])]
enh  = df[df['work_item_type'] == 'Enhancement']

# Defect escape rate
all_bugs  = len(bugs)
prod_bugs = len(bugs[bugs['stage'] == '4 - PROD'])
dev_bugs  = len(bugs[bugs['stage'] == '2 - Dev'])
qa_bugs   = len(bugs[bugs['stage'] == '3 - QA'])
print('=== Defect Escape Rate ===')
print(f'Found in Dev:    {dev_bugs} ({dev_bugs/all_bugs*100:.0f}%)')
print(f'Found in QA:     {qa_bugs} ({qa_bugs/all_bugs*100:.0f}%)')
print(f'Escaped to PROD: {prod_bugs} ({prod_bugs/all_bugs*100:.0f}%)')

# Open bugs
open_bugs = bugs[bugs['is_active'] == True]
print()
print('=== Open bugs ===')
print(f'Total open: {len(open_bugs)}')
print(f'Critical: {len(open_bugs[open_bugs["priority"]==1])}')
print(f'High:     {len(open_bugs[open_bugs["priority"]==2])}')
print(f'Medium:   {len(open_bugs[open_bugs["priority"]==3])}')

# Customer issues
cust_bugs = bugs[bugs['type'] == 'Customer']
open_cust = cust_bugs[cust_bugs['is_active'] == True]
print()
print('=== Customer issues ===')
print(f'Total customer bugs (all time): {len(cust_bugs)}')
print(f'Open customer bugs: {len(open_cust)}')
print(f'Customer % of PROD bugs: {len(bugs[(bugs["stage"]=="4 - PROD") & (bugs["type"]=="Customer")])/prod_bugs*100:.0f}%')

# 2025-2026 iterations
recent_bugs = bugs[bugs['iteration_path'].astype(str).str.contains('2025|2026', na=False)]
def get_iter(x):
    parts = str(x).split('\\')
    return parts[-1]
recent_bugs = recent_bugs.copy()
recent_bugs['iter_label'] = recent_bugs['iteration_path'].apply(get_iter)
per_iter = recent_bugs.groupby('iter_label').size().sort_values(ascending=False)
print()
print('=== Bugs per iteration (recent) ===')
print(per_iter.head(10))

# Avg bugs per iteration
print(f'\nAvg bugs per iteration: {per_iter.mean():.0f}')

# Enh vs bug trend
print()
print('=== Overall ratio ===')
print(f'Total enhancements: {len(enh)}')
print(f'Total bugs:         {len(bugs)}')
print(f'Enh:Bug ratio:      {len(enh)/len(bugs):.2f} (target should be >= 1.0)')

# MTTC by priority
bugs_closed = bugs[bugs['closed_date'].notna() & bugs['created_date'].notna()].copy()
bugs_closed['mttc'] = (pd.to_datetime(bugs_closed['closed_date']) - pd.to_datetime(bugs_closed['created_date'])).dt.days
bugs_closed = bugs_closed[bugs_closed['mttc'] >= 0]
print()
print('=== MTTC by priority ===')
for p, label in [(1,'Critical'), (2,'High'), (3,'Medium'), (4,'Low')]:
    sub = bugs_closed[bugs_closed['priority'] == p]
    if len(sub):
        print(f'{label}: median {sub["mttc"].median():.0f}d, mean {sub["mttc"].mean():.0f}d  (n={len(sub)})')
