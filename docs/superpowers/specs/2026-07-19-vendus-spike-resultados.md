# Resultados do Spike Vendus — 2026-07-19

> Preenchido ao correr `backend/scripts/vendus_spike.py` com `VENDUS_MODE=tests`.

## 1. Salas/mesas usadas
- Sala: `<id>` · Mesa: `<id>` · Register: `<id/none>`

## 2. Append (R3-a) — dois POST DC na mesma mesa
- doc1 id: `<...>` · doc2 id: `<...>`
- **MESMO documento?** `SIM | NÃO`
- Conclusão: as linhas **[somam no mesmo DC] / [criam DCs separados]**.

## 3. POS ↔ API (R3-b) — item metido à mão no POS
- Apareceu no MESMO documento que a app criou? `SIM | NÃO`
- Conclusão: adições manuais **[são lidas pela app] / [ficam noutro documento]**.

## 4. Fecho (R3-c) — faturar no POS
- Após FT/FR, a mesa deixou de ter DC aberto? `SIM | NÃO`
- O FT/FR é visível por `GET /documents?since=hoje`? `SIM | NÃO`
- Conclusão: fecho **[detetável por polling] / [não detetável]**.

## 5. Campos úteis observados
- `tables` reflete estado ocupada/livre? `SIM(campo=...) | NÃO`
- Campo do total do DC: `amount_gross | amount | outro=...`
- `tax_id` aceite para os itens: `<...>`

## DECISÃO
- [ ] **Cenário "SOMAM"** (2 SIM e 3 SIM) → Plano C segue o **caminho principal** (a app abre/segue 1 DC por mesa; conta = ler esse DC).
- [ ] **Cenário "SEPARAM"** → Plano C usa **reconciliação** (listar DC do dia por `rest_table`, agregar; `external_reference` para reconhecer os da app).
