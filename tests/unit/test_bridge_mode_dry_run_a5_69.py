"""Guard della coerenza `bridge_mode` ↔ `dry_run` — ambiguità A5 della #69.

Due chiavi descrivono lo **stesso asse** simulazione/reale, ma **non hanno lo stesso peso**:

- **`dry_run` è autoritativo** e fail-closed: `True`, assente o malformato → SIMULAZIONE,
  qualunque cosa dica `bridge_mode`;
- **`bridge_mode` è solo un'etichetta**, e in una config editata a mano può *mentire*.

Chi legge l'etichetta grezza per decidere qualcosa sbaglia. La domanda va fatta a
`bridge_mode.mode_from_cfg(cfg)` o a `safety_guard.is_dry_run(cfg)`, che sono le uniche due
fonti di verità.

Il difetto che questi test bloccano è stato **trovato eseguendo il codice**, non leggendolo: il
tool `get_health` dell'assistente passava al semaforo l'etichetta grezza, quindi con la coppia
incoerente `bridge_mode="SIMULAZIONE"` + `dry_run=False` mostrava

    GREEN — «🧪 Simulazione Bridge — NON scrive il CSV operativo»

mentre la modalità effettiva era **REALE** e il bridge il CSV lo scriveva davvero. Un semaforo
verde su una modalità che muove soldi è la direzione sbagliata in cui sbagliare.

⚠️ **Portata onesta:** con il loader reale il caso non si presenta, perché
`config_store.load_config` **ri-deriva** `bridge_mode` dalla coppia salvata (test più sotto).
Era quindi un difetto **latente**, sicuro *per via di una normalizzazione altrove* — e il tool
accetta un `config_loader` iniettabile, mentre l'altro percorso salute dello stesso modulo usava
già la fonte autoritativa. Due strade per la stessa domanda, di cui una sicura per caso.
"""

import json

from xtrader_bridge import bridge_mode, config_agent, safety_guard

# La coppia bugiarda: l'etichetta dice simulazione, `dry_run` dice che si scrive davvero.
_CFG_INCOERENTE = {"bridge_mode": "SIMULAZIONE", "dry_run": False}


def _semaforo_modalita(cfg) -> dict:
    """Il semaforo «Modalità» come lo vede l'assistente attraverso il suo tool `get_health`."""
    tools = config_agent.build_read_only_tools(config_loader=lambda: cfg)
    health = next(t for t in tools if "health" in t.name)
    return next(i for i in json.loads(health.handler("")) if i["key"] == "mode")


# ── il difetto riprodotto: il semaforo deve dire la VERITÀ, non l'etichetta ──────────────────────
def test_get_health_segue_la_modalita_effettiva_non_l_etichetta():
    """Con la coppia incoerente il semaforo deve essere ROSSO (reale), non verde.

    Se questo test fallisce, l'assistente sta dicendo all'utente «non scrive il CSV operativo»
    mentre il bridge scrive: è il modo peggiore di sbagliare."""
    assert bridge_mode.mode_from_cfg(_CFG_INCOERENTE) == bridge_mode.REALE   # verità
    assert safety_guard.is_dry_run(_CFG_INCOERENTE) is False

    item = _semaforo_modalita(_CFG_INCOERENTE)
    assert item["state"] == "RED", f"semaforo verde su modalità reale: {item}"
    assert "imulazione" not in item["detail"], item["detail"]


def test_get_health_dice_simulazione_quando_lo_e_davvero():
    """Il rovescio: `dry_run=True` è autoritativo anche se l'etichetta grida REALE."""
    item = _semaforo_modalita({"bridge_mode": "REALE", "dry_run": True})
    assert item["state"] == "GREEN"
    assert bridge_mode.mode_from_cfg({"bridge_mode": "REALE", "dry_run": True}) == \
        bridge_mode.SIMULAZIONE


# ── la rete di sicurezza che rende il caso irraggiungibile in produzione ─────────────────────────
def test_load_config_ri_deriva_l_etichetta_dalla_coppia(tmp_path, monkeypatch):
    """`load_config` **ri-deriva** `bridge_mode` da `mode_from_cfg`: una coppia incoerente su
    disco viene sanata al caricamento. È il motivo per cui il difetto sopra era latente e non
    vivo — e va blindato, perché se questa normalizzazione sparisse la lettura grezza tornerebbe
    a mentire (e non solo nell'assistente)."""
    import importlib
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    from xtrader_bridge import config_store
    importlib.reload(config_store)
    try:
        percorso = config_store.config_path()
        import os
        os.makedirs(os.path.dirname(percorso), exist_ok=True)
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(_CFG_INCOERENTE, f)

        cfg = config_store.load_config()
        assert cfg["bridge_mode"] == bridge_mode.REALE, \
            "l'etichetta salvata non è stata ri-derivata: una config incoerente resterebbe tale"
        assert cfg["dry_run"] is False
    finally:
        importlib.reload(config_store)      # non lasciare il modulo agganciato alla tmp


# ── nessuno deve tornare a leggere l'etichetta grezza per DECIDERE ───────────────────────────────
def test_nessuna_lettura_grezza_di_bridge_mode_fuori_dal_suo_modulo():
    """Source-scan: `cfg.get("bridge_mode")` può comparire **solo** in `bridge_mode.py` (che è
    la funzione autoritativa) e in `config_store.py` (che ri-deriva al load).

    Altrove significa che qualcuno sta decidendo su un'etichetta che può mentire — il difetto
    A5 esatto. Chi deve sapere la modalità chiama `mode_from_cfg`; chi deve sapere se si scrive
    chiama `is_dry_run`."""
    import pathlib
    pkg = pathlib.Path(config_agent.__file__).parent
    consentiti = {"bridge_mode.py", "config_store.py"}
    offenders = []
    for path in sorted(pkg.rglob("*.py")):
        if path.name in consentiti:
            continue
        testo = path.read_text(encoding="utf-8")
        for forma in ('cfg.get("bridge_mode"', 'cfg["bridge_mode"]'):
            if forma in testo:
                offenders.append(f"{path.name}: {forma}")
    assert not offenders, (
        "lettura grezza di `bridge_mode` (può mentire: `dry_run` è autoritativo) — usa "
        "`bridge_mode.mode_from_cfg(cfg)` o `safety_guard.is_dry_run(cfg)`:\n  "
        + "\n  ".join(offenders))
