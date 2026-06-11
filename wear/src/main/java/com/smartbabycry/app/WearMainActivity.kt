package com.smartbabycry.app

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.text.DateFormat
import java.util.Date

class WearMainActivity : Activity() {
    private val navy = Color.rgb(13, 40, 77)
    private val coral = Color.rgb(255, 105, 97)
    private lateinit var statusText: TextView
    private lateinit var detailText: TextView
    private lateinit var confirmButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContentView())
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 200)
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val timestamp = CryAlertStore.lastAlert(this)
        val hasAlert = timestamp != 0L
        statusText.text = if (hasAlert) "Baby may be crying" else "All calm"
        detailText.text = if (hasAlert) {
            val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(timestamp))
            "Alert received at $time"
        } else {
            "HearMe is connected"
        }
        statusText.setTextColor(if (hasAlert) coral else Color.WHITE)
        confirmButton.visibility = if (hasAlert) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun buildContentView() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        setPadding(dp(28), dp(16), dp(28), dp(16))
        setBackgroundColor(navy)

        addView(TextView(this@WearMainActivity).apply {
            text = "HearMe"
            textSize = 18f
            gravity = Gravity.CENTER
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(Color.WHITE)
        }, fullWidth(0))

        statusText = TextView(this@WearMainActivity).apply {
            textSize = 19f
            gravity = Gravity.CENTER
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(Color.WHITE)
        }
        addView(statusText, fullWidth(14))

        detailText = TextView(this@WearMainActivity).apply {
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(207, 218, 232))
        }
        addView(detailText, fullWidth(6))

        confirmButton = Button(this@WearMainActivity).apply {
            text = "I'm on it"
            textSize = 13f
            isAllCaps = false
            setTextColor(navy)
            background = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(18).toFloat()
            }
            stateListAnimator = null
            setOnClickListener {
                CryAlertStore.clear(this@WearMainActivity)
                refresh()
            }
        }
        addView(confirmButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(40),
        ).apply { topMargin = dp(14) })
    }

    private fun fullWidth(top: Int) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(top) }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
