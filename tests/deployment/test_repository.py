"""Check the actual tracked product tree, not a separate export allowlist."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def tracked_files():
    if not (ROOT / ".git").exists():
        manifest = json.loads((ROOT / "docs/source-export.json").read_text())
        if manifest.get("distribution") != "clean-source-snapshot":
            raise ValueError("Unrecognized source distribution")
        files = list(manifest["files"])
        for name, expected in manifest["files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Exported file changed: {name}")
        return files + ["docs/source-export.json"]
    return [p for p in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0") if p]


def scan(files):
    patterns = {
        "provider credential": rb"\b(?:sk-proj-|sk-ant-|gsk_)[A-Za-z0-9_-]{24,}",
        "Google credential": rb"\bAIza[A-Za-z0-9_-]{30,}",
        "AWS credential": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "AWS account resource": rb"(?:\d{12}\.dkr\.ecr\.|arn:aws:[^\s\"']*:\d{12}:)",
        "private infrastructure ID": rb"\b(?:sg|subnet|vpc|vol)-[0-9a-f]{8,}\b",
        "database endpoint": rb"\b[A-Za-z0-9.-]+\.rds\.amazonaws\.com\b",
    }
    findings = []
    for name in files:
        if Path(name).name.startswith(".env") and Path(name).name != ".env.example":
            findings.append((name, "real environment file"))
        data = (ROOT / name).read_bytes()
        for category, pattern in patterns.items():
            inspected = data
            if category == "database endpoint":
                # Existing UI input placeholders use an unmistakable example ID.
                inspected = re.sub(rb"\bmydb\.abc123\.us-east-1\.rds\.amazonaws\.com\b", b"example.invalid", inspected)
            if re.search(pattern, inspected):
                findings.append((name, category))
    return findings  # Deliberately never includes a matched value or secret fingerprint.


class ProductTreeTests(unittest.TestCase):
    def test_current_tracked_tree_has_no_known_credentials_or_private_deployment_ids(self):
        self.assertEqual(scan(tracked_files()), [])

    def test_layout_contains_only_clear_product_entry_points(self):
        files = tracked_files()
        roots = {p.split("/")[0] for p in files}
        allowed = {".env.example", ".gitattributes", ".github", ".gitignore", "README.md", "LICENSE", "NOTICE",
                   "AGENTS.md", "CLAUDE.md", "backend", "frontend", "mcp-server", "deploy", "docs", "tests",
                   "internal", "compose.yaml"}
        self.assertEqual(roots - allowed, set())
        for prefix in ("saas db/", "saas evals/", "spider evals/", "evals/", "scripts/", "standalone/"):
            self.assertFalse(any(p.startswith(prefix) for p in files), prefix)
        self.assertTrue((ROOT / "backend/standalone/baseline.sql").is_file())
        self.assertTrue((ROOT / "frontend/Dockerfile").is_file())

    def test_tracked_private_memory_is_excluded_from_native_source_snapshots(self):
        if (ROOT / "docs/source-export.json").is_file():
            self.assertEqual(json.loads((ROOT / "docs/source-export.json").read_text())["distribution"],
                             "clean-source-snapshot")
            names = tracked_files()
            self.assertFalse((ROOT / "internal").exists())
            self.assertFalse(any("internal" in Path(p).parts for p in names))
            self.assertEqual(sorted(p.name for p in (ROOT / ".github/workflows").glob("*.yml")),
                             ["standalone-product.yml"])
            self.assertFalse((ROOT / "AGENTS.md").exists())
            return
        private = [p for p in tracked_files() if p.startswith("internal/")]
        self.assertIn("internal/STATUS.md", private)
        # Archive the actual staged tree, including tracked private files. This
        # checks export rules rather than pretending .gitignore hides tracked data.
        tree = subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip()
        data = subprocess.check_output(["git", "archive", "--format=tar", tree], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            names = archive.getnames()
        self.assertIn("backend/main.py", names)
        self.assertIn("frontend/Dockerfile", names)
        self.assertFalse(any(p == "internal" or p.startswith("internal/") for p in names))

    def test_both_image_contexts_exclude_private_memory(self):
        compose = (ROOT / "compose.yaml").read_text()
        private = ROOT / "internal"
        for name in ("backend", "frontend"):
            self.assertIn("context: ./" + name, compose)
            self.assertFalse(private.is_relative_to(ROOT / name))
            rules = (ROOT / name / ".dockerignore").read_text()
            self.assertIn("**/internal/", rules)

    def test_sources_preserve_the_layout_snapshot_except_recorded_followup_changes(self):
        manifest = json.loads((ROOT / "docs/source-preservation.json").read_text())
        changes = manifest.get("reviewed_changes", {})
        self.assertFalse(set(changes) - set(manifest["unchanged_files"]))
        for name, digest in manifest["unchanged_files"].items():
            with self.subTest(path=name):
                if name in changes:
                    change = changes[name]
                    self.assertEqual(change["baseline_sha256"], digest)
                    self.assertTrue(change["issue"] and change["reason"])
                    digest = change["current_sha256"]
                data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_shell_scripts_the_workflows_run_are_executable(self):
        # Workflows call these directly (`scripts/promote-release.sh`); a 100644 mode failed
        # the first hosted deploy from this repository with "Permission denied".
        if not (ROOT / ".git").exists():
            self.skipTest("file modes come from the Git index")
        entries = subprocess.check_output(["git", "ls-files", "-s", "--", "*.sh"], cwd=ROOT, text=True).splitlines()
        self.assertTrue(entries)
        for entry in entries:
            mode, _, _, name = entry.split(maxsplit=3)
            self.assertEqual(mode, "100755", name)

    def test_automation_does_not_publish_or_write_to_external_task_systems(self):
        # Only the product CI and the hosted frontend deploy run on push. The deploy is
        # limited to main and to changes under frontend/ (its OIDC role trusts only main);
        # everything else that reaches production or the public repository is manual.
        for name in (ROOT / ".github/workflows").glob("*.yml"):
            text = name.read_text()
            if name.name == "frontend-deploy.yml":
                self.assertIn("    branches: [main]\n    paths:\n      - \"frontend/**\"", text)
                self.assertIn("github.ref == 'refs/heads/main'", text)
            elif name.name != "standalone-product.yml":
                self.assertIn("workflow_dispatch:", text)
                self.assertNotIn("  push:", text)
            self.assertNotIn("push_docs_to_clickup", text)
            self.assertNotIn(".env.prod", text)


if __name__ == "__main__":
    unittest.main()
