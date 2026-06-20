"""
Email service for TMS Platform.

Uses SMTP to send HTML emails with templates.
Configuration is loaded from environment variables.
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader
except ModuleNotFoundError:
    Environment = None
    FileSystemLoader = None

from app.core.config import (
    FRONTEND_BASE_URL,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)

logger = logging.getLogger(__name__)

# Template directory path
TEMPLATE_DIR = Path(__file__).parent.parent / "email_templates"

# Jinja2 environment
jinja_env = (
    Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
    )
    if Environment and FileSystemLoader
    else None
)


def render_template(template_name: str, context: dict) -> str:
    """
    Render a Jinja2 template with the given context.

    Args:
        template_name: Name of the template file (e.g., 'temporary_password.html')
        context: Dictionary with template variables

    Returns:
        Rendered HTML string
    """
    if not jinja_env:
        raise RuntimeError(
            "Jinja2 is not installed. Install backend requirements to enable email templates."
        )

    # Add global context variables
    context.setdefault("current_year", datetime.now().year)
    context.setdefault("frontend_url", FRONTEND_BASE_URL)

    template = jinja_env.get_template(template_name)
    return template.render(context)


def try_render_template(template_name: str, context: dict) -> str | None:
    try:
        return render_template(template_name, context)
    except Exception as e:
        logger.error(f"Failed to render email template {template_name}: {str(e)}")
        return None


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
) -> bool:
    """
    Send an HTML email using SMTP.

    Args:
        to_email: Recipient email address
        to_name: Recipient name
        subject: Email subject
        html_content: HTML content of the email

    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = f"{to_name} <{to_email}>"

        # Attach HTML part
        html_part = MIMEText(html_content, "html", "utf-8")
        msg.attach(html_part)

        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls()

            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)

            server.send_message(msg)

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        # For development: still print to console so we can see the email content
        print("\n" + "=" * 80)
        print(f"EMAIL SEND FAILED: {subject}")
        print(f"Recipient: {to_name} <{to_email}>")
        print(f"Error: {str(e)}")
        print("=" * 80 + "\n")
        return False


def send_password_reset_email(
    to_email: str,
    to_name: str,
    reset_token: str,
) -> bool:
    """
    Send password reset email with HTML template.

    Args:
        to_email: Recipient email address
        to_name: Recipient full name
        reset_token: The reset token for the password reset link

    Returns:
        True if email was sent successfully, False otherwise
    """
    reset_link = f"{FRONTEND_BASE_URL}/change-password?token={reset_token}"

    context = {
        "user_name": to_name or to_email,
        "reset_link": reset_link,
    }

    html_content = try_render_template("password_reset.html", context)
    if not html_content:
        return False

    return send_email(
        to_email=to_email,
        to_name=to_name or to_email,
        subject="🔐 Resetare parolă - TMS Platform",
        html_content=html_content,
    )


def send_temporary_password_email(
    to_email: str,
    to_name: str,
    temporary_password: str,
) -> bool:
    """
    Send temporary password email for newly invited users.

    Args:
        to_email: Recipient email address
        to_name: Recipient full name
        temporary_password: The temporary password for first login

    Returns:
        True if email was sent successfully, False otherwise
    """
    login_url = f"{FRONTEND_BASE_URL}/login"

    context = {
        "user_name": to_name or to_email,
        "email": to_email,
        "temporary_password": temporary_password,
        "login_url": login_url,
    }

    html_content = try_render_template("temporary_password.html", context)
    if not html_content:
        return False

    return send_email(
        to_email=to_email,
        to_name=to_name or to_email,
        subject="✅ Contul tău a fost creat - TMS Platform",
        html_content=html_content,
    )


def send_client_approved_email(
    to_email: str,
    to_name: str,
) -> bool:
    """
    Send approval email to client after manager approval.

    Args:
        to_email: Recipient email address
        to_name: Recipient full name

    Returns:
        True if email was sent successfully, False otherwise
    """
    login_url = f"{FRONTEND_BASE_URL}/login"

    context = {
        "user_name": to_name or to_email,
        "login_url": login_url,
    }

    html_content = try_render_template("client_approved.html", context)
    if not html_content:
        return False

    return send_email(
        to_email=to_email,
        to_name=to_name or to_email,
        subject="🎉 Contul tău a fost aprobat - TMS Platform",
        html_content=html_content,
    )
