package com.smartbabycry.app

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.DateFormat
import java.util.Date
import java.util.Locale

class MainActivity : Activity() {
    companion object {
        private const val MICROPHONE_PERMISSION_REQUEST = 100
        private val NAVY = Color.rgb(13, 40, 77)
        private val CORAL = Color.rgb(255, 105, 97)
        private val CREAM = Color.rgb(252, 248, 241)
        private val MUTED = Color.rgb(98, 108, 120)
        private val PALE_BLUE = Color.rgb(233, 241, 248)
    }

    private lateinit var statusText: TextView
    private lateinit var statusDetailText: TextView
    private lateinit var watchText: TextView
    private lateinit var toggleButton: Button
    private lateinit var testAlertButton: Button
    private lateinit var statusCard: LinearLayout

    private lateinit var detector: CryDetector
    private lateinit var audioMonitor: AudioMonitor
    private lateinit var wearAlertSender: WearAlertSender
    private var latestAudioLevel = 0f

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        detector = YamNetCryDetector(this)
        setContentView(buildContentView())

        wearAlertSender = WearAlertSender(this)
        audioMonitor = AudioMonitor(
            detector = detector,
            decisionPolicy = CryDecisionPolicy(),
            onAudioLevel = { level ->
                runOnUiThread {
                    latestAudioLevel = level
                }
            },
            onDecision = { score, decision ->
                runOnUiThread {
                    statusDetailText.text = if (latestAudioLevel == 0f) {
                        "No microphone signal. Check the emulator host microphone."
                    } else if (decision.detectorState == CryDetectorState.POSSIBLE_CRY) {
                        "Possible cry: ${decision.positiveSegments} of " +
                            "${decision.requiredPositiveSegments} confirming segments."
                    } else if (decision.shouldAlert) {
                        "Cry confirmed. Sending one alert to the watch."
                    } else if (decision.detectorState == CryDetectorState.COOLDOWN ||
                        decision.detectorState == CryDetectorState.ALERTED
                    ) {
                        "Alert sent. Waiting for the sound to calm before rearming."
                    } else {
                        "State: ${decision.detectorState.name.lowercase(Locale.US)} | " +
                            "score ${String.format(Locale.US, "%.2f", decision.smoothedScore)}"
                    }
                }
            },
            onCryDetected = { score ->
                runOnUiThread {
                    setStatus("Baby may be crying", "Sending a gentle alert to your watch.", true)
                    sendWatchAlert(score)
                }
            },
            onError = { message ->
                runOnUiThread {
                    setStatus("Monitoring paused", message, true)
                    updateRunningUi(false)
                }
            },
        )

        toggleButton.setOnClickListener {
            if (audioMonitor.isRunning()) stopMonitoring() else ensurePermissionAndStart()
        }
        testAlertButton.setOnClickListener { sendWatchAlert(1f) }
    }

    override fun onDestroy() {
        audioMonitor.stop()
        detector.close()
        super.onDestroy()
    }

    private fun ensurePermissionAndStart() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startMonitoring()
        } else {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MICROPHONE_PERMISSION_REQUEST)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == MICROPHONE_PERMISSION_REQUEST &&
            grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        ) {
            startMonitoring()
        } else {
            setStatus("Microphone needed", "Allow microphone access so HearMe can listen.", true)
        }
    }

    private fun startMonitoring() {
        audioMonitor.start()
        setStatus("Listening", "HearMe is quietly monitoring near your baby.", false)
        updateRunningUi(true)
    }

    private fun stopMonitoring() {
        audioMonitor.stop()
        setStatus("Ready when you are", "Place the phone near your baby, then start listening.", false)
        updateRunningUi(false)
    }

    private fun setStatus(title: String, detail: String, alert: Boolean) {
        statusText.text = title
        statusDetailText.text = detail
        statusCard.background = rounded(if (alert) Color.rgb(255, 235, 232) else Color.WHITE, 28)
        statusText.setTextColor(if (alert) Color.rgb(151, 48, 48) else NAVY)
    }

    private fun updateRunningUi(running: Boolean) {
        toggleButton.text = if (running) "Stop listening" else "Start listening"
        toggleButton.background = rounded(if (running) PALE_BLUE else NAVY, 18)
        toggleButton.setTextColor(if (running) NAVY else Color.WHITE)
    }

    private fun sendWatchAlert(score: Float) {
        watchText.text = "Contacting your watch..."
        wearAlertSender.send(score) { result ->
            runOnUiThread {
                watchText.text = result.fold(
                    onSuccess = {
                        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date())
                        "Watch connected | Last alert $time"
                    },
                    onFailure = { "Watch unavailable | ${it.message}" },
                )
            }
        }
    }

    private fun buildContentView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(18), dp(24), dp(32))
            setBackgroundColor(CREAM)
        }

        root.addView(ImageView(this).apply {
            setImageResource(R.drawable.hearme_mark)
            scaleType = ImageView.ScaleType.FIT_CENTER
            contentDescription = "HearMe"
        }, LinearLayout.LayoutParams(dp(82), dp(82)).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        })

        root.addView(TextView(this).apply {
            text = "HearMe"
            textSize = 30f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(NAVY)
        }, fullWidth(top = 0))

        root.addView(TextView(this).apply {
            text = "Peace of mind, within reach."
            textSize = 15f
            gravity = Gravity.CENTER
            setTextColor(MUTED)
        }, fullWidth(top = 2))

        statusCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(28), dp(24), dp(28))
            background = rounded(Color.WHITE, 28)
            elevation = dp(3).toFloat()
        }
        statusText = TextView(this).apply {
            text = "Ready when you are"
            textSize = 25f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(NAVY)
        }
        statusDetailText = TextView(this).apply {
            text = "Place the phone near your baby, then start listening."
            textSize = 15f
            gravity = Gravity.CENTER
            setTextColor(MUTED)
            setLineSpacing(0f, 1.15f)
        }
        statusCard.addView(statusText, fullWidth())
        statusCard.addView(statusDetailText, fullWidth(top = 10))
        root.addView(statusCard, fullWidth(top = 24))

        toggleButton = Button(this).apply {
            text = "Start listening"
            textSize = 17f
            isAllCaps = false
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(Color.WHITE)
            background = rounded(NAVY, 18)
            stateListAnimator = null
        }
        root.addView(toggleButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(58),
        ).apply { topMargin = dp(26) })

        testAlertButton = Button(this).apply {
            text = "Test watch connection"
            textSize = 15f
            isAllCaps = false
            setTextColor(NAVY)
            background = rounded(PALE_BLUE, 18)
            stateListAnimator = null
        }
        root.addView(testAlertButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(52),
        ).apply { topMargin = dp(12) })

        watchText = TextView(this).apply {
            text = "Watch ready for alerts"
            textSize = 13f
            gravity = Gravity.CENTER
            setTextColor(MUTED)
        }
        root.addView(watchText, fullWidth(top = 14))

        root.addView(TextView(this).apply {
            text = "YAMNet AI  |  5 sec samples  |  state-machine alerts"
            textSize = 12f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(135, 143, 151))
        }, fullWidth(top = 28))

        return ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(CREAM)
            addView(root)
        }
    }

    private fun rounded(color: Int, radiusDp: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(color)
        cornerRadius = dp(radiusDp).toFloat()
    }

    private fun fullWidth(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(top) }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
