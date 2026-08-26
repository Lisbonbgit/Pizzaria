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
    static void Assert(bool cond, string what) { if (!cond) throw new Exception("SELFTEST FALHOU: " + what); }

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
