#!/usr/bin/env bash
# Secret scan condiviso (audit #105 / roadmap #153 — voce H3).
#
# Difesa-in-profondità contro il commit accidentale di segreti. Fonte UNICA dei pattern,
# usata sia dal gate CI (`forbidden-files`) sia dall'hook pre-commit locale
# (`.githooks/pre-commit`), così le regole non divergono.
#
# Stampa SOLO i path dei file sospetti — il valore del segreto NON viene mai stampato —
# ed esce 1 se trova qualcosa, 0 altrimenti.
#
# Uso:
#   tools/secret_scan.sh [file...]   # scansiona i file indicati
#   tools/secret_scan.sh             # scansiona tutti i file tracciati (git ls-files)
#
# Nota: i pattern sono ad ALTO segnale, scelti per ~zero falsi positivi (verificati a 0
# match sul repo). chat-id e path utente NON sono inclusi come regex di contenuto: come
# stringhe sono comuni nei doc/test (alto rischio di falsi positivi) e sono già coperti
# dal blocco file di `forbidden-files` (es. `config.json` reale non è committabile).
set -u

PATTERNS=(
  '[0-9]{8,10}:[A-Za-z0-9_-]{35}'          # token bot Telegram "<id>:<35 char>"
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'     # blocco chiave privata PEM
  'AKIA[0-9A-Z]{16}'                       # AWS Access Key ID
)
NAMES=(
  'Telegram bot token'
  'PEM private key'
  'AWS access key id'
)

if [ "$#" -gt 0 ]; then
  files=("$@")
else
  mapfile -t files < <(git ls-files)
fi

# Nessun file da scansionare: niente da fare (evita che grep legga da stdin e si blocchi).
if [ "${#files[@]}" -eq 0 ]; then
  echo "OK: nessun file da scansionare."
  exit 0
fi

found=0
scan_error=0
for i in "${!PATTERNS[@]}"; do
  # -I salta i binari; -l stampa SOLO i path (segreto mai stampato); -E ERE; -- fine opzioni.
  hits=$(grep -lIE -- "${PATTERNS[$i]}" "${files[@]}" 2>/dev/null)
  rc=$?
  # grep: 0 = match, 1 = nessun match, >=2 = ERRORE reale (file illeggibile, encoding, ...).
  # Un errore NON deve passare per "pulito": un gate di sicurezza fa FAIL-CLOSED (review
  # CodeRabbit #155), altrimenti un segreto potrebbe sfuggire silenziosamente.
  if [ "$rc" -ge 2 ]; then
    scan_error=1
    echo "::error::grep ha fallito (rc=$rc) sul pattern ${NAMES[$i]}: scan non affidabile." >&2
  fi
  if [ -n "$hits" ]; then
    found=1
    echo "::error::Possibile segreto (${NAMES[$i]}) in file tracciati (valore redatto):"
    echo "$hits"
  fi
done

if [ "$found" -ne 0 ] || [ "$scan_error" -ne 0 ]; then
  exit 1
fi
echo "OK: nessun segreto noto rilevato."
