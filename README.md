# Smart Baby Cry Detection and Smartwatch Alert

Android phone and Wear OS prototype for notifying hearing-impaired parents when
a nearby phone detects a possible baby cry.

## Current milestone

The first prototype includes:

- 16 kHz mono microphone capture on the Android phone
- 5-second audio segments captured at 16 kHz
- on-device YAMNet TensorFlow Lite inference
- a 2-minute rolling confirmation window and configurable 2-5 minute cooldown
- Wear OS Data Layer messages
- watch vibration, notification, alert screen, and confirmation button
- a manual test-alert button for testing the phone/watch connection

The phone uses Google's metadata-enabled YAMNet TensorFlow Lite model. Every
5-second segment is split into 15,600-sample model frames, and the maximum
`Baby cry, infant cry` score becomes the score for that segment.

## Required tools

Install:

1. Android Studio with its bundled JDK
2. Android SDK Platform 35
3. Android SDK Build Tools
4. An Android phone/emulator and Wear OS watch/emulator

Open this directory in Android Studio and allow Gradle sync to complete.

After the first setup, Windows users can run `start-hearme.ps1` from
PowerShell. It starts both emulators, enables host microphone audio, restores
the emulator bridge, installs the latest debug APKs, and opens HearMe.

## Run the prototype

1. Pair the Wear OS emulator/watch with the Android emulator/phone.
2. Run the `wear` module on the watch.
3. Run the `mobile` module on the phone.
4. Grant microphone permission on the phone.
5. Press **Send test watch alert** and confirm the watch vibrates.
6. Press **Start monitoring** to exercise live microphone capture.

Both modules intentionally use the same application ID,
`com.smartbabycry.app`, so the Wear OS Data Layer can authenticate messages.
Use matching signing keys for both modules when producing release builds.

## Detection behavior

Audio is divided into 5-second app segments. YAMNet evaluates each segment and
the detector state machine applies smoothing, a trigger threshold, a lower clear
threshold, persistence, cooldown, and rearming rules. The default mobile
configuration is:

- trigger threshold: `0.05`
- clear threshold: `0.00`
- smoothing: none
- persistence: 1 positive app segment
- cooldown: 10 seconds
- rearming: 2 seconds below the clear threshold

This selected configuration came from the first synthetic one-hour night test.
It should be revalidated on real labeled long recordings before final use.

The state machine uses `IDLE`, `POSSIBLE_CRY`, `CONFIRMED_CRY`, `ALERTED`,
`COOLDOWN`, and `REARMING`. The phone sends a watch message only when a cry is
confirmed, and duplicate alerts are suppressed until the event clears and the
detector rearms.

Before reporting final accuracy, verify the mobile implementation against the
same validation audio used by the Python evaluation. In particular, compare
the 5-second frame aggregation and the `0.30` threshold.

## Long-audio evaluation

The repository includes a Python toolkit in `tools/long_audio_evaluation/`.
It processes long audio incrementally, records YAMNet frame scores, evaluates
event-level alerts, sweeps alert parameters, generates charts, and writes a
Markdown/HTML report.

Install dependencies from Windows PowerShell:

```powershell
cd C:\Users\ibrahem_PC\Documents\Codex\2026-06-08\smart-baby-cry-detection-and-smartwatch
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\tools\long_audio_evaluation\requirements.txt
pip install tensorflow
```

The evaluator uses the app model at:

```text
mobile/src/main/assets/yamnet.tflite
```

Ground-truth CSV format:

```csv
event_id,start_sec,end_sec,label
1,300.25,314.80,Cry
2,00:17:05.500,00:17:21.200,Cry
```

Run one evaluation:

```powershell
python .\tools\long_audio_evaluation\evaluate_long_audio.py `
  --audio .\data\test_night.wav `
  --ground-truth .\data\ground_truth.csv `
  --output-dir .\results\test_night
```

Run a parameter sweep:

```powershell
python .\tools\long_audio_evaluation\evaluate_long_audio.py `
  --audio .\data\test_night.wav `
  --ground-truth .\data\ground_truth.csv `
  --output-dir .\results\test_night_sweep `
  --sweep `
  --max-sweep-combinations 5000
```

Build a reproducible synthetic one-hour night from user-supplied audio:

```powershell
python .\tools\long_audio_evaluation\build_synthetic_night.py `
  --background .\data\room_background.wav `
  --cry-dir .\data\cry_samples `
  --duration-hours 1 `
  --number-of-events 8 `
  --seed 42 `
  --output .\data\synthetic_night.wav
```

The generator writes:

- `synthetic_night.wav`
- `synthetic_night_ground_truth.csv`
- `synthetic_night_manifest.json`

Evaluation outputs are written under `results/<run_name>/`:

- `frame_scores.csv`
- `ground_truth_normalized.csv`
- `detected_events.csv`
- `alert_log.csv`
- `parameter_sweep.csv`
- `best_sensitive_config.json`
- `best_balanced_config.json`
- `best_conservative_config.json`
- `summary_metrics.json`
- `report.md`
- `report.html`
- `plots/*.png`
- `plots/*.svg`

Interpretation:

- Event recall tells how many real crying events produced an alert.
- Event precision tells how many generated alerts matched real crying events.
- False alerts per hour estimates unnecessary wakeups.
- Latency is `alert_timestamp - ground_truth_cry_start`.
- Negative latency means an early alert; high positive latency means a late
  alert.
- The Pareto plot shows the trade-off between recall, false alerts, and delay.

Python-versus-app parity instructions are in:

```text
tools/long_audio_evaluation/app_python_parity.md
```

## Project structure

```text
mobile/
  AudioMonitor.kt          microphone capture and audio windows
  CryDetector.kt           detector contract and temporary detector
  CryDecisionPolicy.kt     threshold, consecutive-window, and cooldown logic
  WearAlertSender.kt       phone-to-watch Data Layer messaging
  MainActivity.kt          phone UI

wear/
  CryAlertListenerService.kt  receives message, vibrates, posts notification
  CryAlertStore.kt            stores latest alert state
  WearMainActivity.kt         watch UI and confirmation
```

## Safety

This is a student prototype, not a certified medical or child-safety device.
It must not be the only method used to supervise a baby.
