package com.smartbabycry.app

data class CryDecisionState(
    val shouldAlert: Boolean,
    val isCurrentSegmentPositive: Boolean,
    val positiveSegments: Int,
    val collectedSegments: Int,
    val requiredPositiveSegments: Int,
    val windowSize: Int,
)

class CryDecisionPolicy(
    private val threshold: Float = 0.30f,
    private val confirmationWindowSize: Int = 24,
    private val minimumPositiveSegments: Int = 20,
    private val cooldownMillis: Long = DEFAULT_COOLDOWN_MILLIS,
) {
    companion object {
        const val MIN_COOLDOWN_MINUTES = 2L
        const val DEFAULT_COOLDOWN_MINUTES = MIN_COOLDOWN_MINUTES
        const val DEFAULT_COOLDOWN_MILLIS = DEFAULT_COOLDOWN_MINUTES * 60_000L
        const val MAX_COOLDOWN_MINUTES = 5L
    }

    init {
        require(confirmationWindowSize > 0)
        require(minimumPositiveSegments in 1..confirmationWindowSize)
        require(
            cooldownMillis in
                MIN_COOLDOWN_MINUTES * 60_000L..MAX_COOLDOWN_MINUTES * 60_000L,
        )
    }

    private val recentSegments = ArrayDeque<Boolean>(confirmationWindowSize)
    private var positiveSegments = 0
    private var lastAlertAt = Long.MIN_VALUE

    fun update(score: Float, nowMillis: Long = System.currentTimeMillis()): CryDecisionState {
        val isPositive = score >= threshold
        recentSegments.addLast(isPositive)
        if (isPositive) positiveSegments++

        if (recentSegments.size > confirmationWindowSize) {
            if (recentSegments.removeFirst()) positiveSegments--
        }

        val windowConfirmed =
            recentSegments.size == confirmationWindowSize &&
                positiveSegments >= minimumPositiveSegments
        val cooldownComplete =
            lastAlertAt == Long.MIN_VALUE || nowMillis - lastAlertAt >= cooldownMillis
        val shouldAlert = windowConfirmed && cooldownComplete

        if (shouldAlert) lastAlertAt = nowMillis
        return CryDecisionState(
            shouldAlert = shouldAlert,
            isCurrentSegmentPositive = isPositive,
            positiveSegments = positiveSegments,
            collectedSegments = recentSegments.size,
            requiredPositiveSegments = minimumPositiveSegments,
            windowSize = confirmationWindowSize,
        )
    }

    fun reset() {
        recentSegments.clear()
        positiveSegments = 0
        lastAlertAt = Long.MIN_VALUE
    }
}
