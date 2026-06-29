"""PR-14c: test del report diagnostico (logica pura)."""

from xtrader_bridge import __version__, diagnostics


def test_report_contiene_titolo_versione_e_campi():
    report = diagnostics.build_report([
        ("Stato", "ATTIVO"),
        ("Ricevuti", 5),
        ("Ultimo CSV", "C:/x/segnali.csv @ 10:00"),
    ])
    assert "XTrader Signal Bridge — diagnostica" in report
    assert f"versione: {__version__}" in report
    assert "Stato: ATTIVO" in report
    assert "Ricevuti: 5" in report
    assert "Ultimo CSV: C:/x/segnali.csv @ 10:00" in report


def test_valori_vuoti_mostrati_come_trattino():
    report = diagnostics.build_report([("Ultimo errore", ""), ("Ultimo segnale", None)])
    assert "Ultimo errore: —" in report
    assert "Ultimo segnale: —" in report


def test_valori_di_soli_spazi_mostrati_come_trattino():
    # #184 LOW: un valore whitespace-only (spazi/tab) NON deve apparire come campo
    # vuoto (`label: `) ma come `—`, come un valore assente.
    report = diagnostics.build_report([
        ("Spazi", "   "), ("Tab", "\t"), ("Newline", "\n  ")])
    assert "Spazi: —" in report
    assert "Tab: —" in report
    assert "Newline: —" in report
    # nessun campo deve restare con valore vuoto dopo i due punti
    for label in ("Spazi", "Tab", "Newline"):
        assert f"{label}: \n" not in report and not report.endswith(f"{label}: ")


def test_zero_non_e_trattato_come_vuoto():
    # Lo `0` (numerico) è un valore reale, non "vuoto": deve restare "0", non "—".
    report = diagnostics.build_report([("Ricevuti", 0), ("Scartati", 0)])
    assert "Ricevuti: 0" in report
    assert "Scartati: 0" in report


def test_valore_con_spazi_attorno_viene_strippato():
    report = diagnostics.build_report([("Stato", "  ATTIVO  ")])
    assert "Stato: ATTIVO" in report


def test_accetta_anche_un_dict_in_ordine():
    report = diagnostics.build_report({"A": "1", "B": "2"})
    # L'ordine di inserimento del dict è preservato.
    assert report.index("A: 1") < report.index("B: 2")


def test_redazione_token_nel_report():
    # Un bot token incollato per sbaglio in un campo NON deve finire nel report.
    # Il valore token-like è COSTRUITO a runtime: nel sorgente non compare un letterale
    # che combaci con lo scanner segreti del repo (forbidden-files/safety), ma a runtime
    # innesca comunque la redazione (`\d{6,}:[A-Za-z0-9_-]{20,}`).
    token = "1234567" + ":" + "x" * 30
    report = diagnostics.build_report([("Note", f"token {token} qui")])
    assert token not in report
    assert "[REDACTED_TOKEN]" in report
