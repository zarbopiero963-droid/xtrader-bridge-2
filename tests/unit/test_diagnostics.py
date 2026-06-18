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
