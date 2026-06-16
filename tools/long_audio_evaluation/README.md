# HearMe Long-Audio Evaluation

This folder contains the professor-required long-form evaluation system for the
HearMe baby-cry detection app.

## Install

```powershell
cd C:\Users\ibrahem_PC\Documents\Codex\2026-06-08\smart-baby-cry-detection-and-smartwatch
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\tools\long_audio_evaluation\requirements.txt
pip install tensorflow
```

Use `tflite-runtime` instead of TensorFlow if your Python environment supports
it.

## Model

The evaluator defaults to the mobile model:

```text
mobile/src/main/assets/yamnet.tflite
```

The Baby Cry / Infant Cry index is read from `yamnet_class_map.csv` instead of
being embedded directly in the scorer code.

## Ground Truth

```csv
event_id,start_sec,end_sec,label
1,300.25,314.80,Cry
2,00:17:05.500,00:17:21.200,Cry
```

Only rows labeled `Cry` are positive events.

## Run Evaluation

```powershell
python .\tools\long_audio_evaluation\evaluate_long_audio.py `
  --audio .\data\test_night.wav `
  --ground-truth .\data\ground_truth.csv `
  --output-dir .\results\test_night
```

## Run Sweep

```powershell
python .\tools\long_audio_evaluation\evaluate_long_audio.py `
  --audio .\data\test_night.wav `
  --ground-truth .\data\ground_truth.csv `
  --output-dir .\results\test_night_sweep `
  --sweep
```

Edit `config.default.json` or pass `--config my_config.json` to change
thresholds, persistence, smoothing, cooldown, rearming, and cost weights.

## Scientific Before/After Validation

```powershell
python .\tools\long_audio_evaluation\scientific_validation.py `
  --output-dir .\results\scientific_validation `
  --duration-minutes 30 `
  --events-per-night 6 `
  --seeds 42,77,123
```

This creates the required before/after timelines, metrics comparison,
multi-night parameter sweep, best-operating-point graph, and academic report.

## Synthetic Night

```powershell
python .\tools\long_audio_evaluation\build_synthetic_night.py `
  --background .\data\room_background.wav `
  --cry-dir .\data\cry_samples `
  --duration-hours 1 `
  --number-of-events 8 `
  --seed 42 `
  --output .\data\synthetic_night.wav
```

Use only audio you are allowed to use. The script never downloads audio.

## Outputs

`results/<run_name>/` contains frame scores, normalized annotations, detected
events, alert logs, parameter-sweep metrics, recommended configurations,
summary metrics, Markdown/HTML reports, and PNG/SVG plots.

## Tests

```powershell
python -m pytest .\tools\long_audio_evaluation\tests
```

Android policy tests:

```powershell
.\gradlew.bat :mobile:testDebugUnitTest
```
