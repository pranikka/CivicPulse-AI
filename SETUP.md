# CivicPulse AI - Windows Setup Guide

This guide provides exact step-by-step instructions for setting up CivicPulse AI on Windows using VS Code.

## Prerequisites

Before you begin, install:

1. **Python 3.8+**
   - Download from: https://www.python.org/downloads/
   - **Important**: Check "Add Python to PATH" during installation
   - Verify: Open PowerShell and type `python --version`

2. **VS Code**
   - Download from: https://code.visualstudio.com/
   - Install the "Python" extension by Microsoft

3. **Git** (optional but recommended)
   - Download from: https://git-scm.com/

## Step-by-Step Setup

### Step 1: Create Project Folder

Open PowerShell and run:

```powershell
cd Documents
mkdir CivicPulse-AI
cd CivicPulse-AI
```

### Step 2: Open in VS Code

```powershell
code .
```

This opens VS Code in the current folder.

### Step 3: Create All Required Files

In VS Code terminal (Ctrl + `), create the folder structure:

```powershell
# Create folders
mkdir templates
mkdir static
mkdir static\css
mkdir static\js
mkdir services

# Create empty __init__.py files
New-Item -Path services\__init__.py -ItemType File
```

### Step 4: Create Configuration Files

Create these files in the root folder (copy-paste the complete content):

- `app.py` - Main application
- `config.py` - Settings
- `models.py` - Database models
- `seed.py` - Demo data
- `requirements.txt` - Dependencies
- `.env.example` - Environment template

### Step 5: Create Service Files

In `services/` folder, create:

- `__init__.py` (empty file)
- `ai_service.py` - AI analysis logic

### Step 6: Create Templates

In `templates/` folder, create all HTML files:

- `base.html`
- `index.html`
- `register.html`
- `login.html`
- `citizen_request.html`
- `request_success.html`
- `ai_analysis.html`
- `demand_analysis.html`
- `hotspots.html`
- `government_dashboard.html`
- `admin_dashboard.html`
- `404.html`
- `500.html`

### Step 7: Create Static Files

In `static/css/` create:
- `style.css`

In `static/js/` create:
- `script.js`
- `chart-config.js`
- `map-handler.js`

### Step 8: Create Virtual Environment

In PowerShell, in your project folder:

```powershell
python -m venv venv
```

This creates a virtual environment folder called `venv`.

### Step 9: Activate Virtual Environment

**On Windows PowerShell**:

```powershell
.\venv\Scripts\Activate.ps1
```

You should see `(venv)` at the start of your PowerShell prompt.

**If you get an execution policy error**, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

### Step 10: Install Dependencies

With the virtual environment activated, run:

```powershell
pip install -r requirements.txt
```

This installs:
- Flask
- Flask-SQLAlchemy
- Werkzeug

Wait for the installation to complete.

### Step 11: Seed Demo Data

```powershell
python seed.py
```

You should see:

## Smart Complaint & AI Configuration

The updated project keeps the existing Flask/SQLite architecture and adds secure complaint evidence uploads, GPS coordinates, AI complaint analysis, an interactive issue map, hotspot detection, and advanced analytics.

By default the AI analyzer runs locally, so no API key is required. To enable an OpenAI-compatible provider, copy `.env.example` values into your environment and set:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Never commit a real API key to the project.

Complaint uploads are stored under `instance/uploads/complaints/` and are served only through an authenticated route. Supported photo/video/document formats and size limits are enforced by the application.

If you already have the included `instance/civicpulse.db`, starting the application automatically adds only the new nullable compatibility columns; existing records are preserved.

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



## Updated feature notes

The application now performs a non-destructive database migration at startup. Do not delete `instance/civicpulse.db` if you want to preserve existing data.

For demo data, run:

```bash
python seed.py
```

The seed script is now non-destructive: it creates missing demo records but never drops tables or deletes existing records.

### Voice reporting

Use a Chromium-based browser that supports the Web Speech API for voice transcription. If unavailable, use the normal text field.

### Human review

Officer/Admin users can open a request and use **Human Review of AI Analysis** to record Accepted, Modified or Rejected. Modified decisions require a review note.

### Analytics

Officer/Admin users can open:

- Government Dashboard
- Demand Analysis
- Hotspots
- Area Intelligence

All extended analytics are calculated from stored records. Where evidence is insufficient, the UI reports that limitation rather than fabricating a value.


## Hack2Skill demo extensions
Use the seeded demo accounts to walk through `/demo-center`, then show `/outcomes`, `/trust-center`, and `/system-status`. Admins can inspect `/admin/data-governance`.


## Feature 39–44 smoke test
After login as Officer/Admin:
- Open `/impact-dashboard`
- Open `/civic-insight`
- Open `/outcomes`
- Open `/officer/area-intelligence`
- Open `/officer/complaints` and use language/date/category/status filters
- Open `/system-status`

As Admin:
- Open `/admin/data-quality`
- Open `/admin/data-governance`
- Open `/admin/audit-log`

As a public visitor:
- Open `/trust-center`
- Open `/public-transparency`

The public transparency page intentionally contains only aggregate data.
