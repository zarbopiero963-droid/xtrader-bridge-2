"""CRUD condiviso dei profili di mappatura (store refactor #114 — M2/M8/AC-I4/B44).

`name_mapping_store` (dizionario nomi squadra) e `market_mapping_store` (dizionario mercati)
avevano **dieci** funzioni CRUD **byte-identiche** sul `dict` di config, divergenti solo per:

- la **chiave di config** che ospita i profili (`name_mappings` vs `market_mappings`);
- la funzione **`_clean_entry`** per-store (schemi diversi: `betfair/provider/sport/entity_type`
  vs `phrase/market_name/selection_name/delimitatori`);
- il **prefisso di log** del warning sui profili duplicati (`name_mappings:`/`market_mappings:`).

Due copie identiche di logica safety-critical (un profilo perso/scambiato = riga CSV sbagliata o
non riconosciuta) potevano **divergere in silenzio** a una modifica futura. `make_profile_crud`
è la **fonte unica**: ogni store la chiama una volta iniettando le proprie tre differenze e ottiene
le dieci funzioni. Le parti genuinamente per-store (`_clean_entry`, `_malformed_fields`,
`malformed_entry_warnings`, i resolver, il dedup dei warning) restano nei rispettivi moduli.

Logica **PURA** su un `dict` (nessun I/O, nessuna GUI): la persistenza resta del chiamante
(`config_store.save_config`), come prima. Ogni funzione di modifica ritorna una **COPIA** di
`cfg`, non muta l'originale. Stesso modello di estrazione già usato nel repo per `atomic_io` e
`validators.safe_filename_core` (core condiviso, dettagli per-dominio iniettati).
"""

from types import SimpleNamespace


def make_profile_crud(*, store_key, clean_entry, dup_warn_prefix, logger):
    """Crea le dieci funzioni CRUD condivise per uno store di profili di mappatura.

    Parametri (le UNICHE differenze fra i due store):
    - ``store_key``: chiave di config che ospita i profili (es. ``"name_mappings"``);
    - ``clean_entry``: funzione ``(entry) -> dict|None`` che normalizza/valida UNA riga secondo
      lo schema del proprio store (scarta le righe inutili/malformate, fail-closed);
    - ``dup_warn_prefix``: prefisso del warning sui profili duplicati (es. ``"name_mappings"``),
      così il log resta riconoscibile per lo store giusto;
    - ``logger``: il ``logging.Logger`` del modulo chiamante, così i record del warning mantengono
      la loro origine (nome logger dello store, non di questo modulo).

    Ritorna un ``SimpleNamespace`` con: ``_store``, ``_norm_profile_name``, ``_find_store_key``,
    ``profile_names``, ``get_entries``, ``entries_for_profiles``, ``set_entries``, ``add_profile``,
    ``delete_profile``, ``rename_profile`` — con le stesse firme e lo stesso comportamento delle
    versioni originali per-store."""

    def _store(cfg):
        """Sezione ``store_key`` della config (dict vuoto se assente/malformata)."""
        raw = (cfg or {}).get(store_key, {})
        return raw if isinstance(raw, dict) else {}

    def _norm_profile_name(name):
        """Nome profilo normalizzato per il confronto: stringa ripulita (strip)."""
        return str(name or "").strip()

    def _find_store_key(store, name):
        """Chiave REALE in ``store`` che corrisponde a ``name`` normalizzato, o ``None``. Serve a
        ritrovare profili salvati con spazi attorno al nome (``config.json`` legacy/editato a mano),
        che ``profile_names`` mostra già ripuliti: senza, lookup/CRUD mancherebbero il profilo o
        creerebbero un doppione, disabilitando in silenzio la mappatura per quel profilo. Con
        DOPPIONI normalizzati-uguali (config manomessa: ``"Prof"`` e ``" Prof "``) il match ESATTO
        vince sempre (niente shadowing silenzioso) + warning (P3-22 #76)."""
        target = _norm_profile_name(name)
        if not target:
            return None
        matches = [k for k in store if _norm_profile_name(k) == target]
        if not matches:
            return None
        if len(matches) > 1:
            logger.warning(
                "%s: profili DUPLICATI dopo normalizzazione (%s) -> uso %r "
                "(match esatto se presente); rinomina/rimuovi i doppioni in config.json "
                "(P3-22 #76).", dup_warn_prefix, ", ".join(repr(k) for k in matches),
                name if name in matches else matches[0])
        if name in matches:
            return name
        return matches[0]

    def profile_names(cfg):
        """Nomi dei profili salvati, ordinati (case-insensitive). Per le tendine/checkbox GUI."""
        names = [str(k).strip() for k in _store(cfg).keys() if str(k).strip()]
        return sorted(names, key=str.casefold)

    def get_entries(cfg, name):
        """Righe (ripulite) di un profilo, nell'ordine salvato. Profilo assente → ``[]``.
        Le righe vuote/incomplete vengono filtrate, così il resolver non itera su rumore."""
        store = _store(cfg)
        key = _find_store_key(store, name)
        rows = store.get(key, []) if key is not None else []
        if not isinstance(rows, (list, tuple)):
            return []
        out = []
        for e in rows:
            ce = clean_entry(e)
            if ce is not None:
                out.append(ce)
        return out

    def entries_for_profiles(cfg, names):
        """Lista di liste-di-righe per i profili indicati (ordine preservato): la forma attesa dai
        resolver. Un profilo mancante contribuisce con ``[]`` (nessun match da lì → fail-closed)."""
        return [get_entries(cfg, n) for n in (names or []) if str(n or "").strip()]

    def set_entries(cfg, name, entries):
        """Copia di ``cfg`` con il profilo ``name`` impostato/sostituito da ``entries`` (ripulite).
        Nome vuoto → config invariata. Crea il profilo se non esiste."""
        out = dict(cfg or {})
        nm = _norm_profile_name(name)
        if not nm:
            return out
        store = dict(_store(out))
        existing = _find_store_key(store, nm)
        if existing is not None and existing != nm:
            store.pop(existing)   # migra una chiave legacy con spazi al nome normalizzato (no doppioni)
        store[nm] = [ce for ce in (clean_entry(e) for e in (entries or [])) if ce is not None]
        out[store_key] = store
        return out

    def add_profile(cfg, name):
        """Copia di ``cfg`` con un profilo vuoto ``name`` (no-op se esiste già o nome vuoto): la
        creazione non deve mai cancellare le righe di un profilo omonimo."""
        out = dict(cfg or {})
        nm = _norm_profile_name(name)
        store = dict(_store(out))
        if nm and _find_store_key(store, nm) is None:
            store[nm] = []
        out[store_key] = store
        return out

    def delete_profile(cfg, name):
        """Copia di ``cfg`` senza il profilo ``name`` (idempotente)."""
        out = dict(cfg or {})
        nm = _norm_profile_name(name)
        store = {k: v for k, v in _store(out).items() if _norm_profile_name(k) != nm}
        out[store_key] = store
        return out

    def rename_profile(cfg, old, new):
        """Copia di ``cfg`` con il profilo ``old`` rinominato ``new`` (conserva le righe). No-op se
        ``old`` non esiste, ``new`` è vuoto, o ``new`` esiste già (non si sovrascrive in silenzio
        un altro profilo)."""
        out = dict(cfg or {})
        o = _norm_profile_name(old)
        n = _norm_profile_name(new)
        store = dict(_store(out))
        old_key = _find_store_key(store, o)
        new_key = _find_store_key(store, n)
        if o == n or old_key is None or not n or new_key is not None:
            return out
        store[n] = store.pop(old_key)
        out[store_key] = store
        return out

    return SimpleNamespace(
        _store=_store, _norm_profile_name=_norm_profile_name, _find_store_key=_find_store_key,
        profile_names=profile_names, get_entries=get_entries,
        entries_for_profiles=entries_for_profiles, set_entries=set_entries,
        add_profile=add_profile, delete_profile=delete_profile, rename_profile=rename_profile)
