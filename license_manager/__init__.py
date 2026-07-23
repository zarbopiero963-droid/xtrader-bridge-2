"""License Manager del proprietario (issue #140, PR 3) — package **separato** dal bridge.

⚠️ Questo package NON fa parte del bridge distribuito. Vive come package top-level a sé (non
sotto `xtrader_bridge/`) proprio perché la build dell'EXE del bridge colleziona **solo**
`xtrader_bridge` (`--collect-submodules xtrader_bridge`): così la logica di **firma** e di
**custodia della chiave privata** non entra mai nell'eseguibile del bridge. Il bridge deve solo
**verificare** le licenze con la chiave PUBBLICA (invariante #1, issue #140).

PR 3a (questa): **solo logica pura + test** — generazione keypair Ed25519, custodia locale del
seed PRIVATO in `%APPDATA%\\XTraderLicenseManager\\`, firma delle licenze (Nome/Cognome/Giorni +
Hardware ID → chiave). Nessuna GUI e nessun workflow di build: arrivano con **PR 3b**.

La chiave PRIVATA non è e non deve mai essere nel repository né nell'EXE. Un file-chiave corrotto
non viene **mai** scartato in silenzio: perderlo significa non poter più rinnovare le licenze dei
bridge già distribuiti.
"""

from .core import (
    APP_DIR_NAME,
    KEY_FORMAT_VERSION,
    MAX_LICENSE_DAYS,
    KeyExistsError,
    KeyFileCorruptError,
    export_signing_key,
    generate_keypair,
    issue_license,
    load_signing_key,
    manager_dir,
    save_signing_key,
    signing_key_path,
)

__all__ = [
    "APP_DIR_NAME",
    "KEY_FORMAT_VERSION",
    "MAX_LICENSE_DAYS",
    "KeyExistsError",
    "KeyFileCorruptError",
    "export_signing_key",
    "generate_keypair",
    "issue_license",
    "load_signing_key",
    "manager_dir",
    "save_signing_key",
    "signing_key_path",
]
