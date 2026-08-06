"""#286 — in EN/ES il software di destinazione si chiama «Betting Toolkit», non «XTrader».

Richiesta del proprietario, indicata su due schermate dei dialoghi di conferma. **XTrader e
Betting Toolkit sono lo stesso prodotto con nomi diversi per mercato**: XTrader in Italia,
BETTINGTOOLKIT.COM/.ES/.LAT fuori. Il nome italiano non deve comparire nell'interfaccia
inglese e spagnola, dove quel programma semplicemente non si chiama così.

## Cosa NON è questa issue

Il **bridge** — cioè questo programma — si chiama **BetRelay** (#232), e il suo nome è
uguale in tutte le lingue. Qui si traduce solo il nome del software di **destinazione**.
Confondere i due significherebbe tradurre il nome del nostro programma in quello di un
altro: verificato che «XTrader Signal Bridge» non è a catalogo (è hardcoded in 5 punti),
quindi le due rinomine non si sovrappongono in nessun sito.

## Le chiavi italiane non si toccano

Le chiavi del catalogo **sono** le stringhe italiane: cambia solo il **valore** EN/ES.
L'interfaccia italiana resta identica al carattere, e c'è un test che lo pretende — altrimenti
«rinominare in EN» potrebbe silenziosamente rinominare anche in IT.

## La trappola: una chiave di configurazione dentro un messaggio

Un messaggio EN/ES dice all'utente di correggere `xtrader_notification_chat_id`. Quella è una
**chiave di config reale**, non prosa: rinominarla renderebbe il messaggio un'istruzione a
modificare qualcosa che non esiste. È minuscola, quindi una sostituzione case-sensitive la
salta — ma «si salva da sola» non è un presidio, quindi c'è un test che lo pretende.
"""

import re

import pytest

from xtrader_bridge import i18n

#: Il nome nel mercato non italiano. Con lo spazio: è la forma usata dal sito già
#: ribrandizzato (68 occorrenze), quindi quella che l'utente vede altrove.
NOME_ESTERO = "Betting Toolkit"

#: La chiave di config che compare DENTRO un messaggio tradotto e non va rinominata.
CHIAVE_CONFIG = "xtrader_notification_chat_id"


def _valori_con_xtrader(lingua) -> list:
    """Le voci del catalogo il cui VALORE nomina ancora XTrader."""
    return [(k, v) for k, v in i18n._CATALOG[lingua].items()
            if re.search(r"XTrader|XTRADER", str(v))]


# ── ① EN e ES non nominano più il prodotto italiano ───────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_nessun_valore_tradotto_nomina_piu_xtrader(lingua):
    """FAIL-FIRST: 18 valori per lingua dicevano «XTrader» a un utente per cui quel
    programma si chiama Betting Toolkit."""
    residui = _valori_con_xtrader(lingua)
    assert not residui, (
        f"{len(residui)} valori {lingua} nominano ancora XTrader:\n  "
        + "\n  ".join(repr(k[:60]) for k, _ in residui)
    )


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_ogni_chiave_che_nomina_xtrader_ha_un_valore_che_nomina_betting_toolkit(lingua):
    """La metà che impedisce di «correggere» **cancellando** il nome invece di tradurlo: se
    sparisse e basta, l'utente non saprebbe più di quale programma si parla.

    **Invariante derivato, non una soglia** (rilievo GPT-5.5 sulla #298, ed era giusto). La
    prima stesura pretendeva `>= 15` valori: un numero arbitrario, che avrebbe dato falsi
    rossi aggiungendo stringhe e falsi verdi togliendone. Qui la regola si deduce dal catalogo
    stesso — *ogni chiave italiana che nomina XTrader deve avere un valore che nomina Betting
    Toolkit* — quindi resta esatta comunque il catalogo cresca o si riduca, senza manutenzione.
    """
    orfane = [
        k for k, v in i18n._CATALOG[lingua].items()
        if ("XTrader" in k or "XTRADER" in k) and NOME_ESTERO.lower() not in str(v).lower()
    ]
    assert not orfane, (
        f"chiavi {lingua} che nominano XTrader ma il cui valore NON nomina «{NOME_ESTERO}»: "
        f"il nome è stato cancellato invece che tradotto:\n  "
        + "\n  ".join(repr(k[:60]) for k in orfane)
    )


# ── ② l'italiano non cambia di un carattere ───────────────────────────────────────────

def test_le_chiavi_italiane_restano_xtrader():
    """Le chiavi SONO l'interfaccia italiana. Se cambiassero, avremmo rinominato il prodotto
    anche per l'utente italiano — che invece quel programma lo chiama davvero XTrader."""
    chiavi_it = [k for k in i18n._CATALOG["EN"] if "XTrader" in k or "XTRADER" in k]
    assert len(chiavi_it) >= 15, (
        f"solo {len(chiavi_it)} chiavi italiane nominano XTrader: l'italiano è stato "
        f"toccato, e non doveva"
    )


# ── ③ la chiave di config dentro il messaggio ─────────────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_la_chiave_di_config_nel_messaggio_non_e_stata_rinominata(lingua):
    """`xtrader_notification_chat_id` è una chiave REALE citata dentro un messaggio d'errore.
    Rinominarla trasformerebbe l'istruzione «correggi X» in «correggi una cosa che non
    esiste» — un messaggio d'aiuto che manda l'utente a sbattere."""
    citata = any(CHIAVE_CONFIG in str(v) for v in i18n._CATALOG[lingua].values())
    assert citata, (
        f"«{CHIAVE_CONFIG}» non compare più nei valori {lingua}: la rinomina ha inghiottito "
        f"una chiave di configurazione"
    )


# ── ④ la quinta lacuna, e la guardia che l'avrebbe trovata ────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_ultima_conferma_e_tradotta(lingua):
    """FAIL-FIRST: «Ultima conferma XTrader» è wrappata in `tr()` al rendering ma non era a
    catalogo, quindi restava **italiana** in EN e ES. È la quinta lacuna della stessa
    famiglia dei quattro punti della #269."""
    chiave = "Ultima conferma XTrader"
    tradotta = i18n.tr_in(lingua, chiave)
    assert tradotta != chiave, f"«{chiave}» non tradotta in {lingua}: tr_in ha fatto fallback"
    assert "XTrader" not in tradotta, tradotta


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_le_etichette_del_cruscotto_sono_tutte_tradotte(lingua):
    """**La guardia che mancava**, ed è il motivo per cui la quinta lacuna è sopravvissuta.

    L'anti-drift esistente (`test_i18n_343`) verifica che ogni CHIAVE del catalogo esista nel
    sorgente. Non il verso opposto: che ogni stringa resa all'utente sia a catalogo. Così una
    voce aggiunta a `_LAST_FIELDS` e mai tradotta resta italiana in EN/ES senza che nulla
    protesti — è esattamente ciò che è successo a «Ultima conferma XTrader».

    **Esercita la struttura reale, non una regex.** La prima stesura di questa guardia cercava
    `i18n.tr("letterale")` col regex ed era VACUA: passava verde pur essendoci la lacuna,
    perché quelle etichette non sono letterali dentro `tr()` — stanno in `_LAST_FIELDS` e
    arrivano a `tr()` come **variabile** (`app.py:2082`). Una guardia che non vede il difetto
    per cui è stata scritta è peggio di nessuna guardia: dà l'impressione della copertura.

    Iterare la tupla vera la vede, perché è la stessa cosa che l'app rende.
    """
    from xtrader_bridge import app

    mancanti = []
    for _nome, etichetta in app._LAST_FIELDS:
        tradotta = i18n.tr_in(lingua, etichetta)
        if tradotta == etichetta:
            mancanti.append(etichetta)

    assert not mancanti, (
        f"etichette del cruscotto non tradotte in {lingua} (l'utente {lingua} le vede in "
        f"italiano): {mancanti}"
    )
