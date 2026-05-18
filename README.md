# Auditory Mask Generator

This audio-only project provides a PyQt6 GUI for:

* generating auditory masking sounds
* previewing generated audio
* saving generated WAV files and metadata
* saving, loading, and resetting audio presets

This version does not connect to stimulation hardware and does not include TPO, NeuroFUS, ultrasound parameter, or sonication controls.

## Main Features

* Audio generation modes:

  * `Background Only`
  * `Matching Only`
  * `Combined`
* Background types:

  * `Narrowband Noise`
  * `Colored Noise`
  * `Hybrid Ultrasound Mask`
  * `Auditory Mondrian`
* Stimulation matching audio controls:

  * pulse train duration
  * PRI / PRF
  * pulse duration
  * optional carrier
  * ramp shape and ramp length
  * optional SNR noise
  * pulse train repetition
  * matching volume
* Background audio controls:

  * background duration
  * background volume
  * background ramping
  * narrowband, colored noise, hybrid mask, and Mondrian settings
* Lateralization:

  * pan slider
  * left/right channel volume display
* Plotting:

  * waveform view
  * FFT/spectrogram view
  * double-click popups for larger plots
* Playback and file actions:

  * `Generate`
  * `Play Audio`
  * `Stop Audio`
  * `Save`
  * `Presets`
  * `Reset`

## Project Files

Core files used by the app:

* [main_gui.py](./main_gui.py): main PyQt6 GUI
* [session_controller.py](./session_controller.py): builds audio sessions
* [signal_generator.py](./signal_generator.py): signal generation utilities
* [utils.py](./utils.py): ramp/window helper functions
* [audio_engine.py](./audio_engine.py): play, stop, save audio
* [plotting.py](./plotting.py): waveform and spectrum plots
* [logger.py](./logger.py): session metadata saving
* [preset_manager.py](./preset_manager.py): audio preset save/load and reset actions

## Requirements

Install Python packages:

```bash
pip install -r requirements.txt
```

Current `requirements.txt` includes:

* `numpy`
* `scipy`
* `matplotlib`
* `PyQt6`
* `sounddevice`
* `colorednoise`

## Run

Start the GUI with:

```bash
python main_gui.py
```

## Typical Workflow

1. Choose a playback mode.
2. Enter the sound parameters.
3. Choose a background type if using `Background Only` or `Combined`.
4. Adjust ramping, volume, and pan/lateralization as needed.
5. Click `Generate`.
6. Click `Play Audio` to preview.
7. Click `Save` to save the generated audio and metadata.
8. Use `Presets` to save or restore an audio parameter setup if needed.

## Save Behavior

`Save` writes:

* the main generated WAV
* a JSON metadata sidecar
* extra component WAVs for combined output when available

The JSON contains:

* playback mode
* generation parameters
* saved filenames
* audio duration
* sample rate
* channel count

## Presets

Presets save only audio GUI state:

* stimulation matching audio fields
* background audio fields
* hybrid mask and Mondrian settings
* ramping controls
* volume sliders
* pan/lateralization
* graph display toggles
* playback mode


## Troubleshooting

### Save is disabled

Generate audio first.

### Stop Audio is disabled

It starts disabled on app launch and becomes available after audio is generated.

### Audio playback fails

Confirm that the system has a working output device selected. If `sounddevice` has installation or runtime issues, update `pip` and reinstall the requirements:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```
