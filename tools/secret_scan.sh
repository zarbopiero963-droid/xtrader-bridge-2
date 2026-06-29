#!/usr/bin/env bash
# Wrapper di RETRO-COMPATIBILITÀ. Lo scanner canonico è ora `tools/secret_scan.py`
# (cross-platform, Windows GitHub Actions incluso): qui si delega soltanto, così esiste
# un'unica fonte di pattern e logica. Mantenuto perché qualche entrypoint/doc poteva
# riferirsi a questo path; i nuovi chiamanti (test, hook, CI) usano direttamente il .py.
#
# Uso:
#   tools/secret_scan.sh [file...]   # scansiona i file indicati
#   tools/secret_scan.sh             # scansiona tutti i file tracciati (git ls-files)
set -u

here="$(cd "$(dirname "$0")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "::error::python non trovato: scan non affidabile (fail-closed)." >&2
  exit 1
fi

exec "$PY" "$here/secret_scan.py" "$@"
