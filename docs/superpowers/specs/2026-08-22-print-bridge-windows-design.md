# Ponte de impressão para Windows

**Data:** 2026-08-22
**Estado:** aprovado (design), por implementar
**Âmbito:** substituir a APK-ponte Android por um programa no PC Windows (10/11, 32-bit) da loja. **O backend não muda.**

## Objetivo

Um `.exe` que corre no PC Windows da loja e faz o que a APK faz hoje: faz polling à fila de impressão do backend e imprime cada trabalho na impressora **instalada no Windows** (cozinha ou caixa). Sem instalar runtime (Windows 10/11 já traz .NET Framework 4.x e o compilador `csc.exe`).

## Contrato com o backend (já existe, não muda)

- `GET /api/agent/pending-jobs` — header `X-API-Key`. Devolve um array; por trabalho interessam 3 campos: `escpos_base64` (bytes ESC/POS já prontos), `printer_type` (`"kitchen"` | `"cashier"`), e `job.id`.
- `PUT /api/agent/jobs/{id}/status` — header `X-API-Key`, corpo `{"status": "printing" | "printed" | "failed"}`.
- O GET só devolve trabalhos `pending`. O agente marca `printing` **antes** de imprimir → o poll seguinte já não o traz (evita imprimir a dobrar).

## Tecnologia

**C# / .NET Framework 4.x** (pré-instalado no Windows 10/11). Compila-se com o `csc.exe` que já vem no Windows (`C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe`) — o dono corre um `build.bat` no próprio PC, sem instalar nada. Um único ficheiro `.cs` → um `.exe`.

- HTTP: `HttpClient` (nativo).
- Impressão RAW: P/Invoke a `winspool.drv` (`OpenPrinter` → `StartDocPrinter` com datatype `"RAW"` → `WritePrinter` → fechar). RAW manda os bytes crus, ignorando o driver — é o que o ESC/POS precisa e funciona com qualquer impressora instalada.
- JSON: parse mínimo do próprio (só 3 campos) ou `JavaScriptSerializer` (nativo, `System.Web.Extensions`). Zero dependências externas.

## Componentes (um ficheiro `PrintBridge.cs`)

1. **Config** — lê um `config.txt` (key=value) ao lado do `.exe`: `url`, `api_key`, `printer_kitchen`, `printer_cashier`, `poll_seconds` (default 3). No arranque, imprime na consola a lista de impressoras instaladas (para o dono confirmar os nomes).
2. **Loop** — a cada `poll_seconds`: GET pending-jobs; para cada trabalho → resolve a impressora pelo `printer_type` → `printing` → descodifica base64 → `RawPrint` → `printed` (ou `failed` no erro). `escpos_base64` vazio → `failed` (nada para imprimir). Erros de rede: loga e continua (nunca crasha).
3. **RawPrint(printerName, bytes)** — o P/Invoke winspool.

## Configuração e arranque

- `config.txt` ao lado do `.exe` (o `printer_kitchen`/`printer_cashier` são os NOMES exatos das impressoras no Windows).
- Arranque automático: atalho do `.exe` na pasta *Startup* (`shell:startup`). Abre uma janela de consola com o log (o operador vê que está a correr).

## Fora de âmbito (YAGNI)

- Impressão por IP/TCP (só spooler Windows) — se um dia for preciso, acrescenta-se um ramo no `RawPrint`.
- Instalar como Serviço Windows (a pasta Startup chega; um serviço é mais setup).
- UI gráfica / auto-update / descoberta automática de impressoras.
- Alterações no backend.

## Substituição do tablet

O PC **substitui** o tablet: só um agente ativo por loja (a mesma `api_key`). Desliga-se a ponte no tablet quando a do PC arrancar, senão os dois puxam os mesmos trabalhos.

## Testes

Um self-check (`--selftest`) sem impressora nem rede: valida o parse do `config.txt` e o roteamento `printer_type → nome de impressora` (kitchen→printer_kitchen, cashier→printer_cashier, desconhecido→erro). O `RawPrint` (winspool) e o HTTP verificam-se no smoke real no PC.
