# ===============================================
# CIVICPULSE AI - Optional Email Notification Service
# ===============================================

import smtplib
from email.message import EmailMessage

from config import Config


def send_email(recipient, subject, body):
    """Send an optional plain-text email.

    Missing/invalid SMTP configuration never interrupts the main application.
    Returns True only when the message is accepted by the SMTP server.
    """
    if not Config.EMAIL_NOTIFICATIONS_ENABLED:
        return False
    if not recipient or not Config.SMTP_SERVER or not Config.SMTP_FROM:
        return False

    message = EmailMessage()
    message['From'] = Config.SMTP_FROM
    message['To'] = recipient
    message['Subject'] = f"{Config.EMAIL_SUBJECT_PREFIX} {subject}".strip()
    message.set_content(body)

    try:
        if Config.SMTP_USE_TLS:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if Config.SMTP_USERNAME:
                    smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as smtp:
                if Config.SMTP_USERNAME:
                    smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
                smtp.send_message(message)
        return True
    except Exception:
        return False
