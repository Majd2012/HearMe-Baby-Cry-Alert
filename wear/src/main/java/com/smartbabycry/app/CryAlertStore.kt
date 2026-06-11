package com.smartbabycry.app

import android.content.Context

object CryAlertStore {
    private const val PREFERENCES = "cry_alerts"
    private const val KEY_LAST_ALERT = "last_alert"

    fun save(context: Context, timestamp: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_ALERT, timestamp)
            .apply()
    }

    fun lastAlert(context: Context): Long =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .getLong(KEY_LAST_ALERT, 0L)

    fun clear(context: Context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_LAST_ALERT)
            .apply()
    }
}

