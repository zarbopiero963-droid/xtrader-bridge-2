"""XTrader Signal Bridge — package.

Separazione (PR-03):
- `parser`       : parsing dei messaggi Telegram P.Bet. (nessuna dipendenza GUI)
- `csv_writer`   : contratto CSV XTrader, costruzione/scrittura righe
- `config_store` : caricamento/salvataggio configurazione (funzioni pure)
- `app`          : GUI CustomTkinter + listener Telegram (unica parte con GUI)

`main.py` nella root è solo l'entrypoint.
"""
