"""The public repository is produced only by deploy/publish_public.py (docs/publication.md)."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
import export_source  # noqa: E402
import publish_public  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, check=True,
                          capture_output=True).stdout


class PrivateLinkGateTests(unittest.TestCase):
    def test_only_the_public_repository_may_be_linked(self):
        allowed = [b"https://github.com/FutureSmart-AI/database-agent", b"github.com/FutureSmart-AI/database-agent.git",
                   b"(https://github.com/FutureSmart-AI/database-agent/pull/1)", b"github.com/FutureSmart-AI/database-agent#x"]
        org = b"github.com/FutureSmart-AI/"  # joined at runtime so this file itself passes the gate
        refused = [b"https://" + org + b"fs-agent-nl2sql/actions/runs/1",
                   org + b"database-agent-ui", org + b"futuresmart-website/pull/2"]
        for text in allowed:
            self.assertIsNone(export_source.PRIVATE_LINK.search(text), text)
        for text in refused:
            self.assertIsNotNone(export_source.PRIVATE_LINK.search(text), text)


@unittest.skipUnless((ROOT / ".git").exists(), "needs the development repository")
class SnapshotTests(unittest.TestCase):
    def test_snapshot_of_head_excludes_private_and_hosted_files(self):
        files = export_source.snapshot("HEAD")
        self.assertIn("backend/main.py", files)
        self.assertIn("frontend/package.json", files)
        self.assertIn("mcp-server/pyproject.toml", files)
        self.assertNotIn(export_source.MANIFEST, files)
        self.assertFalse([n for n in files if n.startswith("internal/")])
        self.assertEqual([n for n in files if n.startswith(".github/workflows/")], [".github/workflows/standalone-product.yml"])
        self.assertNotIn("AGENTS.md", files)


class DriftTests(unittest.TestCase):
    """A file edited in the public repository after an export stops the next publication."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q")
        git(self.dir, "config", "user.email", "test@example.invalid")
        git(self.dir, "config", "user.name", "test")
        (self.dir / "docs").mkdir()
        (self.dir / "a.txt").write_bytes(b"a\n")
        manifest = {"distribution": "clean-source-snapshot", "files": {"a.txt": hashlib.sha256(b"a\n").hexdigest()}}
        (self.dir / export_source.MANIFEST).write_text(json.dumps(manifest))
        git(self.dir, "add", "--all", "--", ".")
        git(self.dir, "commit", "-q", "-m", "export")

    def test_an_exported_checkout_has_no_drift(self):
        self.assertEqual(publish_public.drift(self.dir), [])

    def test_direct_public_edits_are_reported(self):
        (self.dir / "a.txt").write_bytes(b"edited in public\n")
        (self.dir / "b.txt").write_bytes(b"new\n")
        git(self.dir, "add", "--all", "--", ".")
        git(self.dir, "commit", "-q", "-m", "direct edit")
        self.assertEqual(publish_public.drift(self.dir),
                         ["a.txt (changed after export)", "b.txt (not in the last export)"])

    def test_pending_lists_what_a_publication_changes(self):
        files = {"a.txt": (b"a\n", 0o644), "c.txt": (b"c\n", 0o644)}
        self.assertEqual(publish_public.pending(self.dir, files), ["A c.txt"])


if __name__ == "__main__":
    unittest.main()
