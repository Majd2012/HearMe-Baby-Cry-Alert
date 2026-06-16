# Python-versus-App Parity Procedure

The Python evaluator and Android app use the same policy concepts, but they run
different inference runtimes:

- Python uses TensorFlow Lite through `tensorflow` or `tflite-runtime`.
- Android uses TensorFlow Lite Task Audio and model metadata labels.

Procedure:

1. Collect at least 20 short WAV clips: clear cry, weak cry, silence, adult
   speech, television, music, and room noise.
2. Run each clip through `evaluate_long_audio.py` and save `frame_scores.csv`.
3. In the Android app debug mode, record exported frame logs with timestamp,
   raw score, smoothed score, detector state, and alert flag.
4. Align frames by timestamp.
5. Calculate mean absolute score difference, maximum score difference,
   classification agreement, and alert-time difference.
6. Store results in `app_python_parity.csv`.

Acceptable tolerance for the first prototype:

- mean absolute score difference <= 0.05
- classification agreement >= 95%
- alert-time difference <= one app segment

If this tolerance is not met, document likely causes: different YAMNet metadata
handling, different audio chunking, Android microphone gain, or device-specific
resampling.
