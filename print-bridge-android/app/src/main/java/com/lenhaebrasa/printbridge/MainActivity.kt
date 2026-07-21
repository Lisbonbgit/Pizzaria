package com.lenhaebrasa.printbridge

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

class MainActivity : Activity() {

    private lateinit var s: Settings

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        s = Settings(this)

        val backendUrl = findViewById<EditText>(R.id.backendUrl)
        val apiKey = findViewById<EditText>(R.id.apiKey)
        val kitchenIp = findViewById<EditText>(R.id.kitchenIp)
        val cashierIp = findViewById<EditText>(R.id.cashierIp)
        val pollSeconds = findViewById<EditText>(R.id.pollSeconds)
        val status = findViewById<TextView>(R.id.status)

        backendUrl.setText(s.backendUrl)
        apiKey.setText(s.apiKey)
        kitchenIp.setText(s.kitchenIp)
        cashierIp.setText(s.cashierIp)
        pollSeconds.setText(s.pollSeconds.toString())
        status.text = if (s.running) "A correr (serviço ativo)" else "Parado"

        fun save() {
            s.backendUrl = backendUrl.text.toString()
            s.apiKey = apiKey.text.toString()
            s.kitchenIp = kitchenIp.text.toString()
            s.cashierIp = cashierIp.text.toString()
            s.pollSeconds = pollSeconds.text.toString().toIntOrNull() ?: 3
        }

        findViewById<Button>(R.id.startBtn).setOnClickListener {
            save()
            ensureNotifPermission()
            val i = Intent(this, PrintService::class.java)
            startForegroundService(i)
            status.text = "A correr…"
            toast("Ponte iniciada")
        }

        findViewById<Button>(R.id.stopBtn).setOnClickListener {
            val i = Intent(this, PrintService::class.java).setAction(PrintService.ACTION_STOP)
            startService(i)
            status.text = "Parado"
        }

        findViewById<Button>(R.id.testKitchen).setOnClickListener { save(); testPrint(s.kitchenIp, "COZINHA") }
        findViewById<Button>(R.id.testCashier).setOnClickListener { save(); testPrint(s.cashierIp, "CAIXA") }
        findViewById<Button>(R.id.batteryBtn).setOnClickListener { requestIgnoreBattery() }
    }

    private fun testPrint(ip: String, name: String) {
        if (ip.isBlank()) { toast("Configura o IP primeiro"); return }
        thread {
            val (ok, msg) = Printer.send(ip, 9100, Printer.testTicket(name))
            runOnUiThread { toast(if (ok) "Teste enviado para $name" else "Falha: $msg") }
        }
    }

    private fun ensureNotifPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    private fun requestIgnoreBattery() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("Já está isento da poupança de bateria")
            return
        }
        try {
            startActivity(
                Intent(AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
            )
        } catch (e: Exception) {
            startActivity(Intent(AndroidSettings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()
}
