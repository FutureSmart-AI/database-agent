"""Environment loading and metadata address shared by API, sessions and Alembic."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parent


def load_environment():
    # One explicit file or the installation's .env; process values always win.
    explicit = os.getenv("ENV_FILE")
    path = Path(explicit) if explicit else ROOT / ".env"
    if explicit and not path.is_file():
        raise ValueError("ENV_FILE does not exist")
    if not explicit and not path.is_file():
        path = ROOT.parent / ".env"
    load_dotenv(path, override=False)


def metadata_url(driver="asyncpg"):
    load_environment()
    raw = os.getenv("DATABASE_URL")
    if raw:
        url = make_url(raw)
        if url.get_backend_name() != "postgresql":
            raise ValueError("Metadata DATABASE_URL must use PostgreSQL")
        return url.set(drivername=f"postgresql+{driver}")
    names = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB_NAME")
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise ValueError("Missing metadata configuration: " + ", ".join(missing))
    return URL.create(
        f"postgresql+{driver}", username=os.environ[names[0]], password=os.environ[names[1]],
        host=os.environ[names[2]], port=int(os.environ[names[3]]), database=os.environ[names[4]],
    )
