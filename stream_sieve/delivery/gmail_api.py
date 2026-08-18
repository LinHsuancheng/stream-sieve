from __future__ import annotations

import base64
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from stream_sieve.delivery.smtp import build_message


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def send(config: dict, subject: str, html: str, text: str | None = None) -> str:
    settings = config["gmail_api"]
    token_file = Path(settings["token_file"]).expanduser()
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_file.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError(f"invalid Gmail OAuth credentials: {token_file}")

    message = build_message(config, subject, html)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    response = AuthorizedSession(credentials).post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        json={"raw": raw},
        timeout=float(settings.get("timeout", 30)),
    )
    response.raise_for_status()
    return "gmail_api"
