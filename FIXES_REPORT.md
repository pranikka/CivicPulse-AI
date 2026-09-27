# CivicPulse AI — Existing Project Modification Report

## Scope

This update modifies the supplied `CivicPulse-AI-Hack2Skill-FINAL-COMPLETE.zip` in place. The existing Flask architecture, routes, database tables, citizen workflow, AI service, authentication, CSS/design system and existing pages are retained.

No tables or existing records are deleted.

## 1. Bugs / issues discovered

### High-priority assignment issues
- Officer visibility was based only on `assigned_officer_id`.
- A request with a valid AI recommendation could therefore appear as unassigned or remain invisible to an officer whose department matched the official department.
- `assigned_department` was stored as free text, while `User.department_id` used a stable department ID.
- AI department labels did not always exactly match the existing department directory, for example:
  - `Roads & Highways` vs `Road Maintenance`
  - `Electricity Board` vs `Electricity`
  - `Public Works / Drainage` vs `Drainage`
- Complaint details and management screens displayed AI recommendations as if they were official assignments.
- The assignment API did not validate that the selected officer belonged to the selected department.
- State-changing JavaScript requests for assignment/priority/notifications were missing CSRF headers in places, causing the application's CSRF protection to reject them.
- Government Dashboard department analytics was requested by Officer users, but its endpoint was Admin-only, producing an authorization error.
- Several Admin Dashboard module buttons were visual placeholders rather than real navigation.

### Analytics issues
- Some dashboard counts did not distinguish pending, in-progress, resolved, overdue and high/critical requests.
- Advanced analytics used the AI recommended department as the department distribution, which could misrepresent official government assignment.
- The older `/api/hotspots` endpoint used a synthetic population calculation (`demand * 150`); this was replaced with stored `Location.population` data or an explicit unavailable value.

## 2. Root cause of the "Unassigned" issue

The primary root cause was **assignment model separation being incomplete**.

The original project had:
- `CitizenRequest.assigned_department` — free-text official assignment
- `CitizenRequest.assigned_officer_id` — individual officer assignment
- `User.department_id` — officer's department
- `RequestAnalysis.recommended_department` — AI recommendation

But the officer scope was:

`assigned_officer_id == current_user.id`

Therefore, an officer could not see department-level requests unless they were individually assigned.

In addition, several templates used:

`assigned_department OR AI recommended_department OR Unassigned`

This made an AI recommendation look like an official department assignment.

The update now keeps the concepts separate:

1. **AI Recommended Department**
2. **Official Assigned Department**
3. **Assigned Officer**

If AI recommends a department but Admin has not officially assigned it, the UI reports:

`AI recommendation • Official assignment pending`

Only an actual official assignment is used for official department analytics.

## 3. Database changes

Backward-compatible nullable columns were added:

### `citizen_requests`
- `assigned_department_id`

### `request_analysis`
- `recommended_department_id`

Existing text fields remain intact for compatibility.

The existing startup migration was extended to add these columns only when they are missing.

Existing data is preserved.

The supplied SQLite database was also safely updated with these columns and missing AI recommendation metadata was backfilled from the already stored category analysis. No request/user records were deleted.

## 4. Backend changes

### Assignment
- Added stable department ID handling.
- Added explicit department compatibility aliases for existing department naming differences.
- Added official assignment resolution helpers.
- Added AI-vs-official assignment state logic.
- Added officer/department validation.
- Prevented AI re-analysis from overwriting official assignments.
- Assignment responses now return the resulting assignment state.

### Officer authorization
Officer visibility now supports:
- individually assigned requests;
- officially assigned requests in the officer's authorized department when no different officer is assigned.

Direct request access and update APIs use the same authorization rules.

### Analytics
- Officer dashboard statistics are database-backed.
- Department analytics is available to both Officer and Admin within their authorized scope.
- Official department analytics no longer treats AI recommendations as official assignments.
- Advanced statistics now expose assignment-state counts.
- Overdue and high/critical counts are database-derived.

### Existing-data compatibility
Missing historical AI department recommendations are backfilled from stored category analysis only when the recommendation field is empty.

## 5. Frontend changes

### Complaint details
Now clearly shows:
- AI Recommended Department
- Official Assigned Department
- Assigned Officer
- Pending official assignment state
- AI transparency wording

Assignment controls now:
- use stable department IDs;
- filter officer choices by department;
- send CSRF tokens;
- return the refreshed persisted state.

### Complaint management
Department column now distinguishes:
- Official assignment
- AI recommendation pending official assignment
- Truly unassigned

Officer column now uses `Not Assigned` instead of conflating AI recommendation with officer assignment.

### Officer / Government Dashboard
Live dashboard values now come from the database/API, including:
- Total Requests
- Active Requests
- High/Critical
- Resolved
- Overdue
- SLA compliance
- Emerging Issues
- Department Performance

API errors and empty data now receive explicit fallback UI.

### Admin Dashboard
Added live database-backed visibility for:
- Citizens
- Officers
- Departments
- Requests
- Pending
- In Progress
- High/Critical
- Resolved
- Overdue
- Truly Unassigned
- AI recommendation pending official assignment
- SLA compliance
- Feedback
- Districts
- Recent audit activity

Placeholder management buttons were replaced with working navigation to the project's existing Department Management, Complaint Management, Audit Log, Data Quality, SLA and Data Governance pages.

## 6. Features fixed

- Department-scoped Officer visibility
- Official/AI assignment distinction
- Officer/department assignment validation
- Stable department references
- Assignment CSRF handling
- Priority override CSRF handling
- Notification action CSRF handling
- Officer department analytics authorization
- Department performance calculation
- Complaint assignment display
- Assignment-state reporting
- Existing-data AI recommendation backfill
- Admin dashboard operational metrics
- Non-working Admin module navigation
- Synthetic hotspot population calculation

## 7. Features already working and preserved

The following existing areas were retained:
- Citizen registration/login
- Officer/Admin authentication
- Citizen request submission
- AI analysis
- Request tracking
- Complaint details
- Feedback
- Timeline
- Evidence upload
- Before/after evidence
- SLA configuration
- Audit logging
- Notifications
- Department creation/edit/activation
- Existing analytics
- Hotspot and area intelligence
- Trust/governance pages
- Existing CSS/design language
- Existing Flask routing structure

## 8. Verification performed

### Static/code verification
- `app.py` compiles successfully.
- `models.py` compiles successfully.
- `seed.py` compiles successfully.
- Existing Flask route inventory remains present.
- Assignment-related access-control paths were inspected.
- All occurrences of `Unassigned` were inspected after modification.

### Database verification
The supplied SQLite database was inspected before modification:
- 4 users
- 8 citizen requests
- 9 analysis rows
- 8 departments
- existing audit/notification data

The database was migrated non-destructively and existing request records were preserved.

Existing missing AI recommendations were backfilled from their stored analysis category without creating official government assignments.

### Workflow logic verification
A temporary database copy was used to simulate:
- Officer assigned to Water Supply department
- Request officially assigned to Water Supply
- Officer assigned to that request

The department-scope query correctly returned the request to that officer.

### Runtime limitation of this inspection environment
The provided ZIP could be statically compiled and its SQLite database inspected/migrated, but the execution environment did not have Flask/Flask-SQLAlchemy installed and could not download packages because external package access was unavailable. Therefore a live HTTP/browser test of every route could not be executed here.

The project remains dependent on the existing `requirements.txt` and should be run with the user's existing Flask environment.

## 9. Remaining limitations

- The existing department directory does not contain dedicated Health, Education or Transport departments. Those AI recommendations remain AI recommendations until an Admin creates/configures the corresponding official department.
- AI recommendations are intentionally not automatically converted into government assignments.
- External AI provider behavior still depends on the provider/API configuration already present in the project.
- Browser-level visual testing could not be performed in this environment.

## Responsible-AI wording

Where AI recommendations are shown, the project retains:

**AI-generated recommendation • Human review required.**

AI output remains separate from official government assignment/action.
