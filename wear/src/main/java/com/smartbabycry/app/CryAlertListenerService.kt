package com.smartbabycry.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService

class CryAlertListenerService : WearableListenerService() {
    companion object {
        private const val CRY_ALERT_PATH = "/baby-cry/alert"
        private const val CHANNEL_ID = "baby_cry_alerts"
        private const val NOTIFICATION_ID = 101
    }

    override fun onMessageReceived(event: MessageEvent) {
        if (event.path != CRY_ALERT_PATH) return
        CryAlertStore.save(this)
        vibrate()
        showNotification()
    }

    private fun vibrate() {
        val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            getSystemService(VibratorManager::class.java).defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }
        val pattern = longArrayOf(0, 500, 250, 500, 250, 800)
        vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
    }

    private fun showNotification() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Baby cry alerts",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "Urgent alerts when the phone detects baby crying"
                enableVibration(false)
            },
        )

        val intent = Intent(this, WearMainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = android.app.Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_alert)
            .setContentTitle("Baby is crying")
            .setContentText("Tap to open the alert.")
            .setCategory(android.app.Notification.CATEGORY_ALARM)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()
        manager.notify(NOTIFICATION_ID, notification)
    }
}
