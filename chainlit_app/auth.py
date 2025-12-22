from typing import Dict, Optional
import chainlit as cl
from chainlit.user import User

from config import ALLOWED_EMAILS, ALLOWED_DOMAINS, ADMIN_EMAILS

@cl.oauth_callback
async def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_app_user: User,
    id_token: Optional[str] = None,
    **kwargs,
) -> Optional[User]:
    email = (raw_user_data.get("email") or raw_user_data.get("preferred_username") or "").strip().lower()
    name = (raw_user_data.get("name") or raw_user_data.get("login") or raw_user_data.get("display_name") or "").strip()

    if not email:
        print("[oauth] No email found in user data.")
        return None

    domain = email.split("@")[-1] if "@" in email else ""

    allowed = False
    if ALLOWED_DOMAINS and domain in ALLOWED_DOMAINS:
        allowed = True
    if ALLOWED_EMAILS and email in ALLOWED_EMAILS:
        allowed = True

    if not allowed:
        print(f"[oauth] Email {email} with domain {domain} is not allowed.")
        print("[oauth] Allowed emails:", ALLOWED_EMAILS)
        return None

    role = "ADMIN" if email in ADMIN_EMAILS else "USER"

    default_app_user.metadata = {
        **(default_app_user.metadata or {}),
        "provider": provider_id,
        "email": email,
        "name": name or email.split("@")[0],
        "role": role,
    }
    import sys

    print(f"[oauth] provider={provider_id} raw_user_data_keys={list(raw_user_data.keys())}", file=sys.stderr)
    print(f"[oauth] email={raw_user_data.get('email')} preferred={raw_user_data.get('preferred_username')}", file=sys.stderr)
    print(f"[oauth] allowed_emails={len(ALLOWED_EMAILS)} allowed_domains={len(ALLOWED_DOMAINS)}", file=sys.stderr)


    return default_app_user
