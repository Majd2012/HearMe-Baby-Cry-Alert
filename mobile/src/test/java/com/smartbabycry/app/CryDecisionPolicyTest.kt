package com.smartbabycry.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CryDecisionPolicyTest {
    @Test
    fun requiresTwentyPositiveSegmentsInFullTwentyFourSegmentWindow() {
        val policy = CryDecisionPolicy()

        repeat(19) { index ->
            assertFalse(policy.update(score = 0.30f, nowMillis = index * 5_000L).shouldAlert)
        }
        repeat(4) { index ->
            assertFalse(policy.update(score = 0.10f, nowMillis = (19 + index) * 5_000L).shouldAlert)
        }
        assertTrue(policy.update(score = 0.30f, nowMillis = 23 * 5_000L).shouldAlert)
    }

    @Test
    fun doesNotAlertWhenOnlyNineteenOfTwentyFourSegmentsArePositive() {
        val policy = CryDecisionPolicy()

        repeat(19) { index ->
            assertFalse(policy.update(score = 0.80f, nowMillis = index * 5_000L).shouldAlert)
        }
        repeat(5) { index ->
            assertFalse(policy.update(score = 0.20f, nowMillis = (19 + index) * 5_000L).shouldAlert)
        }
    }

    @Test
    fun usesRollingWindowInsteadOfResettingAfterTwentyFourSegments() {
        val policy = CryDecisionPolicy()

        repeat(4) { index ->
            assertFalse(policy.update(score = 0.10f, nowMillis = index * 5_000L).shouldAlert)
        }
        repeat(19) { index ->
            assertFalse(policy.update(score = 0.80f, nowMillis = (4 + index) * 5_000L).shouldAlert)
        }
        assertFalse(policy.update(score = 0.10f, nowMillis = 23 * 5_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 24 * 5_000L).shouldAlert)
    }

    @Test
    fun cooldownSuppressesRepeatedAlertForTwoMinutes() {
        val policy = CryDecisionPolicy()

        repeat(23) { index ->
            assertFalse(policy.update(score = 0.80f, nowMillis = index * 5_000L).shouldAlert)
        }
        assertTrue(policy.update(score = 0.80f, nowMillis = 115_000L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 120_000L).shouldAlert)
        assertFalse(policy.update(score = 0.80f, nowMillis = 230_000L).shouldAlert)
        assertTrue(policy.update(score = 0.80f, nowMillis = 235_000L).shouldAlert)
    }

    @Test
    fun reportsConfirmationProgress() {
        val policy = CryDecisionPolicy()

        repeat(7) { policy.update(score = 0.80f, nowMillis = it * 5_000L) }
        val state = policy.update(score = 0.10f, nowMillis = 35_000L)

        assertFalse(state.shouldAlert)
        assertFalse(state.isCurrentSegmentPositive)
        org.junit.Assert.assertEquals(7, state.positiveSegments)
        org.junit.Assert.assertEquals(8, state.collectedSegments)
        org.junit.Assert.assertEquals(20, state.requiredPositiveSegments)
        org.junit.Assert.assertEquals(24, state.windowSize)
    }
}
