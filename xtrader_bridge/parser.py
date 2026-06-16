"""Parsing dei messaggi Telegram P.Bet. (nessuna dipendenza dalla GUI)."""

import re


def parse_message(text: str) -> dict:
    """Estrae i campi da un messaggio P.Bet."""
    lines = text.strip().split('\n')
    result = {
        'signal_type': '',
        'competition': '',
        'teams': '',
        'score': '',
        'time_': '',
        'quota': '',
        'probability': '',
        'bet_type': 'BACK',
    }
    for line in lines:
        line = line.strip()
        if 'P.Bet.' in line:
            m = re.search(r'P\.Bet\.\s+(.+?)(?:\s+[🔊✅🔇]|$)', line)
            if m:
                result['signal_type'] = m.group(1).strip()
        elif '🏆' in line:
            result['competition'] = re.sub(r'[🏆\s]+', ' ', line).strip()
        elif '🆚' in line:
            result['teams'] = re.sub(r'[🆚\s]+', ' ', line).strip().lstrip()
        elif '⚽' in line:
            result['score'] = re.sub(r'[⚽\s]+', ' ', line).strip()
        elif '⌚' in line:
            result['time_'] = re.sub(r'[⌚\s]+', ' ', line).strip()
        elif 'Quota' in line or '📈' in line:
            m = re.search(r'Quota\s*([\d,\.]+)', line)
            if m:
                result['quota'] = m.group(1).replace(',', '.')
        elif '📊' in line:
            m = re.search(r'([\d\.]+)\s*%', line)
            if m:
                result['probability'] = m.group(1)
    return result
