package com.lenhaebrasa.printbridge

import java.io.ByteArrayOutputStream
import java.net.InetSocketAddress
import java.net.Socket

/** Envia bytes ESC/POS crus para uma impressora de rede (porta 9100). */
object Printer {

    fun send(ip: String, port: Int, data: ByteArray): Pair<Boolean, String> {
        return try {
            Socket().use { s ->
                s.connect(InetSocketAddress(ip, port), 6000)
                val out = s.getOutputStream()
                out.write(data)
                out.flush()
            }
            true to "ok"
        } catch (e: Exception) {
            false to (e.message ?: "erro de ligação")
        }
    }

    /** Talão de teste gerado localmente (não depende do servidor). */
    fun testTicket(name: String): ByteArray {
        val esc = 0x1B.toByte()
        val gs = 0x1D.toByte()
        val out = ByteArrayOutputStream()
        out.write(byteArrayOf(esc, '@'.code.toByte()))               // init
        out.write(byteArrayOf(esc, 'a'.code.toByte(), 1))            // alinhar ao centro
        out.write("LENHA E BRASA\n".toByteArray(Charsets.ISO_8859_1))
        out.write("Ponte de impressao\n".toByteArray(Charsets.ISO_8859_1))
        out.write("[$name] OK\n".toByteArray(Charsets.ISO_8859_1))
        out.write("\n\n\n".toByteArray(Charsets.ISO_8859_1))
        out.write(byteArrayOf(gs, 'V'.code.toByte(), 0))             // corte total
        return out.toByteArray()
    }
}
