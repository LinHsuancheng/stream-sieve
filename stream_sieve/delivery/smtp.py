from __future__ import annotations

from email.message import EmailMessage
import os
import socket
import smtplib


def send(config: dict, subject: str, html: str, text: str | None = None) -> str:
    smtp = config["smtp"]
    username_env = smtp.get("username_env", "STREAM_SIEVE_EMAIL_USER")
    password_env = smtp.get("password_env", "STREAM_SIEVE_EMAIL_PASSWORD")
    username = smtp.get("username") or os.environ.get(username_env)
    password = smtp.get("password") or os.environ.get(password_env)
    if isinstance(password, str):
        password = password.replace(" ", "")
    if not username or not password:
        missing = []
        if not username:
            missing.append(f"username/{username_env}")
        if not password:
            missing.append(f"password/{password_env}")
        raise RuntimeError(f"missing SMTP {' and '.join(missing)}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["from"]
    msg["To"] = ", ".join(config["to"])
    msg.set_content(text or "Your Stream Sieve brief is attached as HTML.")
    msg.add_alternative(html, subtype="html")

    host = smtp["host"]
    port = int(smtp.get("port", 465))
    security = smtp.get("security", "ssl")
    timeout = float(smtp.get("timeout", 20))
    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as client:
                client.login(username, password)
                client.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as client:
                if security == "starttls":
                    client.starttls()
                client.login(username, password)
                client.send_message(msg)
    except (TimeoutError, socket.timeout, OSError) as exc:
        raise RuntimeError(f"cannot connect to SMTP server {host}:{port}: {exc}") from exc
    return "smtp"
