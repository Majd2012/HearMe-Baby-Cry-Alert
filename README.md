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

Audio is divided into 5-second segments. YAMNet evaluates each segment and a
segment is positive when its baby-cry score is at least `0.30`. The decision
policy evaluates the latest 24 segments
(2 minutes) and sends an alert when at least 20 are positive. Repeat alerts are
suppressed for 2 minutes by default. `CryDecisionPolicy` accepts any cooldown
from 2 to 5 minutes, so the default can be changed to 5 minutes after field
testing.

Before reporting final accuracy, verify the mobile implementation against the
same validation audio used by the Python evaluation. In particular, compare
the 5-second frame aggregation and the `0.30` threshold.

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
