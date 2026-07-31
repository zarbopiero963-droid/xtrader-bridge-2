#!/usr/bin/env python3
"""Gate dei **percorsi** vietati — PR-D del piano #194.

Sostituisce le `grep -E` scritte a mano dentro `.github/workflows/forbidden-files.yml`. Non è un
cambio di forma: quelle `grep` erano una **copia** dei pattern, e le copie divergono. Misurato
sul repo prima di questa PR: il workflow cercava un bot-id Telegram `[0-9]{8,10}` mentre
`tools/secret_scan.py` cercava `[0-9]{8,12}` — il gate CI non intercettava i bot-id lunghi che
l'hook pre-commit intercettava. Ora le regole vivono solo in `tools/secret_policy.py`.

Cosa controlla, sui file **tracciati**:

1. i file che `.gitignore` direbbe di ignorare ma che risultano tracciati lo stesso
   (`git ls-files -i -c`): è `.gitignore` a fare da fonte, quindi nessuna regex da mantenere;
2. la rete **case-insensitive** di `secret_policy.PERCORSI_VIETATI`, che copre le varianti
   Windows che al punto 1 sfuggono (su Linux `.gitignore` è case-sensitive: `Config.json`,
   `.ENV`, `secret.EXE` non verrebbero visti);
3. i CSV: ammesso solo `data/dizionario_xtrader.csv` (file dati versionato).

Il controllo dei **contenuti** (token, chiavi, seed) non è qui: lo fa `tools/secret_scan.py`,
invocato subito dopo nello stesso job, che è l'unica fonte dei pattern di contenuto.

**Fail-closed**: se `git` fallisce, il gate non passa per "pulito" — esce 1 dicendo perché.

Uso:
  python tools/forbidden_paths.py     # controlla i file tracciati nel repo corrente
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import secret_policy  # noqa: E402  (dopo il sys.path: il modulo vive accanto a questo file)


def _git(args):
    """Esegue `git <args>` catturando l'output testuale. Ritorna il CompletedProcess."""
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _righe(r) -> list:
    """Le righe non vuote dello stdout di un CompletedProcess."""
    return [p for p in r.stdout.splitlines() if p.strip()]


def _segnala(titolo: str, percorsi: list) -> None:
    """Stampa un gruppo di violazioni: SOLO i percorsi (nessun contenuto di file)."""
    print(f"{titolo}:")
    for p in percorsi:
        print(f"  {p}")


def main() -> int:
    """Ritorna 0 se tutto è pulito, 1 se trova un file vietato o se `git` non è utilizzabile."""
    ignorati_ma_tracciati = _git(["ls-files", "-i", "-c", "--exclude-standard"])
    tutti = _git(["ls-files"])
    for r, cosa in ((ignorati_ma_tracciati, "git ls-files -i -c"), (tutti, "git ls-files")):
        if r.returncode != 0:
            print(f"::error::{cosa} fallito (controllo non affidabile).", file=sys.stderr)
            return 1

    tracciati = _righe(tutti)
    vietati = [p for p in tracciati if secret_policy.PERCORSI_VIETATI.search(p)]
    csv_estranei = [p for p in tracciati
                    if p.lower().endswith(".csv") and p not in secret_policy.CSV_CONSENTITI]
    ignorati = _righe(ignorati_ma_tracciati)

    if not (ignorati or vietati or csv_estranei):
        print("OK: nessun file vietato tracciato.")
        return 0

    print("::error::File vietati tracciati nel repository:")
    if ignorati:
        _segnala("Ignorati da .gitignore ma tracciati", ignorati)
    if vietati:
        _segnala("Config/segreti/stati del License Manager/artefatti (qualsiasi maiuscola)",
                 vietati)
    if csv_estranei:
        _segnala("CSV non ammessi (solo data/dizionario_xtrader.csv)", csv_estranei)
    return 1


if __name__ == "__main__":
    sys.exit(main())
