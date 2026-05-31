"""Update Lio's Zoho SMTP/IMAP app password in .env — without echoing the value.

Usage:
    cd ~/ashrah-agent
    ./bin/python scripts/update_smtp_password.py

Prompts for the new password via getpass (hidden input — won't appear on screen,
in shell history, or in any log). Rewrites only the LIO_SMTP_PASSWORD line in
.env (preserving everything else), keeps file permissions at 0600, then verifies
the new password by performing an SMTP login round-trip. Does NOT send an email.
"""

import getpass
import os
import re
import smtplib
import ssl
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"


def update_env_password(new_pw: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"LIO_SMTP_PASSWORD={new_pw}\n", encoding="utf-8")
        os.chmod(ENV_PATH, 0o600)
        return

    text = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"^LIO_SMTP_PASSWORD\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(f"LIO_SMTP_PASSWORD={new_pw}", text)
    else:
        # Append if not present
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + f"LIO_SMTP_PASSWORD={new_pw}\n"

    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(REPO))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, ENV_PATH)
        os.chmod(ENV_PATH, 0o600)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def smtp_login_test(host: str, port: int, user: str, pw: str) -> tuple[bool, str]:
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, pw)
        return True, "SMTP login accepted"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"SMTP AUTH FAILED: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    print("Lio — rotate SMTP/IMAP password")
    print(f"Updating: {ENV_PATH}")
    print()

    no_confirm = "--no-confirm" in sys.argv
    new_pw = getpass.getpass("New Zoho app password (input hidden): ").strip()
    if not new_pw:
        print("Cancelled — empty password.")
        return 1
    if not no_confirm:
        confirm = getpass.getpass("Confirm: ").strip()
        if new_pw != confirm:
            print("Mismatch — aborted, .env not modified.")
            print("Tip: re-run with --no-confirm if you're pasting from a password manager:")
            print("    ./bin/python scripts/update_smtp_password.py --no-confirm")
            return 1

    update_env_password(new_pw)
    print(f"\n.env updated · permissions {oct(os.stat(ENV_PATH).st_mode)[-3:]}")

    # Re-read env so the test below uses the freshly written value
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    host = os.getenv("LIO_SMTP_HOST", "smtp.zoho.com")
    port = int(os.getenv("LIO_SMTP_PORT", "465"))
    user = os.getenv("LIO_SMTP_USER", "lio.ashrah@ashrahpainting.ca")
    pw = os.getenv("LIO_SMTP_PASSWORD", "")

    print(f"\nTesting SMTP login as {user} → {host}:{port} …")
    ok, msg = smtp_login_test(host, port, user, pw)
    print(("✓ " if ok else "✗ ") + msg)

    if ok:
        print("\nDone. Restart Lio so the running app picks up the new password:")
        print("    ./bin/python lio_app.py")
        return 0
    else:
        print("\nLogin failed. The .env was still updated to the value you typed —")
        print("if that's wrong, re-run this script with the correct one.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
