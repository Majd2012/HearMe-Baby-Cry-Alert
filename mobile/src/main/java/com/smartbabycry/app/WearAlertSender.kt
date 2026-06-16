package com.smartbabycry.app

import android.content.Context
import com.google.android.gms.wearable.Wearable
import java.nio.charset.StandardCharsets

class WearAlertSender(context: Context) {
    companion object {
        const val CRY_ALERT_PATH = "/baby-cry/alert"
    }

    private val nodeClient = Wearable.getNodeClient(context)
    private val messageClient = Wearable.getMessageClient(context)

    fun send(score: Float, callback: (Result<Int>) -> Unit) {
        val payload = """{"score":$score,"timestamp":${System.currentTimeMillis()}}"""
            .toByteArray(StandardCharsets.UTF_8)

        nodeClient.connectedNodes
            .addOnSuccessListener { nodes ->
                if (nodes.isEmpty()) {
                    callback(Result.failure(IllegalStateException("No connected Wear OS watch.")))
                    return@addOnSuccessListener
                }

                var remaining = nodes.size
                var successful = 0
                nodes.forEach { node ->
                    messageClient.sendMessage(node.id, CRY_ALERT_PATH, payload)
                        .addOnSuccessListener {
                            successful++
                            remaining--
                            if (remaining == 0) callback(Result.success(successful))
                        }
                        .addOnFailureListener { error ->
                            remaining--
                            if (remaining == 0) {
                                if (successful > 0) callback(Result.success(successful))
                                else callback(Result.failure(error))
                            }
                        }
                }
            }
            .addOnFailureListener { callback(Result.failure(it)) }
    }
}
