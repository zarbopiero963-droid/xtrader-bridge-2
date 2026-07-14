"""Test degli helper PURI della tab «🤖 Assistente» (#41 PR-3). La costruzione widget è verifica
manuale (nessun display in CI); qui si esercita solo la logica di testo/stato/trascritto."""

from xtrader_bridge import config_agent_controller as ctl
from xtrader_bridge import config_agent_gui as g


def test_state_label_per_stato():
    assert "OFFLINE" in g.state_label(ctl.STOPPED)
    assert "ATTIVO" in g.state_label(ctl.RUNNING)
    assert "ERRORE" in g.state_label(ctl.ERROR)


def test_state_color_per_stato():
    assert g.state_color(ctl.STOPPED) == "gray"
    assert g.state_color(ctl.RUNNING) == g._COLOR_OK
    assert g.state_color(ctl.ERROR) == g._COLOR_ERR


def test_input_enabled_solo_running():
    assert g.input_enabled(ctl.RUNNING) is True
    assert g.input_enabled(ctl.STOPPED) is False
    assert g.input_enabled(ctl.ERROR) is False


def test_transcript_line_prefissi():
    assert g.transcript_line("user", "ciao").endswith("ciao")
    assert "🧑" in g.transcript_line("user", "x")
    assert "🤖" in g.transcript_line("assistant", "y")


def test_messages_to_transcript_mostra_solo_testo():
    msgs = [
        {"role": "user", "content": "imposta il token"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "fatto"},
            {"type": "tool_use", "id": "t", "name": "get_health", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "semaforo verde"}]},
    ]
    lines = g.messages_to_transcript(msgs)
    # solo le due righe di TESTO (tool_use/tool_result esclusi dalla chat)
    assert len(lines) == 2
    assert "imposta il token" in lines[0] and "fatto" in lines[1]


def test_messages_to_transcript_robusto_su_input_sporco():
    # elementi non-dict / content assente → ignorati, nessun crash
    out = g.messages_to_transcript([None, {"role": "user"}, "x",
                                    {"role": "user", "content": "vero"}])
    assert out == ["🧑 Tu: vero"]
