# ===============================================
# CIVICPULSE AI - Database Models
# ===============================================

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets
import string

db = SQLAlchemy()


class User(db.Model):
    """User model."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Citizen')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)

    department = db.relationship('Department', backref=db.backref('officers', lazy=True), foreign_keys=[department_id])

    citizen_requests = db.relationship(
        'CitizenRequest',
        backref='user',
        lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='CitizenRequest.user_id'
    )

    @property
    def is_authenticated(self):
        return True

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class CitizenRequest(db.Model):
    """Citizen complaint/request model.

    Existing fields are retained for backward compatibility. The additional
    fields extend the existing complaint workflow without replacing it.
    """
    __tablename__ = 'citizen_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Existing request fields
    category = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(20), default='en')
    # Multilingual/voice provenance fields (backward-compatible additions)
    original_language = db.Column(db.String(20), default='en', index=True)
    language_override = db.Column(db.String(20), nullable=True)
    original_text = db.Column(db.Text)
    normalized_text = db.Column(db.Text)
    voice_transcript = db.Column(db.Text)
    input_mode = db.Column(db.String(20), default='text')
    state = db.Column(db.String(50), nullable=False)
    district = db.Column(db.String(50), nullable=False)
    local_area = db.Column(db.String(100), nullable=False, index=True)

    # Smart complaint registration extensions
    title = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    complaint_datetime = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    photo_filename = db.Column(db.String(255))
    video_filename = db.Column(db.String(255))
    evidence_filename = db.Column(db.String(255))
    contact_phone = db.Column(db.String(30))
    contact_email = db.Column(db.String(120))
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)

    status = db.Column(db.String(20), default='Submitted', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    assigned_department = db.Column(db.String(100), index=True)
    # Stable department reference for official assignment; assigned_department is retained for backward compatibility.
    assigned_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True, index=True)
    assigned_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    assigned_at = db.Column(db.DateTime)
    due_at = db.Column(db.DateTime, index=True)
    officer_remarks = db.Column(db.Text)
    before_evidence_filename = db.Column(db.String(255))
    after_evidence_filename = db.Column(db.String(255))

    assigned_officer = db.relationship('User', foreign_keys=[assigned_officer_id], backref='assigned_requests', lazy=True)
    timeline_events = db.relationship('ComplaintTimeline', backref='complaint', lazy=True, cascade='all, delete-orphan')

    analysis = db.relationship(
        'RequestAnalysis',
        backref='request',
        lazy=True,
        uselist=False,
        cascade='all, delete-orphan'
    )

    def generate_request_id(self):
        while True:
            chars = string.ascii_uppercase + string.digits
            random_part = ''.join(secrets.choice(chars) for _ in range(9))
            self.request_id = f"CP-{random_part}"
            if not CitizenRequest.query.filter_by(request_id=self.request_id).first():
                break

    def __repr__(self):
        return f'<CitizenRequest {self.request_id}>'


class RequestAnalysis(db.Model):
    """AI analysis results model."""
    __tablename__ = 'request_analysis'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(
        db.String(20),
        db.ForeignKey('citizen_requests.request_id'),
        nullable=False,
        index=True
    )

    # Existing analysis fields
    language_detected = db.Column(db.String(20), default='en')
    category_classified = db.Column(db.String(50), nullable=False, index=True)
    urgency_level = db.Column(db.String(20))
    infrastructure_gap = db.Column(db.Float)
    similar_requests_count = db.Column(db.Integer, default=0)
    population_impacted = db.Column(db.Integer, default=0)

    ai_recommendation = db.Column(db.Text)
    explainability_factors = db.Column(db.JSON)

    # Smart AI complaint analysis extensions
    issue_type = db.Column(db.String(100))
    priority = db.Column(db.String(20), index=True)
    recommended_department = db.Column(db.String(100), index=True)
    # Stable AI recommendation reference when it can be mapped to an existing department.
    recommended_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True, index=True)
    sentiment = db.Column(db.String(30))
    confidence_score = db.Column(db.Float)
    ai_provider = db.Column(db.String(30), default='local')

    human_review_required = db.Column(db.Boolean, default=True)
    review_status = db.Column(db.String(30), default='Review Required', index=True)
    officer_decision = db.Column(db.String(30))
    officer_modification = db.Column(db.Text)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    reviewed_by = db.Column(db.String(80))
    reviewed_at = db.Column(db.DateTime)
    confidence_details = db.Column(db.JSON)

    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow)
    original_priority = db.Column(db.String(20), index=True)
    priority_override = db.Column(db.String(20), index=True)

    def __repr__(self):
        return f'<RequestAnalysis {self.request_id}>'


class Location(db.Model):
    """Geographic location data."""
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(50), nullable=False)
    district = db.Column(db.String(50), nullable=False, index=True)

    citizen_demand_count = db.Column(db.Integer, default=0)
    infrastructure_gap_score = db.Column(db.Float, default=0.0)
    population = db.Column(db.Integer, default=0)
    ongoing_projects = db.Column(db.Integer, default=0)

    projects = db.relationship(
        'Project',
        backref='location',
        lazy=True,
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        db.UniqueConstraint('state', 'district', name='uq_state_district'),
    )

    def __repr__(self):
        return f'<Location {self.state}-{self.district}>'


class Project(db.Model):
    """Government project model."""
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))
    status = db.Column(db.String(20), default='Planned')
    estimated_people_impacted = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Project {self.title}>'


class ComplaintTimeline(db.Model):
    """Auditable history for each complaint."""
    __tablename__ = 'complaint_timeline'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(20), db.ForeignKey('citizen_requests.request_id'), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    actor_role = db.Column(db.String(20))
    evidence_filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User', foreign_keys=[actor_user_id], lazy=True)

class Notification(db.Model):
    """Reliable in-app notifications."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    request_id = db.Column(db.String(20), db.ForeignKey('citizen_requests.request_id'), nullable=True, index=True)
    notification_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref='notifications', lazy=True)


class CitizenFeedback(db.Model):
    """Optional post-resolution citizen feedback."""
    __tablename__ = 'citizen_feedback'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(20), db.ForeignKey('citizen_requests.request_id'), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    satisfaction_level = db.Column(db.String(40))
    issue_resolved = db.Column(db.Boolean, nullable=False, default=True)
    reopened_requested = db.Column(db.Boolean, nullable=False, default=False)
    reopened_reason = db.Column(db.Text)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    request = db.relationship('CitizenRequest', backref=db.backref('feedback', uselist=False, cascade='all, delete-orphan'))
    user = db.relationship('User', lazy=True)


class Department(db.Model):
    """Administrative department directory with soft deactivation."""
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Department {self.name}>'


class SLAConfig(db.Model):
    """Configurable resolution target for each complaint priority."""
    __tablename__ = 'sla_configs'

    id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.String(20), unique=True, nullable=False, index=True)
    target_hours = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<SLAConfig {self.priority}: {self.target_hours}h>'

class AuditLog(db.Model):
    """Administrative audit trail. Secrets and passwords are never stored."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(120), nullable=False, index=True)
    entity = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(120), nullable=True, index=True)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('audit_logs', lazy=True))

    def __repr__(self):
        return f'<AuditLog {self.action} {self.entity}:{self.entity_id}>'

