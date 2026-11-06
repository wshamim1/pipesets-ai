"""Email sender (SMTP) — built-in tool `email_sender`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="email_sender",
    name="Email Sender (SMTP)",
    icon="📧",
    category="Communication",
    description="Sends emails via SMTP. Input is the message body.",
    default_config={
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "username": "",
        "password": "",
        "from_address": "",
        "to_address": "",
        "subject": "Pipesets AI Notification",
    },
    order=10,
    required=("smtp_host", "to_address"),
    parameters=params(
        {"body": {"type": "string", "description": "The email body"}},
        {"subject": {"type": "string", "description": "Subject line"}},
    ),
    input_param="body",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import smtplib
    from email.mime.text import MIMEText
    smtp_host = cfg.get("smtp_host", "")
    smtp_port = int(cfg.get("smtp_port", 587))
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    from_addr = cfg.get("from_address", username)
    to_addr = cfg.get("to_address", "")
    subject = cfg.get("subject", "Message from Pipesets AI")
    if not smtp_host:
        return "[Email] smtp_host is required in config."
    if not to_addr:
        return "[Email] to_address is required in config."
    msg = MIMEText(inp, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return f"[Email] Sent to {to_addr} via {smtp_host}:{smtp_port}"
    except Exception as e:
        return f"[Email] SMTP error: {e}"
