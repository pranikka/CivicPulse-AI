# ===============================================
# CIVICPULSE AI - Configuration
# ===============================================

import os
import secrets
from datetime import timedelta

try:
    _SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
except (TypeError, ValueError):
    _SMTP_PORT = 587

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///civicpulse.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '1' if os.environ.get('FLASK_ENV') == 'production' else '0') == '1'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_REFRESH_EACH_REQUEST = False
    SESSION_COOKIE_NAME = 'civicpulse_session'
    
    # Application
    ITEMS_PER_PAGE = 20
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024

    # Secure complaint/evidence uploads. Files are stored outside the public
    # static directory and are served through an authenticated route.
    UPLOAD_FOLDER = os.environ.get('CIVICPULSE_UPLOAD_FOLDER') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'instance', 'uploads', 'complaints'
    )
    ALLOWED_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi'}
    ALLOWED_EVIDENCE_EXTENSIONS = {
        'jpg', 'jpeg', 'png', 'webp', 'pdf', 'txt', 'doc', 'docx'
    }
    MAX_PHOTO_SIZE = 8 * 1024 * 1024
    MAX_VIDEO_SIZE = 24 * 1024 * 1024
    MAX_EVIDENCE_SIZE = 10 * 1024 * 1024
    MAX_BEFORE_AFTER_SIZE = 10 * 1024 * 1024
    ALLOWED_BEFORE_AFTER_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'pdf'}

    # AI provider configuration. Defaults to the safe local analyzer.
    AI_PROVIDER = os.environ.get('AI_PROVIDER', 'local').lower()
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')


    # Optional email notifications. Disabled by default so the app works
    # normally when SMTP configuration is not present.
    EMAIL_NOTIFICATIONS_ENABLED = os.environ.get('EMAIL_NOTIFICATIONS_ENABLED', '0') == '1'
    SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
    SMTP_PORT = _SMTP_PORT
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_FROM = os.environ.get('SMTP_FROM', '') or SMTP_USERNAME
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', '1') == '1'
    EMAIL_SUBJECT_PREFIX = os.environ.get('EMAIL_SUBJECT_PREFIX', '[CivicPulse AI]')

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}