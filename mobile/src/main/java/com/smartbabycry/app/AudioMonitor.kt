package com.smartbabycry.app

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.util.concurrent.atomic.AtomicBoolean

class AudioMonitor(
    private val detector: CryDetector,
    private val decisionPolicy: CryDecisionPolicy,
    private val onAudioLevel: (Float) -> Unit,
    private val onDecision: (Float, CryDecisionState) -> Unit,
    private val onCryDetected: (Float) -> Unit,
    private val onError: (String) -> Unit,
) {
    companion object {
        const val SAMPLE_RATE = 16_000
        const val SEGMENT_SECONDS = 5
        const val WINDOW_SAMPLES = SAMPLE_RATE * SEGMENT_SECONDS
    }

    private val running = AtomicBoolean(false)
    private var worker: Thread? = null

    @SuppressLint("MissingPermission")
    fun start() {
        if (!running.compareAndSet(false, true)) return

        worker = Thread({
            val minimumBuffer = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minimumBuffer <= 0) {
                running.set(false)
                onError("This device cannot create the required audio buffer.")
                return@Thread
            }

            val recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minimumBuffer, WINDOW_SAMPLES * 2),
            )

            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                recorder.release()
                running.set(false)
                onError("Microphone initialization failed.")
                return@Thread
            }

            val window = ShortArray(WINDOW_SAMPLES)
            try {
                recorder.startRecording()
                while (running.get()) {
                    var offset = 0
                    while (running.get() && offset < window.size) {
                        val count = recorder.read(window, offset, window.size - offset)
                        if (count <= 0) {
                            throw IllegalStateException("Microphone read failed with code $count")
                        }
                        offset += count
                    }
                    if (!running.get()) break

                    onAudioLevel(calculatePeakLevel(window))
                    val score = detector.score(window)
                    val decision = decisionPolicy.update(score)
                    onDecision(score, decision)
                    if (decision.shouldAlert) {
                        onCryDetected(score)
                    }
                }
            } catch (error: Exception) {
                if (running.get()) onError(error.message ?: "Audio monitoring failed.")
            } finally {
                running.set(false)
                if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    recorder.stop()
                }
                recorder.release()
            }
        }, "baby-cry-audio-monitor").also { it.start() }
    }

    fun stop() {
        running.set(false)
        worker?.interrupt()
        worker = null
        decisionPolicy.reset()
    }

    fun isRunning(): Boolean = running.get()

    private fun calculatePeakLevel(samples: ShortArray): Float {
        if (samples.isEmpty()) return 0f
        var peak = 0
        samples.forEach { sample ->
            peak = maxOf(peak, kotlin.math.abs(sample.toInt()))
        }
        return peak / 32768f
    }
}
