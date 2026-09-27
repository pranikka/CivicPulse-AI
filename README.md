# CivicPulse AI

**Turning Citizen Voices into Smarter Public Development**

CivicPulse AI is a full-stack GovTech web application that harnesses citizen feedback to identify infrastructure gaps, prioritize development investments, and enable data-driven governance with human oversight.

## Features

- **Smart Complaint Registration**: Title, description, category, location, optional GPS, date/time, contact details, anonymous submission, and secure evidence uploads
- **AI-Powered Complaint Analysis**: Category, issue type, priority, urgency, recommended department, sentiment, and confidence score
- **AI Provider Fallback**: Local analysis works without an API; an OpenAI-compatible provider can be enabled with environment variables
- **Demand Aggregation**: Identify patterns and hotspots from real complaint data
- **Civic Hotspot Detection**: Area/ward complaint concentration, category/priority distribution, trend, and severity
- **Officer Dashboard**: Government officers access analytics and recommendations
- **Interactive Civic Issue Map**: GPS complaint markers, category/priority/status/date filters, zoom, and marker clustering
- **Advanced Analytics**: Status KPIs, category/department/location/month/priority charts, resolution metrics, workload, and optional satisfaction data
- **Explainable AI**: Every recommendation includes reasoning for transparency
- **Human Review**: Government officers verify all AI recommendations before action
- **Multilingual Support**: English, Hindi, Tamil, Telugu, Kannada, Malayalam

## Technology Stack

- **Frontend**: HTML5, CSS3, JavaScript
- **Backend**: Python Flask
- **Database**: SQLite
- **Charts**: Chart.js (via CDN)
- **Authentication**: Session-based with password hashing
- **Secure Media Storage**: Uploaded complaint evidence is stored outside the public static directory and served through an authenticated route

## Project Structure

## Added in this update

- Role-based access control is scoped to Citizen-owned complaints, Officer-assigned complaints, and Admin-wide management.
- Admin PDF reports with date/category/department/status/priority/location filters.
- Admin CSV and Excel exports using the same filters.
- English/Tamil language switcher with a centralized translation dictionary.
- Public Civic Assistant with local FAQ/navigation support and optional use of the existing configured AI provider without exposing API keys.
- Additive citizen profile page.
- Additional authorization checks for complaint APIs, timelines, media, assignments, updates, priorities, statuses, analytics, maps, hotspots, and demand prediction.

Report/export dependencies are listed in `requirements.txt`.

## Optional Email Notifications

Email notifications are disabled by default and never replace the existing in-app notification system. To enable them, set these environment variables:

- `EMAIL_NOTIFICATIONS_ENABLED=1`
- `SMTP_SERVER`
- `SMTP_PORT` (default `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS=1`

If SMTP configuration is missing or an email send fails, the CivicPulse AI application continues normally and logs the failure.

## Admin Audit Log

Administrators can open `/admin/audit-log` from the Admin Panel navigation. The audit trail records important administrative actions such as user creation, department changes, complaint reassignment, priority overrides, authorized status changes, and SLA/configuration changes. Passwords, API keys, and other secrets are not stored.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.



## Extended Hack2Skill Features (Integrated into the Existing Architecture)

The updated CivicPulse AI project preserves the existing Flask routes, authentication, database, dashboards and request workflow while extending them with:

1. Multilingual citizen requests: English, Tamil, Hindi, Telugu, Kannada and Malayalam, with original/normalized text and language metadata.
2. Browser voice reporting using Web Speech API where supported, with editable transcription and text fallback.
3. Automatic language detection with confidence and manual language selection.
4. Explainable AI results showing supporting factors, request patterns, signals and limitations.
5. Confidence details for category, urgency, priority and recommendation, including low-confidence handling.
6. Human-in-the-loop AI review: Review Required -> Accepted / Modified / Rejected, with reviewer and timestamp audit data.
7. Real-data geographic hotspot analytics with category distribution, priority distribution, trends, projects and affected-population fields when available.
8. Demand trend analytics for 7/30/90/365-day periods with category, location, department, priority and status filters.
9. Emerging issue analytics comparing the latest 30 days with the preceding 30 days, with evidence and small-data caution.
10. Infrastructure/service-gap indicators using stored citizen demand, infrastructure records and project records.
11. Officer Area Intelligence for locality/ward analysis.
12. Lifecycle timeline from submission through AI analysis, department/officer assignment, progress, resolution and feedback.
13. SLA overview with target, elapsed/remaining time, due-soon and overdue alerts.
14. Secure before/after evidence workflow retained and extended with role-protected media handling.
15. Citizen-safe request tracking with timestamps and no internal officer information.

### Important methodology note

The default AI provider is the existing deterministic local analyzer. It uses stored request text, selected category, keyword/context evidence and real database counts. It does not invent production confidence values. If `AI_PROVIDER=openai` and the required environment variables are configured, the existing OpenAI-compatible integration can be used. AI output remains advisory and must be reviewed by an authorized human officer.

### New important routes

- `/citizen/request`
- `/citizen/analysis`
- `/citizen/track`
- `/officer/government-dashboard`
- `/officer/demand-analysis`
- `/officer/hotspots`
- `/officer/area-intelligence`
- `/api/language-detect`
- `/api/request/<request_id>/review`
- `/api/analytics/trends`
- `/api/analytics/emerging-issues`
- `/api/analytics/infrastructure-gaps`
- `/api/area-intelligence`
- `/api/sla/overview`

### Database migration

The application performs an idempotent SQLite schema migration at startup. Existing records are preserved. New multilingual/voice fields were added to `citizen_requests`; human-review and confidence metadata were added to `request_analysis`. No destructive migration is used.

### Demo credentials

- Citizen: `demo_citizen` / `demo123`
- Officer: `demo_officer` / `demo123`
- Admin: `demo_admin` / `demo123`

Demo records are synthetic and are not real government data.

### Limitations

- Browser voice recognition depends on browser/device support and may require online browser speech services.
- Language detection is strongest for native Indic scripts. Transliteration and Latin-script Indian languages are conservatively handled using the selected language metadata.
- The local AI analyzer is a transparent deterministic baseline, not a trained government-grade model.
- Infrastructure-gap and emerging-issue indicators depend on the amount and quality of data available in the database.
- Maps use the existing OpenStreetMap/Leaflet integration and require network access for map tiles.
- Production deployment should use a strong persistent `SECRET_KEY`, HTTPS, secure session cookies, a production WSGI server and a managed database.


## Hack2Skill 2026 Closed-Loop Extensions

This version preserves the existing CivicPulse AI Flask architecture and adds:
- post-resolution citizen feedback with optional reopen request
- Responsible AI / Trust Center
- implementation-backed Data Governance view
- outcome intelligence and closed-loop analytics
- citizen demand vs existing project comparison
- consolidated government dashboard signals
- category and department analytics
- role-aware notifications for request lifecycle events
- judge-facing Demo Center
- demo Citizen/Officer/Admin accounts
- system status page
- enhanced government development-insight PDF reporting

Responsible-AI notice: **AI-generated recommendation • Human review required.**

### Demo accounts
- Citizen: `demo_citizen` / `demo123`
- Officer: `demo_officer` / `demo123`
- Admin: `demo_admin` / `demo123`

These are synthetic hackathon accounts only.

### Additional routes
- `/trust-center`
- `/admin/data-governance`
- `/outcomes`
- `/demo-center`
- `/system-status`
- `/api/analytics/outcomes`
- `/api/analytics/categories`
- `/api/analytics/project-comparison`
- `/api/system-status`

### Database migration
The existing database is preserved. Startup migration adds only missing feedback fields:
`reopened_requested` and `reopened_reason`.


## Hack2Skill Feature 39–44 Update

This release extends the existing CivicPulse AI application without replacing its Flask architecture.

### New judge-facing capabilities
- Development Impact Dashboard (`/impact-dashboard`)
- Civic Insight Summary (`/civic-insight`)
- Admin Data Quality & Coverage (`/admin/data-quality`)
- Public Transparency Dashboard (`/public-transparency`)
- Database-backed unified government search now includes language filtering.
- AI analysis includes historical similarity evidence using the application's existing token/location/category similarity method.
- Existing priority classification remains documented and human-overridable.
- Accessibility and mobile hardening added without changing the visual identity.
- System Status now reports additional implemented modules.

### Data methodology
Measured metrics are calculated from stored CivicPulse records. When there is insufficient data, the interface displays **Not enough data** rather than inventing values. AI-assisted summaries state **AI-generated summary • Verify with source data.**

### Privacy
The public transparency dashboard is aggregate-only. It does not expose names, emails, phone numbers, private addresses, request descriptions, or evidence.

### Responsible AI
**AI-generated recommendation • Human review required.**
CivicPulse AI is decision support. Authorized officers remain responsible for final government decisions.

### Production checklist
Before production deployment:
1. Set a persistent high-entropy `SECRET_KEY` in environment variables.
2. Use HTTPS and `SESSION_COOKIE_SECURE=1`.
3. Use a production WSGI server and production database.
4. Review upload storage permissions and backups.
5. Configure only required external AI/email providers.
6. Review the System Status and Data Quality pages after deployment.
7. Keep demo credentials disabled or rotated outside hackathon demonstrations.


## Existing Project Assignment Fixes

The current build preserves the existing CivicPulse AI Flask architecture and adds backward-compatible official department references for requests and AI recommendations. Officer visibility now supports authorized department scope, while AI recommendations remain separate from official government assignment. See `FIXES_REPORT.md` for the verified modification report.
