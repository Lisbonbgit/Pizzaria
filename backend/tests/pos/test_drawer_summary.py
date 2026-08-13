"""Resumo das aberturas de gaveta para o relatório do backoffice."""
from zoneinfo import ZoneInfo

from pos.drawer import summarize_drawer_opens

LISBON = ZoneInfo("Europe/Lisbon")


def test_ordena_por_hora_e_formata_em_lisboa():
    rows = [
        {"at": "2026-08-09T20:30:00+00:00", "operator_name": "Ana", "had_open_session": True},
        {"at": "2026-08-09T18:05:00+00:00", "operator_name": "Rui", "had_open_session": False},
    ]
    out = summarize_drawer_opens(rows, LISBON)
    # Agosto = hora de verão (UTC+1): 18:05Z -> 19:05, 20:30Z -> 21:30.
    assert [o["time"] for o in out] == ["19:05", "21:30"]
    assert out[0] == {"time": "19:05", "operator": "Rui", "had_session": False}
    assert out[1] == {"time": "21:30", "operator": "Ana", "had_session": True}


def test_at_invalido_nao_rebenta():
    out = summarize_drawer_opens([{"at": None, "operator_name": None}], LISBON)
    assert out == [{"time": "—", "operator": "—", "had_session": False}]
