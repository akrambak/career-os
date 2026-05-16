from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailResult:
    provider: str
    ok: bool
    detail: str


class DigestEmailer:
    """
    Adapter for sending the daily digest. Three backends:

      - resend      → https://api.resend.com/emails        (POST, Bearer token)
      - postmark    → https://api.postmarkapp.com/email    (POST, X-Postmark-Server-Token)
      - gmail       → smtp.gmail.com:587 with app password (SMTP_API_KEY)

    Pick by setting SMTP_PROVIDER in .env. SMTP_FROM and SMTP_TO are required.
    """

    def __init__(
        self, provider: str, api_key: str, sender: str, recipient: str,
        subject_prefix: str = "[Career-OS] ",
    ):
        if provider not in {"resend", "postmark", "gmail"}:
            raise ValueError(f"Unknown SMTP_PROVIDER {provider!r}")
        if not api_key:
            raise ValueError("SMTP_API_KEY is empty")
        if not sender or not recipient:
            raise ValueError("SMTP_FROM and SMTP_TO are required")
        self.provider = provider
        self.api_key = api_key
        self.sender = sender
        self.recipient = recipient
        self.subject_prefix = subject_prefix

    def send(self, subject: str, markdown_body: str) -> EmailResult:
        full_subject = f"{self.subject_prefix}{subject}"
        plain = markdown_body  # we send Markdown as plain text; recipients view in monospace
        html = _markdown_to_minimal_html(markdown_body)
        if self.provider == "resend":
            return self._send_resend(full_subject, plain, html)
        if self.provider == "postmark":
            return self._send_postmark(full_subject, plain, html)
        return self._send_gmail(full_subject, plain, html)

    def _send_resend(self, subject: str, text: str, html: str) -> EmailResult:
        try:
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.sender, "to": [self.recipient],
                    "subject": subject, "text": text, "html": html,
                },
                timeout=30.0,
            )
            r.raise_for_status()
            return EmailResult("resend", True, r.json().get("id", "sent"))
        except httpx.HTTPError as exc:
            logger.error("resend send failed: %s", exc)
            return EmailResult("resend", False, str(exc))

    def _send_postmark(self, subject: str, text: str, html: str) -> EmailResult:
        try:
            r = httpx.post(
                "https://api.postmarkapp.com/email",
                headers={
                    "X-Postmark-Server-Token": self.api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "From": self.sender, "To": self.recipient,
                    "Subject": subject, "TextBody": text, "HtmlBody": html,
                    "MessageStream": "outbound",
                },
                timeout=30.0,
            )
            r.raise_for_status()
            return EmailResult("postmark", True, r.json().get("MessageID", "sent"))
        except httpx.HTTPError as exc:
            logger.error("postmark send failed: %s", exc)
            return EmailResult("postmark", False, str(exc))

    def _send_gmail(self, subject: str, text: str, html: str) -> EmailResult:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
                s.starttls()
                s.login(self.sender, self.api_key)
                s.send_message(msg)
            return EmailResult("gmail", True, "sent")
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("gmail send failed: %s", exc)
            return EmailResult("gmail", False, str(exc))


def _markdown_to_minimal_html(md: str) -> str:
    """Lightweight Markdown→HTML for email — we don't pull a full parser."""
    lines = []
    in_list = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append("<br>")
            continue
        if line.startswith("# "):
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<h1>{_esc(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<h2>{_esc(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{_bold(_esc(line[2:]))}</li>")
        else:
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<p>{_bold(_esc(line))}</p>")
    if in_list:
        lines.append("</ul>")
    body = "\n".join(lines)
    return (
        "<html><body style=\"font-family:ui-monospace,Menlo,monospace;"
        "max-width:680px;margin:0 auto;padding:16px;\">"
        f"{body}</body></html>"
    )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bold(s: str) -> str:
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
