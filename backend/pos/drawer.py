"""Helper puro: formata os registos de abertura de gaveta (`db.drawer_opens`)
para o relatório do backoffice — hora local HH:MM, operador, e se havia caixa
aberta. Sem I/O; recebe já os documentos lidos da BD."""
from datetime import datetime


def summarize_drawer_opens(rows, tz):
    out = []
    for r in rows:
        at = r.get("at")
        try:
            dt = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(tz)
            hhmm = dt.strftime("%H:%M")
        except Exception:
            hhmm = "—"
        out.append({
            "time": hhmm,
            "operator": r.get("operator_name") or "—",
            "had_session": bool(r.get("had_open_session")),
        })
    # Ordenar por "HH:MM" só é correto porque o relatório cobre UM dia.
    # TODO(Fase 3 — intervalo de datas): quando `rows` abranger vários dias,
    # ordenar pelo datetime de `at` (não pela hora local formatada), senão os
    # dias interleavam-se.
    out.sort(key=lambda x: x["time"])
    return out
