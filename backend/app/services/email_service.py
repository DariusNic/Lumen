"""Transactional email sender for verification + password-reset flows.

Plain `smtplib` over STARTTLS (port 587) — no extra dependency.
Two modes:
  - **Live**: SMTP creds in env → real send via Gmail / Yahoo / etc.
  - **Dry-run**: no creds OR `MAIL_DRY_RUN=true` → body logged to stdout,
    returns success. Keeps local dev unblocked when running without an
    app password.

Email bodies are inline HTML (and a matching plain-text fallback) so we
don't take a templating dependency for the two emails we send.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import quote

from flask import current_app

log = logging.getLogger(__name__)


def send_verification_email(*, to_email: str, full_name: str, token: str) -> None:
    """Send the verify-your-email message after registration."""
    link = _absolute_url(f"/auth/verify?token={quote(token)}")
    subject = "Verify your Lumen account"

    text = (
        f"Hi {full_name},\n\n"
        f"Welcome to Lumen! Please confirm this email address to activate your account.\n\n"
        f"Open this link in your browser:\n{link}\n\n"
        f"The link expires in 24 hours. If you didn't sign up for Lumen, you can ignore this email.\n\n"
        f"— Lumen"
    )
    html = _render_html(
        title="Welcome to Lumen",
        intro=f"Hi {full_name}, please confirm this email address to finish setting up your account.",
        cta_label="Verify my email",
        cta_url=link,
        footnote="The link expires in 24 hours. If you didn't sign up for Lumen, you can safely ignore this message.",
    )
    _send(to_email=to_email, subject=subject, text=text, html=html)


def send_password_reset_email(*, to_email: str, full_name: str, token: str) -> None:
    """Send the password-reset message after a /forgot request."""
    link = _absolute_url(f"/auth/reset?token={quote(token)}")
    subject = "Reset your Lumen password"

    text = (
        f"Hi {full_name},\n\n"
        f"We received a request to reset the password on your Lumen account.\n\n"
        f"Open this link to choose a new password:\n{link}\n\n"
        f"The link expires in 1 hour. If you didn't ask to reset your password, you can ignore this email.\n\n"
        f"— Lumen"
    )
    html = _render_html(
        title="Reset your password",
        intro=f"Hi {full_name}, we received a request to reset the password on your Lumen account.",
        cta_label="Choose a new password",
        cta_url=link,
        footnote="The link expires in 1 hour. If you didn't make this request, you can safely ignore this message — your password stays the same.",
    )
    _send(to_email=to_email, subject=subject, text=text, html=html)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _absolute_url(path: str) -> str:
    base = current_app.config["APP_BASE_URL"].rstrip("/")
    return f"{base}{path}"


def _send(*, to_email: str, subject: str, text: str, html: str) -> None:
    """Either send via SMTP or log to stdout in dry-run mode."""
    cfg = current_app.config
    username: str = cfg.get("SMTP_USERNAME", "") or ""
    password: str = cfg.get("SMTP_PASSWORD", "") or ""
    dry_run: bool = bool(cfg.get("MAIL_DRY_RUN")) or not (username and password)

    if dry_run:
        log.warning(
            "[email:dry-run] would send to=%s subject=%r\n--- body ---\n%s\n--- end ---",
            to_email, subject, text,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["MAIL_FROM_NAME"], cfg["MAIL_FROM_ADDRESS"] or username))
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    host: str = cfg["SMTP_HOST"]
    port: int = int(cfg["SMTP_PORT"])
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        # Gmail returns "Application-specific password required" when 2FA is on
        # and a regular password was used. Surface that clearly.
        log.exception("SMTP auth failed: %s", e)
        raise
    except Exception:  # noqa: BLE001 — we log everything below
        log.exception("SMTP send failed (host=%s port=%s to=%s)", host, port, to_email)
        raise


def _render_html(*, title: str, intro: str, cta_label: str, cta_url: str, footnote: str) -> str:
    """Tiny inline-styled HTML — no external CSS, renders in every mail client."""
    return f"""<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,sans-serif;">
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f4f5f7;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;border:1px solid #e2e4e8;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 8px 32px;">
                <div style="font-size:14px;font-weight:600;color:#4f46e5;letter-spacing:0.04em;text-transform:uppercase;">Lumen</div>
                <h1 style="margin:8px 0 0 0;font-size:24px;line-height:1.2;color:#0f172a;">{title}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px 24px 32px;color:#475569;font-size:15px;line-height:1.55;">
                <p style="margin:0 0 24px 0;">{intro}</p>
                <p style="margin:0 0 8px 0;">
                  <a href="{cta_url}" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:12px 22px;border-radius:8px;">{cta_label}</a>
                </p>
                <p style="margin:24px 0 0 0;font-size:13px;color:#94a3b8;word-break:break-all;">Or copy this link into your browser:<br><span style="color:#64748b;">{cta_url}</span></p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px 28px 32px;border-top:1px solid #e2e4e8;color:#94a3b8;font-size:12px;line-height:1.5;">
                {footnote}
              </td>
            </tr>
          </table>
          <div style="margin-top:16px;color:#94a3b8;font-size:11px;letter-spacing:0.04em;text-transform:uppercase;">
            Lumen · For education only — not financial advice
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>"""
