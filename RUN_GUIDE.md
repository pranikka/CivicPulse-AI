# CivicPulse AI — Local Run Guide

## Windows + VS Code
1. Extract the ZIP.
2. Open the extracted `CivicPulse-AI` folder in VS Code.
3. Open Terminal → PowerShell.
4. Create a virtual environment:
   `py -m venv venv`
5. Activate it:
   `venv\Scripts\Activate.ps1`
   If PowerShell blocks scripts, run: `Set-ExecutionPolicy -Scope Process Bypass` and activate again.
6. Install dependencies:
   `python -m pip install -r requirements.txt`
7. Start the app:
   `python app.py`
8. Open the URL printed by Flask, normally `http://127.0.0.1:5000`.

## Demo accounts
Use the existing credentials in the project README/SETUP files. Do not delete the existing `instance/civicpulse.db`.

## Feature verification
Test Citizen → request/track/notifications/profile/assistant; Officer → dashboard/charts/filters/hotspots/area intelligence/complaints; Admin → dashboard/search/filters/departments/SLA/audit/data governance/data quality/Civic Insight.

The application uses existing database records and shows empty-state messages when real data is unavailable.
