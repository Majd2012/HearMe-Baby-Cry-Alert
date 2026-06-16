# Python-versus-App Parity Report

No parity run has been executed yet because representative audio clips and
mobile-exported frame logs are not included in the repository.

Planned clips:

- clear baby cry
- weak baby cry
- silence
- adult speech
- television
- music
- room noise

Metrics to fill after running the procedure:

- mean absolute score difference
- maximum score difference
- classification agreement
- alert-time difference

Prototype tolerance:

- mean absolute score difference <= 0.05
- classification agreement >= 95%
- alert-time difference <= one app segment

Known possible causes of mismatch:

- Android TensorFlow Lite Task Audio metadata handling
- Python TensorFlow Lite output ordering
- mobile microphone gain and resampling
- different app segment cadence versus native YAMNet frame cadence
