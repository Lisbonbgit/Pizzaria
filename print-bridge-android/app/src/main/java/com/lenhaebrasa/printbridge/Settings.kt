package com.lenhaebrasa.printbridge

import android.content.Context

/** Guarda a configuração da ponte em SharedPreferences. */
class Settings(context: Context) {
    private val p = context.getSharedPreferences("printbridge", Context.MODE_PRIVATE)

    var backendUrl: String
        get() = p.getString("backendUrl", "https://pedido.lenhaebrasa.com") ?: ""
        set(v) { p.edit().putString("backendUrl", v.trim().trimEnd('/')).apply() }

    var apiKey: String
        get() = p.getString("apiKey", "") ?: ""
        set(v) { p.edit().putString("apiKey", v.trim()).apply() }

    var kitchenIp: String
        get() = p.getString("kitchenIp", "") ?: ""
        set(v) { p.edit().putString("kitchenIp", v.trim()).apply() }

    var cashierIp: String
        get() = p.getString("cashierIp", "") ?: ""
        set(v) { p.edit().putString("cashierIp", v.trim()).apply() }

    var pollSeconds: Int
        get() = p.getInt("pollSeconds", 3)
        set(v) { p.edit().putInt("pollSeconds", v).apply() }

    /** true quando o utilizador iniciou a ponte (usado para religar no boot). */
    var running: Boolean
        get() = p.getBoolean("running", false)
        set(v) { p.edit().putBoolean("running", v).apply() }
}
