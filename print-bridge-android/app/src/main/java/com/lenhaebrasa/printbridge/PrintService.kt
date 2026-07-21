package com.lenhaebrasa.printbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.os.PowerManager
import android.util.Base64
import android.util.Log
import org.json.JSONObject

/**
 * Serviço em primeiro plano: faz polling aos talões pendentes e imprime-os.
 * Notificação permanente + wake lock para sobreviver com o ecrã apagado.
 */
class PrintService : Service() {

    companion object {
        const val ACTION_STOP = "com.lenhaebrasa.printbridge.STOP"
        private const val CHANNEL = "printbridge"
        private const val NOTIF_ID = 1001
        private const val TAG = "PrintBridge"
    }

    @Volatile private var running = false
    private var worker: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val ch = NotificationChannel(CHANNEL, "Ponte de impressão", NotificationManager.IMPORTANCE_LOW)
        ch.setShowBadge(false)
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopEverything()
            return START_NOT_STICKY
        }
        startForeground(NOTIF_ID, notif("A ligar…"))
        if (!running) {
            running = true
            Settings(this).running = true
            acquireWake()
            worker = Thread { loop() }.also { it.start() }
        }
        return START_STICKY
    }

    private fun loop() {
        val s = Settings(this)
        var errors = 0
        while (running) {
            try {
                val api = Api(s.backendUrl, s.apiKey)
                val jobs = api.pendingJobs()
                if (jobs.length() == 0) {
                    update("Ligado · sem talões pendentes")
                } else {
                    var ok = 0
                    for (i in 0 until jobs.length()) {
                        if (!running) break
                        if (handle(s, api, jobs.getJSONObject(i))) ok++
                    }
                    update("Ligado · $ok/${jobs.length()} impresso(s)")
                }
                errors = 0
            } catch (e: Exception) {
                errors++
                update("Sem ligação ao servidor ($errors)")
                Log.w(TAG, "poll", e)
            }
            try {
                Thread.sleep(s.pollSeconds.coerceIn(1, 60) * 1000L)
            } catch (e: InterruptedException) {
                break
            }
        }
    }

    /** Processa um job: escolhe a impressora (por tipo), imprime os bytes e confirma. */
    private fun handle(s: Settings, api: Api, entry: JSONObject): Boolean {
        val job = entry.optJSONObject("job") ?: return false
        val jobId = job.optString("id")
        if (jobId.isBlank()) return false

        val type = entry.optString("printer_type", job.optString("printer_type", "kitchen"))
        val printer = entry.optJSONObject("printer")
        val jobIp = printer?.optString("ip")?.takeIf { it.isNotBlank() }
        val ip = jobIp ?: if (type == "cashier") s.cashierIp else s.kitchenIp
        val port = printer?.optInt("port", 9100) ?: 9100
        val b64 = entry.optString("escpos_base64", "")

        if (ip.isBlank()) {
            api.confirmSafe(jobId, "failed", "IP da impressora ($type) não configurado")
            return false
        }
        if (b64.isBlank()) {
            api.confirmSafe(jobId, "failed", "Sem conteúdo para imprimir")
            return false
        }
        val data = try {
            Base64.decode(b64, Base64.DEFAULT)
        } catch (e: Exception) {
            api.confirmSafe(jobId, "failed", "Conteúdo inválido")
            return false
        }

        val (ok, msg) = Printer.send(ip, port, data)
        api.confirmSafe(jobId, if (ok) "printed" else "failed", if (ok) null else msg)
        return ok
    }

    private fun acquireWake() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PrintBridge:wake").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun stopEverything() {
        running = false
        Settings(this).running = false
        worker?.interrupt()
        wakeLock?.let { if (it.isHeld) it.release() }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun notif(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Ponte de impressão")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private fun update(text: String) {
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, notif(text))
    }
}
