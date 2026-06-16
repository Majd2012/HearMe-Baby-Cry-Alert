package com.smartbabycry.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CryDecisionPolicyTest {
    private fun policy() = CryDecisionPolicy(
        CryDetectionConfig(
            triggerThreshold = 0.30f,
            clearThreshold = 0.20f,
            persistenceFrames = 3,
            smoothingMode = SmoothingMode.NONE,
            cooldownMillis = 20_000L,
            rearmingMillis = 10_000L,
        ),
    )

    @Test
    fun noAlertWhenScoresStayBelowThreshold() {
        val policy = policy()

        repeat(10) { index ->
            assertFalse(policy.update(score = 0.10f, nowMillis = index * 5_000L).shouldAlert)
        }
    }

    @Test
    fun alertsAfterRequiredPositiveFrames() {
        val policy = policy()

        assertFalse(policy.update(score = 0.80f, nowMillis = 0L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 5_000L).shouldAlert)
        val state = policy.update(score = 0.80f, nowMillis = 10_000L)

        assertTrue(state.shouldAlert)
        assertEquals(CryDetectorState.ALERTED, state.detectorState)
    }

    @Test
    fun ignoresOneIsolatedScoreSpike() {
        val policy = policy()

        assertFalse(policy.update(score = 0.90f, nowMillis = 0L).shouldAlert)
        assertFalse(policy.update(score = 0.10f, nowMillis = 5_000L).shouldAlert)
        assertFalse(policy.update(score = 0.10f, nowMillis = 10_000L).shouldAlert)
    }

    @Test
    fun hysteresisRequiresClearThresholdBeforeRearming() {
        val policy = policy()

        assertFalse(policy.update(score = 0.80f, nowMillis = 0L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 5_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 10_000L).shouldAlert)

        assertEquals(CryDetectorState.ALERTED, policy.update(score = 0.25f, nowMillis = 15_000L).detectorState)
        assertEquals(CryDetectorState.COOLDOWN, policy.update(score = 0.10f, nowMillis = 20_000L).detectorState)
    }

    @Test
    fun cooldownSuppressesRepeatedAlertDuringOneEvent() {
        val policy = policy()

        assertFalse(policy.update(score = 0.80f, nowMillis = 0L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 5_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 10_000L).shouldAlert)

        repeat(8) { index ->
            assertFalse(policy.update(score = 0.85f, nowMillis = 15_000L + index * 5_000L).shouldAlert)
        }
    }

    @Test
    fun rearmsAfterSustainedLowScores() {
        val policy = policy()

        assertFalse(policy.update(score = 0.80f, nowMillis = 0L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 5_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 10_000L).shouldAlert)

        assertFalse(policy.update(score = 0.10f, nowMillis = 20_000L).shouldAlert)
        assertFalse(policy.update(score = 0.10f, nowMillis = 30_000L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 35_000L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 40_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 45_000L).shouldAlert)
    }
}
