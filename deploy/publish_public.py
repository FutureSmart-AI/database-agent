"""Publish this repository's source snapshot to the public FutureSmart-AI/database-agent repository.

Usage: python deploy/publish_public.py --public-dir <clone of the public repository> [--rev HEAD] [--check]
       [--adopt-public-head SHA]

The public repository is an export of this one, never a second place to develop: every
public commit after the first is produced here. Before writing anything this tool checks
that the public checkout still matches the manifest of its last export; a file changed
directly in the public repository stops the publication until that change has been brought
into this repository. --check runs every gate and reports the pending changes without
writing. Without --check it replaces the public checkout's files with the snapshot and
commits there; pushing is left to the caller (.github/workflows/public-release.yml).

--adopt-public-head names a public commit whose direct edits have already been brought into
this repository by hand; the drift gate then lists them and continues, for that commit only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_source import MANIFEST, ROOT, manifest, snapshot  # noqa: E402


def git(cwd, *args):
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", *args], cwd=cwd)


def drift(public):
    """Paths whose committed public content differs from the public repository's own last manifest."""
    tracked = [p for p in git(public, "ls-files", "-z").decode().split("\0") if p]
    recorded = json.loads(git(public, "show", f"HEAD:{MANIFEST}"))["files"]
    found = []
    for name in tracked:
        if name == MANIFEST:
            continue
        digest = hashlib.sha256(git(public, "show", f"HEAD:{name}")).hexdigest()
        if recorded.get(name) != digest:
            found.append(f"{name} ({'not in the last export' if name not in recorded else 'changed after export'})")
    found += [f"{name} (deleted after export)" for name in sorted(set(recorded) - set(tracked))]
    return found


def pending(public, files):
    """Paths the snapshot would add, change or delete in the public checkout's HEAD."""
    recorded = json.loads(git(public, "show", f"HEAD:{MANIFEST}"))["files"]
    current = {name: hashlib.sha256(content).hexdigest() for name, (content, _) in files.items()}
    changes = [f"A {n}" for n in sorted(set(current) - set(recorded))]
    changes += [f"M {n}" for n in sorted(n for n in set(current) & set(recorded) if current[n] != recorded[n])]
    changes += [f"D {n}" for n in sorted(set(recorded) - set(current))]
    return changes


def write(public, files):
    for name in [p for p in git(public, "ls-files", "-z").decode().split("\0") if p]:
        if name not in files:
            (public / name).unlink()
    for name, (content, mode) in files.items():
        target = public / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--adopt-public-head", metavar="SHA")
    args = parser.parse_args()
    public = args.public_dir.resolve()
    source_commit = git(ROOT, "rev-parse", args.rev).decode().strip()

    edited = drift(public)
    public_head = git(public, "rev-parse", "HEAD").decode().strip()
    adopted = bool(edited) and bool(args.adopt_public_head) and public_head.startswith(args.adopt_public_head)
    if edited:
        print("The public repository was changed outside this export"
              + (f"; adopting {public_head[:12]}, whose edits are already in the development repository:"
                 if adopted else ". Bring these changes into the development repository first, then publish again:"))
        print("\n".join(f"  {line}" for line in edited))
        if not adopted:
            return 2

    files = snapshot(source_commit)
    changes = pending(public, files)
    print(f"Source commit {source_commit}: {len(files)} files, {len(changes)} changed in the public repository.")
    print("\n".join(f"  {line}" for line in changes))
    if args.check or not changes:
        return 0

    files[MANIFEST] = (manifest(files, source_commit), 0o644)
    write(public, files)
    git(public, "add", "--all", "--", ".")
    git(public, "commit", "--quiet", "-m",
        f"Release from the development repository at {source_commit[:12]}\n\n"
        f"{len(changes)} files changed. Exported by deploy/publish_public.py; see docs/publication.md."
        + (f"\nAdopts direct public edits up to {public_head[:12]}, already in the development repository."
           if adopted else ""))
    print(git(public, "log", "-1", "--format=%H %s").decode().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
