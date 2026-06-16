# Current Signal Flow

Platform: native Android phone app plus native Wear OS watch app, written in Kotlin.

Model runtime: TensorFlow Lite Task Audio on Android. The model file is
`mobile/src/main/assets/yamnet.tflite`.

Phone flow:

1. `AudioMonitor` records mono microphone audio with `AudioRecord`.
2. Audio is captured at 16,000 Hz as signed 16-bit PCM.
3. `YamNetCryDetector` converts samples to float32 in `[-1.0, 1.0]`.
4. YAMNet evaluates 15,600-sample frames from each captured segment.
5. Scores whose labels contain `baby cry` or `infant cry` are selected from
   TensorFlow Lite Task Audio metadata labels.
6. `CryDecisionPolicy` smooths scores and applies trigger threshold,
   clear threshold, persistence, cooldown, and rearming rules.
7. `WearAlertSender` sends a Wear OS Data Layer message only when the policy
   generates an alert.

Watch flow:

1. `CryAlertListenerService` receives `/baby-cry/alert` messages through Wear OS.
2. The watch stores the latest alert in `CryAlertStore`.
3. The watch vibrates, posts a notification, and shows the alert screen.

Default mobile policy after this update:

- trigger threshold: `0.30`
- clear threshold: `0.20`
- smoothing: rolling mean over 3 app segments
- persistence: 3 positive app segments
- cooldown: 120 seconds
- rearming: 5 seconds below clear threshold

Important limitation:

The current mobile microphone loop still batches 5-second app segments for
resource simplicity. The Python long-audio evaluator records YAMNet's native
approximately 0.96-second frames with approximately 0.48-second hops, then can
simulate app-style persistence and cooldown rules.
