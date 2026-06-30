"""Test del profilo impostazioni con nome (A3): salva/carica/elenca/elimina, con la
garanzia di sicurezza che i segreti (bot_token) NON finiscono mai in un profilo."""

import json

import pytest

from xtrader_bridge import profile_store as ps


# ── round-trip base ──────────────────────────────────────────────────────────

def test_save_list_load_round_trip(tmp_path):
    cfg = {"chat_id": "42", "clear_delay": 90, "queue_mode": "OVERWRITE_LAST"}
    path = ps.save_profile("Prematch", cfg, dir_path=str(tmp_path))
    assert path.endswith("Prematch.json")
    assert ps.list_profiles(str(tmp_path)) == ["Prematch"]
    assert ps.load_profile("Prematch", str(tmp_path)) == cfg


def test_lista_vuota_se_cartella_inesistente(tmp_path):
    assert ps.list_profiles(str(tmp_path / "nope")) == []


def test_safe_filename_evita_nomi_device_riservati_windows():
    # audit L2: "con"/"nul"/"com1"… sono device riservati su Windows: un file "con.json"
    # non è creabile. Vanno prefissati con "_". I nomi normali restano invariati.
    assert ps._safe_filename("con") == "_con"
    assert ps._safe_filename("NUL") == "_NUL"          # case-insensitive (mantiene il case)
    assert ps._safe_filename("com1") == "_com1"
    assert ps._safe_filename("lpt9") == "_lpt9"
    assert ps._safe_filename("Prematch") == "Prematch"  # nome normale: invariato
    assert ps._safe_filename("console") == "console"    # solo il match ESATTO è riservato


def test_lista_ordinata_case_insensitive(tmp_path):
    for n in ("zeta", "Alfa", "beta"):
        ps.save_profile(n, {"chat_id": n}, dir_path=str(tmp_path))
    assert ps.list_profiles(str(tmp_path)) == ["Alfa", "beta", "zeta"]


# ── sicurezza: niente segreti nei profili ────────────────────────────────────

def test_save_profile_non_scrive_il_bot_token(tmp_path):
    cfg = {"bot_token": "123:SEGRETO", "chat_id": "42"}
    path = ps.save_profile("ConToken", cfg, dir_path=str(tmp_path))
    raw = json.loads(open(path, encoding="utf-8").read())
    assert "bot_token" not in raw["config"]          # non sul disco
    assert raw["config"] == {"chat_id": "42"}
    assert "bot_token" not in ps.load_profile("ConToken", str(tmp_path))


def test_load_profile_difesa_in_profondita_su_file_manomesso(tmp_path):
    # Un file profilo editato a mano per inserire un token NON deve restituirlo.
    path = ps.profile_path("Manomesso", str(tmp_path))
    open(path, "w", encoding="utf-8").write(json.dumps(
        {"name": "Manomesso", "config": {"bot_token": "x:y", "chat_id": "9"}}))
    assert ps.load_profile("Manomesso", str(tmp_path)) == {"chat_id": "9"}


def test_apply_profile_preserva_il_token_corrente(tmp_path):
    current = {"bot_token": "LIVE:TOKEN", "chat_id": "1", "clear_delay": 90}
    profile = {"chat_id": "999", "clear_delay": 30}
    merged = ps.apply_profile(current, profile)
    assert merged["bot_token"] == "LIVE:TOKEN"        # token NON sovrascritto
    assert merged["chat_id"] == "999"                 # impostazioni applicate
    assert merged["clear_delay"] == 30
    assert current["chat_id"] == "1"                  # input non mutato


def test_apply_profile_ignora_token_in_un_profilo_manomesso():
    current = {"bot_token": "LIVE:TOKEN", "chat_id": "1"}
    tampered = {"bot_token": "ATTACKER:TOKEN", "chat_id": "2"}
    merged = ps.apply_profile(current, tampered)
    assert merged["bot_token"] == "LIVE:TOKEN"        # il token vivo vince sempre


def test_save_profile_non_scrive_i_marker_ram_only(tmp_path):
    """#256 (Codex): i marker SOLO-IN-RAM (`_post_corruption`, `_token_load_incomplete`) NON
    devono finire nel JSON del profilo: sono flag interni dello stato del token, non impostazioni.

    Fail-first: prima `_strip_secrets` toglieva solo `bot_token`/`bot_token_storage` e i marker
    venivano serializzati nel profilo."""
    cfg = {"chat_id": "42",
           "_post_corruption": True,
           "_token_load_incomplete": True}
    path = ps.save_profile("ConMarker", cfg, dir_path=str(tmp_path))
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["config"] == {"chat_id": "42"}          # solo l'impostazione reale, niente marker
    assert "_post_corruption" not in raw["config"]
    assert "_token_load_incomplete" not in raw["config"]


def test_apply_profile_ignora_marker_ram_only_in_profilo_vecchio(tmp_path):
    """#256 (Codex), difesa in profondità: un profilo VECCHIO che già contiene un marker RAM-only
    non deve applicarlo allo stato corrente del token (falserebbe la logica clear/preserve)."""
    current = {"bot_token": "LIVE:TOKEN", "bot_token_storage": "none", "chat_id": "1"}
    old_profile = {"chat_id": "2", "_token_load_incomplete": True, "_post_corruption": True}
    merged = ps.apply_profile(current, old_profile)
    assert merged["chat_id"] == "2"                    # impostazione applicata
    assert "_token_load_incomplete" not in merged      # marker NON propagato
    assert "_post_corruption" not in merged
    assert merged["bot_token_storage"] == "none"       # stato token corrente intatto


# ── collisioni / nomi non validi ─────────────────────────────────────────────

def test_collisione_filename_tra_nomi_diversi_rifiutata(tmp_path):
    ps.save_profile("Live", {"chat_id": "1"}, dir_path=str(tmp_path))
    with pytest.raises(ValueError, match="collide"):
        ps.save_profile("Live!", {"chat_id": "2"}, dir_path=str(tmp_path))


def test_update_stesso_profilo_consentito(tmp_path):
    ps.save_profile("Live", {"chat_id": "1"}, dir_path=str(tmp_path))
    ps.save_profile("Live", {"chat_id": "2"}, dir_path=str(tmp_path))   # update, no raise
    assert ps.load_profile("Live", str(tmp_path)) == {"chat_id": "2"}
    assert ps.list_profiles(str(tmp_path)) == ["Live"]


@pytest.mark.parametrize("bad", ["", "   ", "!!!", "/", ".."])
def test_nome_vuoto_o_non_valido_rifiutato(tmp_path, bad):
    with pytest.raises(ValueError):
        ps.save_profile(bad, {"chat_id": "1"}, dir_path=str(tmp_path))


def test_ensure_valid_new_name_precheck_senza_scrivere(tmp_path):
    # La GUI valida il nome PRIMA di persistere il form: nome valido → ritorna il nome
    # pulito senza creare file; nome vuoto/collidente → ValueError (niente file scritto).
    assert ps.ensure_valid_new_name("Prematch", str(tmp_path)) == "Prematch"
    assert ps.list_profiles(str(tmp_path)) == []          # pre-check non scrive nulla
    with pytest.raises(ValueError):
        ps.ensure_valid_new_name("   ", str(tmp_path))
    ps.save_profile("Live", {"chat_id": "1"}, dir_path=str(tmp_path))
    with pytest.raises(ValueError, match="collide"):
        ps.ensure_valid_new_name("Live!", str(tmp_path))   # collisione filename
    assert ps.ensure_valid_new_name("Live", str(tmp_path)) == "Live"   # stesso = update ok


# ── delete / errori di load ──────────────────────────────────────────────────

def test_delete_profile(tmp_path):
    ps.save_profile("Tmp", {"chat_id": "1"}, dir_path=str(tmp_path))
    assert ps.delete_profile("Tmp", str(tmp_path)) is True
    assert ps.delete_profile("Tmp", str(tmp_path)) is False     # già rimosso
    assert ps.list_profiles(str(tmp_path)) == []


def test_load_profile_inesistente_solleva(tmp_path):
    with pytest.raises(FileNotFoundError):
        ps.load_profile("NonEsiste", str(tmp_path))


@pytest.mark.parametrize("bad", ["", "   ", "!!!"])
def test_load_e_delete_con_nome_non_valido_non_toccano_file(tmp_path, bad):
    # Un nome vuoto/non valido non deve mai mappare sul file ".json" (Sourcery):
    # load solleva ValueError, delete ritorna False senza rimuovere nulla.
    open(tmp_path / ".json", "w", encoding="utf-8").write("non-toccare")
    with pytest.raises(ValueError):
        ps.load_profile(bad, str(tmp_path))
    assert ps.delete_profile(bad, str(tmp_path)) is False
    assert (tmp_path / ".json").exists()   # file non voluto NON rimosso


def test_load_profile_corrotto_solleva_valueerror(tmp_path):
    path = ps.profile_path("Rotto", str(tmp_path))
    open(path, "w", encoding="utf-8").write("{ non json")
    with pytest.raises(ValueError):
        ps.load_profile("Rotto", str(tmp_path))


def test_lista_ignora_file_corrotti_e_temporanei(tmp_path):
    ps.save_profile("Buono", {"chat_id": "1"}, dir_path=str(tmp_path))
    open(tmp_path / "rotto.json", "w", encoding="utf-8").write("{ nope")
    open(tmp_path / ".profile_tmp.json", "w", encoding="utf-8").write(
        json.dumps({"name": "Fantasma", "config": {}}))
    assert ps.list_profiles(str(tmp_path)) == ["Buono"]
