#!/usr/bin/env bash
# Make an archived release the live one.
#
#   scripts/promote-release.sh <release sha>
#
# Env: S3_BUCKET; optional S3_KEY_ROOT (a key prefix both route trees sit
# under; empty = the bucket root). Used by deploy.yml after archiving a fresh
# build and by rollback.yml to put an older one back — one code path both ways.
#
# Keys mirror URL paths, because CloudFront forwards the full path:
#   /database-agent/…  ->  <root>/database-agent/…   (the product, and its _next/)
#   /nl2sql/…          ->  <root>/nl2sql/…           (retired URLs: redirect stubs)
# `/nl2sql/api/*` is the NL2SQL service and must be routed to it ahead of the
# `/nl2sql/*` behaviour; nothing here is ever written under `nl2sql/api/`.
#
# Order matters for anyone with the app open while this runs:
#   1. hashed chunks first, and never deleted: a tab still running the previous
#      release keeps lazy-loading its own chunks, and a rollback finds them;
#   2. then the HTML routes, which switch readers over, with --delete so a
#      route that no longer exists stops being served.
set -euo pipefail

RELEASE="${1:?usage: promote-release.sh <release sha>}"
: "${S3_BUCKET:?S3_BUCKET is required}"
ROOT="s3://$S3_BUCKET${S3_KEY_ROOT:+/$S3_KEY_ROOT}"
APP="$ROOT/database-agent"
LEGACY="$ROOT/nl2sql"
ARCHIVE="s3://$S3_BUCKET/_releases/$RELEASE"

if ! aws s3 ls "$ARCHIVE/database-agent/index.html" >/dev/null; then
  echo "::error::No archived release at $ARCHIVE — deploy it first or pick another sha."
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Download and re-upload rather than copying S3 to S3, so every object gets the
# content type and cache policy set below instead of inheriting the archive's.
aws s3 sync "$ARCHIVE/" "$WORK/" --only-show-errors
# `aws s3 sync` uploads a file only when its size differs or the local copy is
# newer. A download keeps the archive's timestamps, which are older than what is
# live, so on a rollback every same-size file — `release.txt`, any HTML route
# whose size happens to match — was silently skipped and the newer release kept
# serving. Stamping the working copy "now" makes the promote authoritative.
find "$WORK" -type f -exec touch {} +
echo "Promoting $RELEASE to $APP/ and $LEGACY/"

NOCACHE="public, max-age=0, must-revalidate"

aws s3 sync "$WORK/_next/static/" "$APP/_next/static/" \
  --cache-control "public, max-age=31536000, immutable" --only-show-errors

aws s3 sync "$WORK/_next/" "$APP/_next/" --exclude "static/*" \
  --cache-control "$NOCACHE" --only-show-errors

aws s3 sync "$WORK/database-agent/" "$APP/" \
  --exclude "_next/*" --exclude "404.html" \
  --cache-control "$NOCACHE" --delete --only-show-errors

aws s3 sync "$WORK/nl2sql/" "$LEGACY/" --exclude "api/*" \
  --cache-control "$NOCACHE" --delete --only-show-errors

aws s3 cp "$WORK/404.html" "$APP/404.html" \
  --cache-control "$NOCACHE" --only-show-errors

echo "$RELEASE is live."
