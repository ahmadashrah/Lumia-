"""Send a one-off test email from Lio's Zoho mailbox.

Usage:
    cd ~/ashrah-agent
    ./bin/python scripts/send_test_email.py recipient@example.com
    ./bin/python scripts/send_test_email.py recipient@example.com "Custom subject"

Reads .env automatically. No CRM contacts are touched. The send is logged to
logs/lio/{date}/sends_*.json.
"""

import sys
from pathlib import Path

# Load .env from the repo root regardless of where the script is invoked
from dotenv import load_dotenv
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

# Make the lio package importable when running from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lio.core import mailer


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: ./bin/python scripts/send_test_email.py <recipient> [subject]")
        return 64

    to = sys.argv[1].strip()
    subject = sys.argv[2].strip() if len(sys.argv) >= 3 else "Lio outbound test"

    if "@" not in to:
        print(f"Invalid recipient: {to!r}")
        return 64

    s = mailer.status()
    print(f"From:        {s['from']}")
    print(f"To:          {to}")
    print(f"Subject:     {subject}")
    print(f"SMTP host:   {s['host']}:{s['port']} (ssl={s['use_ssl']})")
    print(f"Configured:  {s['configured']}")
    if not s["configured"]:
        print(f"\nERROR: {s['error']}")
        print("Check that .env exists at ~/ashrah-agent/.env and contains LIO_SMTP_PASSWORD.")
        return 78

    body = (
        "Hi —\n\n"
        "Quick smoke test from Lio's mailbox. If you're seeing this, outbound through "
        "Zoho SMTP from lio.ashrah@ashrahpainting.ca is working end-to-end.\n\n"
        "Reply to this email; once IMAP is enabled in Zoho settings, Lio's inbox loop "
        "will pick up the response and surface it in the Pipeline tab.\n"
    )

    print("\nSending…")
    result = mailer.send(
        to_email=to,
        to_name="",
        subject=subject,
        body=body,
        contact_id="manual-test",
    )

    print("\nResult:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    if result.get("ok"):
        print("\nSent. Check the recipient inbox (and the spam folder, just in case).")
        return 0
    print(f"\nFailed: {result.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
