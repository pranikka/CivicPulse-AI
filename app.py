# ===============================================
# CIVICPULSE AI - Flask Application
# ===============================================

import os
import sys
import re
import uuid
import io
import csv
import secrets
import unicodedata
import math
import json
from collections import Counter
from statistics import mean, pstdev
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify,
    session, flash, send_from_directory, abort, send_file
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, or_
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Import configuration and models
from config import Config
from models import (
    db, User, CitizenRequest, RequestAnalysis, Location, Project,
    ComplaintTimeline, Notification, CitizenFeedback, Department, SLAConfig, AuditLog
)
from services.ai_service import AIService
from services.email_service import send_email
from translations import get_translation, get_language, SUPPORTED_LANGUAGES, TRANSLATIONS, WORD_TRANSLATIONS

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# ===============================================
# SECURITY HELPERS
# ===============================================

CSRF_EXEMPT_ENDPOINTS = {'set_language', 'auth_logout'}

def _csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

@app.context_processor
def inject_security_context():
    return {'csrf_token': _csrf_token()}

@app.before_request
def enforce_csrf():
    # Cookie-authenticated state-changing requests require a per-session token.
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    endpoint = request.endpoint or ''
    if endpoint in CSRF_EXEMPT_ENDPOINTS:
        return None
    token = request.headers.get('X-CSRFToken') or request.form.get('_csrf_token')
    if not token or not secrets.compare_digest(token, session.get('_csrf_token', '')):
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'CSRF validation failed.'}), 400
        abort(400, description='CSRF validation failed.')
    return None

@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(self), microphone=(self), camera=()')
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: blob: https://{s}.tile.openstreetmap.org https://unpkg.com; "
        "font-src 'self' data: https://unpkg.com; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'self'"
    )
    return response

# ===============================================
# UPLOAD & DATABASE COMPATIBILITY HELPERS
# ===============================================

def _ensure_upload_folder():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def _migrate_existing_schema():
    """Add only new columns to the existing SQLite database.

    SQLAlchemy's create_all() does not alter existing tables. This small,
    idempotent migration keeps the user's existing data and schema intact.
    """
    inspector = inspect(db.engine)
    if 'citizen_requests' in inspector.get_table_names():
        existing = {col['name'] for col in inspector.get_columns('citizen_requests')}
        additions = {
            'title': 'VARCHAR(200)',
            'latitude': 'FLOAT',
            'longitude': 'FLOAT',
            'complaint_datetime': 'DATETIME',
            'photo_filename': 'VARCHAR(255)',
            'video_filename': 'VARCHAR(255)',
            'evidence_filename': 'VARCHAR(255)',
            'contact_phone': 'VARCHAR(30)',
            'contact_email': 'VARCHAR(120)',
            'is_anonymous': 'BOOLEAN DEFAULT 0',
            'resolved_at': 'DATETIME',
            'assigned_department': 'VARCHAR(100)',
            'assigned_department_id': 'INTEGER',
            'assigned_officer_id': 'INTEGER',
            'assigned_at': 'DATETIME',
            'due_at': 'DATETIME',
            'officer_remarks': 'TEXT',
            'before_evidence_filename': 'VARCHAR(255)',
            'after_evidence_filename': 'VARCHAR(255)',
            'original_language': 'VARCHAR(20)',
            'language_override': 'VARCHAR(20)',
            'original_text': 'TEXT',
            'normalized_text': 'TEXT',
            'voice_transcript': 'TEXT',
            'input_mode': "VARCHAR(20) DEFAULT 'text'"
        }
        with db.engine.begin() as conn:
            for name, definition in additions.items():
                if name not in existing:
                    conn.exec_driver_sql(
                        f'ALTER TABLE citizen_requests ADD COLUMN {name} {definition}'
                    )

    if 'users' in inspector.get_table_names():
        existing = {col['name'] for col in inspector.get_columns('users')}
        if 'department_id' not in existing:
            with db.engine.begin() as conn:
                conn.exec_driver_sql('ALTER TABLE users ADD COLUMN department_id INTEGER')

    if 'citizen_feedback' in inspector.get_table_names():
        existing = {col['name'] for col in inspector.get_columns('citizen_feedback')}
        additions = {
            'satisfaction_level': 'VARCHAR(40)',
            'issue_resolved': 'BOOLEAN DEFAULT 1',
            'reopened_requested': 'BOOLEAN DEFAULT 0',
            'reopened_reason': 'TEXT'
        }
        with db.engine.begin() as conn:
            for name, definition in additions.items():
                if name not in existing:
                    conn.exec_driver_sql(f'ALTER TABLE citizen_feedback ADD COLUMN {name} {definition}')

    if 'request_analysis' in inspector.get_table_names():
        existing = {col['name'] for col in inspector.get_columns('request_analysis')}
        additions = {
            'issue_type': 'VARCHAR(100)',
            'priority': 'VARCHAR(20)',
            'recommended_department': 'VARCHAR(100)',
            'recommended_department_id': 'INTEGER',
            'sentiment': 'VARCHAR(30)',
            'confidence_score': 'FLOAT',
            'ai_provider': "VARCHAR(30) DEFAULT 'local'",
            'original_priority': 'VARCHAR(20)',
            'priority_override': 'VARCHAR(20)',
            'review_status': "VARCHAR(30) DEFAULT 'Review Required'",
            'officer_decision': 'VARCHAR(30)',
            'officer_modification': 'TEXT',
            'reviewer_id': 'INTEGER',
            'confidence_details': 'JSON'
        }
        with db.engine.begin() as conn:
            for name, definition in additions.items():
                if name not in existing:
                    conn.exec_driver_sql(
                        f'ALTER TABLE request_analysis ADD COLUMN {name} {definition}'
                    )


    # Add indexes needed by complaint search, SLA checks and analytics.
    indexes = {
        'ix_citizen_requests_category': 'citizen_requests(category)',
        'ix_citizen_requests_local_area': 'citizen_requests(local_area)',
        'ix_citizen_requests_assigned_department': 'citizen_requests(assigned_department)',
        'ix_citizen_requests_assigned_department_id': 'citizen_requests(assigned_department_id)',
        'ix_citizen_requests_assigned_officer_id': 'citizen_requests(assigned_officer_id)',
        'ix_citizen_requests_due_at': 'citizen_requests(due_at)',
        'ix_request_analysis_category_classified': 'request_analysis(category_classified)',
        'ix_request_analysis_priority': 'request_analysis(priority)',
        'ix_request_analysis_priority_override': 'request_analysis(priority_override)',
        'ix_request_analysis_recommended_department': 'request_analysis(recommended_department)',
        'ix_request_analysis_recommended_department_id': 'request_analysis(recommended_department_id)',
        'ix_citizen_requests_original_language': 'citizen_requests(original_language)',
        'ix_request_analysis_review_status': 'request_analysis(review_status)',
    }
    with db.engine.begin() as conn:
        existing_indexes = {
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list('citizen_requests')").fetchall()
        }
        existing_indexes.update(
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list('request_analysis')").fetchall()
        )
        for index_name, target in indexes.items():
            if index_name not in existing_indexes:
                conn.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS {index_name} ON {target}')

def _allowed_extension(filename, allowed):
    if not filename or '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in allowed


def _file_size(file_storage):
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return 0
    size = getattr(file_storage, 'content_length', None)
    if size is not None and size > 0:
        return size
    try:
        current = file_storage.stream.tell()
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(current)
        return size
    except (AttributeError, OSError):
        return 0


def _validate_file_signature(file_storage, extension):
    """Reject common extension/MIME spoofing without adding a heavy dependency."""
    if extension in {'txt'}:
        return
    try:
        current = file_storage.stream.tell()
        file_storage.stream.seek(0)
        header = file_storage.stream.read(16)
        file_storage.stream.seek(current)
    except (AttributeError, OSError):
        raise ValueError('Unable to validate uploaded file.')

    signatures = {
        'jpg': header.startswith(b'\xff\xd8\xff'),
        'jpeg': header.startswith(b'\xff\xd8\xff'),
        'png': header.startswith(b'\x89PNG\r\n\x1a\n'),
        'webp': header.startswith(b'RIFF') and header[8:12] == b'WEBP',
        'pdf': header.startswith(b'%PDF-'),
        'mp4': len(header) >= 8 and header[4:8] == b'ftyp',
        'mov': len(header) >= 8 and header[4:8] == b'ftyp',
        'webm': header.startswith(b'\x1a\x45\xdf\xa3'),
        'avi': header.startswith(b'RIFF') and header[8:12] == b'AVI ',
        'doc': header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'),
        'docx': header.startswith(b'PK\x03\x04'),
    }
    if extension in signatures and not signatures[extension]:
        raise ValueError('Uploaded file content does not match its file type.')

def _save_upload(file_storage, allowed_extensions, max_size):
    """Save an uploaded file using a random server-side filename."""
    if not file_storage or not file_storage.filename:
        return None

    original = secure_filename(file_storage.filename)
    if not original or not _allowed_extension(original, allowed_extensions):
        raise ValueError('Unsupported file type.')

    extension = original.rsplit('.', 1)[1].lower()
    mimetype = (getattr(file_storage, 'mimetype', '') or '').lower()
    if extension in app.config['ALLOWED_PHOTO_EXTENSIONS'] and mimetype and not mimetype.startswith('image/'):
        raise ValueError('Photo MIME type does not match the selected file type.')
    if extension in app.config['ALLOWED_VIDEO_EXTENSIONS'] and mimetype and not mimetype.startswith('video/'):
        raise ValueError('Video MIME type does not match the selected file type.')

    size = _file_size(file_storage)
    if size <= 0 or size > max_size:
        raise ValueError('Uploaded file is empty or exceeds the allowed size.')

    _validate_file_signature(file_storage, extension)

    stored_name = f'{uuid.uuid4().hex}.{extension}'
    _ensure_upload_folder()
    file_storage.save(os.path.join(app.config['UPLOAD_FOLDER'], stored_name))
    return stored_name


def _parse_coordinates(latitude, longitude):
    if latitude in (None, '') and longitude in (None, ''):
        return None, None
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        raise ValueError('Latitude and longitude must be valid numbers.')
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Latitude/longitude values are outside valid ranges.')
    return lat, lon


def _parse_complaint_datetime(value):
    if not value:
        return datetime.utcnow()
    try:
        # datetime-local values are intentionally stored as a naive timestamp,
        # consistent with the existing SQLite model.
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('Invalid complaint date/time.')


def _delete_upload(filename):
    if not filename:
        return
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _filtered_requests_from_query():
    """Return a real-data query filtered by dashboard/map query parameters."""
    query = CitizenRequest.query
    start = request.args.get('start_date', '').strip()
    end = request.args.get('end_date', '').strip()
    category = request.args.get('category', '').strip()
    department = request.args.get('department', '').strip()
    status = request.args.get('status', '').strip()
    priority = request.args.get('priority', '').strip()
    location = request.args.get('location', '').strip()
    state = request.args.get('state', '').strip()

    analysis_joined = False

    if start:
        try:
            query = query.filter(CitizenRequest.created_at >= datetime.fromisoformat(start))
        except ValueError:
            pass
    if end:
        try:
            end_value = datetime.fromisoformat(end)
            if len(end) == 10:
                end_value += timedelta(days=1)
            query = query.filter(CitizenRequest.created_at < end_value)
        except ValueError:
            pass
    if category:
        query = query.outerjoin(
            RequestAnalysis,
            CitizenRequest.request_id == RequestAnalysis.request_id
        )
        analysis_joined = True
        query = query.filter(
            or_(
                CitizenRequest.category == category,
                RequestAnalysis.category_classified == category
            )
        )
    if state:
        query = query.filter(CitizenRequest.state == state)
    if status:
        query = query.filter(CitizenRequest.status == status)
    if location:
        like = f'%{location}%'
        query = query.filter(
            or_(
                CitizenRequest.state.ilike(like),
                CitizenRequest.district.ilike(like),
                CitizenRequest.local_area.ilike(like)
            )
        )

    if department or priority:
        if not analysis_joined:
            query = query.join(
                RequestAnalysis,
                CitizenRequest.request_id == RequestAnalysis.request_id
            )
        if department:
            query = query.filter(
                or_(
                    CitizenRequest.assigned_department == department,
                    RequestAnalysis.recommended_department == department
                )
            )
        if priority:
            query = query.filter(
                db.func.coalesce(
                    RequestAnalysis.priority_override,
                    RequestAnalysis.priority
                ) == priority
            )

    return query


def _resolution_minutes(created_at, resolved_at):
    if not created_at or not resolved_at:
        return None
    return max(0.0, (resolved_at - created_at).total_seconds() / 60.0)




# ===============================================
# SLA HELPERS
# ===============================================

DEFAULT_SLA_TARGETS = {
    'Critical': 24,
    'High': 48,
    'Medium': 72,
    'Low': 120,
}

def _effective_priority_for_complaint(complaint):
    return _effective_priority(complaint.analysis) if complaint else 'Low'

def _sla_target_hours(priority):
    priority = priority if priority in DEFAULT_SLA_TARGETS else 'Low'
    config = SLAConfig.query.filter_by(priority=priority).first()
    return int(config.target_hours) if config else DEFAULT_SLA_TARGETS[priority]

def _ensure_sla_due(complaint, commit=False):
    """Populate a missing SLA due date from the complaint creation time."""
    if complaint and complaint.due_at is None and complaint.created_at:
        complaint.due_at = complaint.created_at + timedelta(
            hours=_sla_target_hours(_effective_priority_for_complaint(complaint))
        )
        if commit:
            db.session.commit()
    return complaint.due_at if complaint else None

def _sla_status(complaint, now=None):
    now = now or datetime.utcnow()
    due_at = complaint.due_at or _ensure_sla_due(complaint)
    if not due_at:
        return {'status': 'No SLA', 'remaining_seconds': None, 'compliant': None}
    if complaint.status == 'Resolved':
        completed_at = complaint.resolved_at or complaint.updated_at or now
        compliant = completed_at <= due_at
        remaining = int((due_at - completed_at).total_seconds())
        return {
            'status': 'Compliant' if compliant else 'Breached',
            'remaining_seconds': remaining,
            'compliant': compliant
        }
    remaining = int((due_at - now).total_seconds())
    if remaining < 0:
        label = 'Overdue'
    elif remaining <= 24 * 3600:
        label = 'Due soon'
    else:
        label = 'On track'
    return {
        'status': label,
        'remaining_seconds': remaining,
        'compliant': None if remaining >= 0 else False
    }

# ===============================================
# NEW FEATURE HELPERS
# ===============================================

def _normalize_citizen_text(text):
    """Unicode-normalize citizen input while preserving the original statement."""
    value = unicodedata.normalize('NFKC', str(text or ''))
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def _detect_language_metadata(text, selected_language='en'):
    """Return language code and an evidence-based confidence estimate.

    Script-based detection is high confidence for supported Indic scripts.
    Latin-script text is conservatively treated as English unless the citizen
    selected another supported language.
    """
    detected = AIService.detect_language(text)
    if detected != 'en':
        return detected, 0.99
    if selected_language in SUPPORTED_LANGUAGES and selected_language != 'en':
        # No script evidence for many transliterated Indian-language inputs.
        # Preserve the citizen selection rather than pretending to know more.
        return selected_language, 0.60
    return 'en', 0.70


def _language_label(code):
    labels = {
        'en': 'English', 'ta': 'Tamil', 'hi': 'Hindi',
        'te': 'Telugu', 'ka': 'Kannada', 'ml': 'Malayalam'
    }
    return labels.get(code, code or 'Unknown')


def _confidence_band(value):
    if value is None:
        return {'label': 'Unavailable', 'low': True}
    value = float(value)
    return {
        'label': 'High' if value >= 0.80 else 'Moderate' if value >= 0.60 else 'Low',
        'low': value < 0.60
    }


def _build_analysis_explanation(complaint, analysis):
    """Build explainability from stored request data, not invented scores."""
    if not analysis:
        return {}
    same_area = CitizenRequest.query.filter(
        CitizenRequest.id != complaint.id,
        CitizenRequest.state == complaint.state,
        CitizenRequest.district == complaint.district,
        CitizenRequest.local_area == complaint.local_area
    ).count()
    previous_cutoff = datetime.utcnow() - timedelta(days=30)
    recent_cutoff = datetime.utcnow() - timedelta(days=7)
    recent = CitizenRequest.query.filter(
        CitizenRequest.id != complaint.id,
        CitizenRequest.state == complaint.state,
        CitizenRequest.district == complaint.district,
        CitizenRequest.category == complaint.category,
        CitizenRequest.created_at >= recent_cutoff
    ).count()
    previous = CitizenRequest.query.filter(
        CitizenRequest.id != complaint.id,
        CitizenRequest.state == complaint.state,
        CitizenRequest.district == complaint.district,
        CitizenRequest.category == complaint.category,
        CitizenRequest.created_at >= previous_cutoff,
        CitizenRequest.created_at < recent_cutoff
    ).count()
    change = None
    if previous:
        change = round(((recent - previous) / previous) * 100, 1)
    elif recent:
        change = 100.0

    factors = []
    if analysis.explainability_factors:
        if isinstance(analysis.explainability_factors, dict):
            factors.extend(str(v) for v in analysis.explainability_factors.values() if v)
    if analysis.similar_requests_count:
        factors.append(f"{analysis.similar_requests_count} similar requests in the stored dataset.")
    if same_area:
        factors.append(f"{same_area} other requests are recorded in the same locality.")
    if recent or previous:
        factors.append(f"{recent} matching requests in the last 7 days versus {previous} in the preceding 23 days.")
    if change is not None and change > 0:
        factors.append(f"Recent matching demand changed by {change}% across the comparison periods.")
    # Supporting priority factors are evidence-only; they do not silently alter
    # the existing priority classification.
    if same_area:
        factors.append(f"Geographic concentration: {same_area} other requests in the same locality.")
    if analysis.infrastructure_gap is not None:
        factors.append(f"Recorded infrastructure-gap indicator: {analysis.infrastructure_gap}/10.")
    if analysis.population_impacted:
        factors.append(f"Affected-population estimate stored for this request: {analysis.population_impacted:,}.")
    if not factors:
        factors.append("No additional supporting pattern was found in the available dataset.")

    details = analysis.confidence_details or {}
    similar_rows = []
    try:
        matches = _duplicate_matches(complaint, exclude_id=complaint.id, days=365, limit=5)
        for score, item in matches:
            similar_rows.append({
                'request_id': item.request_id,
                'similarity': round(min(1.0, score) * 100, 1),
                'category': item.analysis.category_classified if item.analysis else item.category or 'Other',
                'location': f'{item.local_area or item.district}, {item.district or ""}',
                'date': item.created_at.isoformat() if item.created_at else None
            })
    except Exception:
        similar_rows = []
    return {
        'supporting_factors': factors,
        'recent_matching_requests': recent,
        'previous_matching_requests': previous,
        'recent_change_percent': change,
        'similar_requests': similar_rows,
        'signals': {
            'similar_requests': analysis.similar_requests_count or 0,
            'same_locality_requests': same_area,
            'priority': analysis.priority,
            'urgency': analysis.urgency_level,
            'ai_provider': analysis.ai_provider or 'local'
        },
        'limitations': [
            "Results depend on the available citizen-request dataset.",
            "Small samples can produce unstable trends.",
            "The system is decision support; an authorized human officer must review recommendations."
        ],
        'confidence_details': details
    }


def _status_timeline_labels(complaint):
    """Citizen-safe lifecycle timeline with no internal officer details."""
    labels = [
        ('Submitted', 'Request received by CivicPulse AI'),
        ('Analyzed', 'AI-assisted analysis completed'),
        ('Department Assigned', 'Request routed to a government department'),
        ('Officer Assigned', 'A responsible officer was assigned'),
        ('In-Progress', 'Work is in progress'),
        ('Resolved', 'Resolution recorded'),
        ('Citizen Feedback', 'Citizen feedback received')
    ]
    events = ComplaintTimeline.query.filter_by(
        request_id=complaint.request_id
    ).order_by(ComplaintTimeline.created_at.asc()).all()
    result = []
    for label, description in labels:
        matches = [e for e in events if label.lower() in (e.event_type or '').lower()]
        if label == 'Analyzed':
            matches += [e for e in events if 'AI analysis' in (e.event_type or '')]
        if label == 'Citizen Feedback':
            matches += [e for e in events if 'feedback' in (e.event_type or '').lower()]
        event = matches[-1] if matches else None
        if event:
            result.append({
                'label': label,
                'description': event.description or description,
                'created_at': event.created_at
            })
        elif label == 'Submitted' and complaint.created_at:
            result.append({'label': label, 'description': description, 'created_at': complaint.created_at})
    return result


def _parse_period_days(value):
    mapping = {'7d': 7, '30d': 30, '90d': 90, '1y': 365}
    return mapping.get(value, 30)


def _analytics_query(user, start=None, end=None, category=None, location=None, department=None, priority=None, status=None):
    query = _scoped_complaints_query(user)
    if start:
        query = query.filter(CitizenRequest.created_at >= start)
    if end:
        query = query.filter(CitizenRequest.created_at < end)
    if category:
        query = query.filter(CitizenRequest.category == category.lower())
    if location:
        query = query.filter(
            or_(
                CitizenRequest.local_area.ilike(f'%{location}%'),
                CitizenRequest.district.ilike(f'%{location}%')
            )
        )
    if department:
        query = query.filter(CitizenRequest.assigned_department == department)
    if status:
        query = query.filter(CitizenRequest.status == status)
    if priority:
        query = query.join(RequestAnalysis).filter(
            or_(
                RequestAnalysis.priority == priority,
                RequestAnalysis.priority_override == priority
            )
        )
    return query


def _trend_series(complaints, days):
    today = datetime.utcnow().date()
    first = today - timedelta(days=days - 1)
    counts = Counter()
    for item in complaints:
        if item.created_at:
            d = item.created_at.date()
            if first <= d <= today:
                counts[d] += 1
    return [
        {'date': (first + timedelta(days=i)).isoformat(), 'count': counts[first + timedelta(days=i)]}
        for i in range(days)
    ]


def _emerging_issues(user):
    now = datetime.utcnow()
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)
    current = _scoped_complaints_query(user).filter(CitizenRequest.created_at >= current_start).all()
    previous = _scoped_complaints_query(user).filter(
        CitizenRequest.created_at >= previous_start,
        CitizenRequest.created_at < current_start
    ).all()
    current_counts = Counter((c.category or 'other') for c in current)
    previous_counts = Counter((c.category or 'other') for c in previous)
    areas = {}
    for c in current:
        areas.setdefault(c.category or 'other', Counter())[c.local_area or c.district or 'Unknown'] += 1
    rows = []
    for category, count in current_counts.items():
        prev = previous_counts.get(category, 0)
        change = 100.0 if count and not prev else round(((count - prev) / prev) * 100, 1) if prev else 0.0
        if count >= 2 and change > 20:
            rows.append({
                'issue': category,
                'current_count': count,
                'previous_count': prev,
                'change_percent': change,
                'affected_areas': areas.get(category, Counter()).most_common(5),
                'period': 'Last 30 days vs preceding 30 days',
                'evidence': f'{count} current requests compared with {prev} previous requests.'
            })
    return sorted(rows, key=lambda x: (x['change_percent'], x['current_count']), reverse=True)


def _area_intelligence(user, area):
    complaints = _scoped_complaints_query(user).filter(
        or_(CitizenRequest.local_area.ilike(area), CitizenRequest.district.ilike(area))
    ).all()
    total = len(complaints)
    high = sum(1 for c in complaints if _effective_priority(c.analysis) in ('High', 'Critical'))
    unresolved = sum(1 for c in complaints if c.status != 'Resolved')
    resolved = sum(1 for c in complaints if c.status == 'Resolved')
    category_counts = Counter((c.analysis.category_classified if c.analysis else c.category or 'Other') for c in complaints)
    hotspot_counts = Counter((c.local_area or c.district or 'Unknown') for c in complaints)
    projects = []
    locations = Location.query.filter(
        or_(Location.district.ilike(area), Location.state.ilike(area))
    ).all()
    for loc in locations:
        projects.extend(loc.projects)
    gap_candidates = []
    for loc in locations:
        if loc.infrastructure_gap_score and loc.infrastructure_gap_score > 0:
            gap_candidates.append(loc.infrastructure_gap_score)
    gap_score = round(sum(gap_candidates) / len(gap_candidates), 1) if gap_candidates else None
    insights = []
    if category_counts:
        top_cat, top_count = category_counts.most_common(1)[0]
        insights.append(f"{top_cat} is the most frequently recorded category ({top_count} requests).")
    if unresolved:
        insights.append(f"{unresolved} requests remain unresolved in the selected area.")
    if gap_score is not None:
        insights.append(f"Recorded infrastructure-gap indicator is {gap_score}/10.")
    return {
        'area': area,
        'total_requests': total,
        'high_priority_requests': high,
        'unresolved_requests': unresolved,
        'resolved_requests': resolved,
        'top_categories': category_counts.most_common(8),
        'hotspots': hotspot_counts.most_common(8),
        'existing_projects': [{
            'title': p.title, 'category': p.category, 'status': p.status,
            'estimated_people_impacted': p.estimated_people_impacted
        } for p in projects],
        'infrastructure_gap': gap_score,
        'insights': insights,
        'review_status': Counter(
            (c.analysis.review_status if c.analysis else 'Not analyzed') for c in complaints
        )
    }


def _text_tokens(text):
    return set(re.findall(r'\w+', (text or '').lower()))

def _duplicate_matches(candidate, exclude_id=None, days=30, limit=5):
    cutoff = datetime.utcnow() - timedelta(days=days)
    candidate_text = _text_tokens(f'{candidate.title or ''} {candidate.description or ''}')
    if not candidate_text:
        return []
    query = CitizenRequest.query.filter(CitizenRequest.created_at >= cutoff)
    if exclude_id:
        query = query.filter(CitizenRequest.id != exclude_id)
    candidates = query.order_by(CitizenRequest.created_at.desc()).limit(250).all()
    matches = []
    for item in candidates:
        score = 0.0
        item_text = _text_tokens(f'{item.title or ''} {item.description or ''}')
        if item_text:
            intersection = len(candidate_text & item_text)
            union = len(candidate_text | item_text)
            score = intersection / union if union else 0.0
        category_match = (item.category or '').strip().lower() == (candidate.category or '').strip().lower()
        location_match = (item.state or '').strip().lower() == (candidate.state or '').strip().lower() and (item.district or '').strip().lower() == (candidate.district or '').strip().lower()
        area_match = location_match and (item.local_area or '').strip().lower() == (candidate.local_area or '').strip().lower()
        if area_match: score += 0.25
        elif location_match: score += 0.15
        if category_match: score += 0.15
        if score >= 0.55 or (category_match and location_match and score >= 0.35):
            matches.append((score, item))
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[:limit]

def _effective_priority(analysis):
    """Return the effective priority, with urgency as a safe fallback for legacy analyses.

    Older/demo records may contain urgency but no persisted priority. In that case
    the dashboard should still reflect the stored analysis instead of silently
    reporting every item as Low. Explicit officer overrides and persisted priority
    always take precedence.
    """
    if not analysis:
        return 'Low'
    explicit = analysis.priority_override or analysis.priority
    if explicit:
        return explicit
    return {
        'High': 'High',
        'Moderate': 'Medium',
        'Medium': 'Medium',
        'Low': 'Low',
        'Critical': 'Critical',
    }.get(analysis.urgency_level, 'Low')

# ===============================================
# WORKFLOW / NOTIFICATION HELPERS
# ===============================================

def _add_timeline(complaint, event_type, description, actor=None, evidence_filename=None):
    event = ComplaintTimeline(
        request_id=complaint.request_id,
        event_type=event_type,
        description=description,
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        evidence_filename=evidence_filename
    )
    db.session.add(event)
    return event


def _notify(user_id, notification_type, title, message, request_id=None):
    if not user_id:
        return None
    item = Notification(
        user_id=user_id,
        request_id=request_id,
        notification_type=notification_type,
        title=title,
        message=message
    )
    db.session.add(item)
    return item


def _notify_admins(notification_type, title, message, request_id=None):
    for admin in User.query.filter_by(role='Admin').all():
        _notify(admin.id, notification_type, title, message, request_id)


def _send_user_email(user_id, subject, message):
    """Best-effort email notification; never breaks the current workflow."""
    try:
        user = db.session.get(User, user_id) if user_id else None
        if not user or not user.email:
            return False
        ok = send_email(user.email, subject, message)
        if not ok:
            app.logger.info('Optional email notification not sent for user %s.', user_id)
        return ok
    except Exception:
        app.logger.exception('Optional email notification failed for user %s.', user_id)
        return False


def _record_audit(user, action, entity, entity_id=None, details=None):
    """Add an admin/audit event without storing passwords or secrets."""
    import json
    safe_details = details or {}
    if not isinstance(safe_details, dict):
        safe_details = {'message': str(safe_details)}
    db.session.add(AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=json.dumps(safe_details, ensure_ascii=False)
    ))


def _notify_deadlines():
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)
    complaints = CitizenRequest.query.filter(
        CitizenRequest.assigned_officer_id.isnot(None),
        CitizenRequest.due_at.isnot(None),
        CitizenRequest.due_at >= now,
        CitizenRequest.due_at <= soon,
        CitizenRequest.status != 'Resolved'
    ).all()
    overdue = CitizenRequest.query.filter(
        CitizenRequest.due_at.isnot(None),
        CitizenRequest.due_at < now,
        CitizenRequest.status != 'Resolved'
    ).all()
    for c in overdue:
        exists = Notification.query.filter_by(
            request_id=c.request_id,
            notification_type='important_unresolved'
        ).first()
        if not exists:
            _notify_admins(
                'important_unresolved', 'Important unresolved complaint',
                f'Complaint {c.request_id} is overdue and remains unresolved.',
                c.request_id
            )
    for c in complaints:
        exists = Notification.query.filter_by(
            user_id=c.assigned_officer_id,
            request_id=c.request_id,
            notification_type='deadline_approaching'
        ).first()
        if not exists:
            _notify(
                c.assigned_officer_id, 'deadline_approaching', 'Complaint approaching deadline',
                f'Complaint {c.request_id} is due within 24 hours.',
                c.request_id
            )
    if complaints:
        db.session.commit()


def _complaint_can_view(complaint, user):
    if not complaint or not user:
        return False
    if user.role == 'Admin':
        return True
    if user.role == 'Officer':
        if complaint.assigned_officer_id == user.id:
            return True
        if user.department_id and complaint.assigned_officer_id is None:
            official = _official_department(complaint)
            return bool(official and official.id == user.department_id)
        return False
    return complaint.user_id == user.id


def _prediction_for_series(values, horizon=7):
    """Simple linear trend forecast using real historical daily counts."""
    if len(values) < 14:
        return None
    n = len(values)
    xs = list(range(n))
    xbar = sum(xs) / n
    ybar = sum(values) / n
    denom = sum((x - xbar) ** 2 for x in xs)
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, values)) / denom if denom else 0
    intercept = ybar - slope * xbar
    forecast = max(0, round(sum(intercept + slope * (n + i) for i in range(1, horizon + 1)) / horizon, 2))
    change = ((forecast - ybar) / ybar * 100) if ybar else 0
    trend = 'Increasing' if change > 10 else 'Decreasing' if change < -10 else 'Stable'
    return {'forecast': forecast, 'trend': trend, 'change_percent': round(change, 1), 'history_days': n}


def _build_demand_prediction(user=None):
    complaints = _scoped_complaints_query(user).order_by(CitizenRequest.created_at.asc()).all()
    if not complaints:
        return {'sufficient_data': False, 'message': 'Insufficient historical data for reliable prediction.'}

    dates = [c.created_at.date() for c in complaints if c.created_at]
    if not dates:
        return {'sufficient_data': False, 'message': 'Insufficient historical data for reliable prediction.'}

    first = min(dates)
    last = max(dates)
    total_days = (last - first).days + 1
    if total_days < 14 or len(set(dates)) < 14:
        return {'sufficient_data': False, 'message': 'Insufficient historical data for reliable prediction.', 'history_days': total_days}

    day_counts = {}
    cursor = first
    while cursor <= last:
        day_counts[cursor] = 0
        cursor += timedelta(days=1)
    for d in dates:
        day_counts[d] += 1

    series = [day_counts[d] for d in sorted(day_counts)]
    overall = _prediction_for_series(series, 7)

    # 30-day trend is only shown when a full 30-day history exists.
    thirty = None
    if total_days >= 30:
        thirty = _prediction_for_series(series[-30:], 30)

    def grouped_predictions(key_func):
        groups = {}
        for c in complaints:
            key = key_func(c)
            if not key:
                continue
            groups.setdefault(key, {})
            d = c.created_at.date()
            groups[key][d] = groups[key].get(d, 0) + 1
        result = []
        for key, counts in groups.items():
            if len(counts) < 14:
                continue
            start = min(counts)
            end = max(counts)
            span = (end - start).days + 1
            if span < 14:
                continue
            vals = []
            d = start
            while d <= end:
                vals.append(counts.get(d, 0))
                d += timedelta(days=1)
            pred = _prediction_for_series(vals, 7)
            if pred:
                result.append({'name': key, **pred})
        return sorted(result, key=lambda x: x['forecast'], reverse=True)[:10]

    return {
        'sufficient_data': True,
        'message': 'Predictions are calculated from actual complaint history.',
        'history_days': total_days,
        'overall': overall,
        'thirty_day': thirty,
        'category_predictions': grouped_predictions(
            lambda c: c.analysis.category_classified if c.analysis else c.category
        ),
        'area_predictions': grouped_predictions(lambda c: c.local_area),
    }


# ===============================================
# ROLE / DATA-SCOPE HELPERS
# ===============================================

# ---------------------------------------------------------------------------
# Department / assignment helpers
# ---------------------------------------------------------------------------

# AI department labels can differ from the department directory used by a
# particular deployment. These are explicit, reviewable compatibility aliases;
# they never create or silently assign a department.
DEPARTMENT_NAME_ALIASES = {
    'roads & highways': 'Road Maintenance',
    'road infrastructure': 'Road Maintenance',
    'electricity board': 'Electricity',
    'public works / drainage': 'Drainage',
}

def _normalize_department_name(value):
    return re.sub(r'\\s+', ' ', str(value or '').strip()).lower()

def _department_for_name(value, active_only=False):
    """Resolve a department name to an existing Department row."""
    if not value:
        return None
    normalized = _normalize_department_name(value)
    department = Department.query.filter(
        db.func.lower(db.func.trim(Department.name)) == normalized
    ).first()
    if not department:
        alias = DEPARTMENT_NAME_ALIASES.get(normalized)
        if alias:
            department = Department.query.filter(
                db.func.lower(db.func.trim(Department.name)) == _normalize_department_name(alias)
            ).first()
    if active_only and department and not department.is_active:
        return None
    return department

def _official_department(complaint):
    """Return the official department object, never the AI recommendation."""
    if not complaint:
        return None
    if complaint.assigned_department_id:
        department = db.session.get(Department, complaint.assigned_department_id)
        if department:
            return department
    if complaint.assigned_department:
        department = _department_for_name(complaint.assigned_department)
        if department:
            return department
    if complaint.assigned_officer and complaint.assigned_officer.department:
        return complaint.assigned_officer.department
    return None

def _ai_recommended_department(complaint):
    """Return the AI recommendation department object, if it maps to a directory entry."""
    if not complaint or not complaint.analysis:
        return None
    if complaint.analysis.recommended_department_id:
        department = db.session.get(Department, complaint.analysis.recommended_department_id)
        if department:
            return department
    return _department_for_name(complaint.analysis.recommended_department)

def _assignment_state(complaint):
    """Provide consistent UI/API assignment semantics.

    AI recommendation and official government assignment are deliberately
    separate. A recommendation is never treated as an official assignment.
    """
    official = _official_department(complaint)
    ai = _ai_recommended_department(complaint)
    officer = complaint.assigned_officer if complaint else None
    return {
        'ai_recommended_department': ai.name if ai else (
            complaint.analysis.recommended_department
            if complaint and complaint.analysis and complaint.analysis.recommended_department
            else None
        ),
        'ai_recommended_department_id': ai.id if ai else None,
        'official_department': official.name if official else None,
        'official_department_id': official.id if official else (
            complaint.assigned_department_id if complaint else None
        ),
        'assigned_officer': officer.username if officer else None,
        'assigned_officer_id': officer.id if officer else None,
        'official_assignment_pending': bool(ai and not official),
        'truly_unassigned': not bool(ai or official or officer),
    }

def _backfill_department_references():
    """Backfill only stable references from existing text; never overwrite assignments."""
    changed = False
    for complaint in CitizenRequest.query.all():
        if complaint.assigned_department and not complaint.assigned_department_id:
            department = _department_for_name(complaint.assigned_department)
            if department:
                complaint.assigned_department_id = department.id
                changed = True
        if complaint.analysis:
            # Older records in the supplied database may predate the
            # recommended_department field. Backfill only missing analysis
            # metadata from the stored category; never replace an existing
            # recommendation.
            if not complaint.analysis.recommended_department:
                category_value = str(complaint.analysis.category_classified or '').strip()
                category_key = category_value.lower()
                if category_key not in AIService.DEPARTMENTS:
                    category_key = next(
                        (key for key, label in AIService.CATEGORIES.items()
                         if str(label).strip().lower() == category_value.lower()),
                        None
                    )
                if category_key and category_key in AIService.DEPARTMENTS:
                    complaint.analysis.recommended_department = AIService.DEPARTMENTS[category_key]
                    changed = True
            if not complaint.analysis.recommended_department_id:
                department = _department_for_name(complaint.analysis.recommended_department)
                if department:
                    complaint.analysis.recommended_department_id = department.id
                    changed = True
    if changed:
        db.session.commit()

def _scoped_complaints_query(user=None):
    """Return complaints visible to the supplied user within their authorized scope.

    Officers can see requests officially assigned to their department even when
    an individual officer has not yet been selected. A request explicitly
    assigned to another officer remains outside that officer's working queue.
    """
    user = user or get_current_user()
    if not user:
        return CitizenRequest.query.filter(CitizenRequest.id == -1)
    if user.role == 'Admin':
        return CitizenRequest.query
    if user.role == 'Officer':
        if not user.department_id:
            return CitizenRequest.query.filter(CitizenRequest.assigned_officer_id == user.id)
        return CitizenRequest.query.filter(
            or_(
                CitizenRequest.assigned_officer_id == user.id,
                db.and_(
                    CitizenRequest.assigned_department_id == user.department_id,
                    db.or_(
                        CitizenRequest.assigned_officer_id.is_(None),
                        CitizenRequest.assigned_officer_id == user.id
                    )
                ),
                db.and_(
                    CitizenRequest.assigned_department_id.is_(None),
                    CitizenRequest.assigned_department == user.department.name,
                    CitizenRequest.assigned_officer_id.is_(None)
                )
            )
        )
    return CitizenRequest.query.filter(CitizenRequest.user_id == user.id)


def _complaint_can_update(complaint, user):
    if not complaint or not user:
        return False
    if user.role == 'Admin':
        return True
    if user.role != 'Officer':
        return False
    if complaint.assigned_officer_id == user.id:
        return True
    if user.department_id and complaint.assigned_officer_id is None:
        official = _official_department(complaint)
        return bool(official and official.id == user.department_id)
    return False


def _complaint_can_assign(user):
    return bool(user and user.role == 'Admin')


def _parse_report_filters():
    """Normalize admin report/export filters from query parameters."""
    return {
        'start_date': request.args.get('start_date', '').strip(),
        'end_date': request.args.get('end_date', '').strip(),
        'category': request.args.get('category', '').strip(),
        'department': request.args.get('department', '').strip(),
        'status': request.args.get('status', '').strip(),
        'priority': request.args.get('priority', '').strip(),
        'location': request.args.get('location', '').strip(),
    }


def _admin_filtered_complaints():
    """Apply existing dashboard filters to the admin-visible complaint set."""
    query = _filtered_requests_from_query()
    return query.order_by(CitizenRequest.created_at.asc())


def _complaint_export_row(complaint):
    analysis = complaint.analysis
    feedback = complaint.feedback
    priority = _effective_priority(analysis)
    resolution_minutes = _resolution_minutes(complaint.created_at, complaint.resolved_at)
    return {
        'Complaint ID': complaint.request_id,
        'Title': complaint.title or '',
        'Category': analysis.category_classified if analysis and analysis.category_classified else complaint.category or '',
        'Description': complaint.description or '',
        'Date': complaint.created_at.strftime('%Y-%m-%d %H:%M') if complaint.created_at else '',
        'State': complaint.state or '',
        'District': complaint.district or '',
        'Local Area': complaint.local_area or '',
        'Official Department': _official_department(complaint).name if _official_department(complaint) else '',
        'AI Recommended Department': analysis.recommended_department if analysis else '',
        'Assignment Status': (
            'Officially Assigned' if _official_department(complaint)
            else 'AI Recommended - Official Assignment Pending' if analysis and analysis.recommended_department
            else 'Truly Unassigned'
        ),
        'Status': complaint.status or '',
        'Priority': priority,
        'Resolution Time (hours)': round(resolution_minutes / 60, 2) if resolution_minutes is not None else '',
        'Feedback Rating': feedback.rating if feedback else '',
        'Feedback Satisfaction': feedback.satisfaction_level if feedback else '',
        'Feedback Resolved': 'Yes' if feedback and feedback.issue_resolved else ('No' if feedback else ''),
        'Feedback Comment': feedback.comment if feedback else '',
    }


def _report_summary(complaints):
    category = Counter()
    department = Counter()
    priority = Counter()
    hotspots = Counter()
    resolution_minutes = []
    ratings = []
    resolved = pending = 0

    for complaint in complaints:
        analysis = complaint.analysis
        category[analysis.category_classified if analysis and analysis.category_classified else complaint.category or 'Other'] += 1
        official = _official_department(complaint)
        if official:
            department[official.name] += 1
        elif analysis and analysis.recommended_department:
            department[f'AI Pending: {analysis.recommended_department}'] += 1
        else:
            department['Truly Unassigned'] += 1
        priority[_effective_priority(analysis)] += 1
        hotspots[(complaint.state or 'Unknown', complaint.district or 'Unknown', complaint.local_area or 'Unknown')] += 1
        if (complaint.status or '').lower() == 'resolved':
            resolved += 1
        else:
            pending += 1
        minutes = _resolution_minutes(complaint.created_at, complaint.resolved_at)
        if minutes is not None:
            resolution_minutes.append(minutes)
        if complaint.feedback and complaint.feedback.rating is not None:
            ratings.append(float(complaint.feedback.rating))

    return {
        'total': len(complaints),
        'resolved': resolved,
        'pending': pending,
        'category': category,
        'department': department,
        'priority': priority,
        'hotspots': hotspots,
        'avg_resolution_hours': (sum(resolution_minutes) / len(resolution_minutes) / 60) if resolution_minutes else None,
        'avg_feedback': (sum(ratings) / len(ratings)) if ratings else None,
        'feedback_count': len(ratings),
    }



# ===============================================
# HACK2SKILL CLOSED-LOOP INTELLIGENCE HELPERS
# ===============================================

def _outcome_metrics(complaints):
    total = len(complaints)
    resolved = sum(1 for c in complaints if c.status == 'Resolved')
    feedback = [c.feedback for c in complaints if c.feedback]
    ratings = [float(f.rating) for f in feedback if f.rating is not None]
    reopened = sum(1 for f in feedback if f.reopened_requested)
    resolution_hours = []
    sla_resolved = 0
    sla_total = 0
    for c in complaints:
        mins = _resolution_minutes(c.created_at, c.resolved_at)
        if mins is not None:
            resolution_hours.append(mins / 60)
            if c.due_at:
                sla_total += 1
                if c.resolved_at <= c.due_at:
                    sla_resolved += 1
    return {
        'total_requests': total,
        'resolved_requests': resolved,
        'resolution_rate': round(resolved / total * 100, 2) if total else 0,
        'feedback_count': len(feedback),
        'feedback_rate': round(len(feedback) / resolved * 100, 2) if resolved else 0,
        'satisfaction': round(sum(ratings) / len(ratings), 2) if ratings else None,
        'reopened_requests': reopened,
        'sla_compliance': round(sla_resolved / sla_total * 100, 2) if sla_total else None,
        'average_resolution_hours': round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None
    }

def _category_intelligence(user, complaints):
    groups = {}
    for c in complaints:
        category = c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category or 'Other'
        item = groups.setdefault(category, {'category': category, 'volume': 0, 'high_priority': 0, 'resolved': 0, 'areas': Counter()})
        item['volume'] += 1
        if _effective_priority(c.analysis) in ('High', 'Critical'):
            item['high_priority'] += 1
        if c.status == 'Resolved':
            item['resolved'] += 1
        item['areas'][c.local_area or c.district or 'Unknown'] += 1
    result=[]
    for item in groups.values():
        result.append({
            'category': item['category'],
            'volume': item['volume'],
            'high_priority': item['high_priority'],
            'resolved': item['resolved'],
            'resolution_rate': round(item['resolved']/item['volume']*100,2) if item['volume'] else 0,
            'affected_areas': item['areas'].most_common(5),
        })
    return sorted(result, key=lambda x: x['volume'], reverse=True)

def _project_comparison(user, area='', category=''):
    complaints = _scoped_complaints_query(user).all()
    if area:
        complaints = [c for c in complaints if area.lower() in (c.local_area or '').lower() or area.lower() in (c.district or '').lower()]
    demand = Counter()
    trend = Counter()
    for c in complaints:
        cat = c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category or 'Other'
        if category and cat.lower() != category.lower():
            continue
        demand[cat] += 1
        if c.created_at and c.created_at >= datetime.utcnow() - timedelta(days=30):
            trend[cat] += 1
    locations = Location.query.all()
    projects=[]
    for loc in locations:
        if area and area.lower() not in (loc.state or '').lower() and area.lower() not in (loc.district or '').lower():
            continue
        for p in loc.projects:
            if category and (p.category or '').lower() != category.lower():
                continue
            projects.append({
                'area': f'{loc.state} / {loc.district}',
                'title': p.title,
                'category': p.category or 'Other',
                'status': p.status,
                'estimated_people_impacted': p.estimated_people_impacted
            })
    rows=[]
    cats=set(demand)|{p['category'] for p in projects}
    for cat in sorted(cats):
        ps=[p for p in projects if p['category']==cat]
        dc=demand.get(cat,0)
        rows.append({
            'category':cat,'citizen_demand':dc,'last_30_days':trend.get(cat,0),
            'existing_projects':len(ps),'project_statuses':Counter(p['status'] for p in ps),
            'potential_gap': dc>len(ps),
            'projects':ps
        })
    return rows

def _status_snapshot():
    checks = {
        'Authentication': True,
        'Request management': CitizenRequest is not None,
        'AI analysis': AIService is not None,
        'Demand analytics': CitizenRequest is not None,
        'Hotspot engine': CitizenRequest is not None,
        'Notifications': Notification is not None,
        'Reporting': os.path.exists(os.path.join(app.root_path, 'templates')),
        'Audit logging': AuditLog is not None,
        'Data quality monitoring': CitizenRequest is not None,
        'Public transparency': CitizenRequest is not None
    }
    return checks


# ===============================================
# AUTHENTICATION CONTEXT
# ===============================================

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        session['current_user'] = None
    else:
        user = db.session.get(User, user_id)
        if user is None:
            session.clear()
            app.jinja_env.globals['current_user'] = None
            return None
        session['current_user'] = user.id
        app.jinja_env.globals['current_user'] = user

# Make current_user available in templates
def get_current_user():
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None



# ===============================================
# AUTHORIZATION DECORATORS
# ===============================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('auth_login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please login first.', 'error')
                return redirect(url_for('auth_login'))
            
            user = db.session.get(User, session['user_id'])
            if user.role not in roles:
                flash(f'Access denied. This page requires {" or ".join(roles)} role.', 'error')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.context_processor
def inject_civicpulse_context():
    user = get_current_user()
    language = get_language(session)
    return {
        'current_user': user,
        'language': language,
        'supported_languages': SUPPORTED_LANGUAGES,
        '_': lambda text: get_translation(text, language),
    }


@app.route('/language/<lang>')
def set_language(lang):
    if lang not in SUPPORTED_LANGUAGES:
        abort(404)
    session['language'] = lang
    return redirect(request.referrer or url_for('index'))


@app.route('/citizen/dashboard')
@login_required
@role_required('Citizen')
def citizen_dashboard():
    # Keep a stable dashboard entry point while reusing the existing citizen request view.
    return redirect(url_for('citizen_analysis'))

@app.route('/citizen/profile')
@login_required
@role_required('Citizen')
def citizen_profile():
    user = get_current_user()
    return render_template('profile.html', profile_user=user)


# ===============================================
# ADMIN REPORT / EXPORT FEATURES
# ===============================================

@app.route('/admin/reports/pdf')
@login_required
@role_required('Admin')
def admin_report_pdf():
    """Generate a PDF report from the existing admin-visible complaint data."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        )
    except ImportError:
        flash('PDF generation requires reportlab. Please install the package from requirements.txt.', 'error')
        return redirect(url_for('admin_dashboard'))

    filters = _parse_report_filters()
    complaints = _admin_filtered_complaints().all()
    summary = _report_summary(complaints)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm,
        topMargin=14*mm, bottomMargin=14*mm,
        title='CivicPulse AI Complaint Report',
        author='CivicPulse AI'
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CivicTitle', parent=styles['Title'], alignment=TA_CENTER,
        fontSize=20, leading=24, spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'CivicSubtitle', parent=styles['Normal'], alignment=TA_CENTER,
        fontSize=9, textColor=colors.HexColor('#52606D'), spaceAfter=14
    )
    small = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, leading=10)
    body = ParagraphStyle('Body', parent=styles['BodyText'], fontSize=9, leading=12)

    story = [
        Paragraph('CivicPulse AI', title_style),
        Paragraph('Civic Complaint Analytics Report', styles['Heading2']),
        Paragraph(
            f"Generated: {datetime.utcnow().strftime('%d %B %Y, %H:%M UTC')} | "
            f"Date range: {filters['start_date'] or 'All'} to {filters['end_date'] or 'All'}",
            subtitle_style
        )
    ]

    summary_data = [
        ['Metric', 'Value'],
        ['Total complaints', str(summary['total'])],
        ['Resolved complaints', str(summary['resolved'])],
        ['Pending complaints', str(summary['pending'])],
        ['Average resolution time', f"{summary['avg_resolution_hours']:.2f} hours" if summary['avg_resolution_hours'] is not None else 'N/A'],
        ['Citizen feedback', f"{summary['avg_feedback']:.2f}/5 ({summary['feedback_count']} responses)" if summary['avg_feedback'] is not None else 'No feedback'],
    ]
    table = Table(summary_data, colWidths=[75*mm, 90*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0B1F3A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), .4, colors.HexColor('#D9E2EC')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F5F7FA')]),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story += [table, Spacer(1, 10)]

    def add_distribution(title, counter):
        story.append(Paragraph(title, styles['Heading3']))
        rows = [['Name', 'Complaints']]
        rows += [[str(k), str(v)] for k, v in counter.most_common()]
        t = Table(rows, colWidths=[110*mm, 35*mm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#123B63')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), .35, colors.HexColor('#D9E2EC')),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.extend([t, Spacer(1, 8)])

    add_distribution('Category Statistics', summary['category'])
    add_distribution('Department Statistics', summary['department'])
    add_distribution('Priority Statistics', summary['priority'])

    story.append(Paragraph('Hotspots', styles['Heading3']))
    hotspot_rows = [['State', 'District', 'Local area', 'Complaints']]
    for (state, district, area), count in summary['hotspots'].most_common(15):
        hotspot_rows.append([state, district, area, str(count)])
    ht = Table(hotspot_rows, colWidths=[35*mm, 45*mm, 60*mm, 25*mm], repeatRows=1)
    ht.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#123B63')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), .35, colors.HexColor('#D9E2EC')),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.extend([ht, Spacer(1, 10)])

    if complaints:
        story.append(Paragraph('Filtered Complaint Snapshot', styles['Heading3']))
        snapshot = [['ID', 'Category', 'Status', 'Priority', 'Location']]
        for c in complaints[:60]:
            snapshot.append([
                c.request_id,
                (c.analysis.category_classified if c.analysis else c.category)[:24],
                c.status or '',
                _effective_priority(c.analysis),
                f"{c.district or ''}, {c.local_area or ''}"[:38]
            ])
        st = Table(snapshot, colWidths=[27*mm, 40*mm, 30*mm, 25*mm, 48*mm], repeatRows=1)
        st.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0B1F3A')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), .3, colors.HexColor('#D9E2EC')),
            ('FONTSIZE', (0,0), (-1,-1), 6.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        story.extend([st, Spacer(1, 8)])

    # Development insight section: compare stored citizen demand with recorded projects.
    area_name = filters.get('district') or filters.get('state') or 'Selected area'
    category_filter = filters.get('category') or ''
    comparison = _project_comparison(get_current_user(), area_name if area_name != 'Selected area' else '', category_filter)
    story.append(Paragraph('Development Insight Comparison', styles['Heading3']))
    insight_rows = [['Category', 'Citizen demand', 'Existing projects', 'Potential attention']]
    for item in comparison[:20]:
        insight_rows.append([
            item['category'], str(item['citizen_demand']), str(item['existing_projects']),
            'Potential development attention area' if item['potential_gap'] else '—'
        ])
    if len(insight_rows) == 1:
        insight_rows.append(['No comparable project records', '0', '0', 'Insufficient data'])
    it = Table(insight_rows, colWidths=[65*mm, 30*mm, 35*mm, 55*mm], repeatRows=1)
    it.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#123B63')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), .35, colors.HexColor('#D9E2EC')),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.extend([it, Spacer(1, 8)])
    story.append(Paragraph('Limitations and human review', styles['Heading3']))
    story.append(Paragraph(
        'Demand is based on records available in the selected dataset. Existing-project comparisons '
        'only use projects stored in CivicPulse AI. Small samples may not represent the wider population. '
        'AI-assisted recommendations are decision-support information and require human review; this report '
        'does not automatically approve, reject or prioritize government projects.',
        body
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        'CivicPulse AI • AI-generated recommendation • Human review required.',
        small
    ))
    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer, mimetype='application/pdf', as_attachment=True,
        download_name=f"civicpulse-report-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.pdf"
    )


@app.route('/admin/reports/export/<fmt>')
@login_required
@role_required('Admin')
def admin_export(fmt):
    """Export filtered complaint data without mutating the database."""
    if fmt not in {'csv', 'xlsx'}:
        abort(404)

    complaints = _admin_filtered_complaints().all()
    rows = [_complaint_export_row(c) for c in complaints]
    headers = list(rows[0].keys()) if rows else list(_complaint_export_row(
        CitizenRequest(request_id=''),  # only used to obtain stable headers
    ).keys())

    if fmt == 'csv':
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
        data = io.BytesIO(buffer.getvalue().encode('utf-8-sig'))
        return send_file(
            data, mimetype='text/csv', as_attachment=True,
            download_name=f"civicpulse-complaints-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
        )

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        flash('Excel export requires openpyxl. Please install the package from requirements.txt.', 'error')
        return redirect(url_for('admin_dashboard'))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Complaints'
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='0B1F3A')
        cell.alignment = Alignment(horizontal='center')
    for row in rows:
        sheet.append([row[h] for h in headers])
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for idx, header in enumerate(headers, start=1):
        max_len = max([len(str(sheet.cell(r, idx).value or '')) for r in range(1, min(sheet.max_row, 200)+1)] + [len(header)])
        sheet.column_dimensions[get_column_letter(idx)].width = min(max(max_len + 2, 12), 45)

    data = io.BytesIO()
    workbook.save(data)
    data.seek(0)
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"civicpulse-complaints-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.xlsx"
    )


# ===============================================
# CIVIC ASSISTANT
# ===============================================

@app.route('/api/translations')
def api_translations():
    lang = get_language(session)
    return jsonify({'language': lang, 'translations': TRANSLATIONS.get(lang, {}), 'word_translations': WORD_TRANSLATIONS if lang == 'ta' else {}})


@app.route('/api/civic-assistant', methods=['POST'])
def civic_assistant():
    """Public FAQ/navigation assistant. It never queries private complaint data."""
    data = request.get_json(silent=True) or {}
    question = str(data.get('message', '')).strip()
    if not question or len(question) > 1000:
        return jsonify({'success': False, 'error': 'Please enter a question up to 1000 characters.'}), 400

    q = question.lower()
    if get_language(session) == 'ta':
        local_answers = [
            (('track', 'status', 'where is', 'progress'), 'புகாரை கண்காணிக்க Track Complaint பக்கத்தைத் திறந்து உங்கள் Complaint ID-ஐ உள்ளிடுங்கள். உங்கள் கணக்கிற்கு அனுமதி உள்ள புகார்களை மட்டுமே பார்க்க முடியும்.'),
            (('submit', 'complaint', 'report', 'request'), 'புகாரை சமர்ப்பிக்க Submit Request-ஐத் திறந்து வகை, தெளிவான விளக்கம் மற்றும் இட விவரங்களை உள்ளிட்டு சமர்ப்பிக்கவும். பின்னர் ஒரு தனிப்பட்ட Complaint ID உருவாகும்.'),
            (('category', 'categories'), 'Roads & Highways, Water Supply, Electricity, Healthcare, Sanitation, Education, Public Transport, Waste Management, Drainage மற்றும் Other போன்ற வகைகள் உள்ளன.'),
            (('department', 'office', 'who handles'), 'புகார் பகுப்பாய்வு தொடர்புடைய துறையை பரிந்துரைக்கும். இறுதி நடவடிக்கை மற்றும் தீர்வு அனுமதிக்கப்பட்ட அரசு அலுவலர்களால் மேற்கொள்ளப்படும்.'),
            (('faq', 'frequently', 'help'), 'கோரிக்கை சமர்ப்பித்தல், அனுமதிக்கப்பட்ட புகாரை கண்காணித்தல், அறிவிப்புகளைப் பார்ப்பது மற்றும் புகார் timeline-ஐப் பார்ப்பது போன்றவற்றில் உதவ முடியும்.'),
            (('dashboard', 'navigate', 'navigation', 'page'), 'உங்கள் role-க்கு கிடைக்கும் பக்கங்களை navigation menu மூலம் திறக்கலாம். Citizen தங்கள் கோரிக்கைகள், Officer assigned work, Admin system management அம்சங்களைப் பார்க்கலாம்.'),
        ]
    else:
        local_answers = [
            (('track', 'status', 'where is', 'progress'), 'To track a complaint, open Track Complaint and enter your Complaint ID. You can only view complaints that your account is authorized to access.'),
            (('submit', 'complaint', 'report', 'request'), 'To submit a complaint, open Submit Request, choose a category, add a clear description and location, then submit. A unique Complaint ID is generated for tracking.'),
            (('category', 'categories'), 'CivicPulse AI supports categories such as Roads & Highways, Water Supply, Electricity, Healthcare, Sanitation, Education, Public Transport, Waste Management, Drainage and Other.'),
            (('department', 'office', 'who handles'), 'The complaint analysis suggests a relevant department. Final handling and resolution remain under authorized government staff.'),
            (('faq', 'frequently', 'help'), 'You can submit a request, track an authorized complaint, review your notifications, and view your complaint timeline from the navigation menu.'),
            (('dashboard', 'navigate', 'navigation', 'page'), 'Use the navigation menu for the pages available to your role. Citizens see their requests, Officers see assigned work, and Admins see system management features.'),
        ]
    answer = None
    for keywords, response in local_answers:
        if any(k in q for k in keywords):
            answer = response
            break

    if answer is None:
        answer = (
            'புகார் சமர்ப்பித்தல், கண்காணித்தல், வகைகள், குடிமை சேவைகள், துறைகள், FAQ மற்றும் navigation பற்றி கேளுங்கள்.'
            if get_language(session) == 'ta'
            else 'I can help with complaint submission, tracking, categories, civic services, departments, FAQs and website navigation. Please ask one of those questions.'
        )

    # If the existing external AI provider is configured, it may improve the
    # public answer. Only the user's question is sent; no complaint/user data is read.
    try:
        ai_answer = AIService.public_assistant_answer(question, get_language(session))
        if ai_answer:
            answer = ai_answer
    except Exception as exc:
        app.logger.debug('Public assistant AI fallback: %s', exc)

    return jsonify({'success': True, 'answer': answer, 'language': get_language(session)})


# ===============================================
# PUBLIC ROUTES
# ===============================================

@app.route('/')
def index():
    """Homepage with actual aggregate CivicPulse statistics."""
    total = CitizenRequest.query.count()
    resolved = CitizenRequest.query.filter_by(status='Resolved').count()
    districts = db.session.query(CitizenRequest.district).filter(
        CitizenRequest.district.isnot(None), CitizenRequest.district != ''
    ).distinct().count()
    high = sum(
        1 for c in CitizenRequest.query.all()
        if _effective_priority(c.analysis) in ('High', 'Critical')
    )
    return render_template(
        'index.html',
        hero_stats={
            'requests': total,
            'districts': districts,
            'high_demand': high,
            'resolved': resolved
        }
    )

@app.route('/auth/register', methods=['GET', 'POST'])
def auth_register():
    """User registration."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role = request.form.get('role', 'Citizen')
        
        # Validation
        if not username or len(username) < 3:
            flash('Username must be at least 3 characters.', 'error')
            return redirect(url_for('auth_register'))
        
        if not email or '@' not in email:
            flash('Invalid email address.', 'error')
            return redirect(url_for('auth_register'))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth_register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('auth_register'))
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return redirect(url_for('auth_register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('auth_register'))
        
        # Only allow Citizen registration via form
        # Officer/Admin must use demo seed data
        if role in ['Officer', 'Admin']:
            flash('Officer and Admin accounts are pre-configured. Please login with demo credentials.', 'error')
            return redirect(url_for('auth_login'))
        
        # Create user
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        
        try:
            db.session.add(user)
            db.session.flush()
            _record_audit(
                user,
                'User creation',
                'User',
                user.id,
                {'username': user.username, 'role': user.role, 'source': 'self-registration'}
            )
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('auth_login'))
        except Exception as e:
            db.session.rollback()
            app.logger.exception('Registration failed')
            flash('Registration failed. Please try again.', 'error')
            return redirect(url_for('auth_register'))
    
    return render_template('register.html')

@app.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    """User login."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # Rotate the session contents on login to reduce session-fixation risk.
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            _csrf_token()
            flash(f'Welcome, {user.username}! (Role: {user.role})', 'success')
            
            # Redirect based on role
            if user.role == 'Citizen':
                return redirect(url_for('citizen_request'))
            elif user.role == 'Officer':
                return redirect(url_for('officer_dashboard'))
            elif user.role == 'Admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
            return redirect(url_for('auth_login'))
    
    return render_template('login.html')

@app.route('/auth/logout')
def auth_logout():
    """User logout."""
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

# ===============================================
# CITIZEN ROUTES
# ===============================================

@app.route('/citizen/request', methods=['GET', 'POST'])
@login_required
@role_required('Citizen')
def citizen_request():
    """Submit a citizen complaint using the existing request workflow."""
    if request.method == 'POST':
        category = request.form.get('category', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        language = request.form.get('language', 'en')
        if language not in {'en', 'ta', 'hi', 'te', 'ka', 'ml'}:
            language = 'en'
        input_mode = request.form.get('input_mode', 'text').strip().lower()
        if input_mode not in {'text', 'voice'}:
            input_mode = 'text'
        voice_transcript = request.form.get('voice_transcript', '').strip()
        original_text = description
        normalized_text = _normalize_citizen_text(description)
        detected_language, detection_confidence = _detect_language_metadata(
            description, language
        )
        # A citizen's manual language selection is retained as the processing
        # language when it differs from script-based detection.
        processing_language = language if language != 'en' or detected_language == 'en' else detected_language
        state = request.form.get('state', '').strip()
        district = request.form.get('district', '').strip()
        local_area = request.form.get('local_area', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        contact_email = request.form.get('contact_email', '').strip()
        is_anonymous = request.form.get('is_anonymous') == 'on'

        try:
            latitude, longitude = _parse_coordinates(
                request.form.get('latitude', '').strip(),
                request.form.get('longitude', '').strip()
            )
            complaint_datetime = _parse_complaint_datetime(
                request.form.get('complaint_datetime', '').strip()
            )
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('citizen_request'))

        # Server-side validation remains mandatory even when browser validation is enabled.
        if not all([category, title, description, state, district, local_area]):
            flash('Title, category, description, and complete location are required.', 'error')
            return redirect(url_for('citizen_request'))

        if len(title) > 200:
            flash('Complaint title must be 200 characters or fewer.', 'error')
            return redirect(url_for('citizen_request'))

        if len(description) < 20 or len(description) > 5000:
            flash('Description must be between 20 and 5000 characters.', 'error')
            return redirect(url_for('citizen_request'))

        if contact_email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', contact_email):
            flash('Please enter a valid contact email address.', 'error')
            return redirect(url_for('citizen_request'))

        if is_anonymous:
            # The authenticated user remains the owner for access control, while
            # contact information is not attached to the complaint.
            contact_phone = None
            contact_email = None

        saved_files = []
        try:
            photo_filename = _save_upload(
                request.files.get('photo'),
                app.config['ALLOWED_PHOTO_EXTENSIONS'],
                app.config['MAX_PHOTO_SIZE']
            )
            if photo_filename:
                saved_files.append(photo_filename)

            video_filename = _save_upload(
                request.files.get('video'),
                app.config['ALLOWED_VIDEO_EXTENSIONS'],
                app.config['MAX_VIDEO_SIZE']
            )
            if video_filename:
                saved_files.append(video_filename)

            evidence_filename = _save_upload(
                request.files.get('evidence'),
                app.config['ALLOWED_EVIDENCE_EXTENSIONS'],
                app.config['MAX_EVIDENCE_SIZE']
            )
            if evidence_filename:
                saved_files.append(evidence_filename)

            citizen_request_obj = CitizenRequest(
                user_id=session['user_id'],
                title=title,
                category=category,
                description=description,
                language=processing_language,
                original_language=detected_language,
                language_override=(language if language != detected_language else None),
                original_text=original_text,
                normalized_text=normalized_text,
                voice_transcript=voice_transcript or (description if input_mode == 'voice' else None),
                input_mode=input_mode,
                state=state,
                district=district,
                local_area=local_area,
                latitude=latitude,
                longitude=longitude,
                complaint_datetime=complaint_datetime,
                photo_filename=photo_filename,
                video_filename=video_filename,
                evidence_filename=evidence_filename,
                contact_phone=contact_phone,
                contact_email=contact_email,
                is_anonymous=is_anonymous,
                status='Submitted',
                due_at=complaint_datetime + timedelta(hours=DEFAULT_SLA_TARGETS['Low'])
            )
            duplicate_matches = _duplicate_matches(citizen_request_obj)
            citizen_request_obj.generate_request_id()
            db.session.add(citizen_request_obj)
            db.session.commit()
            _notify(
                citizen_request_obj.user_id, 'request_submitted', 'Request submitted',
                f'Your request {citizen_request_obj.request_id} has been submitted.',
                citizen_request_obj.request_id
            )
            db.session.commit()

            # AI is deliberately isolated from complaint persistence. A remote
            # AI outage can never prevent the complaint from being registered.
            analysis_data = None
            try:
                analysis_data = AIService.perform_full_analysis({
                    'title': title,
                    'description': description,
                    'category': category,
                    'district': district,
                    'state': state,
                    'local_area': local_area,
                    'language': processing_language,
                    'original_language': detected_language,
                    'language_confidence': detection_confidence,
                    'original_text': original_text,
                    'normalized_text': normalized_text
                })

                # Similar-request count comes from the real database, not mock data.
                similar_count = CitizenRequest.query.filter(
                    CitizenRequest.id != citizen_request_obj.id,
                    CitizenRequest.district.ilike(district),
                    CitizenRequest.category == category
                ).count()
                analysis_data['similar_requests_count'] = similar_count

                analysis = RequestAnalysis(
                    request_id=citizen_request_obj.request_id,
                    language_detected=analysis_data['language_detected'],
                    category_classified=analysis_data['category_classified'],
                    urgency_level=analysis_data['urgency_level'],
                    infrastructure_gap=analysis_data['infrastructure_gap'],
                    similar_requests_count=similar_count,
                    population_impacted=analysis_data.get('population_impacted', 0),
                    ai_recommendation=analysis_data['ai_recommendation'],
                    explainability_factors=analysis_data['explainability_factors'],
                    issue_type=analysis_data.get('issue_type'),
                    priority=analysis_data.get('priority'),
                    original_priority=analysis_data.get('priority'),
                    recommended_department=analysis_data.get('recommended_department'),
                    recommended_department_id=(
                        _department_for_name(analysis_data.get('recommended_department'), active_only=True).id
                        if _department_for_name(analysis_data.get('recommended_department'), active_only=True)
                        else None
                    ),
                    sentiment=analysis_data.get('sentiment'),
                    confidence_score=analysis_data.get('confidence_score'),
                    ai_provider=analysis_data.get('ai_provider', 'local'),
                    human_review_required=True,
                    review_status='Review Required',
                    confidence_details={
                        'category': analysis_data.get('confidence_score'),
                        'urgency': analysis_data.get('urgency_confidence', analysis_data.get('confidence_score')),
                        'priority': analysis_data.get('priority_confidence', analysis_data.get('confidence_score')),
                        'recommendation': analysis_data.get('recommendation_confidence', analysis_data.get('confidence_score')),
                        'language_detection': detection_confidence,
                        'methodology': 'Local deterministic keyword/context analysis' if analysis_data.get('ai_provider') == 'local' else 'Configured AI provider response'
                    }
                )
                db.session.add(analysis)
                citizen_request_obj.due_at = citizen_request_obj.created_at + timedelta(
                    hours=_sla_target_hours(analysis.priority)
                )
                citizen_request_obj.status = 'Analyzed'
                db.session.flush()
                _add_timeline(
                    citizen_request_obj,
                    'AI analysis completed',
                    f'AI analysis completed using {analysis.ai_provider} analysis.'
                )
                db.session.commit()
                _notify(
                    citizen_request_obj.user_id, 'ai_analysis_completed', 'AI analysis completed',
                    f'AI-assisted analysis is available for {citizen_request_obj.request_id}. Human review is required.',
                    citizen_request_obj.request_id
                )
                db.session.commit()
            except Exception as ai_error:
                # Preserve the successfully stored complaint.
                db.session.rollback()
                citizen_request_obj = CitizenRequest.query.filter_by(
                    request_id=citizen_request_obj.request_id
                ).first()
                if citizen_request_obj:
                    citizen_request_obj.status = 'Submitted'
                    db.session.commit()
                app.logger.warning('AI analysis failed for %s: %s',
                                   citizen_request_obj.request_id if citizen_request_obj else 'unknown',
                                   ai_error)
                flash(
                    'Complaint registered successfully. AI analysis is temporarily unavailable; '
                    'the complaint remains available for officer review.',
                    'info'
                )
            else:
                flash('Complaint submitted and analyzed successfully.', 'success')

            # Record the first lifecycle event and notify the citizen.
            _add_timeline(
                citizen_request_obj,
                'Complaint submitted',
                f'Complaint {citizen_request_obj.request_id} was submitted.'
            )
            _notify(
                citizen_request_obj.user_id,
                'complaint_submitted',
                'Complaint submitted',
                f'Your complaint {citizen_request_obj.request_id} was registered successfully.',
                citizen_request_obj.request_id
            )
            if citizen_request_obj.analysis and citizen_request_obj.analysis.priority in ('Critical', 'High'):
                _notify_admins(
                    'critical_complaint' if citizen_request_obj.analysis.priority == 'Critical' else 'priority_complaint',
                    f"{citizen_request_obj.analysis.priority} priority complaint",
                    f"{citizen_request_obj.request_id} requires review.",
                    citizen_request_obj.request_id
                )
            db.session.commit()
            _send_user_email(
                citizen_request_obj.user_id,
                f'Complaint submitted - {citizen_request_obj.request_id}',
                f'Your complaint {citizen_request_obj.request_id} was registered successfully. '
                f'Current status: {citizen_request_obj.status}.'
            )
            if duplicate_matches:
                flash(
                    'Similar complaint found. Please review the existing complaint ID on the confirmation page. You can still continue because duplicate detection does not automatically reject submissions.',
                    'info'
                )

            return redirect(url_for(
                'citizen_success',
                request_id=citizen_request_obj.request_id
            ))

        except ValueError as exc:
            db.session.rollback()
            for filename in saved_files:
                _delete_upload(filename)
            flash(f'Upload validation failed: {exc}', 'error')
            return redirect(url_for('citizen_request'))
        except Exception as exc:
            db.session.rollback()
            for filename in saved_files:
                _delete_upload(filename)
            app.logger.exception('Complaint submission failed')
            flash('Unable to submit the complaint. Please try again.', 'error')
            return redirect(url_for('citizen_request'))

    return render_template('citizen_request.html')



@app.route('/citizen/track', methods=['GET', 'POST'])
@login_required
def complaint_tracking():
    """Citizen-safe complaint lookup by unique complaint ID."""
    complaint = None
    events = []
    if request.method == 'POST':
        request_id = request.form.get('request_id', '').strip().upper()
        complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
        if not complaint or not _complaint_can_view(complaint, get_current_user()):
            flash('Complaint not found or you are not authorized to view it.', 'error')
            complaint = None
        else:
            events = ComplaintTimeline.query.filter_by(
                request_id=complaint.request_id
            ).order_by(ComplaintTimeline.created_at.asc()).all()
    lifecycle_events = _status_timeline_labels(complaint) if complaint else []
    return render_template(
        'complaint_tracking.html',
        complaint=complaint,
        events=events,
        lifecycle_events=lifecycle_events,
        sla_info=_sla_status(complaint) if complaint else None
    )



@app.route('/citizen/feedback/<request_id>', methods=['POST'])
@login_required
def submit_feedback(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    user = get_current_user()
    if not complaint or complaint.user_id != user.id:
        abort(404)
    if complaint.status != 'Resolved':
        flash('Feedback is available after the complaint is resolved.', 'error')
        return redirect(url_for('complaint_details', request_id=request_id))
    if complaint.feedback:
        flash('Feedback has already been submitted for this complaint.', 'info')
        return redirect(url_for('complaint_details', request_id=request_id))
    try:
        rating = int(request.form.get('rating', '0'))
    except ValueError:
        rating = 0
    satisfaction = request.form.get('satisfaction_level', '').strip()
    issue_resolved = request.form.get('issue_resolved') == 'yes'
    reopened_requested = request.form.get('reopened_requested') == 'yes'
    reopened_reason = request.form.get('reopened_reason', '').strip()
    comment = request.form.get('comment', '').strip()
    allowed_satisfaction = {'Very dissatisfied', 'Dissatisfied', 'Neutral', 'Satisfied', 'Very satisfied'}
    if rating < 1 or rating > 5 or satisfaction not in allowed_satisfaction:
        flash('Please provide a valid rating and satisfaction level.', 'error')
        return redirect(url_for('complaint_details', request_id=request_id))
    if reopened_requested and not reopened_reason:
        flash('Please explain why the issue should be reopened.', 'error')
        return redirect(url_for('complaint_details', request_id=request_id))
    db.session.add(CitizenFeedback(
        request_id=request_id, user_id=user.id, rating=rating,
        satisfaction_level=satisfaction, issue_resolved=issue_resolved,
        reopened_requested=reopened_requested, reopened_reason=reopened_reason or None,
        comment=comment
    ))
    _add_timeline(
        complaint, 'Citizen feedback',
        f'Citizen submitted a {rating}/5 satisfaction rating.' +
        (' Reopen requested.' if reopened_requested else ''), user
    )
    if reopened_requested:
        complaint.status = 'Reopened'
        complaint.resolved_at = None
        complaint.updated_at = datetime.utcnow()
        _add_timeline(complaint, 'Reopened', f'Citizen requested reopening: {reopened_reason}', user)
        _notify_admins('request_reopened', 'Request reopened', f'{request_id} was reopened after citizen feedback.', request_id)
        if complaint.assigned_officer_id:
            _notify(complaint.assigned_officer_id, 'request_reopened', 'Request reopened', f'{request_id} was reopened after citizen feedback.', request_id)
    db.session.commit()
    flash('Thank you for your feedback.', 'success')
    return redirect(url_for('complaint_details', request_id=request_id))


@app.route('/citizen/complaint/<request_id>')
@login_required
def complaint_details(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    user = get_current_user()
    if not complaint or not _complaint_can_view(complaint, user):
        abort(404)
    events = ComplaintTimeline.query.filter_by(
        request_id=request_id
    ).order_by(ComplaintTimeline.created_at.asc()).all()
    officers = User.query.filter_by(role='Officer').order_by(User.username.asc()).all() if user.role in ('Officer', 'Admin') else []
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all() if user.role in ('Officer', 'Admin') else []
    return render_template(
        'complaint_details.html',
        complaint=complaint,
        assignment=_assignment_state(complaint),
        events=events,
        officers=officers,
        departments=departments,
        can_assign=_complaint_can_assign(user),
        can_update=_complaint_can_update(complaint, user),
        sla_info=_sla_status(complaint),
        lifecycle_events=_status_timeline_labels(complaint)
    )


@app.route('/api/notifications')
@login_required
def api_notifications():
    user = get_current_user()
    items = Notification.query.filter_by(user_id=user.id).order_by(
        Notification.created_at.desc()
    ).limit(50).all()
    unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return jsonify({
        'unread_count': unread,
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.notification_type,
            'request_id': n.request_id,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat() if n.created_at else None
        } for n in items]
    })


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    n = Notification.query.filter_by(
        id=notification_id, user_id=session['user_id']
    ).first()
    if not n:
        return jsonify({'success': False, 'error': 'Notification not found.'}), 404
    n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=session['user_id'], is_read=False).update(
        {'is_read': True}, synchronize_session=False
    )
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/demand-prediction')
@login_required
@role_required('Officer', 'Admin')
def api_demand_prediction():
    return jsonify(_build_demand_prediction(get_current_user()))


@app.route('/citizen/success/<request_id>')
def citizen_success(request_id):
    """Success page after request submission, including non-blocking duplicate hints."""
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint or not get_current_user() or not _complaint_can_view(complaint, get_current_user()):
        abort(404)
    matches = _duplicate_matches(complaint, exclude_id=complaint.id)
    return render_template('request_success.html', request_id=request_id, duplicate_count=len(matches))

@app.route('/citizen/analysis')
@login_required
@role_required('Citizen')
def citizen_analysis():
    """View citizen's submitted requests."""
    requests = CitizenRequest.query.filter_by(user_id=session['user_id']).order_by(CitizenRequest.created_at.desc()).all()
    explanations = {
        item.request_id: _build_analysis_explanation(item, item.analysis)
        for item in requests if item.analysis
    }
    return render_template('ai_analysis.html', requests=requests, explanations=explanations)


def _officer_dashboard_records(user, state_filter='', district_filter='', category_filter=''):
    """Return one consistent officer queue and derived metrics for every dashboard view.

    The officer dashboard, charts and complaint-management page must all operate on
    the same authorized queue. Category/priority values also fall back to the
    citizen request/urgency fields for older records that predate AI analysis.
    """
    query = _scoped_complaints_query(user)
    if state_filter:
        query = query.filter(db.func.lower(CitizenRequest.state) == state_filter.lower())
    if district_filter:
        query = query.filter(db.func.lower(CitizenRequest.district) == district_filter.lower())
    rows = query.order_by(CitizenRequest.created_at.desc()).all()

    if category_filter:
        wanted = category_filter.strip().lower()
        rows = [
            c for c in rows
            if (str(c.category or '').strip().lower() == wanted)
            or (c.analysis and str(c.analysis.category_classified or '').strip().lower() == wanted)
        ]

    now = datetime.utcnow()
    today = now.date()
    pending_statuses = {'Submitted', 'Analyzed', 'Pending', 'Reopened', 'In-Progress', 'In Progress'}
    resolved = [c for c in rows if (c.status or '').strip().lower() == 'resolved']
    pending = [c for c in rows if (c.status or '') in pending_statuses]
    effective_priorities = [_effective_priority(c.analysis) for c in rows]

    category_dist = {}
    urgency_dist = {}
    for c in rows:
        category = (c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category) or 'Other'
        category = str(category).strip() or 'Other'
        category_dist[category] = category_dist.get(category, 0) + 1

        urgency = (c.analysis.urgency_level if c.analysis and c.analysis.urgency_level else None)
        if not urgency:
            priority = _effective_priority(c.analysis)
            urgency = {'Critical': 'Critical', 'High': 'High', 'Medium': 'Moderate', 'Low': 'Low'}.get(priority, 'Low')
        urgency = str(urgency).strip() or 'Low'
        urgency_dist[urgency] = urgency_dist.get(urgency, 0) + 1

    resolution_hours = [
        _resolution_minutes(c.created_at, c.resolved_at) / 60
        for c in resolved
        if _resolution_minutes(c.created_at, c.resolved_at) is not None
    ]
    return {
        'rows': rows,
        'assigned': len(rows),
        'pending': len(pending),
        'critical': sum(1 for p in effective_priorities if p == 'Critical'),
        'high_critical': sum(1 for p in effective_priorities if p in ('High', 'Critical')),
        'overdue': sum(1 for c in rows if c.due_at and c.due_at < now and (c.status or '').lower() != 'resolved'),
        'due_today': sum(1 for c in rows if c.due_at and c.due_at.date() == today and (c.status or '').lower() != 'resolved'),
        'resolved': len(resolved),
        'analyzed': sum(1 for c in rows if (c.status or '') == 'Analyzed'),
        'average_resolution_hours': round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None,
        'category_distribution': category_dist,
        'urgency_distribution': urgency_dist,
        'recent_assigned': rows[:10],
    }


def _officer_smart_stats(user):
    data = _officer_dashboard_records(user)
    return {key: data[key] for key in (
        'assigned', 'pending', 'critical', 'high_critical', 'overdue',
        'due_today', 'resolved', 'average_resolution_hours', 'recent_assigned'
    )}


# ===============================================
# OFFICER ROUTES
# ===============================================

@app.route('/officer/dashboard')
@login_required
@role_required('Officer', 'Admin')
def officer_dashboard():
    """Officer dashboard with one consistent, database-backed queue definition."""
    user = get_current_user()
    data = _officer_dashboard_records(user)
    top_categories = [
        {'category': category, 'count': count}
        for category, count in sorted(
            data['category_distribution'].items(), key=lambda item: item[1], reverse=True
        )[:5]
    ]
    stats = {
        'total_requests': data['assigned'],
        'analyzed_requests': data['analyzed'],
        'pending_requests': data['pending'],
        'category_distribution': data['category_distribution'],
        'urgency_distribution': data['urgency_distribution']
    }
    department_options = sorted({d.name for d in Department.query.filter_by(is_active=True).all()})
    trend_categories = sorted({
        (c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category)
        for c in data['rows'] if (c.analysis and c.analysis.category_classified) or c.category
    })
    return render_template(
        'demand_analysis.html',
        stats=stats,
        top_categories=top_categories,
        smart_stats=_officer_smart_stats(user) if user.role == 'Officer' else None,
        trend_categories=trend_categories,
        trend_departments=department_options
    )

@app.route('/officer/demand-analysis')
@login_required
@role_required('Officer', 'Admin')
def officer_demand_analysis():
    """Demand analysis dashboard using the exact same officer queue as the main dashboard."""
    user = get_current_user()
    data = _officer_dashboard_records(user)
    top_categories = [
        {'category': category, 'count': count}
        for category, count in sorted(
            data['category_distribution'].items(), key=lambda item: item[1], reverse=True
        )[:5]
    ]
    stats = {
        'total_requests': data['assigned'],
        'analyzed_requests': data['analyzed'],
        'pending_requests': data['pending'],
        'category_distribution': data['category_distribution'],
        'urgency_distribution': data['urgency_distribution']
    }
    department_options = sorted({d.name for d in Department.query.filter_by(is_active=True).all()})
    trend_categories = sorted({
        (c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category)
        for c in data['rows'] if (c.analysis and c.analysis.category_classified) or c.category
    })
    return render_template(
        'demand_analysis.html',
        stats=stats,
        top_categories=top_categories,
        smart_stats=_officer_smart_stats(user) if user.role == 'Officer' else None,
        trend_categories=trend_categories,
        trend_departments=department_options
    )

@app.route('/officer/hotspots')
@login_required
@role_required('Officer', 'Admin')
def officer_hotspots():
    """Hotspot map page for complaints assigned to this officer."""
    user = get_current_user()
    scoped = _scoped_complaints_query(user)
    hotspots_data = scoped.outerjoin(RequestAnalysis).with_entities(
        CitizenRequest.state,
        CitizenRequest.district,
        db.func.count(CitizenRequest.id).label('demand'),
        db.func.avg(RequestAnalysis.infrastructure_gap).label('gap')
    ).group_by(
        CitizenRequest.state,
        CitizenRequest.district
    ).order_by(db.desc('gap')).limit(10).all()
    
    hotspots = []
    for state, district, demand, gap in hotspots_data:
        hotspots.append({
            'state': state or 'Unknown',
            'district': district or 'Unknown',
            'demand': demand or 0,
            'gap': float(gap) if gap else 5.0,
            'population': (demand or 0) * 150  # Mock population
        })
    
    return render_template('hotspots.html', hotspots=hotspots)

@app.route('/officer/government-dashboard')
@login_required
@role_required('Officer', 'Admin')
def officer_government_dashboard():
    """Government decision-support dashboard using actual stored records."""
    user = get_current_user()
    complaints = _scoped_complaints_query(user).all()
    grouped = {}
    for c in complaints:
        category = c.analysis.category_classified if c.analysis else c.category or 'Other'
        key = (category, c.state, c.district)
        item = grouped.setdefault(key, {'category': category, 'state': c.state, 'district': c.district, 'requests': 0, 'high': 0, 'unresolved': 0, 'recommendations': []})
        item['requests'] += 1
        if _effective_priority(c.analysis) in ('High', 'Critical'):
            item['high'] += 1
        if c.status != 'Resolved':
            item['unresolved'] += 1
        if c.analysis and c.analysis.ai_recommendation:
            item['recommendations'].append(c.analysis.ai_recommendation)
    priority_areas = sorted(grouped.values(), key=lambda x: (x['high'], x['requests']), reverse=True)[:10]
    for item in priority_areas:
        item['recommendation'] = Counter(item['recommendations']).most_common(1)[0][0] if item['recommendations'] else 'No AI recommendation is available yet.'
    return render_template('government_dashboard.html', priority_areas=priority_areas)

# ===============================================
# ADMIN ROUTES
# ===============================================
@app.route('/admin/audit-log')
@login_required
@role_required('Admin')
def admin_audit_log():
    """Admin-only audit history for important administrative actions."""
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = min(max(request.args.get('per_page', 50, type=int), 10), 100)
    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin_audit_log.html', pagination=pagination)



@app.route('/admin/dashboard')
@login_required
@role_required('Admin')
def admin_dashboard():
    """Admin control dashboard using one consistent, live platform dataset.

    The Admin view intentionally follows the Officer dashboard pattern: the
    summary cards, charts and filtered complaint count are all derived from
    the same current request set. Admins can see the complete platform scope.
    """
    _notify_deadlines()

    state_filter = request.args.get('state', '').strip()
    district_filter = request.args.get('district', '').strip()
    category_filter = request.args.get('category', '').strip()
    priority_filter = request.args.get('priority', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = CitizenRequest.query
    if state_filter:
        query = query.filter(db.func.lower(CitizenRequest.state) == state_filter.lower())
    if district_filter:
        query = query.filter(db.func.lower(CitizenRequest.district) == district_filter.lower())
    if status_filter:
        query = query.filter(CitizenRequest.status == status_filter)
    rows = query.order_by(CitizenRequest.created_at.desc()).all()

    if category_filter:
        wanted = category_filter.lower()
        rows = [c for c in rows if (
            str(c.category or '').strip().lower() == wanted or
            (c.analysis and str(c.analysis.category_classified or '').strip().lower() == wanted)
        )]

    if priority_filter:
        rows = [c for c in rows if _effective_priority(c.analysis) == priority_filter]

    now = datetime.utcnow()
    today = now.date()
    pending_statuses = {'Submitted', 'Analyzed', 'Pending', 'Reopened', 'In-Progress', 'In Progress'}
    resolved = [c for c in rows if (c.status or '').strip().lower() == 'resolved']
    pending = [c for c in rows if (c.status or '') in pending_statuses]
    effective_priorities = [_effective_priority(c.analysis) for c in rows]

    category_distribution = {}
    urgency_distribution = {}
    state_distribution = {}
    for c in rows:
        category = (c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category) or 'Other'
        category = str(category).strip() or 'Other'
        category_distribution[category] = category_distribution.get(category, 0) + 1
        urgency = c.analysis.urgency_level if c.analysis and c.analysis.urgency_level else None
        if not urgency:
            urgency = {'Critical': 'Critical', 'High': 'High', 'Medium': 'Moderate', 'Low': 'Low'}.get(_effective_priority(c.analysis), 'Low')
        urgency = str(urgency).strip() or 'Low'
        urgency_distribution[urgency] = urgency_distribution.get(urgency, 0) + 1
        state = str(c.state or 'Unknown').strip() or 'Unknown'
        state_distribution[state] = state_distribution.get(state, 0) + 1

    resolution_hours = [
        _resolution_minutes(c.created_at, c.resolved_at) / 60
        for c in resolved if _resolution_minutes(c.created_at, c.resolved_at) is not None
    ]
    overdue = [c for c in rows if c.due_at and c.due_at < now and (c.status or '').lower() != 'resolved']
    due_today = [c for c in rows if c.due_at and c.due_at.date() == today and (c.status or '').lower() != 'resolved']
    unassigned = sum(1 for c in rows if _assignment_state(c)['truly_unassigned'])
    ai_pending = sum(1 for c in rows if _assignment_state(c)['official_assignment_pending'])

    resolved_with_sla = [c for c in resolved if c.due_at and c.resolved_at]
    sla_compliant = sum(1 for c in resolved_with_sla if c.resolved_at <= c.due_at)
    sla_performance = round(sla_compliant / len(resolved_with_sla) * 100, 1) if resolved_with_sla else None

    feedback = [c.feedback.rating for c in rows if c.feedback and c.feedback.rating is not None]
    resolved_feedback = sum(1 for c in rows if c.feedback and c.feedback.issue_resolved)

    total_users = User.query.count()
    total_citizens = User.query.filter_by(role='Citizen').count()
    total_officers = User.query.filter_by(role='Officer').count()
    total_departments = Department.query.count()
    active_departments = Department.query.filter_by(is_active=True).count()
    total_requests = len(rows)

    stats = {
        'total_users': total_users,
        'total_citizens': total_citizens,
        'total_officers': total_officers,
        'total_departments': total_departments,
        'active_departments': active_departments,
        'total_requests': total_requests,
        'analyzed_count': sum(1 for c in rows if (c.status or '') == 'Analyzed'),
        'pending_count': len(pending),
        'in_progress_count': sum(1 for c in rows if (c.status or '') in ('In-Progress', 'In Progress')),
        'resolved_count': len(resolved),
        'high_critical_count': sum(1 for p in effective_priorities if p in ('High', 'Critical')),
        'critical_count': sum(1 for p in effective_priorities if p == 'Critical'),
        'unassigned_count': unassigned,
        'ai_pending_count': ai_pending,
        'overdue_count': len(overdue),
        'due_today_count': len(due_today),
        'districts_count': len({(c.district or '').strip() for c in rows if (c.district or '').strip()}),
        'feedback_count': len(feedback),
        'avg_rating': round(sum(float(x) for x in feedback) / len(feedback), 2) if feedback else None,
        'resolved_feedback': resolved_feedback,
        'sla_performance': sla_performance,
        'average_resolution_hours': round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None,
        'category_distribution': dict(sorted(category_distribution.items(), key=lambda x: (-x[1], x[0]))),
        'urgency_distribution': dict(sorted(urgency_distribution.items(), key=lambda x: (-x[1], x[0]))),
        'state_distribution': dict(sorted(state_distribution.items(), key=lambda x: (-x[1], x[0]))),
    }

    departments = Department.query.order_by(Department.name.asc()).all()
    officers = User.query.filter_by(role='Officer').order_by(User.username.asc()).all()
    recent_activity = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(8).all()
    geo_options = _geo_options()
    categories = sorted({
        str(c.category).strip() for c in CitizenRequest.query.with_entities(CitizenRequest.category).all()
        if str(c.category or '').strip()
    })
    statuses = ['Submitted', 'Analyzed', 'Pending', 'In-Progress', 'Resolved', 'Reopened']

    return render_template(
        'admin_dashboard.html',
        stats=stats,
        departments=departments,
        officers=officers,
        recent_activity=recent_activity,
        geo_options=geo_options,
        categories=categories,
        statuses=statuses,
        filters={
            'state': state_filter, 'district': district_filter,
            'category': category_filter, 'priority': priority_filter,
            'status': status_filter
        }
    )


# ===============================================
# DEPARTMENT MANAGEMENT
# ===============================================

@app.route('/admin/departments', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def admin_departments():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name or len(name) > 100:
            flash('Department name is required and must be 100 characters or fewer.', 'error')
        elif Department.query.filter(db.func.lower(Department.name) == name.lower()).first():
            flash('That department already exists.', 'error')
        else:
            department = Department(name=name, is_active=True)
            db.session.add(department)
            db.session.flush()
            _record_audit(
                get_current_user(), 'Department changes', 'Department', department.id,
                {'operation': 'created', 'name': department.name}
            )
            db.session.commit()
            flash('Department created successfully.', 'success')
        return redirect(url_for('admin_departments'))
    departments = Department.query.order_by(Department.name.asc()).all()
    officers = User.query.filter_by(role='Officer').order_by(User.username.asc()).all()
    return render_template('admin_departments.html', departments=departments, officers=officers)

@app.route('/admin/departments/<int:department_id>/edit', methods=['POST'])
@login_required
@role_required('Admin')
def edit_department(department_id):
    department = Department.query.get_or_404(department_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Department name is required.', 'error')
        return redirect(url_for('admin_departments'))
    duplicate = Department.query.filter(db.func.lower(Department.name) == name.lower(), Department.id != department.id).first()
    if duplicate:
        flash('Another department already uses that name.', 'error')
        return redirect(url_for('admin_departments'))
    old_name = department.name
    department.name = name
    if old_name != name:
        CitizenRequest.query.filter_by(assigned_department=old_name).update({'assigned_department': name}, synchronize_session=False)
    _record_audit(
        get_current_user(), 'Department changes', 'Department', department.id,
        {'operation': 'renamed', 'old_name': old_name, 'new_name': name}
    )
    db.session.commit()
    flash('Department updated successfully.', 'success')
    return redirect(url_for('admin_departments'))

@app.route('/admin/departments/<int:department_id>/toggle', methods=['POST'])
@login_required
@role_required('Admin')
def toggle_department(department_id):
    department = Department.query.get_or_404(department_id)
    department.is_active = not department.is_active
    _record_audit(
        get_current_user(), 'Department changes', 'Department', department.id,
        {'operation': 'activated' if department.is_active else 'deactivated', 'name': department.name}
    )
    db.session.commit()
    flash(f'Department {"activated" if department.is_active else "deactivated"}. Existing data was preserved.', 'success')
    return redirect(url_for('admin_departments'))

@app.route('/admin/departments/<int:department_id>/officers', methods=['POST'])
@login_required
@role_required('Admin')
def assign_department_officers(department_id):
    department = Department.query.get_or_404(department_id)
    ids = {int(x) for x in request.form.getlist('officer_ids') if x.isdigit()}
    officers = User.query.filter_by(role='Officer').all()
    changed_officers = []
    for officer in officers:
        old_department_id = officer.department_id
        if officer.id in ids:
            officer.department_id = department.id
        elif officer.department_id == department.id:
            officer.department_id = None
        if officer.department_id != old_department_id:
            changed_officers.append({
                'user_id': officer.id,
                'username': officer.username,
                'old_department_id': old_department_id,
                'new_department_id': officer.department_id
            })
    _record_audit(
        get_current_user(), 'Department changes', 'Department', department.id,
        {'operation': 'officer_assignment', 'changes': changed_officers}
    )
    db.session.commit()
    flash('Officer department assignments updated.', 'success')
    return redirect(url_for('admin_departments'))

@app.route('/admin/departments/<int:department_id>')
@login_required
@role_required('Admin')
def department_details(department_id):
    department = Department.query.get_or_404(department_id)
    page = request.args.get('page', 1, type=int) or 1
    per_page = min(max(request.args.get('per_page', app.config.get('ITEMS_PER_PAGE', 20), type=int) or 20, 10), 100)
    officers = User.query.filter_by(
        role='Officer', department_id=department.id
    ).order_by(User.username.asc()).all()
    officer_ids = [o.id for o in officers]
    complaint_query = CitizenRequest.query.filter(
        or_(
            CitizenRequest.assigned_department_id == department.id,
            db.and_(
                CitizenRequest.assigned_department_id.is_(None),
                CitizenRequest.assigned_department == department.name
            ),
            CitizenRequest.assigned_officer_id.in_(officer_ids) if officer_ids else CitizenRequest.id == -1
        )
    )
    complaint_pagination = complaint_query.order_by(
        CitizenRequest.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        'department_details.html',
        department=department,
        complaints=complaint_pagination.items,
        complaint_pagination=complaint_pagination,
        officers=officers
    )


# ===============================================
# COMPLAINT SEARCH / PAGINATION HELPERS
# ===============================================

def _complaint_search_query(user):
    """Build an indexed, server-side complaint query for officer/admin management."""
    query = _scoped_complaints_query(user)
    query = query.outerjoin(
        RequestAnalysis,
        CitizenRequest.request_id == RequestAnalysis.request_id
    )

    complaint_id = request.args.get('complaint_id', '').strip()
    keyword = request.args.get('keyword', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    priority = request.args.get('priority', '').strip()
    department = request.args.get('department', '').strip()
    officer_id = request.args.get('officer', '').strip()
    location = request.args.get('location', '').strip()
    language = request.args.get('language', '').strip().lower()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    if complaint_id:
        query = query.filter(CitizenRequest.request_id.ilike(f'%{complaint_id}%'))
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(
            CitizenRequest.title.ilike(like),
            CitizenRequest.description.ilike(like),
            CitizenRequest.request_id.ilike(like)
        ))
    if category:
        query = query.filter(or_(
            CitizenRequest.category == category,
            RequestAnalysis.category_classified == category
        ))
    if status:
        query = query.filter(CitizenRequest.status == status)
    if priority:
        priority_urgencies = {
            'Critical': ['Critical'],
            'High': ['High'],
            'Medium': ['Medium', 'Moderate'],
            'Low': ['Low'],
        }
        query = query.filter(
            or_(
                db.func.coalesce(RequestAnalysis.priority_override, RequestAnalysis.priority) == priority,
                RequestAnalysis.urgency_level.in_(priority_urgencies.get(priority, [priority]))
            )
        )
    if department:
        query = query.filter(CitizenRequest.assigned_department == department)
    if officer_id:
        try:
            query = query.filter(CitizenRequest.assigned_officer_id == int(officer_id))
        except ValueError:
            query = query.filter(CitizenRequest.id == -1)
    if location:
        like = f'%{location}%'
        query = query.filter(or_(
            CitizenRequest.state.ilike(like),
            CitizenRequest.district.ilike(like),
            CitizenRequest.local_area.ilike(like)
        ))
    if language and language in SUPPORTED_LANGUAGES:
        query = query.filter(
            db.func.coalesce(CitizenRequest.language_override, CitizenRequest.original_language) == language
        )
    if start_date:
        try:
            query = query.filter(CitizenRequest.created_at >= datetime.fromisoformat(start_date))
        except ValueError:
            pass
    if end_date:
        try:
            end_value = datetime.fromisoformat(end_date)
            if len(end_date) == 10:
                end_value += timedelta(days=1)
            query = query.filter(CitizenRequest.created_at < end_value)
        except ValueError:
            pass

    return query.order_by(CitizenRequest.created_at.desc())


def _visible_filter_options(user):
    """Fetch only small distinct filter option sets; complaint rows remain paginated."""
    scoped = _scoped_complaints_query(user)
    categories = {
        value for value, in scoped.with_entities(CitizenRequest.category).distinct().all()
        if value
    }
    analysis_categories = scoped.join(
        RequestAnalysis,
        CitizenRequest.request_id == RequestAnalysis.request_id
    ).with_entities(RequestAnalysis.category_classified).distinct().all()
    categories.update(value for value, in analysis_categories if value)

    departments = [
        value for value, in scoped.with_entities(CitizenRequest.assigned_department).distinct().all()
        if value
    ]
    if user.role == 'Admin':
        departments.extend(
            value for value, in Department.query.filter_by(is_active=True).with_entities(Department.name).all()
            if value
        )
    departments = sorted(set(departments))

    officers_query = User.query.filter_by(role='Officer')
    if user.role == 'Officer':
        officers_query = officers_query.filter(User.id == user.id)
    officers = officers_query.order_by(User.username.asc()).all()
    return sorted(categories), departments, officers


# ===============================================
# AREA / DEPARTMENT ANALYTICS
# ===============================================

def _area_analytics(user):
    scoped = _scoped_complaints_query(user)
    area_rows = scoped.outerjoin(
        RequestAnalysis,
        CitizenRequest.request_id == RequestAnalysis.request_id
    ).with_entities(
        CitizenRequest.state,
        CitizenRequest.district,
        CitizenRequest.local_area,
        db.func.count(CitizenRequest.id).label('total'),
        db.func.sum(db.case((CitizenRequest.status == 'Resolved', 1), else_=0)).label('resolved'),
        db.func.sum(db.case((
            CitizenRequest.status.in_(['Submitted', 'Pending', 'Analyzed', 'In-Progress']),
            1
        ), else_=0)).label('pending'),
        db.func.sum(db.case((
            db.func.coalesce(
                RequestAnalysis.priority_override,
                RequestAnalysis.priority
            ) == 'Critical',
            1
        ), else_=0)).label('critical'),
        db.func.avg(
            db.case((
                CitizenRequest.resolved_at.isnot(None),
                (db.func.julianday(CitizenRequest.resolved_at) -
                 db.func.julianday(CitizenRequest.created_at)) * 24 * 60
            ), else_=None)
        ).label('avg_resolution_minutes')
    ).group_by(
        CitizenRequest.state, CitizenRequest.district, CitizenRequest.local_area
    ).order_by(db.desc('total')).all()

    cutoff = datetime.utcnow() - timedelta(days=30)
    previous_cutoff = datetime.utcnow() - timedelta(days=60)
    recent_rows = scoped.filter(CitizenRequest.created_at >= previous_cutoff).with_entities(
        CitizenRequest.state, CitizenRequest.district, CitizenRequest.local_area,
        db.func.sum(db.case((CitizenRequest.created_at >= cutoff, 1), else_=0)).label('recent'),
        db.func.sum(db.case((
            db.and_(
                CitizenRequest.created_at >= previous_cutoff,
                CitizenRequest.created_at < cutoff
            ), 1
        ), else_=0)).label('previous')
    ).group_by(
        CitizenRequest.state, CitizenRequest.district, CitizenRequest.local_area
    ).all()
    trends = {
        (state or 'Unknown', district or 'Unknown', area or 'Unknown'):
        (int(recent or 0), int(previous or 0))
        for state, district, area, recent, previous in recent_rows
    }

    category_rows = scoped.outerjoin(
        RequestAnalysis,
        CitizenRequest.request_id == RequestAnalysis.request_id
    ).with_entities(
        CitizenRequest.state, CitizenRequest.district, CitizenRequest.local_area,
        db.func.coalesce(RequestAnalysis.category_classified, CitizenRequest.category).label('category'),
        db.func.count(CitizenRequest.id).label('count')
    ).group_by(
        CitizenRequest.state, CitizenRequest.district, CitizenRequest.local_area,
        db.func.coalesce(RequestAnalysis.category_classified, CitizenRequest.category)
    ).order_by(db.desc('count')).all()
    top_category = {}
    for state, district, area, category, count in category_rows:
        key = (state or 'Unknown', district or 'Unknown', area or 'Unknown')
        if key not in top_category:
            top_category[key] = {'name': category or 'Other', 'count': int(count or 0)}

    result = []
    for row in area_rows:
        state = row.state or 'Unknown'
        district = row.district or 'Unknown'
        area = row.local_area or 'Unknown'
        key = (state, district, area)
        recent, previous = trends.get(key, (0, 0))
        trend = 'Increasing' if recent > previous else 'Decreasing' if recent < previous else 'Stable'
        total = int(row.total or 0)
        resolved = int(row.resolved or 0)
        avg_minutes = float(row.avg_resolution_minutes) if row.avg_resolution_minutes is not None else None
        result.append({
            'state': state,
            'district': district,
            'area': area,
            'total': total,
            'pending': int(row.pending or 0),
            'resolved': resolved,
            'critical': int(row.critical or 0),
            'top_category': top_category.get(key, {}).get('name', 'Other'),
            'resolution_rate': round(resolved / total * 100, 2) if total else 0,
            'average_resolution_hours': round(avg_minutes / 60, 2) if avg_minutes is not None else None,
            'recent_trend': trend,
            'recent_30_days': recent,
            'previous_30_days': previous
        })
    return result


def _department_performance(user):
    """Operational department metrics using official assignment only."""
    complaints = _scoped_complaints_query(user).all()
    now = datetime.utcnow()
    grouped = {}

    for complaint in complaints:
        department = _official_department(complaint)
        if not department:
            continue
        key = department.id
        item = grouped.setdefault(key, {
            'department': department.name,
            'department_id': department.id,
            'total_assigned': 0,
            'pending': 0,
            'resolved': 0,
            'overdue': 0,
            'sla_compliant_resolved': 0,
            'sla_resolved_total': 0,
            'ratings': [],
            'categories': Counter()
        })
        item['total_assigned'] += 1
        if complaint.status == 'Resolved':
            item['resolved'] += 1
            if complaint.due_at and complaint.resolved_at:
                item['sla_resolved_total'] += 1
                if complaint.resolved_at <= complaint.due_at:
                    item['sla_compliant_resolved'] += 1
        else:
            item['pending'] += 1
            if complaint.due_at and complaint.due_at < now:
                item['overdue'] += 1

        if complaint.feedback and complaint.feedback.rating is not None:
            item['ratings'].append(float(complaint.feedback.rating))
        category = (
            complaint.analysis.category_classified
            if complaint.analysis and complaint.analysis.category_classified
            else complaint.category or 'Other'
        )
        item['categories'][category] += 1

    result = []
    for item in grouped.values():
        resolved_times = [
            _resolution_minutes(c.created_at, c.resolved_at) / 60
            for c in complaints
            if _official_department(c) and _official_department(c).id == item['department_id']
            and c.status == 'Resolved'
            and _resolution_minutes(c.created_at, c.resolved_at) is not None
        ]
        result.append({
            'department': item['department'],
            'total_assigned': item['total_assigned'],
            'pending': item['pending'],
            'resolved': item['resolved'],
            'average_resolution_hours': round(sum(resolved_times) / len(resolved_times), 2) if resolved_times else None,
            'overdue': item['overdue'],
            'sla_compliance': round(
                item['sla_compliant_resolved'] / item['sla_resolved_total'] * 100, 2
            ) if item['sla_resolved_total'] else None,
            'citizen_satisfaction': round(
                sum(item['ratings']) / len(item['ratings']), 2
            ) if item['ratings'] else None,
            'categories': [
                {'category': category, 'count': count}
                for category, count in item['categories'].most_common()
            ]
        })

    return sorted(result, key=lambda x: x['department'].lower())


# ===============================================
# COMPLAINT MANAGEMENT
# ===============================================

@app.route('/admin/complaints')
@app.route('/officer/complaints')
@login_required
@role_required('Officer', 'Admin')
def complaint_management():
    user = get_current_user()
    query = _complaint_search_query(user)
    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', app.config.get('ITEMS_PER_PAGE', 20), type=int) or 20
    per_page = min(max(per_page, 10), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    categories, departments, officers = _visible_filter_options(user)
    now = datetime.utcnow()
    rows = []
    for complaint in pagination.items:
        sla = _sla_status(complaint, now)
        rows.append({'complaint': complaint, 'sla': sla, 'assignment': _assignment_state(complaint)})
    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop('page', None)
    pagination_query = urlencode(pagination_args)
    return render_template(
        'complaint_management.html',
        rows=rows,
        pagination=pagination,
        categories=categories,
        departments=departments,
        officers=officers,
        statuses=['Submitted', 'Analyzed', 'Pending', 'In-Progress', 'Resolved'],
        priorities=['Critical', 'High', 'Medium', 'Low'],
        filters={
            key: request.args.get(key, '').strip()
            for key in [
                'complaint_id', 'keyword', 'category', 'status', 'priority',
                'department', 'officer', 'location', 'language', 'start_date', 'end_date'
            ]
        },
        pagination_query=pagination_query
    )

@app.route('/admin/sla', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def admin_sla_settings():
    if request.method == 'POST':
        try:
            for priority in DEFAULT_SLA_TARGETS:
                value = request.form.get(f'target_{priority}', '').strip()
                hours = int(value)
                if hours <= 0 or hours > 8760:
                    raise ValueError
                config = SLAConfig.query.filter_by(priority=priority).first()
                if config:
                    config.target_hours = hours
                else:
                    db.session.add(SLAConfig(priority=priority, target_hours=hours))
            _record_audit(
                get_current_user(), 'Configuration changes', 'SLAConfig', 'global',
                {'operation': 'updated', 'targets': {p: SLAConfig.query.filter_by(priority=p).first().target_hours for p in DEFAULT_SLA_TARGETS}}
            )
            db.session.commit()
            flash('SLA targets updated successfully. Existing complaint due dates were preserved.', 'success')
        except (TypeError, ValueError):
            db.session.rollback()
            flash('Each SLA target must be a whole number of hours between 1 and 8760.', 'error')
        return redirect(url_for('admin_sla_settings'))

    configs = {}
    for priority, hours in DEFAULT_SLA_TARGETS.items():
        config = SLAConfig.query.filter_by(priority=priority).first()
        configs[priority] = config.target_hours if config else hours
    return render_template('sla_settings.html', configs=configs)

@app.route('/api/analytics/areas')
@login_required
@role_required('Officer', 'Admin')
def api_area_analytics():
    return jsonify(_area_analytics(get_current_user()))

@app.route('/api/analytics/departments')
@login_required
@role_required('Officer', 'Admin')
def api_department_analytics():
    return jsonify(_department_performance(get_current_user()))

# ===============================================
# API ROUTES
# ===============================================


# ===============================================
# GEOLOCATION FILTER DATA
# ===============================================
_GEO_DATA_CACHE = None

# District-level fallback coordinates used only when a complaint does not store GPS.
# These are approximate district-centre coordinates for the bundled demo data.
# They never replace explicit citizen-provided latitude/longitude.
DISTRICT_COORDINATES = {
    ('Tamil Nadu', 'Salem'): (11.6643, 78.1460),
    ('Maharashtra', 'Nashik'): (19.9975, 73.7898),
    ('Karnataka', 'Davangere'): (14.4644, 75.9218),
    ('Telangana', 'Warangal'): (17.9689, 79.5941),
    ('Andhra Pradesh', 'Vizag'): (17.6868, 83.2185),
}

def _complaint_map_coordinates(complaint):
    """Return coordinates and precision for a map-safe complaint marker.

    Explicit complaint GPS is always preferred. For legacy/demo records without
    GPS, use a maintained district-centre fallback so the existing geographic
    feature remains usable without inventing citizen-level coordinates.
    """
    if complaint.latitude is not None and complaint.longitude is not None:
        return float(complaint.latitude), float(complaint.longitude), 'GPS'
    state = (complaint.state or '').strip()
    district = (complaint.district or '').strip()
    coords = DISTRICT_COORDINATES.get((state, district))
    if coords is None:
        # Handle case differences in legacy records such as ``salem``.
        target = (state.casefold(), district.casefold())
        for (known_state, known_district), value in DISTRICT_COORDINATES.items():
            if (known_state.casefold(), known_district.casefold()) == target:
                coords = value
                break
    if coords is None:
        return None, None, None
    return coords[0], coords[1], 'District centre'

def _geo_options():
    """Load the bundled India state/UT -> district reference data and merge
    any additional state/district values already present in the project DB.
    """
    global _GEO_DATA_CACHE
    if _GEO_DATA_CACHE is None:
        path = os.path.join(app.root_path, 'data', 'india_states_districts.json')
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            _GEO_DATA_CACHE = {
                str(state).strip(): sorted({str(d).strip() for d in districts if str(d).strip()})
                for state, districts in raw.items()
            }
        except (OSError, ValueError, TypeError):
            _GEO_DATA_CACHE = {}
    options = {state: set(districts) for state, districts in _GEO_DATA_CACHE.items()}
    # Preserve/extend with real values already used by existing records.
    try:
        rows = db.session.query(CitizenRequest.state, CitizenRequest.district).filter(
            CitizenRequest.state.isnot(None),
            CitizenRequest.state != ''
        ).distinct().all()
        for state, district in rows:
            state = (state or '').strip()
            district = (district or '').strip()
            if not state:
                continue
            options.setdefault(state, set())
            if district:
                options[state].add(district)
    except Exception:
        pass
    return {state: sorted(values) for state, values in sorted(options.items(), key=lambda x: x[0].lower())}

@app.route('/api/geo/options')
@login_required
@role_required('Officer', 'Admin')
def api_geo_options():
    """Return the complete bundled India state/UT and district reference list."""
    return jsonify(_geo_options())

@app.route('/api/dashboard/stats')
@login_required
@role_required('Officer', 'Admin')
def api_dashboard_stats():
    """Return live stats from the exact same queue used by the officer dashboard."""
    user = get_current_user()
    data = _officer_dashboard_records(
        user,
        state_filter=request.args.get('state', '').strip(),
        district_filter=request.args.get('district', '').strip(),
        category_filter=request.args.get('category', '').strip(),
    )
    return jsonify({
        'total_requests': data['assigned'],
        'analyzed_requests': data['analyzed'],
        'pending_requests': data['pending'],
        'in_progress_requests': sum(1 for c in data['rows'] if (c.status or '') in ('In-Progress', 'In Progress')),
        'resolved_requests': data['resolved'],
        'high_critical_requests': data['high_critical'],
        'critical_requests': data['critical'],
        'overdue_requests': data['overdue'],
        'due_today_requests': data['due_today'],
        'average_resolution_hours': data['average_resolution_hours'],
        'category_distribution': data['category_distribution'],
        'urgency_distribution': data['urgency_distribution']
    })


@app.route('/api/hotspots')
@login_required
@role_required('Officer', 'Admin')
def api_hotspots():
    """API: Get hotspot data within the caller's authorized scope."""
    user = get_current_user()
    scoped = _scoped_complaints_query(user)
    hotspots_data = scoped.outerjoin(RequestAnalysis).with_entities(
        CitizenRequest.state,
        CitizenRequest.district,
        db.func.count(CitizenRequest.id).label('demand'),
        db.func.avg(RequestAnalysis.infrastructure_gap).label('gap')
    ).group_by(
        CitizenRequest.state,
        CitizenRequest.district
    ).all()
    
    hotspots = []
    for state, district, demand, gap in hotspots_data:
        gap_val = float(gap) if gap is not None else None
        location = Location.query.filter_by(state=state, district=district).first()
        hotspots.append({
            'state': state or 'Unknown',
            'district': district or 'Unknown',
            'demand': int(demand or 0),
            'gap': gap_val,
            'population': location.population if location and location.population else None,
            'projects': len(location.projects) if location else 0,
            'color': 'red' if gap_val is not None and gap_val >= 7 else 'orange' if gap_val is not None and gap_val >= 4 else 'gray'
        })
    
    return jsonify(hotspots)

@app.route('/api/requests', methods=['POST'])
@login_required
@role_required('Citizen')
def api_create_request():
    """API: Create citizen request with optional smart AI analysis."""
    data = request.get_json(silent=True) or {}

    try:
        latitude, longitude = _parse_coordinates(
            data.get('latitude'), data.get('longitude')
        )
        description = str(data.get('description', '') or '').strip()
        title = str(data.get('title', '') or 'Citizen Request').strip()
        category = str(data.get('category', '') or '').strip()
        state = str(data.get('state', '') or '').strip()
        district = str(data.get('district', '') or '').strip()
        local_area = str(data.get('local_area', '') or '').strip()

        if not all([category, description, state, district, local_area]):
            return jsonify({'success': False, 'error': 'Required complaint fields are missing.'}), 400
        if len(description) < 20:
            return jsonify({'success': False, 'error': 'Description must be at least 20 characters.'}), 400

        cr = CitizenRequest(
            user_id=session['user_id'],
            title=title,
            category=category,
            description=description,
            language=data.get('language', 'en'),
            state=state,
            district=district,
            local_area=local_area,
            latitude=latitude,
            longitude=longitude,
            complaint_datetime=_parse_complaint_datetime(data.get('complaint_datetime')),
            contact_phone=None if data.get('is_anonymous') else data.get('contact_phone'),
            contact_email=None if data.get('is_anonymous') else data.get('contact_email'),
            is_anonymous=bool(data.get('is_anonymous', False)),
            status='Submitted',
            due_at=datetime.utcnow() + timedelta(hours=DEFAULT_SLA_TARGETS['Low'])
        )
        cr.generate_request_id()
        db.session.add(cr)
        db.session.commit()

        try:
            analysis_data = AIService.perform_full_analysis({
                'title': title,
                'description': description,
                'category': category,
                'district': district,
                'state': state,
                'local_area': local_area,
                'language': data.get('language', 'en')
            })
            similar_count = CitizenRequest.query.filter(
                CitizenRequest.id != cr.id,
                CitizenRequest.district.ilike(district),
                CitizenRequest.category == category
            ).count()
            analysis = RequestAnalysis(
                request_id=cr.request_id,
                language_detected=analysis_data['language_detected'],
                category_classified=analysis_data['category_classified'],
                urgency_level=analysis_data['urgency_level'],
                infrastructure_gap=analysis_data['infrastructure_gap'],
                similar_requests_count=similar_count,
                population_impacted=analysis_data.get('population_impacted', 0),
                ai_recommendation=analysis_data['ai_recommendation'],
                explainability_factors=analysis_data['explainability_factors'],
                issue_type=analysis_data.get('issue_type'),
                priority=analysis_data.get('priority'),
                original_priority=analysis_data.get('priority'),
                recommended_department=analysis_data.get('recommended_department'),
                sentiment=analysis_data.get('sentiment'),
                confidence_score=analysis_data.get('confidence_score'),
                ai_provider=analysis_data.get('ai_provider', 'local'),
                human_review_required=True
            )
            db.session.add(analysis)
            cr.due_at = cr.created_at + timedelta(hours=_sla_target_hours(analysis.priority))
            cr.status = 'Analyzed'
            db.session.commit()
        except Exception as ai_error:
            db.session.rollback()
            cr = CitizenRequest.query.filter_by(request_id=cr.request_id).first()
            if cr:
                cr.status = 'Submitted'
                db.session.commit()
            app.logger.warning('API AI analysis failed for %s: %s', cr.request_id if cr else 'unknown', ai_error)

        _notify(
            cr.user_id,
            'complaint_submitted',
            'Complaint submitted',
            f'Your complaint {cr.request_id} was registered successfully.',
            cr.request_id
        )
        db.session.commit()
        _send_user_email(
            cr.user_id,
            f'Complaint submitted - {cr.request_id}',
            f'Your complaint {cr.request_id} was registered successfully. Current status: {cr.status}.'
        )
        duplicate_matches = _duplicate_matches(cr, exclude_id=cr.id)
        return jsonify({
            'success': True,
            'request_id': cr.request_id,
            'status': cr.status,
            'similar_complaints_count': len(duplicate_matches)
        }), 201
    except Exception as e:
        db.session.rollback()
        app.logger.exception('API complaint creation failed')
        return jsonify({'success': False, 'error': 'Unable to create the complaint.'}), 400


@app.route('/api/request/<request_id>')
@login_required
def api_get_request(request_id):
    """API: Get request details."""
    cr = CitizenRequest.query.filter_by(request_id=request_id).first()
    
    if not cr:
        return jsonify({'error': 'Not found'}), 404
    
    user = get_current_user()
    if not _complaint_can_view(cr, user):
        return jsonify({'error': 'Not found'}), 404

    analysis = RequestAnalysis.query.filter_by(request_id=request_id).first()
    can_view_private = True
    return jsonify({
        'request_id': cr.request_id,
        'title': cr.title,
        'category': cr.category,
        'description': cr.description,
        'state': cr.state,
        'district': cr.district,
        'local_area': cr.local_area,
        'latitude': cr.latitude,
        'longitude': cr.longitude,
        'status': cr.status,
        'assignment': _assignment_state(cr),
        'complaint_datetime': cr.complaint_datetime.isoformat() if cr.complaint_datetime else None,
        'is_anonymous': cr.is_anonymous,
        'contact_phone': cr.contact_phone if can_view_private and not cr.is_anonymous else None,
        'contact_email': cr.contact_email if can_view_private and not cr.is_anonymous else None,
        'media': {
            'photo': url_for('complaint_media', filename=cr.photo_filename) if cr.photo_filename else None,
            'video': url_for('complaint_media', filename=cr.video_filename) if cr.video_filename else None,
            'evidence': url_for('complaint_media', filename=cr.evidence_filename) if cr.evidence_filename else None
        },
        'analysis': {
            'category': analysis.category_classified if analysis else None,
            'issue_type': analysis.issue_type if analysis else None,
            'priority': _effective_priority(analysis) if analysis else None,
            'urgency': analysis.urgency_level if analysis else None,
            'department': analysis.recommended_department if analysis else None,
            'department_id': analysis.recommended_department_id if analysis else None,
            'transparency_note': 'AI-generated recommendation • Human review required.',
            'sentiment': analysis.sentiment if analysis else None,
            'confidence_score': analysis.confidence_score if analysis else None,
            'gap': analysis.infrastructure_gap if analysis else None,
            'provider': analysis.ai_provider if analysis else None
        } if analysis else None
    })

# ===============================================
# SECURE COMPLAINT MEDIA
# ===============================================

@app.route('/media/complaints/<path:filename>')
@login_required
def complaint_media(filename):
    """Serve complaint evidence only to the owner or authorized staff."""
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        abort(404)

    file_record = None
    for field in ('photo_filename', 'video_filename', 'evidence_filename', 'before_evidence_filename', 'after_evidence_filename'):
        file_record = CitizenRequest.query.filter(getattr(CitizenRequest, field) == safe_name).first()
        if file_record:
            break
    if not file_record:
        file_record = CitizenRequest.query.join(ComplaintTimeline, ComplaintTimeline.request_id == CitizenRequest.request_id).filter(ComplaintTimeline.evidence_filename == safe_name).first()
    if not file_record:
        abort(404)

    user = get_current_user()
    if not _complaint_can_view(file_record, user):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name)


# ===============================================
# ADVANCED ANALYTICS API
# ===============================================

@app.route('/api/dashboard/advanced-stats')
@login_required
@role_required('Officer', 'Admin')
def api_advanced_dashboard_stats():
    """Return advanced analytics calculated from real complaint data."""
    user = get_current_user()
    query = _scoped_complaints_query(user)
    if user.role == 'Admin':
        query = _filtered_requests_from_query()
    complaints = query.order_by(CitizenRequest.created_at.asc()).all()

    total = len(complaints)
    resolved = sum(1 for c in complaints if c.status.lower() == 'resolved')
    pending = sum(1 for c in complaints if c.status.lower() in {'submitted', 'pending'})
    in_progress = sum(1 for c in complaints if c.status.lower() in {'in-progress', 'in progress'})
    critical = sum(1 for c in complaints if c.analysis and _effective_priority(c.analysis) == 'Critical')

    category_distribution = {}
    department_distribution = {}
    ai_recommended_pending_distribution = {}
    assignment_state_counts = {
        'officially_assigned': 0,
        'ai_recommended_pending_assignment': 0,
        'truly_unassigned': 0
    }
    location_distribution = {}
    priority_distribution = {}
    monthly = {}

    resolution_minutes = []
    satisfaction_values = []

    for complaint in complaints:
        category = (
            complaint.analysis.category_classified
            if complaint.analysis and complaint.analysis.category_classified
            else complaint.category or 'Other'
        )
        category_distribution[category] = category_distribution.get(category, 0) + 1

        assignment = _assignment_state(complaint)
        if assignment['official_department']:
            department = assignment['official_department']
            department_distribution[department] = department_distribution.get(department, 0) + 1
            assignment_state_counts['officially_assigned'] += 1
        elif assignment['ai_recommended_department']:
            ai_department = assignment['ai_recommended_department']
            ai_recommended_pending_distribution[ai_department] = (
                ai_recommended_pending_distribution.get(ai_department, 0) + 1
            )
            assignment_state_counts['ai_recommended_pending_assignment'] += 1
        else:
            assignment_state_counts['truly_unassigned'] += 1

        location = complaint.local_area or complaint.district or complaint.state or 'Unknown'
        location_distribution[location] = location_distribution.get(location, 0) + 1

        priority = (
            _effective_priority(complaint.analysis)
            if complaint.analysis
            else 'Unclassified'
        )
        priority_distribution[priority] = priority_distribution.get(priority, 0) + 1

        month_key = complaint.created_at.strftime('%Y-%m') if complaint.created_at else 'Unknown'
        monthly[month_key] = monthly.get(month_key, 0) + 1

        minutes = _resolution_minutes(complaint.created_at, complaint.resolved_at)
        if minutes is not None:
            resolution_minutes.append(minutes)

        if complaint.feedback and complaint.feedback.rating is not None:
            satisfaction_values.append(float(complaint.feedback.rating))

    avg_resolution_hours = (
        round(sum(resolution_minutes) / len(resolution_minutes) / 60.0, 2)
        if resolution_minutes else None
    )

    return jsonify({
        'total_complaints': total,
        'resolved_complaints': resolved,
        'pending_complaints': pending,
        'in_progress_complaints': in_progress,
        'critical_complaints': critical,
        'high_critical_complaints': sum(
            1 for c in complaints
            if _effective_priority(c.analysis) in ('High', 'Critical')
        ),
        'overdue_complaints': sum(
            1 for c in complaints
            if c.status != 'Resolved' and c.due_at and c.due_at < datetime.utcnow()
        ),
        'resolution_rate': round((resolved / total) * 100, 2) if total else 0,
        'average_resolution_hours': avg_resolution_hours,
        'category_distribution': dict(sorted(category_distribution.items(), key=lambda x: x[1], reverse=True)),
        'department_distribution': dict(sorted(department_distribution.items(), key=lambda x: x[1], reverse=True)),
        'ai_recommended_pending_distribution': dict(sorted(ai_recommended_pending_distribution.items(), key=lambda x: x[1], reverse=True)),
        'assignment_state_counts': assignment_state_counts,
        'location_distribution': dict(sorted(location_distribution.items(), key=lambda x: x[1], reverse=True)[:15]),
        'monthly_distribution': dict(sorted(monthly.items())),
        'priority_distribution': priority_distribution,
        'citizen_satisfaction': (
            round(sum(satisfaction_values) / len(satisfaction_values), 2)
            if satisfaction_values else None
        )
    })


# ===============================================
# CIVIC ISSUE MAP API
# ===============================================

@app.route('/api/complaints/map')
@login_required
@role_required('Officer', 'Admin')
def api_complaints_map():
    """Return map-safe complaint data; citizen contact information is excluded."""
    user = get_current_user()
    query = _scoped_complaints_query(user)
    if user.role == 'Admin':
        query = _filtered_requests_from_query()
    state = request.args.get('state', '').strip()
    category = request.args.get('category', '').strip()
    priority = request.args.get('priority', '').strip()
    status = request.args.get('status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    district = request.args.get('district', '').strip()
    if state: query = query.filter(CitizenRequest.state == state)
    if district: query = query.filter(CitizenRequest.district == district)
    if status: query = query.filter(CitizenRequest.status == status)
    if start_date:
        try: query = query.filter(CitizenRequest.created_at >= datetime.fromisoformat(start_date))
        except ValueError: pass
    if end_date:
        try:
            end_value=datetime.fromisoformat(end_date) + timedelta(days=1)
            query=query.filter(CitizenRequest.created_at < end_value)
        except ValueError: pass
    complaints = query.order_by(CitizenRequest.created_at.desc()).all()

    result = []
    for complaint in complaints:
        analysis = complaint.analysis
        effective_priority = _effective_priority(analysis)
        effective_category = (analysis.category_classified if analysis and analysis.category_classified else complaint.category) or 'Other'
        if category and effective_category.lower() != category.lower():
            continue
        if priority and effective_priority != priority:
            continue
        latitude, longitude, location_precision = _complaint_map_coordinates(complaint)
        # Keep unmappable complaints out of the map, but do not let missing GPS
        # make the entire Officer map appear empty.
        if latitude is None or longitude is None:
            continue
        result.append({
            'request_id': complaint.request_id,
            'title': complaint.title or 'Citizen Request',
            'category': effective_category,
            'priority': effective_priority,
            'urgency': analysis.urgency_level if analysis else None,
            'status': complaint.status,
            'latitude': latitude,
            'longitude': longitude,
            'location_precision': location_precision,
            'district': complaint.district,
            'local_area': complaint.local_area,
            'created_at': complaint.created_at.isoformat() if complaint.created_at else None
        })
    return jsonify(result)


# ===============================================
# REQUEST STATUS API
# ===============================================


@app.route('/api/request/<request_id>/timeline')
@login_required
def api_request_timeline(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint or not _complaint_can_view(complaint, get_current_user()):
        return jsonify({'error': 'Not found or unauthorized.'}), 404
    events = ComplaintTimeline.query.filter_by(
        request_id=request_id
    ).order_by(ComplaintTimeline.created_at.asc()).all()
    user = get_current_user()
    return jsonify([{
        'event_type': e.event_type,
        'description': e.description,
        'actor': e.actor.username if (e.actor and user.role in ('Officer', 'Admin')) else None,
        'role': e.actor_role if user.role in ('Officer', 'Admin') else None,
        'evidence': url_for('complaint_media', filename=e.evidence_filename) if e.evidence_filename else None,
        'created_at': e.created_at.isoformat() if e.created_at else None
    } for e in events])


@app.route('/api/request/<request_id>/assign', methods=['PUT'])
@login_required
@role_required('Admin')
def assign_request(request_id):
    """Persist official department/officer assignment without overwriting AI analysis."""
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found.'}), 404

    data = request.get_json(silent=True) or {}
    department_id = data.get('department_id')
    department_name = str(data.get('department', '')).strip() or None
    officer_value = data.get('officer_id')
    due_at = str(data.get('due_at', '')).strip()

    department = None
    if department_id not in (None, ''):
        try:
            department = Department.query.filter_by(
                id=int(department_id), is_active=True
            ).first()
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid department ID.'}), 400
        if not department:
            return jsonify({'success': False, 'error': 'Please select an active department.'}), 400
    elif department_name:
        department = _department_for_name(department_name, active_only=True)
        if not department:
            return jsonify({'success': False, 'error': 'Please select an active department.'}), 400

    officer = None
    officer_id = None
    if officer_value not in (None, ''):
        try:
            officer_id = int(officer_value)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid officer ID.'}), 400
        officer = User.query.filter_by(id=officer_id, role='Officer').first()
        if not officer:
            return jsonify({'success': False, 'error': 'Officer not found.'}), 400

        # An officer assignment is always tied to that officer's department.
        if not department:
            if officer.department_id:
                department = db.session.get(Department, officer.department_id)
                if department and not department.is_active:
                    return jsonify({'success': False, 'error': 'The officer belongs to an inactive department.'}), 400
            else:
                return jsonify({'success': False, 'error': 'Assign the officer to a department before assigning a request.'}), 400
        elif officer.department_id != department.id:
            return jsonify({
                'success': False,
                'error': 'The selected officer does not belong to the selected department.'
            }), 400

    parsed_due = None
    if due_at:
        try:
            parsed_due = datetime.fromisoformat(due_at)
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid due date/time.'}), 400

    actor = get_current_user()
    previous_officer_id = complaint.assigned_officer_id
    previous_department = _official_department(complaint)

    complaint.assigned_department_id = department.id if department else None
    complaint.assigned_department = department.name if department else None
    complaint.assigned_officer_id = officer_id
    complaint.assigned_at = datetime.utcnow() if officer_id else (
        complaint.assigned_at if department else None
    )
    if parsed_due:
        complaint.due_at = parsed_due
    elif complaint.due_at is None:
        _ensure_sla_due(complaint)
    complaint.updated_at = datetime.utcnow()

    if previous_department and (not department or previous_department.id != department.id):
        _add_timeline(
            complaint, 'Department reassigned',
            f'Official department changed from {previous_department.name} to {department.name if department else "Pending"}.',
            actor
        )
    elif department and not previous_department:
        _add_timeline(complaint, 'Department assigned', f'Official department assigned: {department.name}.', actor)

    if officer:
        event_type = 'Complaint reassigned' if previous_officer_id and previous_officer_id != officer.id else 'Officer assigned'
        _add_timeline(complaint, event_type, f'Complaint assigned to officer {officer.username}.', actor)
        _notify(
            officer.id, 'complaint_assigned', 'New complaint assigned',
            f'Complaint {complaint.request_id} has been assigned to you.',
            complaint.request_id
        )
        if complaint.analysis and _effective_priority(complaint.analysis) in ('Critical', 'High'):
            _notify(
                officer.id, 'priority_assignment', f'{_effective_priority(complaint.analysis)} priority complaint',
                f'{complaint.request_id} is a {_effective_priority(complaint.analysis).lower()} priority assignment.',
                complaint.request_id
            )
    elif previous_officer_id:
        _add_timeline(complaint, 'Officer unassigned', 'The request is no longer assigned to an individual officer.', actor)
        _notify(
            previous_officer_id, 'complaint_unassigned', 'Complaint unassigned',
            f'Complaint {complaint.request_id} is no longer assigned to you.',
            complaint.request_id
        )

    _record_audit(
        actor,
        'Complaint reassignment',
        'CitizenRequest',
        complaint.request_id,
        {
            'department': department.name if department else None,
            'department_id': department.id if department else None,
            'officer_id': officer_id,
            'previous_officer_id': previous_officer_id,
            'previous_department_id': previous_department.id if previous_department else None
        }
    )
    db.session.commit()

    if department and (not previous_department or previous_department.id != department.id):
        _notify(
            complaint.user_id, 'department_assigned', 'Department assigned',
            f'{complaint.request_id} has been assigned to {department.name}.',
            complaint.request_id
        )
    if officer:
        _notify(
            complaint.user_id, 'officer_assigned', 'Officer assigned',
            f'An officer has been assigned to {complaint.request_id}.',
            complaint.request_id
        )
        _send_user_email(
            officer.id,
            f'Complaint assigned - {complaint.request_id}',
            f'Complaint {complaint.request_id} has been assigned to you.'
        )
    if previous_officer_id and previous_officer_id != officer_id:
        _send_user_email(
            previous_officer_id,
            f'Complaint reassigned - {complaint.request_id}',
            f'Complaint {complaint.request_id} has been reassigned to another officer.'
        )

    assignment = _assignment_state(complaint)
    return jsonify({'success': True, 'assignment': assignment})


@app.route('/api/request/<request_id>/update', methods=['POST'])
@login_required
@role_required('Officer', 'Admin')
def officer_request_update(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found.'}), 404

    actor = get_current_user()
    if not _complaint_can_update(complaint, actor):
        return jsonify({'success': False, 'error': 'You are not authorized to update this complaint.'}), 403
    remarks = request.form.get('remarks', '').strip()
    new_status = request.form.get('status', '').strip()
    evidence = request.files.get('evidence')
    before_evidence = request.files.get('before_evidence')
    after_evidence = request.files.get('after_evidence')

    if not remarks and not new_status and not evidence and not before_evidence and not after_evidence:
        return jsonify({'success': False, 'error': 'Add a status, remark, or evidence.'}), 400

    filename = None
    before_filename = None
    after_filename = None
    try:
        if evidence and evidence.filename:
            filename = _save_upload(
                evidence,
                app.config['ALLOWED_EVIDENCE_EXTENSIONS'],
                app.config['MAX_EVIDENCE_SIZE']
            )
        if before_evidence and before_evidence.filename:
            before_filename = _save_upload(before_evidence, app.config['ALLOWED_BEFORE_AFTER_EXTENSIONS'], app.config['MAX_BEFORE_AFTER_SIZE'])
        if after_evidence and after_evidence.filename:
            after_filename = _save_upload(after_evidence, app.config['ALLOWED_BEFORE_AFTER_EXTENSIONS'], app.config['MAX_BEFORE_AFTER_SIZE'])

        if new_status:
            allowed = {'Submitted', 'Analyzed', 'In-Progress', 'Resolved', 'Pending', 'Reopened'}
            if new_status not in allowed:
                raise ValueError('Invalid status.')
            complaint.status = new_status
            complaint.resolved_at = datetime.utcnow() if new_status == 'Resolved' else complaint.resolved_at
            complaint.updated_at = datetime.utcnow()
            _add_timeline(
                complaint,
                'Resolution' if new_status == 'Resolved' else 'Status changed',
                f'Status changed to {new_status}.',
                actor
            )

            _notify(
                complaint.user_id, 'status_changed', 'Complaint status updated',
                f'Complaint {complaint.request_id} is now {new_status}.',
                complaint.request_id
            )
            if new_status == 'Resolved':
                _notify(
                    complaint.user_id, 'feedback_requested', 'Feedback requested',
                    f'Complaint {complaint.request_id} has been resolved. Please share your feedback.',
                    complaint.request_id
                )

        if remarks:
            complaint.officer_remarks = remarks
            _add_timeline(complaint, 'Officer update', remarks, actor)

        if filename:
            _add_timeline(complaint, 'Evidence uploaded', 'New evidence was uploaded by an officer.', actor, filename)
        if before_filename:
            complaint.before_evidence_filename = before_filename
            _add_timeline(complaint, 'Before-resolution evidence uploaded', 'Before-resolution evidence was uploaded by an officer.', actor, before_filename)
        if after_filename:
            complaint.after_evidence_filename = after_filename
            _add_timeline(complaint, 'After-resolution evidence uploaded', 'After-resolution evidence was uploaded by an officer.', actor, after_filename)

        if new_status:
            _record_audit(
                actor,
                'Status change',
                'CitizenRequest',
                complaint.request_id,
                {'new_status': new_status, 'remarks_present': bool(remarks)}
            )
        db.session.commit()
        if new_status:
            _send_user_email(
                complaint.user_id,
                f'Complaint status updated - {complaint.request_id}',
                f'Your complaint {complaint.request_id} is now {new_status}.'
            )
            if new_status == 'Resolved':
                _send_user_email(
                    complaint.user_id,
                    f'Feedback requested - {complaint.request_id}',
                    f'Your complaint {complaint.request_id} has been resolved. Please sign in to CivicPulse AI to share your feedback.'
                )
        return jsonify({'success': True, 'status': complaint.status})
    except ValueError as exc:
        db.session.rollback()
        for saved in (filename, before_filename, after_filename):
            if saved: _delete_upload(saved)
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        for saved in (filename, before_filename, after_filename):
            if saved: _delete_upload(saved)
        return jsonify({'success': False, 'error': 'Unable to save update.'}), 500


@app.route('/api/request/<request_id>/priority', methods=['PUT'])
@login_required
@role_required('Officer', 'Admin')
def override_request_priority(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint or not complaint.analysis:
        return jsonify({'success': False, 'error': 'Complaint analysis not found.'}), 404
    actor = get_current_user()
    if not _complaint_can_update(complaint, actor):
        return jsonify({'success': False, 'error': 'You are not authorized to update this complaint.'}), 403
    data = request.get_json(silent=True) or {}
    priority = str(data.get('priority', '')).strip()
    if priority not in {'Low', 'Medium', 'High', 'Critical'}:
        return jsonify({'success': False, 'error': 'Invalid priority.'}), 400
    previous_priority = _effective_priority(complaint.analysis)
    previous_auto_due = (
        complaint.due_at is not None and complaint.created_at is not None and
        complaint.due_at == complaint.created_at + timedelta(hours=_sla_target_hours(previous_priority))
    )
    complaint.analysis.priority_override = priority
    if previous_auto_due:
        complaint.due_at = complaint.created_at + timedelta(hours=_sla_target_hours(priority))
    _add_timeline(complaint, 'Priority override', f'Priority manually set to {priority}. Original classification: {complaint.analysis.original_priority or complaint.analysis.priority}.', actor)
    _record_audit(
        actor,
        'Priority override',
        'CitizenRequest',
        complaint.request_id,
        {'old_priority': previous_priority, 'new_priority': priority}
    )
    db.session.commit()
    return jsonify({'success': True, 'priority': priority, 'original_priority': complaint.analysis.original_priority or complaint.analysis.priority})

@app.route('/api/request/<request_id>/status', methods=['PUT'])
@login_required
@role_required('Officer', 'Admin')
def update_request_status(request_id):
    """Update complaint workflow status for analytics and officer operations."""
    data = request.get_json(silent=True) or {}
    status = str(data.get('status', '')).strip()
    allowed = {'Submitted', 'Analyzed', 'In-Progress', 'Resolved', 'Pending', 'Reopened'}
    if status not in allowed:
        return jsonify({
            'success': False,
            'error': f'Status must be one of: {", ".join(sorted(allowed))}.'
        }), 400

    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    if not complaint:
        return jsonify({'success': False, 'error': 'Complaint not found.'}), 404

    actor = get_current_user()
    if not _complaint_can_update(complaint, actor):
        return jsonify({'success': False, 'error': 'You are not authorized to update this complaint.'}), 403
    old_status = complaint.status
    complaint.status = status
    complaint.updated_at = datetime.utcnow()
    complaint.resolved_at = datetime.utcnow() if status == 'Resolved' else complaint.resolved_at
    actor = get_current_user()
    if old_status != status:
        event_name = 'Resolution' if status == 'Resolved' else 'Status changed'
        _add_timeline(complaint, event_name, f'Status changed from {old_status} to {status}.', actor)
        _notify(
            complaint.user_id, 'status_changed', 'Complaint status updated',
            f'Complaint {complaint.request_id} is now {status}.',
            complaint.request_id
        )
        if status == 'Resolved':
            _notify(
                complaint.user_id, 'feedback_requested', 'Feedback requested',
                f'Complaint {complaint.request_id} has been resolved. Please share your feedback.',
                complaint.request_id
            )
    if old_status != status:
        _record_audit(
            actor,
            'Status change',
            'CitizenRequest',
            complaint.request_id,
            {'old_status': old_status, 'new_status': status}
        )
    db.session.commit()
    if old_status != status:
        _send_user_email(
            complaint.user_id,
            f'Complaint status updated - {complaint.request_id}',
            f'Your complaint {complaint.request_id} is now {status}.'
        )
        if status == 'Resolved':
            _send_user_email(
                complaint.user_id,
                f'Feedback requested - {complaint.request_id}',
                f'Your complaint {complaint.request_id} has been resolved. Please sign in to CivicPulse AI to share your feedback.'
            )
    return jsonify({
        'success': True,
        'request_id': request_id,
        'status': complaint.status
    })


# ===============================================
# HOTSPOT DATA API
# ===============================================

@app.route('/api/civic-hotspots')
@login_required
@role_required('Officer', 'Admin')
def api_civic_hotspots():
    """Detect complaint hotspots using actual local-area complaint counts."""
    user = get_current_user()
    complaints = _scoped_complaints_query(user).all()
    state_filter=request.args.get('state','').strip()
    category_filter=request.args.get('category','').strip().lower()
    priority_filter=request.args.get('priority','').strip()
    status_filter=request.args.get('status','').strip()
    start_date=request.args.get('start_date','').strip()
    end_date=request.args.get('end_date','').strip()
    start_dt=end_dt=None
    try: start_dt=datetime.fromisoformat(start_date) if start_date else None
    except ValueError: pass
    try: end_dt=(datetime.fromisoformat(end_date)+timedelta(days=1)) if end_date else None
    except ValueError: pass
    filtered=[]
    for c in complaints:
        cat=(c.analysis.category_classified if c.analysis and c.analysis.category_classified else c.category or 'Other')
        pri=_effective_priority(c.analysis)
        if state_filter and c.state != state_filter: continue
        if category_filter and cat.lower() != category_filter: continue
        if priority_filter and pri != priority_filter: continue
        if status_filter and c.status != status_filter: continue
        if start_dt and c.created_at and c.created_at < start_dt: continue
        if end_dt and c.created_at and c.created_at >= end_dt: continue
        filtered.append(c)
    complaints=filtered
    grouped = {}

    for complaint in complaints:
        key = (
            complaint.state or 'Unknown',
            complaint.district or 'Unknown',
            complaint.local_area or 'Unknown'
        )
        bucket = grouped.setdefault(key, {
            'state': key[0],
            'district': key[1],
            'area': key[2],
            'count': 0,
            'categories': {},
            'priorities': {},
            'recent': [],
            'affected_population': 0
        })
        bucket['count'] += 1

        category = (
            complaint.analysis.category_classified
            if complaint.analysis and complaint.analysis.category_classified
            else complaint.category or 'Other'
        )
        bucket['categories'][category] = bucket['categories'].get(category, 0) + 1

        priority = (
            _effective_priority(complaint.analysis)
            if complaint.analysis
            else 'Unclassified'
        )
        bucket['priorities'][priority] = bucket['priorities'].get(priority, 0) + 1

        if complaint.created_at:
            bucket['recent'].append(complaint.created_at)
        if complaint.analysis and complaint.analysis.population_impacted:
            bucket['affected_population'] += int(complaint.analysis.population_impacted or 0)

    buckets = list(grouped.values())
    counts = [bucket['count'] for bucket in buckets]
    average_count = mean(counts) if counts else 0
    count_std = pstdev(counts) if len(counts) > 1 else 0
    high_threshold = average_count + count_std

    results = []
    for bucket in buckets:
        dates = sorted(bucket['recent'])
        recent_cutoff = datetime.utcnow() - timedelta(days=30)
        previous_cutoff = datetime.utcnow() - timedelta(days=60)
        recent_count = sum(1 for d in dates if d >= recent_cutoff)
        previous_count = sum(1 for d in dates if previous_cutoff <= d < recent_cutoff)

        if recent_count > previous_count:
            trend = 'Increasing'
        elif recent_count < previous_count:
            trend = 'Decreasing'
        else:
            trend = 'Stable'

        severity = 'Low'
        if bucket['count'] >= max(2, high_threshold):
            severity = 'High'
        elif bucket['count'] >= max(1, average_count):
            severity = 'Moderate'

        results.append({
            'state': bucket['state'],
            'district': bucket['district'],
            'area': bucket['area'],
            'count': bucket['count'],
            'main_issue': max(bucket['categories'], key=bucket['categories'].get) if bucket['categories'] else 'Unknown',
            'category_distribution': bucket['categories'],
            'priority_distribution': bucket['priorities'],
            'recent_count': recent_count,
            'previous_count': previous_count,
            'trend': trend,
            'severity': severity,
            'affected_population': bucket['affected_population'],
            'existing_projects': sum(
                len(loc.projects) for loc in Location.query.filter_by(
                    state=bucket['state'], district=bucket['district']
                ).all()
            ),
            'emerging_issue': recent_count > previous_count and previous_count > 0
        })

    results.sort(key=lambda x: x['count'], reverse=True)
    return jsonify(results[:20])



# ===============================================
# CIVICPULSE AI - EXTENDED INTELLIGENCE APIs
# ===============================================

@app.route('/api/language-detect', methods=['POST'])
@login_required
@role_required('Citizen')
def api_language_detect():
    data = request.get_json(silent=True) or {}
    text_value = str(data.get('text', '')).strip()
    selected = str(data.get('language', 'en')).strip()
    if len(text_value) < 2:
        return jsonify({'success': False, 'error': 'Enter some text to detect the language.'}), 400
    detected, confidence = _detect_language_metadata(text_value, selected)
    return jsonify({
        'success': True,
        'detected_language': detected,
        'detected_language_name': _language_label(detected),
        'confidence': confidence,
        'confidence_label': _confidence_band(confidence)['label'],
        'original_text': text_value
    })


@app.route('/api/request/<request_id>/review', methods=['POST'])
@login_required
@role_required('Officer', 'Admin')
def review_request_analysis(request_id):
    complaint = CitizenRequest.query.filter_by(request_id=request_id).first()
    actor = get_current_user()
    if not complaint or not complaint.analysis:
        return jsonify({'success': False, 'error': 'Request analysis not found.'}), 404
    if not _complaint_can_update(complaint, actor):
        return jsonify({'success': False, 'error': 'You are not authorized to review this request.'}), 403
    data = request.get_json(silent=True) or {}
    decision = str(data.get('decision', '')).strip()
    modification = str(data.get('modification', '')).strip()
    allowed = {'Accepted', 'Modified', 'Rejected'}
    if decision not in allowed:
        return jsonify({'success': False, 'error': 'Decision must be Accepted, Modified, or Rejected.'}), 400
    if decision == 'Modified' and not modification:
        return jsonify({'success': False, 'error': 'Please describe the officer modification.'}), 400
    analysis = complaint.analysis
    analysis.review_status = decision
    analysis.officer_decision = decision
    analysis.officer_modification = modification or None
    analysis.reviewer_id = actor.id
    analysis.reviewed_by = actor.username
    analysis.reviewed_at = datetime.utcnow()
    analysis.human_review_required = False
    _add_timeline(
        complaint, 'Officer review',
        f'Officer review completed: {decision}.' +
        (f' Modification: {modification}' if modification else ''),
        actor
    )
    _record_audit(actor, 'AI analysis review', 'CitizenRequest', complaint.request_id, {
        'decision': decision, 'modified': bool(modification)
    })
    db.session.commit()
    return jsonify({'success': True, 'review_status': analysis.review_status})


@app.route('/officer/area-intelligence')
@login_required
@role_required('Officer', 'Admin')
def area_intelligence():
    user = get_current_user()
    areas = db.session.query(CitizenRequest.local_area).filter(
        CitizenRequest.local_area.isnot(None),
        CitizenRequest.local_area != ''
    )
    if user.role == 'Officer':
        areas = areas.filter(CitizenRequest.assigned_officer_id == user.id)
    area_list = sorted({x[0] for x in areas.all() if x[0]})
    selected = request.args.get('area', '').strip()
    data = _area_intelligence(user, selected) if selected else None
    return render_template('area_intelligence.html', areas=area_list, selected=selected, data=data)


@app.route('/api/analytics/trends')
@login_required
@role_required('Officer', 'Admin')
def api_analytics_trends():
    user = get_current_user()
    period = request.args.get('period', '30d')
    days = _parse_period_days(period)
    end = datetime.utcnow() + timedelta(days=1)
    start = datetime.utcnow() - timedelta(days=days)
    complaints = _analytics_query(
        user, start=start, end=end,
        category=request.args.get('category', '').strip(),
        location=request.args.get('location', '').strip(),
        department=request.args.get('department', '').strip(),
        priority=request.args.get('priority', '').strip(),
        status=request.args.get('status', '').strip()
    ).order_by(CitizenRequest.created_at.asc()).all()
    series = _trend_series(complaints, days)
    return jsonify({
        'period': period,
        'days': days,
        'total': len(complaints),
        'series': series,
        'filters': {
            'category': request.args.get('category', ''),
            'location': request.args.get('location', ''),
            'department': request.args.get('department', ''),
            'priority': request.args.get('priority', ''),
            'status': request.args.get('status', '')
        }
    })


@app.route('/api/analytics/emerging-issues')
@login_required
@role_required('Officer', 'Admin')
def api_emerging_issues():
    return jsonify({
        'period': '30 days vs preceding 30 days',
        'issues': _emerging_issues(get_current_user())
    })


@app.route('/api/analytics/infrastructure-gaps')
@login_required
@role_required('Officer', 'Admin')
def api_infrastructure_gaps():
    user = get_current_user()
    complaints = _scoped_complaints_query(user).all()
    groups = {}
    for c in complaints:
        key = f'{c.state} / {c.district}'
        item = groups.setdefault(key, {
            'area': key, 'request_count': 0, 'high_priority': 0,
            'affected_population': 0, 'existing_projects': 0,
            'infrastructure_gap_score': None, 'categories': Counter()
        })
        item['request_count'] += 1
        if _effective_priority(c.analysis) in ('High', 'Critical'):
            item['high_priority'] += 1
        if c.analysis and c.analysis.population_impacted:
            item['affected_population'] += int(c.analysis.population_impacted or 0)
        item['categories'][c.analysis.category_classified if c.analysis else c.category or 'Other'] += 1
    for key, item in groups.items():
        state, district = key.split(' / ', 1)
        loc = Location.query.filter_by(state=state, district=district).first()
        if loc:
            item['existing_projects'] = len(loc.projects)
            item['infrastructure_gap_score'] = loc.infrastructure_gap_score
        # Only call it a potential attention area when actual request demand exists.
        item['potential_attention'] = item['request_count'] > 0
        item['categories'] = item['categories'].most_common(5)
    return jsonify(sorted(groups.values(), key=lambda x: (x['high_priority'], x['request_count']), reverse=True))


@app.route('/api/area-intelligence')
@login_required
@role_required('Officer', 'Admin')
def api_area_intelligence():
    area = request.args.get('area', '').strip()
    if not area:
        return jsonify({'success': False, 'error': 'Area is required.'}), 400
    return jsonify({'success': True, 'data': _area_intelligence(get_current_user(), area)})


@app.route('/api/sla/overview')
@login_required
@role_required('Officer', 'Admin')
def api_sla_overview():
    user = get_current_user()
    _notify_deadlines()
    complaints = _scoped_complaints_query(user).all()
    now = datetime.utcnow()
    counts = Counter()
    rows = []
    for c in complaints:
        info = _sla_status(c, now)
        if c.status == 'Resolved':
            label = 'resolved'
        elif info['status'] == 'Overdue':
            label = 'overdue'
        elif info.get('remaining_seconds') is not None and info['remaining_seconds'] <= 24 * 3600:
            label = 'due_soon'
        else:
            label = 'within_sla'
        counts[label] += 1
        rows.append({
            'request_id': c.request_id,
            'sla_target_hours': _sla_target_hours(_effective_priority_for_complaint(c)),
            'due_at': c.due_at.isoformat() if c.due_at else None,
            'elapsed_hours': round(max(0, (now - c.created_at).total_seconds()) / 3600, 2) if c.created_at else None,
            'remaining_hours': round(info['remaining_seconds'] / 3600, 2) if info['remaining_seconds'] is not None else None,
            'sla_status': label,
            'status': c.status
        })
    return jsonify({'counts': counts, 'requests': rows})



# ===============================================
# HACK2SKILL TRUST / OUTCOME / DEMO ROUTES
# ===============================================

@app.route('/trust-center')
def trust_center():
    return render_template('trust_center.html')

@app.route('/admin/data-governance')
@login_required
@role_required('Admin')
def data_governance():
    controls = [
        ('Role-based access', True, 'Citizen, Officer and Admin protected routes are enforced server-side.'),
        ('Password protection', True, 'Passwords are stored as hashes, never plaintext.'),
        ('Audit logging', True, 'Administrative and workflow actions are recorded in the audit log.'),
        ('Sensitive-data restrictions', True, 'Public/aggregate analytics exclude contact information.'),
        ('Upload validation', True, 'Evidence uploads use extension, size, MIME and signature checks.'),
        ('AI review requirement', True, 'AI analysis records require human review before final acceptance.'),
        ('Data access controls', True, 'Complaint visibility is scoped by authenticated role and ownership.')
    ]
    return render_template('data_governance.html', controls=controls)

@app.route('/outcomes')
@login_required
@role_required('Officer', 'Admin')
def outcomes():
    return render_template('outcome_analytics.html')

@app.route('/demo-center')
@login_required
def demo_center():
    journeys = [
        ('Citizen Journey', url_for('citizen_request'), 'Submit a multilingual or voice-assisted civic request.'),
        ('AI Analysis', url_for('citizen_analysis'), 'Inspect explainable classification, confidence and human-review state.'),
        ('Demand Intelligence', url_for('officer_demand_analysis'), 'Explore category and time-based demand analytics.'),
        ('Hotspot Intelligence', url_for('officer_hotspots'), 'Explore privacy-preserving geographic demand patterns.'),
        ('Government Action', url_for('officer_complaints'), 'Review, assign and update real requests.'),
        ('Resolution', url_for('officer_complaints'), 'Follow evidence, SLA and resolution workflow.'),
        ('Citizen Feedback', url_for('complaint_tracking'), 'Track a request and submit post-resolution feedback.')
    ]
    return render_template('demo_center.html', journeys=journeys)

@app.route('/system-status')
def system_status():
    return render_template('system_status.html', checks=_status_snapshot())

@app.route('/api/analytics/outcomes')
@login_required
@role_required('Officer', 'Admin')
def api_outcome_analytics():
    user=get_current_user()
    days=_parse_period_days(request.args.get('period','365d'))
    start=datetime.utcnow()-timedelta(days=days)
    complaints=_analytics_query(
        user,start=start,end=datetime.utcnow()+timedelta(days=1),
        category=request.args.get('category','').strip(),
        location=request.args.get('location','').strip(),
        department=request.args.get('department','').strip()
    ).all()
    return jsonify(_outcome_metrics(complaints))

@app.route('/api/analytics/categories')
@login_required
@role_required('Officer', 'Admin')
def api_category_analytics():
    user=get_current_user()
    complaints=_scoped_complaints_query(user).all()
    return jsonify(_category_intelligence(user, complaints))

@app.route('/api/analytics/project-comparison')
@login_required
@role_required('Officer', 'Admin')
def api_project_comparison():
    return jsonify(_project_comparison(
        get_current_user(),
        request.args.get('area','').strip(),
        request.args.get('category','').strip()
    ))

@app.route('/api/system-status')
def api_system_status():
    checks=_status_snapshot()
    return jsonify({'operational': all(checks.values()), 'modules': checks})


# ===============================================
# ERROR HANDLERS
# ===============================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# ===============================================
# CONTEXT PROCESSORS
# ===============================================

@app.context_processor
def inject_user():
    return dict(current_user=get_current_user())


# ===============================================
# HACK2SKILL FEATURES 39-44 + SEARCH/QUALITY EXTENSIONS
# ===============================================

def _quality_snapshot(user):
    """Compute transparent data-quality indicators from the authorized dataset."""
    query = _scoped_complaints_query(user)
    total = query.count()
    if total == 0:
        return {
            'records': 0, 'missing_location': 0, 'missing_category': 0,
            'duplicate_indicators': 0, 'incomplete': 0, 'invalid_uploads': 0,
            'date_min': None, 'date_max': None, 'coverage_note': 'No request data available.'
        }
    rows = query.all()
    missing_location = sum(1 for c in rows if not (c.state and c.district and c.local_area))
    missing_category = sum(1 for c in rows if not c.category)
    incomplete = sum(1 for c in rows if not (c.description and c.created_at))
    # Duplicate indicators are calculated from existing duplicate methodology,
    # but never automatically delete or alter records.
    duplicate_ids = set()
    for c in rows[:250]:
        try:
            matches = _duplicate_matches(c, exclude_id=c.id, days=365, limit=3)
            if matches:
                duplicate_ids.add(c.id)
        except Exception:
            pass
    invalid_uploads = 0
    for c in rows:
        for filename in (c.photo_filename, c.video_filename, c.evidence_filename,
                         c.before_evidence_filename, c.after_evidence_filename):
            if filename and (not secure_filename(filename) or os.path.basename(filename) != filename):
                invalid_uploads += 1
    dates = [c.created_at for c in rows if c.created_at]
    return {
        'records': total,
        'missing_location': missing_location,
        'missing_location_pct': round(missing_location / total * 100, 1),
        'missing_category': missing_category,
        'missing_category_pct': round(missing_category / total * 100, 1),
        'duplicate_indicators': len(duplicate_ids),
        'incomplete': incomplete,
        'invalid_uploads': invalid_uploads,
        'date_min': min(dates).strftime('%Y-%m-%d') if dates else None,
        'date_max': max(dates).strftime('%Y-%m-%d') if dates else None,
        'last_updated': max(dates).strftime('%Y-%m-%d %H:%M UTC') if dates else None,
        'coverage_note': (
            'Analytics are based only on records currently stored in CivicPulse AI.'
            if dates else 'Data coverage limitation'
        )
    }


def _development_impact_metrics(complaints):
    total = len(complaints)
    resolved = sum(1 for c in complaints if c.status == 'Resolved')
    resolution_times = [
        _resolution_minutes(c.created_at, c.resolved_at) / 60
        for c in complaints if c.status == 'Resolved' and _resolution_minutes(c.created_at, c.resolved_at) is not None
    ]
    feedback = [c.feedback for c in complaints if c.feedback]
    ratings = [f.rating for f in feedback if f.rating is not None]
    sla_known = [_sla_status(c).get('compliant') for c in complaints if c.due_at]
    sla_known = [x for x in sla_known if x is not None]
    high_addressed = sum(
        1 for c in complaints
        if c.status == 'Resolved' and _effective_priority(c.analysis) in ('High', 'Critical')
    )
    reopened = sum(1 for c in complaints if c.feedback and c.feedback.reopened_requested)
    hotspots = Counter((c.local_area or c.district or 'Unknown') for c in complaints)
    return {
        'requests_received': total,
        'requests_resolved': resolved,
        'average_resolution_hours': round(mean(resolution_times), 2) if resolution_times else None,
        'sla_compliance': round(sum(1 for x in sla_known if x) / len(sla_known) * 100, 1) if sla_known else None,
        'high_priority_issues_addressed': high_addressed,
        'citizen_satisfaction': round(mean(ratings), 2) if ratings else None,
        'repeat_issue_rate': round(reopened / total * 100, 1) if total else None,
        'active_hotspots': hotspots.most_common(8),
        'measured': True
    }


def _civic_insight_summary(user, area='', category='', days=30):
    end = datetime.utcnow() + timedelta(days=1)
    start = datetime.utcnow() - timedelta(days=days)
    complaints = _analytics_query(
        user, start=start, end=end, category=category, location=area
    ).all()
    category_counts = Counter(
        (c.analysis.category_classified if c.analysis else c.category or 'Other')
        for c in complaints
    )
    area_counts = Counter((c.local_area or c.district or 'Unknown') for c in complaints)
    projects = []
    for loc in Location.query.all():
        if area and area.lower() not in f'{loc.state} {loc.district}'.lower():
            continue
        for p in loc.projects:
            if not category or (p.category or '').lower() == category.lower():
                projects.append({'title': p.title, 'category': p.category or 'Other', 'status': p.status})
    unresolved = sum(1 for c in complaints if c.status != 'Resolved')
    emerging = _emerging_issues(user)
    return {
        'period_days': days,
        'records': len(complaints),
        'what_citizens_report': category_counts.most_common(5),
        'demand_concentration': area_counts.most_common(5),
        'dominant_categories': category_counts.most_common(5),
        'existing_projects': projects[:10],
        'unresolved': unresolved,
        'emerging_issues': emerging[:5],
        'human_review_required': True,
        'coverage': _quality_snapshot(user)
    }


@app.route('/impact-dashboard')
@login_required
@role_required('Officer', 'Admin')
def impact_dashboard():
    user = get_current_user()
    days = _parse_period_days(request.args.get('period', '365d'))
    start = datetime.utcnow() - timedelta(days=days)
    complaints = _analytics_query(user, start=start, end=datetime.utcnow() + timedelta(days=1)).all()
    return render_template('impact_dashboard.html',
                           metrics=_development_impact_metrics(complaints),
                           period=request.args.get('period', '365d'),
                           quality=_quality_snapshot(user))


@app.route('/civic-insight')
@login_required
@role_required('Officer', 'Admin')
def civic_insight():
    user = get_current_user()
    area = request.args.get('area', '').strip()
    category = request.args.get('category', '').strip()
    days = _parse_period_days(request.args.get('period', '30d'))
    return render_template(
        'civic_insight.html',
        summary=_civic_insight_summary(user, area, category, days),
        area=area, category=category, period=request.args.get('period', '30d')
    )


@app.route('/admin/data-quality')
@login_required
@role_required('Admin')
def admin_data_quality():
    return render_template('data_quality.html', quality=_quality_snapshot(get_current_user()))


@app.route('/public-transparency')
def public_transparency():
    """Privacy-preserving aggregate view. No request descriptions or PII."""
    requests = CitizenRequest.query
    total = requests.count()
    resolved = requests.filter(CitizenRequest.status == 'Resolved').count()
    categories = Counter()
    for c in requests.all():
        categories[c.analysis.category_classified if c.analysis else c.category or 'Other'] += 1
    feedback = CitizenFeedback.query.all()
    ratings = [f.rating for f in feedback if f.rating is not None]
    by_day = Counter(c.created_at.date().isoformat() for c in requests.all() if c.created_at)
    return render_template(
        'public_transparency.html',
        total=total, resolved=resolved,
        categories=categories.most_common(8),
        ratings=round(mean(ratings), 2) if ratings else None,
        trends=sorted(by_day.items())[-14:]
    )


@app.route('/api/public-transparency')
def api_public_transparency():
    total = CitizenRequest.query.count()
    resolved = CitizenRequest.query.filter_by(status='Resolved').count()
    feedback = CitizenFeedback.query.all()
    ratings = [f.rating for f in feedback if f.rating is not None]
    categories = Counter()
    for c in CitizenRequest.query.all():
        categories[c.analysis.category_classified if c.analysis else c.category or 'Other'] += 1
    return jsonify({
        'total_requests': total,
        'resolved_requests': resolved,
        'resolution_rate': round(resolved / total * 100, 1) if total else None,
        'major_categories': categories.most_common(8),
        'citizen_satisfaction': round(mean(ratings), 2) if ratings else None,
        'data_note': 'Aggregated statistics based on available CivicPulse data.'
    })


@app.route('/api/admin/data-quality')
@login_required
@role_required('Admin')
def api_admin_data_quality():
    return jsonify(_quality_snapshot(get_current_user()))


@app.route('/api/analytics/impact')
@login_required
@role_required('Officer', 'Admin')
def api_impact():
    user = get_current_user()
    days = _parse_period_days(request.args.get('period', '365d'))
    start = datetime.utcnow() - timedelta(days=days)
    complaints = _analytics_query(user, start=start, end=datetime.utcnow() + timedelta(days=1)).all()
    return jsonify(_development_impact_metrics(complaints))


@app.route('/api/analytics/civic-insight')
@login_required
@role_required('Officer', 'Admin')
def api_civic_insight():
    user = get_current_user()
    return jsonify(_civic_insight_summary(
        user,
        request.args.get('area', '').strip(),
        request.args.get('category', '').strip(),
        _parse_period_days(request.args.get('period', '30d'))
    ))


# End of Hack2Skill feature extensions.

# ===============================================
# DATABASE INITIALIZATION
# ===============================================

def _initialize_sla_defaults():
    changed = False
    for priority, hours in DEFAULT_SLA_TARGETS.items():
        config = SLAConfig.query.filter_by(priority=priority).first()
        if not config:
            db.session.add(SLAConfig(priority=priority, target_hours=hours))
            changed = True
    if changed:
        db.session.flush()

def _backfill_missing_sla_due_dates():
    """Assign SLA due dates only to existing complaints that do not have one."""
    complaints = CitizenRequest.query.filter(CitizenRequest.due_at.is_(None)).all()
    changed = False
    for complaint in complaints:
        _ensure_sla_due(complaint)
        changed = True
    return changed

def init_db():
    """Initialize database."""
    with app.app_context():
        db.create_all()
        _migrate_existing_schema()
        _ensure_upload_folder()
        _initialize_sla_defaults()
        _backfill_missing_sla_due_dates()
        defaults = ['Sanitation', 'Water Supply', 'Road Maintenance', 'Drainage', 'Street Lighting', 'Electricity', 'Parks', 'Public Services']
        for name in defaults:
            if not Department.query.filter_by(name=name).first():
                db.session.add(Department(name=name, is_active=True))
        db.session.commit()
        _backfill_department_references()
        print("✓ Database tables created / updated safely")

# ===============================================
# MAIN ENTRY POINT
# ===============================================

if __name__ == '__main__':
    # Create database
    with app.app_context():
        db.create_all()
        _migrate_existing_schema()
        _ensure_upload_folder()
        _initialize_sla_defaults()
        _backfill_missing_sla_due_dates()
        defaults = ['Sanitation', 'Water Supply', 'Road Maintenance', 'Drainage', 'Street Lighting', 'Electricity', 'Parks', 'Public Services']
        for name in defaults:
            if not Department.query.filter_by(name=name).first():
                db.session.add(Department(name=name, is_active=True))
        db.session.commit()
        _backfill_department_references()
    
    # Run Flask app
    print("\n" + "="*50)
    print("CivicPulse AI - Starting Flask Server")
    print("="*50)
    print("Opening at: http://127.0.0.1:5000")
    print("Press CTRL+C to stop")
    print("="*50 + "\n")
    
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='127.0.0.1', port=5000)