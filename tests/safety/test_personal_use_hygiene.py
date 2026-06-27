"""Safety hygiene del blocco personale (issue #86): niente cloud/licenze/admin nel
codice, e nessuna operazione di scommessa fuori dal guard read-only.

Scansiona SOLO i sorgenti Python del package `xtrader_bridge/`:
- nessun riferimento a Supabase / service_role / license key / Admin EXE
  (il bridge personale è 100% locale, senza cloud/licenze/gestionale);
- nessuna delle 4 operazioni di scommessa Betfair nominata nei moduli `betfair/`,
  con l'unica eccezione di `safety.py`, che è il punto autorizzato a definirle nel
  guard read-only. Qualsiasi futuro modulo che voglia instradare un'operazione DEVE
  passare dal guard, non nominare l'operazione direttamente.
"""

import os

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PKG_DIR = os.path.join(_REPO_ROOT, "xtrader_bridge")
_BETFAIR_DIR = os.path.join(_PKG_DIR, "betfair")

# Termini cloud/licenze/admin vietati nel codice del bridge personale (case-insensitive).
_FORBIDDEN_TERMS = (
    "supabase",
    "service_role",
    "license_key",
    "licensekey",
    "admin_exe",
    "adminexe",
)

# Le 4 operazioni di scommessa: vietate nei moduli betfair/ tranne il guard.
_BETTING_OPS = ("placeorders", "cancelorders", "replaceorders", "updateorders")

# Provider di pagamento: nomi non ambigui che NON devono mai comparire nel codice del
# bridge personale (issue #86: niente pagamenti). Non includo la parola generica
# "payment"/"pagamento" perché può comparire legittimamente in un commento di divieto.
_PAYMENT_TERMS = (
    "stripe", "paypal", "braintree", "razorpay", "adyen",
    "payment_intent", "checkout_session", "billing_portal",
)

import re  # noqa: E402

# Funzioni di backup/import/export del dizionario nel subpackage Betfair: vietate
# (issue #86: niente backup/import/export Betfair). Cattura sia il nome **nudo**
# (`def export(`) sia con suffisso (`def export_dictionary(`) — l'underscore dopo il
# verbo è opzionale (CodeRabbit/Codex su #178 §3: prima `def export(` sfuggiva). Resta
# scoped a `betfair/`: nel package esistono `export_parser`/`import_parser` LEGITTIMI
# (import/export di un PARSER su file locale, non il dizionario Betfair, non cloud).
_BETFAIR_EXPORT_RE = re.compile(
    r"def\s+(export|backup|upload|import|dump)[a-z0-9_]*\s*\(", re.IGNORECASE)

# SDK / host / forme "cloud": vietati in TUTTO il package (niente cloud sync; un export
# del dizionario verso il cloud da QUALSIASI modulo sarebbe una violazione, non solo da
# `betfair/`). Nessun uso legittimo nel bridge personale (verificato con grep).
_CLOUD_PATTERNS = (
    re.compile(r"\b(boto3?|botocore|google\.cloud|googleapis|dropbox|onedrive|"
               r"firebase|azure\.storage|gcs_bucket|smart_open)\b", re.IGNORECASE),
    re.compile(r"s3[._]amazonaws|\bto_s3\b|\bto_gcs\b|\bto_cloud\b|upload_to_|"
               r"save_\w*_to_(?:s3|cloud|gcs|dropbox)", re.IGNORECASE),
)


def _py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        # niente cache/bytecode
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _read(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def test_nessun_riferimento_cloud_licenza_admin_nel_package():
    offenders = []
    for path in _py_files(_PKG_DIR):
        low = _read(path).casefold()
        hits = [term for term in _FORBIDDEN_TERMS if term in low]
        if hits:
            rel = os.path.relpath(path, _REPO_ROOT)
            offenders.append((rel, hits))
    assert not offenders, f"Riferimenti cloud/licenza/admin nel codice: {offenders}"


def test_betfair_subpackage_esiste_ed_e_read_only():
    # Il subpackage del blocco personale esiste con il suo guard.
    assert os.path.isdir(_BETFAIR_DIR), "manca il subpackage xtrader_bridge/betfair/"
    assert os.path.isfile(os.path.join(_BETFAIR_DIR, "safety.py"))


def test_nessuna_operazione_di_scommessa_fuori_dal_guard():
    # In betfair/ solo safety.py può nominare le operazioni di scommessa (è il guard).
    offenders = []
    for path in _py_files(_BETFAIR_DIR):
        if os.path.basename(path) == "safety.py":
            continue
        low = _read(path).casefold()
        hits = [op for op in _BETTING_OPS if op in low]
        if hits:
            rel = os.path.relpath(path, _REPO_ROOT)
            offenders.append((rel, hits))
    assert not offenders, (
        f"Operazioni di scommessa nominate fuori dal guard read-only: {offenders}")


def test_nessun_provider_di_pagamento_nel_package():
    # DoD issue #86: niente pagamenti. Nessun nome di payment provider nel codice.
    offenders = []
    for path in _py_files(_PKG_DIR):
        low = _read(path).casefold()
        hits = [term for term in _PAYMENT_TERMS if term in low]
        if hits:
            rel = os.path.relpath(path, _REPO_ROOT)
            offenders.append((rel, hits))
    assert not offenders, f"Riferimenti a provider di pagamento nel codice: {offenders}"


def test_nessun_backup_import_export_dizionario_betfair():
    # DoD issue #86: niente backup/import/export del dizionario Betfair. Nessuna funzione
    # export/backup/upload/import/dump (nuda o con suffisso) nel subpackage betfair/.
    offenders = []
    for path in _py_files(_BETFAIR_DIR):
        if _BETFAIR_EXPORT_RE.search(_read(path)):
            offenders.append(os.path.relpath(path, _REPO_ROOT))
    assert not offenders, (
        f"Funzioni di backup/import/export del dizionario Betfair: {offenders}")


def test_nessun_sdk_o_host_cloud_nel_package():
    # DoD issue #86: niente cloud sync / dati fuori dal PC. Nessun SDK o host cloud in
    # NESSUN modulo del package (scope ampio: un export remoto da qualsiasi modulo è vietato).
    offenders = []
    for path in _py_files(_PKG_DIR):
        text = _read(path)
        hits = [p.pattern for p in _CLOUD_PATTERNS if p.search(text)]
        if hits:
            offenders.append((os.path.relpath(path, _REPO_ROOT), hits))
    assert not offenders, f"SDK/host cloud nel package: {offenders}"
