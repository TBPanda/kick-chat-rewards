#!/usr/bin/env bash
# Generate an unencrypted RSA key pair for Snowflake service-user auth.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT}/.secrets"
mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

PRIV="${OUT_DIR}/snowflake_kick_ingest_key.pem"
PUB="${OUT_DIR}/snowflake_kick_ingest_key.pub"
PUB_BODY="${OUT_DIR}/snowflake_kick_ingest_key.pubbody"

openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out "${PRIV}" -nocrypt
openssl rsa -in "${PRIV}" -pubout -out "${PUB}"

# Snowflake wants the public key body without header/footer
grep -v 'BEGIN PUBLIC\|END PUBLIC' "${PUB}" | tr -d '\n' > "${PUB_BODY}"
echo >> "${PUB_BODY}"

echo "Private key: ${PRIV}"
echo "Public key:  ${PUB}"
echo "Public body (paste into sql/004_service_user.sql):"
echo "-----"
cat "${PUB_BODY}"
echo "-----"
echo
echo "For Railway SNOWFLAKE_PRIVATE_KEY, use a single line with \\n:"
python3 - <<PY
from pathlib import Path
pem = Path("${PRIV}").read_text()
print(pem.replace("\n", "\\n"))
PY
echo
echo "Keep .secrets/ out of git (already gitignored if listed)."
