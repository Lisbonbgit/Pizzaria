# Ponte de impressão para Windows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um `.exe` C# que corre no PC Windows da loja e imprime a fila do backend nas impressoras instaladas no Windows (cozinha/caixa), substituindo a APK Android. Backend intacto.

**Architecture:** Um ficheiro `PrintBridge.cs` → `.exe` via o `csc.exe` que já vem no Windows. Faz polling a `/agent/pending-jobs`, marca `printing`, descodifica o `escpos_base64` e envia RAW à impressora do Windows (P/Invoke `winspool`), confirma `printed`/`failed`. Config num `config.txt`. Corre no arranque via pasta *Startup*.

**Tech Stack:** C# / .NET Framework 4.x (pré-instalado no Win 10/11), `HttpClient`, `System.Web.Extensions` (JSON), `System.Drawing` (listar impressoras), P/Invoke `winspool.drv`.

## Global Constraints

- **Sem dependências externas nem instalação de runtime** — só o que o Windows 10/11 já traz.
- **Backend não muda.** Contrato: `GET /api/agent/pending-jobs` (header `X-API-Key`) → array com `escpos_base64`, `printer_type` (`"kitchen"|"cashier"`), `job.id`; `PUT /api/agent/jobs/{id}/status` (header `X-API-Key`, corpo `{"status":"printing"|"printed"|"failed"}`).
- Marcar `printing` **antes** de imprimir (o GET só devolve `pending`) → não imprime a dobrar.
- Impressão **RAW** (datatype `"RAW"`) — bytes crus, sem o driver interpretar.
- Textos ao utilizador em **PT-PT**.
- Verificação: `PrintBridge.exe --selftest` (sem rede/impressora) + smoke real no PC. Não há compilação/execução no ambiente de desenvolvimento (macOS).

---

### Task 1: `PrintBridge.cs` — o programa + `config.example.txt`

**Files:**
- Create: `print-bridge-windows/PrintBridge.cs`
- Create: `print-bridge-windows/config.example.txt`

**Interfaces:**
- Produces: `PrintBridge.exe`; modos `--selftest` (asserts do config-parse + roteamento) e normal (loop).

- [ ] **Step 1: Escrever `config.example.txt`**

```
# Configuracao da ponte de impressao (renomear para config.txt, ao lado do .exe)
# URL do backend (sem barra no fim)
url=https://pedido.lenhaebrasa.com
# Chave do agente de impressao (a mesma do tablet: Admin -> Definicoes)
api_key=COLAR_A_CHAVE_AQUI
# Nomes EXATOS das impressoras no Windows (ver a lista que o programa mostra no arranque)
printer_kitchen=Cozinha
printer_cashier=Caixa
# Intervalo de consulta em segundos (opcional, default 3)
poll_seconds=3
```

- [ ] **Step 2: Escrever `PrintBridge.cs` (programa completo)**

```csharp
using System;
using System.Collections.Generic;
using System.Drawing.Printing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

class PrintBridge
{
    // ---------- Config ----------
    static Dictionary<string, string> LoadConfig(string path)
    {
        var cfg = new Dictionary<string, string>();
        foreach (var raw in File.ReadAllLines(path))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("#")) continue;
            int eq = line.IndexOf('=');
            if (eq <= 0) continue;
            cfg[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
        }
        foreach (var k in new[] { "url", "api_key", "printer_kitchen", "printer_cashier" })
            if (!cfg.ContainsKey(k) || cfg[k].Length == 0)
                throw new Exception("config.txt: falta '" + k + "'");
        return cfg;
    }

    // Impressora do Windows para o tipo de trabalho.
    static string PrinterFor(string printerType, Dictionary<string, string> cfg)
    {
        if (printerType == "cashier") return cfg["printer_cashier"];
        if (printerType == "kitchen") return cfg["printer_kitchen"];
        throw new Exception("printer_type desconhecido: " + printerType);
    }

    // ---------- Impressao RAW (winspool) ----------
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    class DOCINFOA { public string pDocName; public string pOutputFile; public string pDataType; }

    [DllImport("winspool.Drv", EntryPoint = "OpenPrinterA", SetLastError = true, CharSet = CharSet.Ansi)]
    static extern bool OpenPrinter(string src, out IntPtr hPrinter, IntPtr pd);
    [DllImport("winspool.Drv", EntryPoint = "ClosePrinter", SetLastError = true)]
    static extern bool ClosePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "StartDocPrinterA", SetLastError = true, CharSet = CharSet.Ansi)]
    static extern bool StartDocPrinter(IntPtr hPrinter, int level, [In] DOCINFOA di);
    [DllImport("winspool.Drv", EntryPoint = "EndDocPrinter", SetLastError = true)]
    static extern bool EndDocPrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "StartPagePrinter", SetLastError = true)]
    static extern bool StartPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "EndPagePrinter", SetLastError = true)]
    static extern bool EndPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "WritePrinter", SetLastError = true)]
    static extern bool WritePrinter(IntPtr hPrinter, IntPtr pBytes, int dwCount, out int dwWritten);

    static void RawPrint(string printerName, byte[] bytes)
    {
        IntPtr hPrinter;
        if (!OpenPrinter(printerName, out hPrinter, IntPtr.Zero))
            throw new Exception("Impressora nao encontrada: '" + printerName + "'");
        try
        {
            var di = new DOCINFOA { pDocName = "Pedido", pDataType = "RAW" };
            if (!StartDocPrinter(hPrinter, 1, di)) throw new Exception("StartDocPrinter falhou");
            try
            {
                if (!StartPagePrinter(hPrinter)) throw new Exception("StartPagePrinter falhou");
                IntPtr buf = Marshal.AllocCoTaskMem(bytes.Length);
                try
                {
                    Marshal.Copy(bytes, 0, buf, bytes.Length);
                    int written;
                    if (!WritePrinter(hPrinter, buf, bytes.Length, out written))
                        throw new Exception("WritePrinter falhou");
                }
                finally { Marshal.FreeCoTaskMem(buf); }
                EndPagePrinter(hPrinter);
            }
            finally { EndDocPrinter(hPrinter); }
        }
        finally { ClosePrinter(hPrinter); }
    }

    // ---------- HTTP ----------
    static readonly HttpClient http = new HttpClient();
    static readonly JavaScriptSerializer json = new JavaScriptSerializer();

    static void SetStatus(string url, string key, string jobId, string status)
    {
        var req = new HttpRequestMessage(HttpMethod.Put, url + "/api/agent/jobs/" + jobId + "/status");
        req.Headers.Add("X-API-Key", key);
        req.Content = new StringContent("{\"status\":\"" + status + "\"}", Encoding.UTF8, "application/json");
        http.SendAsync(req).GetAwaiter().GetResult().EnsureSuccessStatusCode();
    }

    static void Log(string msg) { Console.WriteLine(DateTime.Now.ToString("HH:mm:ss") + "  " + msg); }

    // ---------- Loop ----------
    static void Run(Dictionary<string, string> cfg)
    {
        string url = cfg["url"].TrimEnd('/');
        string key = cfg["api_key"];
        int poll = cfg.ContainsKey("poll_seconds") ? int.Parse(cfg["poll_seconds"]) : 3;

        Log("Impressoras instaladas no Windows:");
        foreach (string p in PrinterSettings.InstalledPrinters) Log("   - " + p);
        Log("Cozinha='" + cfg["printer_kitchen"] + "'  Caixa='" + cfg["printer_cashier"] + "'");
        Log("Ligado a " + url + ". A consultar a cada " + poll + "s. (Ctrl+C para sair)");

        while (true)
        {
            try
            {
                var req = new HttpRequestMessage(HttpMethod.Get, url + "/api/agent/pending-jobs");
                req.Headers.Add("X-API-Key", key);
                var resp = http.SendAsync(req).GetAwaiter().GetResult();
                resp.EnsureSuccessStatusCode();
                string body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                var jobs = json.Deserialize<List<Dictionary<string, object>>>(body);

                foreach (var item in jobs)
                {
                    string jobId = null, ptype = null, b64 = null;
                    if (item.ContainsKey("job") && item["job"] is Dictionary<string, object> j && j.ContainsKey("id"))
                        jobId = Convert.ToString(j["id"]);
                    if (item.ContainsKey("printer_type")) ptype = Convert.ToString(item["printer_type"]);
                    if (item.ContainsKey("escpos_base64")) b64 = Convert.ToString(item["escpos_base64"]);
                    if (jobId == null) continue;

                    try
                    {
                        SetStatus(url, key, jobId, "printing");
                        if (string.IsNullOrEmpty(b64))
                        {
                            Log("Job " + jobId + " sem conteudo -> failed");
                            SetStatus(url, key, jobId, "failed");
                            continue;
                        }
                        RawPrint(PrinterFor(ptype, cfg), Convert.FromBase64String(b64));
                        SetStatus(url, key, jobId, "printed");
                        Log("Impresso job " + jobId + " (" + ptype + ")");
                    }
                    catch (Exception ex)
                    {
                        Log("ERRO no job " + jobId + ": " + ex.Message);
                        try { SetStatus(url, key, jobId, "failed"); } catch { }
                    }
                }
            }
            catch (Exception ex) { Log("Rede/consulta falhou (tenta outra vez): " + ex.Message); }
            Thread.Sleep(poll * 1000);
        }
    }

    // ---------- Self-test (sem rede/impressora) ----------
    static int SelfTest()
    {
        string tmp = Path.GetTempFileName();
        File.WriteAllText(tmp, "url=http://x\napi_key=k\nprinter_kitchen=CZ\nprinter_cashier=CX\n# comentario\n");
        var cfg = LoadConfig(tmp);
        File.Delete(tmp);
        Assert(cfg["url"] == "http://x", "url");
        Assert(cfg["printer_cashier"] == "CX", "printer_cashier");
        Assert(PrinterFor("kitchen", cfg) == "CZ", "route kitchen");
        Assert(PrinterFor("cashier", cfg) == "CX", "route cashier");
        bool threw = false;
        try { PrinterFor("outro", cfg); } catch { threw = true; }
        Assert(threw, "printer_type desconhecido deve falhar");
        Console.WriteLine("SELFTEST OK");
        return 0;
    }
    static void Assert(bool cond, string what) { if (!cond) throw new Exception("SELFTEST FALHOU: " + what); }

    // ---------- Main ----------
    static int Main(string[] args)
    {
        try
        {
            if (args.Length > 0 && args[0] == "--selftest") return SelfTest();
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            Run(LoadConfig(Path.Combine(dir, "config.txt")));
            return 0;
        }
        catch (Exception ex) { Console.WriteLine("ERRO FATAL: " + ex.Message); return 1; }
    }
}
```

- [ ] **Step 3: Commit**

```bash
cd ~/dev/pizzaria && git add print-bridge-windows/PrintBridge.cs print-bridge-windows/config.example.txt
git commit -m "Ponte Windows: programa C# (polling + RAW spooler) + config exemplo"
```

---

### Task 2: `build.bat` + `README.md`

**Files:**
- Create: `print-bridge-windows/build.bat`
- Create: `print-bridge-windows/README.md`

- [ ] **Step 1: `build.bat` (compila com o csc que já vem no Windows)**

```bat
@echo off
REM Compila PrintBridge.exe usando o compilador C# que ja vem no Windows.
set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo Nao encontrei o csc.exe do .NET Framework. Este PC precisa do .NET Framework 4.x.
  pause & exit /b 1
)
"%CSC%" /nologo /platform:x86 /reference:System.Web.Extensions.dll /reference:System.Drawing.dll /out:PrintBridge.exe PrintBridge.cs
if errorlevel 1 ( echo FALHOU a compilacao. & pause & exit /b 1 )
echo OK: PrintBridge.exe criado.
PrintBridge.exe --selftest
pause
```

- [ ] **Step 2: `README.md` (instruções para a loja)**

```markdown
# Ponte de impressão (Windows)

Substitui a app do tablet: corre no PC da loja e imprime os pedidos/faturas nas
impressoras instaladas no Windows.

## Instalar (uma vez)
1. Copiar a pasta `print-bridge-windows` para o PC (ex.: `C:\PrintBridge`).
2. Duplo-clique em `build.bat` → cria `PrintBridge.exe` e corre o auto-teste
   (deve dizer `SELFTEST OK`).
3. Renomear `config.example.txt` para `config.txt` e preencher:
   - `api_key`: a chave em Admin → Definições (a mesma do tablet).
   - `printer_kitchen` / `printer_cashier`: os nomes EXATOS das impressoras
     (a lista aparece quando o programa arranca).
4. **Desligar a ponte no tablet** (senão imprime a dobrar).

## Arrancar sempre com o Windows
1. Tecla Windows + R → escrever `shell:startup` → Enter.
2. Criar um atalho para `PrintBridge.exe` dentro dessa pasta.
Fica a correr numa janela; para testar, faz um pedido e vê "Impresso job ...".

## Notas
- Impressão RAW (bytes ESC/POS crus) — funciona com qualquer impressora
  instalada, independentemente do driver.
- Se uma impressão falhar, o programa continua e regista o erro na janela.
```

- [ ] **Step 3: Commit**

```bash
cd ~/dev/pizzaria && git add print-bridge-windows/build.bat print-bridge-windows/README.md
git commit -m "Ponte Windows: build.bat (csc nativo) + README de instalacao"
```

---

## Verificação (no PC Windows do dono — não é possível aqui)

1. `build.bat` → `SELFTEST OK` (valida config-parse + roteamento).
2. `config.txt` preenchido; arrancar → confirma que lista as impressoras e liga ao backend.
3. Desligar a ponte do tablet; fazer um pedido → sai na cozinha; fechar/consulta → sai na caixa.

## Self-review (feito)

- **Cobertura do spec:** polling+status+RAW (Task 1 `Run`/`RawPrint`) ✓; config.txt + lista de impressoras (Task 1) ✓; `--selftest` (Task 1) ✓; build sem instalar nada (Task 2 `build.bat` usa o csc do Windows) ✓; arranque via Startup (README) ✓; marca `printing` antes de imprimir ✓; substitui o tablet (README) ✓; fora de âmbito (TCP/serviço/UI) não incluído ✓.
- **Sem placeholders:** código C# e ficheiros completos.
- **Consistência:** `PrinterFor`/`LoadConfig`/`RawPrint`/`SetStatus` usados em `Run` e `SelfTest` com as mesmas assinaturas; campos do JSON (`job.id`, `printer_type`, `escpos_base64`) batem com o contrato do backend (server.py:2734-2742).
```
