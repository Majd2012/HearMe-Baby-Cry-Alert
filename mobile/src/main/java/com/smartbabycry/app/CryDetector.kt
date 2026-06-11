package com.smartbabycry.app

import android.content.Context
import org.tensorflow.lite.support.audio.TensorAudio
import org.tensorflow.lite.task.audio.classifier.AudioClassifier

interface CryDetector : AutoCloseable {
    val name: String
    fun score(samples: ShortArray): Float

    override fun close() = Unit
}

class YamNetCryDetector(context: Context) : CryDetector {
    companion object {
        private const val MODEL_FILE = "yamnet.tflite"
        private const val MODEL_INPUT_SAMPLES = 15_600
    }

    override val name = "YAMNet AI"

    private val classifier = AudioClassifier.createFromFile(context, MODEL_FILE)
    private val tensorAudio: TensorAudio = classifier.createInputTensorAudio()
    private val modelInput = FloatArray(MODEL_INPUT_SAMPLES)

    override fun score(samples: ShortArray): Float {
        if (samples.isEmpty()) return 0f

        var segmentScore = 0f
        var frameStart = 0
        var lastFrameStart = -1
        while (frameStart + MODEL_INPUT_SAMPLES <= samples.size) {
            segmentScore = maxOf(segmentScore, classifyFrame(samples, frameStart))
            lastFrameStart = frameStart
            frameStart += MODEL_INPUT_SAMPLES
        }

        val endAlignedStart = maxOf(0, samples.size - MODEL_INPUT_SAMPLES)
        if (endAlignedStart != lastFrameStart) {
            segmentScore = maxOf(segmentScore, classifyFrame(samples, endAlignedStart))
        }
        return segmentScore
    }

    private fun classifyFrame(samples: ShortArray, frameStart: Int): Float {
        for (index in modelInput.indices) {
            val sampleIndex = frameStart + index
            modelInput[index] = if (sampleIndex < samples.size) {
                samples[sampleIndex] / 32768f
            } else {
                0f
            }
        }

        tensorAudio.load(modelInput)
        return classifier.classify(tensorAudio)
            .asSequence()
            .flatMap { it.categories.asSequence() }
            .filter { category ->
                val label = category.label.lowercase()
                label.contains("baby cry") || label.contains("infant cry")
            }
            .maxOfOrNull { it.score }
            ?: 0f
    }

    override fun close() {
        classifier.close()
    }
}
