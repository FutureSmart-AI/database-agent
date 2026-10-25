"""Export the product source without private Git history or hosted operations.

Usage: python deploy/export_source.py /absolute/new-output.tar [--rev HEAD]
The output must not exist. Without --rev the staged tree is exported, so review/stage
the candidate first. The public repository FutureSmart-AI/database-agent is published
from this snapshot by deploy/publish_public.py; see docs/publication.md.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/source-export.json"
PUBLIC_REPOSITORY = "https://github.com/FutureSmart-AI/database-agent"
# The only workflow the public snapshot carries is its own CI. Every other workflow runs
# hosted operations from this repository and is `export-ignore` in .gitattributes.
PUBLIC_WORKFLOWS = {".github/workflows/standalone-product.yml"}
# Links into FutureSmart repositories other than the public one are dead (private) links
# in the snapshot; the source must say "private; link omitted" instead.
PRIVATE_LINK = re.compile(rb"github\.com/FutureSmart-AI/(?!database-agent(?:[/.#)\"'\s]|$))[A-Za-z0-9_.-]+")


def snapshot(rev=None):
    """Return {path: (bytes, mode)} for the exported tree of `rev` (default: the staged tree)."""
    tree = rev or subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip()
    # Blob bytes exactly as committed, on every platform.
    data = subprocess.check_output(["git", "-c", "core.autocrlf=false", "archive", "--format=tar", tree], cwd=ROOT)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe archive path")
            if member.isdir() or member.name == MANIFEST:
                continue
            if not member.isfile():
                raise ValueError("Only regular source files are supported")
            if "internal" in path.parts or ".git" in path.parts:
                raise ValueError("Private source exclusion failed")
            if member.name.startswith(".github/workflows/") and member.name not in PUBLIC_WORKFLOWS:
                raise ValueError(f"Hosted workflow entered source export (mark it export-ignore): {member.name}")
            if path.name.startswith(".env") and path.name != ".env.example":
                raise ValueError("Environment file entered source export")
            content = source.extractfile(member).read()
            if PRIVATE_LINK.search(content):
                raise ValueError(f"Link to a private FutureSmart repository in {member.name}")
            files[member.name] = (content, 0o755 if member.mode & 0o111 else 0o644)
    return files


def manifest(files, source_commit=None):
    """The snapshot manifest: exact file hashes; it omits its own hash."""
    data = {
        "distribution": "clean-source-snapshot",
        "project_license": "Apache-2.0; bundled fonts retain their SIL OFL notices",
        "copyright": "Copyright 2026 FutureSmart AI",
        "source_repository": PUBLIC_REPOSITORY,
        "exclusions": ["private Git history", "internal evidence and assets",
                       "hosted deployment, rollback, evaluation and publication workflows"],
    }
    if source_commit:
        data["source_commit"] = source_commit
    data["files"] = {name: hashlib.sha256(content).hexdigest() for name, (content, _) in sorted(files.items())}
    return (json.dumps(data, indent=2) + "\n").encode()


def export(destination, rev=None):
    files = snapshot(rev)
    files[MANIFEST] = (manifest(files), 0o644)
    with destination.open("xb") as output, tarfile.open(fileobj=output, mode="w") as archive:
        for name, (content, mode) in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = mode
            archive.addfile(member, io.BytesIO(content))
    print(f"Exported {len(files)} files; Apache-2.0 source snapshot; bundled font notices retained.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--rev", help="commit to export instead of the staged tree")
    args = parser.parse_args()
    export(args.destination.resolve(), args.rev)
