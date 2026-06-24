package com.smartbabycry.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.DateFormat
import java.util.Date
import kotlin.math.max
import kotlin.math.sin

class MainActivity : Activity() {
    companion object {
        private const val MICROPHONE_PERMISSION_REQUEST = 100

        private val BACKGROUND = Color.rgb(248, 246, 240)
        private val SURFACE = Color.WHITE
        private val SURFACE_TINT = Color.rgb(237, 246, 245)
        private val PRIMARY = Color.rgb(18, 53, 91)
        private val PRIMARY_SOFT = Color.rgb(227, 238, 249)
        private val TEAL = Color.rgb(26, 127, 120)
        private val GREEN = Color.rgb(46, 125, 91)
        private val AMBER = Color.rgb(165, 105, 25)
        private val ALERT = Color.rgb(190, 58, 52)
        private val ALERT_SOFT = Color.rgb(255, 241, 239)
        private val TEXT = Color.rgb(30, 41, 59)
        private val MUTED = Color.rgb(91, 104, 124)
        private val BORDER = Color.rgb(219, 226, 235)
    }

    private data class StatusUi(
        val title: String,
        val detail: String,
        val accent: Int,
        val background: Int,
    )

    private lateinit var statusTitle: TextView
    private lateinit var statusDetail: TextView
    private lateinit var statusCard: LinearLayout
    private lateinit var statusIcon: ImageView
    private lateinit var toggleButton: Button
    private lateinit var testAlertButton: Button
    private lateinit var watchSummary: TextView
    private lateinit var liveSection: LinearLayout
    private lateinit var confidenceText: TextView
    private lateinit var soundWaveView: SoundWaveView
    private lateinit var recentAlertsList: LinearLayout
    private lateinit var emptyHistoryText: TextView
    private lateinit var microphoneChip: TextView
    private lateinit var watchChip: TextView
    private lateinit var monitoringChip: TextView
    private lateinit var headerWatchChip: TextView

    private lateinit var detector: CryDetector
    private lateinit var audioMonitor: AudioMonitor
    private lateinit var wearAlertSender: WearAlertSender
    private val recentAlerts = ArrayDeque<String>()
    private var latestAudioLevel = 0f
    private var isMonitoring = false

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
                    soundWaveView.level = level
                }
            },
            onDecision = { _, decision ->
                runOnUiThread { updateFromDecision(decision) }
            },
            onCryDetected = { score ->
                runOnUiThread {
                    applyStatus(
                        StatusUi(
                            title = "Alert Sent to Watch",
                            detail = "A cry was confirmed. HearMe is notifying the smartwatch now.",
                            accent = ALERT,
                            background = ALERT_SOFT,
                        ),
                    )
                    sendWatchAlert(score, fromCry = true)
                }
            },
            onError = { message ->
                runOnUiThread {
                    applyStatus(
                        StatusUi(
                            title = "Monitoring Paused",
                            detail = message.ifBlank { "Something interrupted monitoring. Please start again." },
                            accent = ALERT,
                            background = ALERT_SOFT,
                        ),
                    )
                    updateRunningUi(false)
                }
            },
        )

        toggleButton.setOnClickListener {
            if (audioMonitor.isRunning()) stopMonitoring() else ensurePermissionAndStart()
        }
        testAlertButton.setOnClickListener { sendWatchAlert(1f, fromCry = false) }
        refreshPermissionUi()
        updateRunningUi(false)
    }

    override fun onDestroy() {
        audioMonitor.stop()
        detector.close()
        super.onDestroy()
    }

    private fun ensurePermissionAndStart() {
        if (hasMicrophonePermission()) {
            startMonitoring()
        } else {
            applyStatus(
                StatusUi(
                    title = "Microphone Permission Needed",
                    detail = "Allow microphone access so HearMe can listen near your baby.",
                    accent = AMBER,
                    background = Color.rgb(255, 248, 235),
                ),
            )
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MICROPHONE_PERMISSION_REQUEST)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refreshPermissionUi()
        if (requestCode == MICROPHONE_PERMISSION_REQUEST &&
            grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        ) {
            startMonitoring()
        } else {
            applyStatus(
                StatusUi(
                    title = "Microphone Permission Needed",
                    detail = "HearMe needs microphone access to monitor baby crying.",
                    accent = AMBER,
                    background = Color.rgb(255, 248, 235),
                ),
            )
        }
    }

    private fun startMonitoring() {
        audioMonitor.start()
        applyStatus(
            StatusUi(
                title = "Monitoring Baby",
                detail = "HearMe is listening calmly and will alert your watch if crying is confirmed.",
                accent = TEAL,
                background = SURFACE_TINT,
            ),
        )
        updateRunningUi(true)
    }

    private fun stopMonitoring() {
        audioMonitor.stop()
        latestAudioLevel = 0f
        soundWaveView.level = 0f
        applyStatus(
            StatusUi(
                title = "Ready to Monitor",
                detail = "Place the phone near your baby, then start monitoring.",
                accent = PRIMARY,
                background = SURFACE,
            ),
        )
        updateRunningUi(false)
    }

    private fun updateFromDecision(decision: CryDecisionState) {
        refreshPermissionUi()
        confidenceText.text = "Confidence: ${confidenceLabel(decision.smoothedScore)}"

        if (isMonitoring && latestAudioLevel == 0f && decision.collectedSegments > 1) {
            applyStatus(
                StatusUi(
                    title = "Microphone Needs Attention",
                    detail = "No microphone signal is detected. Check that microphone access is enabled and the phone can hear sound.",
                    accent = AMBER,
                    background = Color.rgb(255, 248, 235),
                ),
            )
            return
        }

        applyStatus(
            when (decision.detectorState) {
                CryDetectorState.IDLE -> StatusUi(
                    title = if (isMonitoring) "Monitoring Baby" else "Ready to Monitor",
                    detail = if (isMonitoring) {
                        "Listening for baby crying. No alert is needed right now."
                    } else {
                        "Place the phone near your baby, then start monitoring."
                    },
                    accent = if (isMonitoring) TEAL else PRIMARY,
                    background = if (isMonitoring) SURFACE_TINT else SURFACE,
                )
                CryDetectorState.POSSIBLE_CRY -> StatusUi(
                    title = "Checking Sound",
                    detail = "HearMe noticed a possible cry and is checking before sending an alert.",
                    accent = AMBER,
                    background = Color.rgb(255, 248, 235),
                )
                CryDetectorState.CONFIRMED_CRY -> StatusUi(
                    title = "Cry Detected",
                    detail = "Crying was confirmed. HearMe is preparing the smartwatch alert.",
                    accent = ALERT,
                    background = ALERT_SOFT,
                )
                CryDetectorState.ALERTED -> StatusUi(
                    title = "Alert Sent to Watch",
                    detail = "The watch alert was sent. HearMe will avoid duplicate alerts for this same event.",
                    accent = ALERT,
                    background = ALERT_SOFT,
                )
                CryDetectorState.COOLDOWN -> StatusUi(
                    title = "Monitoring Continues",
                    detail = "An alert was already sent. HearMe is preventing repeated alerts for the same cry.",
                    accent = GREEN,
                    background = Color.rgb(238, 248, 242),
                )
                CryDetectorState.REARMING -> StatusUi(
                    title = "Listening for New Activity",
                    detail = "The sound has calmed. HearMe is getting ready for a new event.",
                    accent = TEAL,
                    background = SURFACE_TINT,
                )
            },
        )
    }

    private fun applyStatus(status: StatusUi) {
        statusTitle.text = status.title
        statusDetail.text = status.detail
        statusCard.background = rounded(status.background, 28, BORDER)
        statusIcon.setColorFilter(status.accent)
        statusTitle.setTextColor(status.accent)
        soundWaveView.accent = status.accent
    }

    private fun updateRunningUi(running: Boolean) {
        isMonitoring = running
        toggleButton.text = if (running) "Stop Monitoring" else "Start Monitoring"
        toggleButton.contentDescription = toggleButton.text
        toggleButton.background = rounded(if (running) PRIMARY_SOFT else PRIMARY, 18)
        toggleButton.setTextColor(if (running) PRIMARY else Color.WHITE)
        liveSection.visibility = if (running) View.VISIBLE else View.GONE
        soundWaveView.active = running
        setChip(monitoringChip, "Monitoring: ${if (running) "Active" else "Stopped"}", if (running) GREEN else MUTED)
    }

    private fun sendWatchAlert(score: Float, fromCry: Boolean) {
        watchSummary.text = "Contacting smartwatch..."
        setChip(watchChip, "Smartwatch: Checking", AMBER)
        setChip(headerWatchChip, "Watch: Checking", AMBER)
        wearAlertSender.send(score) { result ->
            runOnUiThread {
                result.fold(
                    onSuccess = {
                        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date())
                        watchSummary.text = "Smartwatch ready for alerts"
                        setChip(watchChip, "Smartwatch: Connected", GREEN)
                        setChip(headerWatchChip, "Watch: Connected", GREEN)
                        addAlertHistory(
                            if (fromCry) "Cry alert sent to watch" else "Test alert sent to watch",
                            time,
                        )
                    },
                    onFailure = {
                        watchSummary.text = "Smartwatch not connected"
                        setChip(watchChip, "Smartwatch: Not connected", ALERT)
                        setChip(headerWatchChip, "Watch: Not connected", ALERT)
                        applyStatus(
                            StatusUi(
                                title = "Watch Not Connected",
                                detail = "Open the Wear OS watch app and try the watch connection again.",
                                accent = AMBER,
                                background = Color.rgb(255, 248, 235),
                            ),
                        )
                    },
                )
            }
        }
    }

    private fun addAlertHistory(message: String, time: String) {
        recentAlerts.addFirst("$time|$message")
        while (recentAlerts.size > 4) recentAlerts.removeLast()
        renderAlertHistory()
    }

    private fun renderAlertHistory() {
        recentAlertsList.removeAllViews()
        emptyHistoryText.visibility = if (recentAlerts.isEmpty()) View.VISIBLE else View.GONE
        recentAlerts.forEach { item ->
            val parts = item.split("|", limit = 2)
            recentAlertsList.addView(historyRow(parts[0], parts.getOrElse(1) { "Cry alert sent to watch" }))
        }
    }

    private fun refreshPermissionUi() {
        setChip(
            microphoneChip,
            "Microphone: ${if (hasMicrophonePermission()) "Connected" else "Permission needed"}",
            if (hasMicrophonePermission()) GREEN else AMBER,
        )
    }

    private fun hasMicrophonePermission(): Boolean =
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun confidenceLabel(score: Float): String = when {
        score >= 0.15f -> "High"
        score >= 0.05f -> "Medium"
        else -> "Low"
    }

    private fun buildContentView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(18), dp(22), dp(30))
            setBackgroundColor(BACKGROUND)
        }

        root.addView(headerView(), fullWidth())
        root.addView(statusView(), fullWidth(top = 20))
        root.addView(actionButtonsView(), fullWidth(top = 22))
        root.addView(liveMonitoringView(), fullWidth(top = 18))
        root.addView(connectionView(), fullWidth(top = 18))
        root.addView(historyView(), fullWidth(top = 18))
        root.addView(safetyNoteView(), fullWidth(top = 18))

        applyStatus(
            StatusUi(
                title = "Ready to Monitor",
                detail = "Place the phone near your baby, then start monitoring.",
                accent = PRIMARY,
                background = SURFACE,
            ),
        )

        return ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(BACKGROUND)
            addView(root)
        }
    }

    private fun headerView(): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        row.addView(ImageView(this).apply {
            setImageResource(R.drawable.hearme_mark)
            contentDescription = "HearMe logo"
        }, LinearLayout.LayoutParams(dp(64), dp(64)))

        row.addView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), 0, 0, 0)
            addView(TextView(context).apply {
                text = "HearMe"
                textSize = 30f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(PRIMARY)
            })
            addView(TextView(context).apply {
                text = "Baby Cry Monitor"
                textSize = 15f
                setTextColor(MUTED)
            })
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))

        headerWatchChip = chip("Watch: Ready", GREEN)
        row.addView(headerWatchChip)
        return row
    }

    private fun statusView(): View {
        statusCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(26), dp(24), dp(26))
            elevation = dp(3).toFloat()
        }

        statusIcon = ImageView(this).apply {
            setImageResource(R.drawable.hearme_mark)
            contentDescription = "Current monitoring status"
            alpha = 0.92f
        }
        statusCard.addView(statusIcon, LinearLayout.LayoutParams(dp(58), dp(58)).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        })

        statusTitle = TextView(this).apply {
            textSize = 25f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(PRIMARY)
        }
        statusDetail = TextView(this).apply {
            textSize = 15f
            gravity = Gravity.CENTER
            setTextColor(MUTED)
            setLineSpacing(0f, 1.18f)
        }
        statusCard.addView(statusTitle, fullWidth(top = 12))
        statusCard.addView(statusDetail, fullWidth(top = 8))
        return statusCard
    }

    private fun actionButtonsView(): View {
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        toggleButton = Button(this).apply {
            text = "Start Monitoring"
            textSize = 17f
            isAllCaps = false
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(Color.WHITE)
            background = rounded(PRIMARY, 18)
            minHeight = dp(58)
            stateListAnimator = null
        }
        column.addView(toggleButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(58),
        ))

        testAlertButton = Button(this).apply {
            text = "Test Watch Alert"
            textSize = 15f
            isAllCaps = false
            setTextColor(PRIMARY)
            background = rounded(PRIMARY_SOFT, 18)
            minHeight = dp(52)
            stateListAnimator = null
            contentDescription = "Send a test alert to the smartwatch"
        }
        column.addView(testAlertButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(52),
        ).apply { topMargin = dp(12) })

        watchSummary = TextView(this).apply {
            text = "Smartwatch ready for alerts"
            textSize = 13f
            gravity = Gravity.CENTER
            setTextColor(MUTED)
        }
        column.addView(watchSummary, fullWidth(top = 12))
        return column
    }

    private fun liveMonitoringView(): View {
        liveSection = card().apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            addView(sectionTitle("Live Monitoring"))
            addView(TextView(context).apply {
                text = "Listening for baby crying"
                textSize = 15f
                setTextColor(MUTED)
                gravity = Gravity.CENTER
            }, fullWidth(top = 6))
            soundWaveView = SoundWaveView(context)
            addView(soundWaveView, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(74),
            ).apply { topMargin = dp(10) })
            confidenceText = TextView(context).apply {
                text = "Confidence: Low"
                textSize = 14f
                gravity = Gravity.CENTER
                setTextColor(MUTED)
            }
            addView(confidenceText, fullWidth(top = 4))
        }
        return liveSection
    }

    private fun connectionView(): View {
        val card = card().apply {
            orientation = LinearLayout.VERTICAL
            addView(sectionTitle("Safety Checks"))
        }
        val chipsRow = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        microphoneChip = chip("Microphone: Connected", GREEN)
        watchChip = chip("Smartwatch: Ready", GREEN)
        monitoringChip = chip("Monitoring: Stopped", MUTED)
        chipsRow.addView(microphoneChip, fullWidth(top = 10))
        chipsRow.addView(watchChip, fullWidth(top = 8))
        chipsRow.addView(monitoringChip, fullWidth(top = 8))
        card.addView(chipsRow)
        return card
    }

    private fun historyView(): View {
        val card = card().apply {
            orientation = LinearLayout.VERTICAL
            addView(sectionTitle("Recent Alerts"))
        }
        emptyHistoryText = TextView(this).apply {
            text = "No alerts yet. When HearMe sends a watch alert, it will appear here."
            textSize = 14f
            setTextColor(MUTED)
            gravity = Gravity.CENTER
            setPadding(dp(10), dp(14), dp(10), dp(8))
        }
        recentAlertsList = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        card.addView(emptyHistoryText, fullWidth())
        card.addView(recentAlertsList, fullWidth())
        return card
    }

    private fun safetyNoteView(): View = TextView(this).apply {
        text = "HearMe is a student prototype and is not a replacement for adult supervision."
        textSize = 12.5f
        gravity = Gravity.CENTER
        setTextColor(MUTED)
        setPadding(dp(10), dp(8), dp(10), dp(8))
    }

    private fun historyRow(time: String, message: String): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = rounded(Color.rgb(250, 252, 254), 16, BORDER)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            addView(TextView(context).apply {
                text = time
                textSize = 13f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(PRIMARY)
            }, LinearLayout.LayoutParams(dp(78), LinearLayout.LayoutParams.WRAP_CONTENT))
            addView(TextView(context).apply {
                text = message
                textSize = 14f
                setTextColor(TEXT)
            }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        }.also {
            it.layoutParams = fullWidth(top = 8)
        }
    }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        setPadding(dp(18), dp(18), dp(18), dp(18))
        background = rounded(SURFACE, 24, BORDER)
        elevation = dp(1).toFloat()
    }

    private fun sectionTitle(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 18f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setTextColor(PRIMARY)
        gravity = Gravity.CENTER
    }

    private fun chip(text: String, accent: Int): TextView =
        TextView(this).apply {
            this.text = text
            textSize = 13f
            setTextColor(accent)
            gravity = Gravity.CENTER
            minHeight = dp(36)
            setPadding(dp(12), dp(8), dp(12), dp(8))
            background = rounded(withAlpha(accent, 0.11f), 18, withAlpha(accent, 0.28f))
            contentDescription = text
        }

    private fun setChip(view: TextView, text: String, accent: Int) {
        view.text = text
        view.setTextColor(accent)
        view.background = rounded(withAlpha(accent, 0.11f), 18, withAlpha(accent, 0.28f))
        view.contentDescription = text
    }

    private fun rounded(color: Int, radiusDp: Int, strokeColor: Int? = null) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(color)
        cornerRadius = dp(radiusDp).toFloat()
        if (strokeColor != null) setStroke(dp(1), strokeColor)
    }

    private fun fullWidth(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(top) }

    private fun withAlpha(color: Int, alpha: Float): Int =
        Color.argb((alpha * 255).toInt(), Color.red(color), Color.green(color), Color.blue(color))

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private class SoundWaveView(context: Context) : View(context) {
        var level: Float = 0f
            set(value) {
                field = value.coerceIn(0f, 1f)
                invalidate()
            }
        var active: Boolean = false
            set(value) {
                field = value
                invalidate()
            }
        var accent: Int = TEAL
            set(value) {
                field = value
                invalidate()
            }

        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val rect = RectF()

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val centerY = height / 2f
            val bars = 13
            val gap = width / 42f
            val barWidth = max(6f, width / 48f)
            val totalWidth = bars * barWidth + (bars - 1) * gap
            var x = (width - totalWidth) / 2f
            val time = System.currentTimeMillis() / 220.0
            paint.color = withAlpha(accent, if (active) 0.88f else 0.34f)

            repeat(bars) { index ->
                val pulse = if (active) ((sin(time + index * 0.65) + 1.0) / 2.0).toFloat() else 0.15f
                val normalized = max(level, 0.12f)
                val barHeight = height * (0.18f + normalized * 0.50f + pulse * 0.20f)
                rect.set(x, centerY - barHeight / 2f, x + barWidth, centerY + barHeight / 2f)
                canvas.drawRoundRect(rect, barWidth / 2f, barWidth / 2f, paint)
                x += barWidth + gap
            }
            if (active) postInvalidateDelayed(180)
        }

        private fun withAlpha(color: Int, alpha: Float): Int =
            Color.argb((alpha * 255).toInt(), Color.red(color), Color.green(color), Color.blue(color))
    }
}
