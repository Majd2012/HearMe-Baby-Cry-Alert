package com.smartbabycry.app

enum class CryDetectorState {
    IDLE,
    POSSIBLE_CRY,
    CONFIRMED_CRY,
    ALERTED,
    COOLDOWN,
    REARMING,
}

enum class SmoothingMode {
    NONE,
    ROLLING_MEAN,
    EMA,
}

data class CryDetectionConfig(
    val triggerThreshold: Float = 0.05f,
    val clearThreshold: Float = 0.00f,
    val persistenceFrames: Int = 1,
    val smoothingMode: SmoothingMode = SmoothingMode.NONE,
    val smoothingWindowFrames: Int = 1,
    val emaAlpha: Float = 0.35f,
    val cooldownMillis: Long = 10_000L,
    val rearmingMillis: Long = 2_000L,
    val frameStepMillis: Long = AudioMonitor.SEGMENT_SECONDS * 1_000L,
) {
    init {
        require(triggerThreshold in 0f..1f)
        require(clearThreshold in 0f..1f)
        require(clearThreshold <= triggerThreshold)
        require(persistenceFrames > 0)
        require(smoothingWindowFrames > 0)
        require(emaAlpha > 0f && emaAlpha <= 1f)
        require(cooldownMillis >= 0L)
        require(rearmingMillis >= 0L)
        require(frameStepMillis > 0L)
    }
}

data class CryDecisionState(
    val shouldAlert: Boolean,
    val isCurrentSegmentPositive: Boolean,
    val positiveSegments: Int,
    val collectedSegments: Int,
    val requiredPositiveSegments: Int,
    val windowSize: Int,
    val rawScore: Float,
    val smoothedScore: Float,
    val detectorState: CryDetectorState,
    val transition: String?,
)

class CryDecisionPolicy(
    private val config: CryDetectionConfig = CryDetectionConfig(),
) {
    companion object {
        const val MIN_COOLDOWN_MINUTES = 2L
        const val DEFAULT_COOLDOWN_MINUTES = MIN_COOLDOWN_MINUTES
        const val DEFAULT_COOLDOWN_MILLIS = DEFAULT_COOLDOWN_MINUTES * 60_000L
        const val MAX_COOLDOWN_MINUTES = 5L
    }

    constructor(
        threshold: Float = 0.30f,
        confirmationWindowSize: Int = 24,
        minimumPositiveSegments: Int = 20,
        cooldownMillis: Long = DEFAULT_COOLDOWN_MILLIS,
    ) : this(
        CryDetectionConfig(
            triggerThreshold = threshold,
            clearThreshold = maxOf(0f, threshold - 0.10f),
            persistenceFrames = minimumPositiveSegments,
            smoothingMode = SmoothingMode.NONE,
            smoothingWindowFrames = confirmationWindowSize,
            cooldownMillis = cooldownMillis,
            rearmingMillis = AudioMonitor.SEGMENT_SECONDS * 1_000L,
        ),
    )

    private val scoreHistory = ArrayDeque<Float>(config.smoothingWindowFrames)
    private var state = CryDetectorState.IDLE
    private var consecutivePositiveFrames = 0
    private var collectedFrames = 0
    private var emaScore: Float? = null
    private var lastAlertAt = Long.MIN_VALUE
    private var lowSince: Long? = null

    fun update(score: Float, nowMillis: Long = System.currentTimeMillis()): CryDecisionState {
        val smoothedScore = smooth(score)
        val isPositive = smoothedScore >= config.triggerThreshold
        val isClear = smoothedScore <= config.clearThreshold
        val previous = state
        var shouldAlert = false

        collectedFrames++
        consecutivePositiveFrames = if (isPositive) consecutivePositiveFrames + 1 else 0
        lowSince = if (isClear) lowSince ?: nowMillis else null

        when (state) {
            CryDetectorState.IDLE -> {
                if (isPositive) state = CryDetectorState.POSSIBLE_CRY
            }
            CryDetectorState.POSSIBLE_CRY -> {
                if (isClear) {
                    state = CryDetectorState.IDLE
                    consecutivePositiveFrames = 0
                } else if (consecutivePositiveFrames >= config.persistenceFrames) {
                    state = CryDetectorState.CONFIRMED_CRY
                }
            }
            CryDetectorState.CONFIRMED_CRY -> {
                if (cooldownComplete(nowMillis)) {
                    shouldAlert = true
                    lastAlertAt = nowMillis
                    state = CryDetectorState.ALERTED
                } else {
                    state = CryDetectorState.COOLDOWN
                }
            }
            CryDetectorState.ALERTED -> {
                if (isClear) state = CryDetectorState.COOLDOWN
            }
            CryDetectorState.COOLDOWN -> {
                if (cooldownComplete(nowMillis) && lowLongEnough(nowMillis)) {
                    state = CryDetectorState.REARMING
                }
            }
            CryDetectorState.REARMING -> {
                if (!isClear) {
                    state = if (isPositive) CryDetectorState.POSSIBLE_CRY else CryDetectorState.IDLE
                } else if (lowLongEnough(nowMillis)) {
                    state = CryDetectorState.IDLE
                    consecutivePositiveFrames = 0
                }
            }
        }

        if (previous == CryDetectorState.POSSIBLE_CRY && state == CryDetectorState.CONFIRMED_CRY) {
            if (cooldownComplete(nowMillis)) {
                shouldAlert = true
                lastAlertAt = nowMillis
                state = CryDetectorState.ALERTED
            } else {
                state = CryDetectorState.COOLDOWN
            }
        }

        return CryDecisionState(
            shouldAlert = shouldAlert,
            isCurrentSegmentPositive = isPositive,
            positiveSegments = consecutivePositiveFrames,
            collectedSegments = collectedFrames,
            requiredPositiveSegments = config.persistenceFrames,
            windowSize = config.persistenceFrames,
            rawScore = score,
            smoothedScore = smoothedScore,
            detectorState = state,
            transition = if (previous != state) "${previous.name}->${state.name}" else null,
        )
    }

    fun reset() {
        scoreHistory.clear()
        state = CryDetectorState.IDLE
        consecutivePositiveFrames = 0
        collectedFrames = 0
        emaScore = null
        lastAlertAt = Long.MIN_VALUE
        lowSince = null
    }

    private fun smooth(score: Float): Float {
        return when (config.smoothingMode) {
            SmoothingMode.NONE -> score
            SmoothingMode.ROLLING_MEAN -> {
                scoreHistory.addLast(score)
                while (scoreHistory.size > config.smoothingWindowFrames) {
                    scoreHistory.removeFirst()
                }
                scoreHistory.sum() / scoreHistory.size
            }
            SmoothingMode.EMA -> {
                val previous = emaScore
                val updated = if (previous == null) {
                    score
                } else {
                    config.emaAlpha * score + (1f - config.emaAlpha) * previous
                }
                emaScore = updated
                updated
            }
        }
    }

    private fun cooldownComplete(nowMillis: Long): Boolean =
        lastAlertAt == Long.MIN_VALUE || nowMillis - lastAlertAt >= config.cooldownMillis

    private fun lowLongEnough(nowMillis: Long): Boolean =
        lowSince?.let { nowMillis - it >= config.rearmingMillis } == true
}
