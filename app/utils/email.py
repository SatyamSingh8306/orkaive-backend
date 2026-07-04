"""Email service.

Reads SMTP credentials from the new `Settings` (instead of the legacy
`os.getenv` cluster), and exposes async `send_*` methods.

The singleton is constructed lazily on first access. Constructing it at
import time would force `Settings()` validation before test code (or any
importer) gets a chance to set env vars, and `Settings` raises on a
missing `GROQ_API_KEY` when `LLM_PROVIDER_ROUTER=groq` (the default) —
which makes `from app.routes.auth import …` fail in CI even for tests
that don't touch email.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_service: Optional["EmailService"] = None


def _get_service() -> "EmailService":
    global _service
    if _service is None:
        _service = EmailService()
    return _service


class _LazyEmailServiceProxy:
    """Proxy that constructs the real `EmailService` on first attribute
    access. Lets callers keep writing `email_service.send_*` while
    deferring `Settings()` until those code paths actually run.

    The cache is per-process. Tests that mutate env should call
    `reset_email_service_cache()` (or `reset_settings_cache()` plus
    this one) to force a fresh construction.
    """

    def __getattr__(self, name: str):
        return getattr(_get_service(), name)


def reset_email_service_cache() -> None:
    """Used by tests to drop the cached `EmailService` after env changes."""
    global _service
    _service = None


class EmailService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.smtp_host = self.settings.smtp_host
        self.smtp_port = self.settings.smtp_port
        self.smtp_username = self.settings.smtp_user
        self.smtp_password = self.settings.smtp_password
        self.from_email = self.settings.from_email or self.smtp_username
        self.frontend_url = self.settings.nextjs_base_url

    def _credentials_present(self) -> bool:
        return bool(self.smtp_username and self.smtp_password)

    async def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        if not self._credentials_present():
            logger.warning("SMTP not configured; skipping reset email")
            return False
        reset_link = f"{self.frontend_url}/reset-password?token={reset_token}"
        html = self._render_template(
            title="Password Reset Request",
            color="#0B0B0F",
            body_html=(
                f"<p>Hello,</p>"
                f"<p>You requested a password reset for your Orkaive account.</p>"
                f'<p><a href="{reset_link}" style="display:inline-block;background:#0B0B0F;color:#F4EFE6;'
                f'padding:14px 22px;text-decoration:none;font-weight:600;">Reset password</a></p>'
                f'<p style="font-size:12px;color:#5C5750;">If the button does not work, paste this URL: '
                f'<br><code>{reset_link}</code></p>'
                f'<p style="font-size:12px;color:#5C5750;">This link expires in 1 hour.</p>'
            ),
        )
        return await self._send(to_email, "Password Reset — Orkaive", html)

    async def send_welcome_email(self, to_email: str, name: str) -> bool:
        if not self._credentials_present():
            return False
        html = self._render_template(
            title="Welcome to Orkaive",
            color="#1F7A3A",
            body_html=(
                f"<p>Hello <strong>{name}</strong>,</p>"
                f"<p>Your Orkaive account is ready. Build workflows, route queries "
                f"through specialized agents, and let the runtime handle the wiring.</p>"
                f'<p><a href="{self.frontend_url}/signin" style="display:inline-block;'
                f'background:#0B0B0F;color:#F4EFE6;padding:14px 22px;text-decoration:none;'
                f'font-weight:600;">Open the console</a></p>'
            ),
        )
        return await self._send(to_email, "Welcome to Orkaive", html)

    # ---- internals ---------------------------------------------------------

    def _render_template(self, *, title: str, color: str, body_html: str) -> str:
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;padding:24px;background:#F4EFE6;font-family:-apple-system,Segoe UI,sans-serif;color:#0B0B0F;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;padding:32px;border:1px solid #0B0B0F;">
    <h1 style="margin:0 0 16px;font-size:22px;color:{color};">{title}</h1>
    {body_html}
  </div>
</body></html>"""

    async def _send(self, to_email: str, subject: str, html: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["From"] = self.from_email or "noreply@orkaive.local"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))
        try:
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                start_tls=True,
                username=self.smtp_username,
                password=self.smtp_password,
            )
            return True
        except Exception as e:
            logger.error("email send failed: %s", e)
            return False


email_service = _LazyEmailServiceProxy()
