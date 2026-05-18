# Lab Quick Start

This quick-start guide is a short setup reference for the audio-only Auditory Mask Generator.
It does not replace the main `README.md`.

## 1. Get the Project

Copy the `amg_app` project folder and open a terminal inside it.

If using Git, clone or checkout the audio-only project folder, then enter it:

```bash
cd amg_app
```

## 2. Create the Conda Environment

```bash
conda env create -f environment.yml
conda activate amg_app
```

The environment file installs the Python packages from `requirements.txt`.

## 3. Run the App

```bash
python main_gui.py
```

## Notes

- This project is for audio masking generation and playback only.
- It does not require NeuroFUS hardware, TPO connection, serial access, ultrasound parameters, or sonication controls.
- If audio playback fails, confirm that the computer has a working output device selected and see the main `README.md` for troubleshooting.
