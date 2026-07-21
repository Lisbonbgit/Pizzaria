package com.lenhaebrasa.printbridge

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Cliente HTTP mínimo para o contrato do agente de impressão. */
class Api(baseUrl: String, private val apiKey: String) {
    private val base = baseUrl.trim().trimEnd('/')

    /** GET /api/agent/pending-jobs → lista de { job, printer, printer_type, order, escpos_base64 }. */
    fun pendingJobs(): JSONArray {
        val c = URL("$base/api/agent/pending-jobs").openConnection() as HttpURLConnection
        c.requestMethod = "GET"
        c.setRequestProperty("X-API-Key", apiKey)
        c.connectTimeout = 8000
        c.readTimeout = 8000
        try {
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) throw RuntimeException("HTTP $code")
            return JSONArray(text)
        } finally {
            c.disconnect()
        }
    }

    /** PUT /api/agent/jobs/{id}/status com { status, error? }. Estados: printed | failed. */
    fun confirm(jobId: String, status: String, error: String?) {
        val c = URL("$base/api/agent/jobs/$jobId/status").openConnection() as HttpURLConnection
        c.requestMethod = "PUT"
        c.setRequestProperty("X-API-Key", apiKey)
        c.setRequestProperty("Content-Type", "application/json")
        c.doOutput = true
        c.connectTimeout = 8000
        c.readTimeout = 8000
        val body = JSONObject().put("status", status)
        if (error != null) body.put("error", error)
        try {
            c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            c.responseCode
        } finally {
            c.disconnect()
        }
    }

    fun confirmSafe(jobId: String, status: String, error: String?) {
        try { confirm(jobId, status, error) } catch (_: Exception) { /* não deixa a falha de confirmação parar a ponte */ }
    }
}
