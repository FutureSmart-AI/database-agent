"""Create local configuration without printing or importing any existing secrets."""
import base64
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    if destination.exists():
        raise SystemExit(".env already exists; preserve it and configure manually")
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("replace-with-a-random-local-bootstrap-secret", secrets.token_urlsafe(32))
    content = content.replace("local-installation-only", secrets.token_urlsafe(24))
    content += "\nAPP_MASTER_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() + "\n"
    content += "HASH_SALT=" + secrets.token_urlsafe(32) + "\n"
    with destination.open("x", encoding="utf-8") as output:
        output.write(content)
    destination.chmod(0o600)
    print("Created .env with independent local secrets. Read STANDALONE_LOGIN_PASSWORD there to sign in.")


if __name__ == "__main__":
    main()
