package com.lenhaebrasa.printbridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Religa a ponte automaticamente depois de o tablet reiniciar. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Settings(context).running) {
            context.startForegroundService(Intent(context, PrintService::class.java))
        }
    }
}
