# Expense on Demand — Phase 3 Analytics Vision
### Customer Intelligence & Product Health Platform
**Prepared for:** Management Review
**Date:** March 2026

---

## Executive Summary

Over the past two phases, we have built an internal analytics platform that gives our delivery teams real-time visibility into sprint health, bug trends, QA output, team capacity, and release readiness. That foundation is now mature and operational.

**Phase 3 is about turning that analytical capability outward — toward our customers.**

The goal is to build a Customer Intelligence layer that tells us, at any point in time: which companies are thriving on Expense on Demand, which are quietly slipping away, where our product is creating friction, and what actions we can take — proactively — before a customer churns, escalates, or disengages.

This is not a reporting exercise. It is a strategic shift from reactive customer management to data-driven account intelligence.

---

## Where We Are Today

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | Internal delivery metrics — sprint tracking, burndown, team velocity | Complete |
| Phase 2 | Quality & release health — bug trends, QA output, capacity planning | Complete |
| **Phase 3** | **Customer intelligence — product usage, churn risk, approval health** | **Proposed** |

Our current platform answers: *"How is our team performing?"*

Phase 3 answers: *"How are our customers performing — and what does that mean for us?"*

---

## The Business Case

Expense management is a workflow product. Customers do not evaluate it on features alone — they evaluate it on whether it makes expense submission and reimbursement **fast and effortless** for their employees. If approval cycles are slow, if employees abandon claims halfway through, if finance teams are manually chasing down rejections — the product feels broken even if it isn't.

We currently have no systematic visibility into any of this at a customer level.

### The Risk of Flying Blind

- A customer's submission volume drops 60% over three months. We find out when they submit a cancellation request.
- A mid-market client has a 14-day average approval cycle because two managers are not actioning claims. Their employees complain to HR. HR complains to the company admin. The admin blames the software.
- A new client goes live but only 15% of their employees ever submit a claim. Low adoption leads to low perceived value. They do not renew.

Each of these scenarios is **detectable weeks or months in advance** with the right data. Phase 3 builds that detection.

---

## Vision: What We Are Building

A **Customer Health Dashboard** integrated into our existing analytics platform, providing:

### 1. Company Health Scorecards
A per-client view showing submission volume trends, user adoption rates, approval cycle times, and reimbursement SLA compliance. Each account gets a health score — green, amber, or red — updated on a rolling basis.

*The output:* Customer Success and Account Management walk into every QBR knowing exactly which metrics are healthy and which need a conversation.

### 2. Churn Risk Detection
Automated flagging of accounts showing early churn signals — declining submission volume, falling active user counts, or unusually high rejection rates. Flagged accounts surface on a watchlist with the specific signal that triggered them.

*The output:* CS teams intervene before the customer has even considered leaving.

### 3. Approval Chain Intelligence
Company-level visibility into where the approval process breaks down. Which companies have the slowest manager approval cycles? Where are claims sitting for more than 5 days? Where are rejection rates high — and why?

*The output:* A targeted conversation with the client admin or a product improvement insight, depending on whether it is a configuration issue or a UX issue.

### 4. Product Funnel Analysis
Where in the claim submission flow do employees drop off? Do users who start on mobile complete at the same rate as web users? Which expense categories generate the most rejections?

*The output:* Direct input to the product roadmap — validated by real usage data, not assumptions.

### 5. Release Impact Correlation
Connecting our internal release data (which we already track) with customer-facing outcomes — did support ticket volume spike after a release? Did approval cycle times change? Which customer segments were most affected?

*The output:* Closes the loop between engineering decisions and customer experience.

---

## Data Requirements

The following data is required from the relevant engineering and data teams to power Phase 3. Most of this exists in the Expense on Demand transactional database today.

### Priority 1 — Core (needed to start)

| Data Point | Source | Notes |
|---|---|---|
| Claim records with timestamps | EoD App DB | Submitted at, approved at, paid at, rejected at |
| Claim status and status history | EoD App DB | Full status trail per claim, not just current state |
| Rejection reason codes | EoD App DB | Structured reason, not free text |
| Company / tenant identifiers | EoD App DB | Company ID linked to each user and claim |
| User records per company | EoD App DB | Total users registered vs. active (submitted in last 30 days) |
| Approver assignment per claim | EoD App DB | Which manager is responsible for each pending claim |

**Delivery ask:** Read-only access to a reporting replica of the EoD production database, or a scheduled export (daily minimum, hourly preferred) of the above tables into our analytics PostgreSQL instance.

---

### Priority 2 — Funnel & Behavioural (needed for drop-off analysis)

| Data Point | Source | Notes |
|---|---|---|
| Claim draft / session start events | App instrumentation | Requires event listeners at claim creation entry points |
| Receipt upload attempts and outcomes | App instrumentation | Success, failure, reason |
| Mobile vs. web session split | App instrumentation | Per user, per session |
| Feature interaction events | App instrumentation | Which features are used, by whom, how often |

**Delivery ask:** Instrumentation of key user journey touchpoints using an agreed event schema (`{ company_id, user_id, event_name, timestamp, properties }`). Events to be routed to a collector endpoint we will provide (self-hosted PostHog on Azure, or direct to our event store).

---

### Priority 3 — Support Correlation (enhances churn model)

| Data Point | Source | Notes |
|---|---|---|
| Support ticket volume per company | Zendesk / Freshdesk API | Ticket open date, category, resolution time |
| NPS or CSAT scores per company | Survey tool (if in use) | Linked by company ID |

**Delivery ask:** API credentials for support platform. We will write the integration.

---

## What We Are NOT Building

To be clear on scope and avoid scope creep:

- We are not building a CRM replacement. Salesforce/HubSpot remains the record of commercial relationships.
- We are not building a billing or revenue analytics tool.
- We are not exposing this data externally to customers. This is an internal intelligence tool.
- We are not replacing Customer Success workflows — we are informing them.

---

## Proposed Roadmap

### Phase 3a — Company Health & Churn Detection (Weeks 1–6)
Requires Priority 1 data only. Delivers company scorecards, churn risk watchlist, and approval chain visibility. Fastest path to value.

### Phase 3b — Product Funnel & Behavioural Analytics (Weeks 7–14)
Requires Priority 2 instrumentation. Delivers drop-off analysis, mobile/web split, feature adoption heatmaps.

### Phase 3c — Release Impact & Support Correlation (Weeks 15–20)
Requires Priority 3 integrations. Closes the loop between engineering, product, and customer outcomes.

---

## What We Need to Proceed

1. **Management sign-off** on Phase 3 scope and roadmap
2. **Data team / engineering engagement** to provide Priority 1 database access or export pipeline
3. **CS and Account Management alignment** — define what a "churn risk" flag should trigger operationally
4. **Instrumentation agreement** — engineering team to agree on event schema and integration approach for Phase 3b

Phase 3a can begin as soon as Priority 1 data access is granted. No new infrastructure is required — we extend the platform we have already built.

---

## Summary

We have the platform. We have the pattern. We have done this for our own teams across two phases and it works.

Phase 3 is about applying the same rigour to the customers who pay for our product — giving every team at Expense on Demand the visibility they need to retain accounts, improve the product, and grow with confidence.

The data is already there. We just need to connect to it.

---

*Analytics Platform — Internal Document*
*For questions or follow-up, contact the Release Analytics team*
