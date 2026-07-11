"""Safety hygiene del blocco personale (issue #86): niente cloud/licenze/admin nel
codice, e nessuna operazione di scommessa fuori dal guard read-only.

Scansiona SOLO i sorgenti Python del package `xtrader_bridge/`:
- nessun riferimento a Supabase / service_role / license key / Admin EXE
  (il bridge personale è 100% locale, senza cloud/licenze/gestionale);
- nessuna delle 4 operazioni di scommessa Betfair nominata nei moduli `betfair/`.
  Con la rimozione della funzione «Betfair Sync» il subpackage non contiene più alcun
  client di rete/login: sopravvivono SOLO il dizionario locale e i suoi lettori (sola
  lettura, nessuna rete), quindi nessun modulo può più nominare un'operazione di scommessa.
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
# (issue #86: niente backup/import/export Betfair). Cattura il nome **nudo** (`def export(`),
# con **suffisso** (`def export_dictionary(`) E **privato** con underscore iniziale
# (`def _export_dictionary(`, `def _backup(`): sia l'underscore dopo il verbo (`[a-z0-9_]*`)
# sia quelli **prima** (`_*`) sono opzionali (CodeRabbit/Codex su #178 §3 / #183: prima
# `def export(` e poi `def _export(` sfuggivano). Resta scoped a `betfair/`: nel package
# esistono `export_parser`/`import_parser` LEGITTIMI (import/export di un PARSER su file
# locale, non il dizionario Betfair, non cloud), fuori da questo subpackage.
_BETFAIR_EXPORT_RE = re.compile(
    r"def\s+_*(export|backup|upload|import|dump)[a-z0-9_]*\s*\(", re.IGNORECASE)

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
    # Il subpackage del dizionario locale esiste (sola lettura, nessuna rete). Dopo la
    # rimozione di «Betfair Sync» non c'è più alcun client di login/rete né guard di
    # scommessa: sopravvivono solo local_db + i lettori del dizionario.
    assert os.path.isdir(_BETFAIR_DIR), "manca il subpackage xtrader_bridge/betfair/"
    assert os.path.isfile(os.path.join(_BETFAIR_DIR, "local_db.py"))
    # Nessun modulo di rete/login deve essere ricomparso.
    for gone in ("auth_client.py", "catalogue_client.py", "credential_store.py",
                 "session.py", "sync_engine.py", "auto_sync.py"):
        assert not os.path.isfile(os.path.join(_BETFAIR_DIR, gone)), (
            f"il modulo di rete/login «{gone}» non deve riesistere dopo la rimozione di Betfair Sync")


def test_nessuna_operazione_di_scommessa_nel_subpackage():
    # Nessun modulo betfair/ può nominare le 4 operazioni di scommessa: non esiste più
    # alcun client di rete, quindi nessun uso legittimo.
    offenders = []
    for path in _py_files(_BETFAIR_DIR):
        low = _read(path).casefold()
        hits = [op for op in _BETTING_OPS if op in low]
        if hits:
            rel = os.path.relpath(path, _REPO_ROOT)
            offenders.append((rel, hits))
    assert not offenders, (
        f"Operazioni di scommessa nominate nel subpackage dizionario: {offenders}")


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


def test_betfair_export_regex_copre_nudo_privato_e_suffisso():
    """#183 (Codex P2): il guard DoD deve intercettare le funzioni backup/import/export/
    upload/dump del dizionario Betfair anche quando sono **private** (underscore iniziale) —
    `def _export_dictionary(`, `def _backup(` — non solo nude o con suffisso. Prima la regex
    richiedeva il verbo subito dopo `def `, così un helper privato sfuggiva al controllo
    (falso negativo). Questo test blocca quella regressione esercitando la regex reale."""
    forbidden = [
        "def export(",                         # nudo
        "def backup ( ",                       # spazi
        "def upload_to_x(",                    # suffisso
        "def import_dictionary(self):",        # suffisso
        "def dump_all(",                       # suffisso
        "def _export_dictionary(self):",       # PRIVATO (prima sfuggiva)
        "def _backup(x):",                     # PRIVATO
        "def __upload(y):",                    # doppio underscore
        "def _dump(",                          # privato nudo
    ]
    for snippet in forbidden:
        assert _BETFAIR_EXPORT_RE.search(snippet), f"guard non intercetta: {snippet!r}"
    # NON deve intercettare funzioni legittime che non sono backup/import/export.
    legit = [
        "def resolve_team(", "def _refresh(", "def market_ids_for_sports(",
        "def transaction(", "def view(", "def report_status(", "def _reload(",
    ]
    for snippet in legit:
        assert not _BETFAIR_EXPORT_RE.search(snippet), f"falso positivo del guard: {snippet!r}"


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
