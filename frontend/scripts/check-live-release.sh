#!/usr/bin/env bash
# Poll the live product until it serves the expected release.
#
#   scripts/check-live-release.sh <product url> <release sha>
#
# A wrong bucket prefix uploads cleanly and the old page keeps answering 200,
# so "the sync succeeded" proves nothing. This reads the `release.txt` the
# build stamped, and checks the page asks for its assets under the product's
# own prefix, retrying while the CloudFront invalidation propagates.
set -euo pipefail

URL="${1:?usage: check-live-release.sh <product url> <release sha>}"
RELEASE="${2:?usage: check-live-release.sh <product url> <release sha>}"
URL="${URL%/}/"

for attempt in $(seq 1 30); do
  served="$(curl -fsS "${URL}release.txt?check=$attempt" 2>/dev/null || true)"
  if [ "$served" = "$RELEASE" ]; then
    if curl -fsS "$URL" | grep -q '/database-agent/_next/'; then
      echo "Live: $URL serves $RELEASE."
      exit 0
    fi
    echo "::error::$URL serves $RELEASE but its HTML does not reference /database-agent/_next/."
    exit 1
  fi
  echo "Attempt $attempt: serving '${served:-nothing}', waiting for $RELEASE…"
  sleep 10
done

echo "::error::$URL did not serve $RELEASE within 5 minutes — check S3_KEY_PREFIX and the CloudFront behaviour."
exit 1
