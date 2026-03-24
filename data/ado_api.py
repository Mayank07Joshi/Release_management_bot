import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

ADO_PAT = os.environ.get("AZURE_DEVOPS_PAT")
ORG_URL = os.environ.get("ORGANIZATION_URL", "").rstrip("/")
PROJECT = os.environ.get("PROJECT_NAME")

def get_auth_header():
    if not ADO_PAT:
        raise ValueError("AZURE_DEVOPS_PAT not found in .env")
    # ADO requires "Basic " + base64(":" + PAT)
    encoded = base64.b64encode(f":{ADO_PAT}".encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json-patch+json"}

def update_work_item(work_item_id, field_reference_name, new_value):
    """
    Sends a JSON Patch to update a single field on a work item.
    Uses ADO REST API version 7.1.
    """
    url = f"{ORG_URL}/{PROJECT}/_apis/wit/workitems/{work_item_id}?api-version=7.1"
    
    headers = get_auth_header()
    
    # JSON Patch document format
    payload = [
        {
            "op": "add",
            "path": f"/fields/{field_reference_name}",
            "value": new_value
        }
    ]
    
    response = requests.patch(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def map_dashboard_col_to_ado_field(dash_col):
    """Maps the dashboard column names to strict ADO field reference names."""
    mapping = {
        "priority": "Microsoft.VSTS.Common.Priority",
        "state": "System.State",
        "severity": "Microsoft.VSTS.Common.Severity",
        "title": "System.Title",
        "assigned_to": "System.AssignedTo",
        "original_estimate": "Microsoft.VSTS.Scheduling.OriginalEstimate",
        "completed_work": "Microsoft.VSTS.Scheduling.CompletedWork",
        "remaining_work": "Microsoft.VSTS.Scheduling.RemainingWork"
    }
    return mapping.get(dash_col)
