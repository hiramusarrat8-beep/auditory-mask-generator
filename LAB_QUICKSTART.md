# Quick Start

This guide provides a minimal setup workflow for the standalone audio-only Auditory Mask Generator.

For detailed documentation and troubleshooting, see the main `README.md`.

## 1. Install Conda

Make sure that one of the following is installed before proceeding:

- Anaconda
- Miniconda

## 2. Get the Project

Clone the repository:

```bash
git clone https://github.com/hiramusarrat8-beep/auditory-mask-generator.git
```

Move into the project folder:

```bash
cd auditory-mask-generator
```

## 3. Create the Conda Environment

Create the environment from the provided configuration file:

```bash
conda env create -f environment.yml
```

Activate the environment:

```bash
conda activate amg_app
```

The environment file installs the required Python packages from `requirements.txt`.


## 4. Run the Application

```bash
python main_gui.py
```

## Notes

- This project is designed for auditory masking generation and playback only.
- It does not require NeuroFUS hardware, TPO communication, serial device access, ultrasound parameters, or sonication controls.
- If audio playback fails, confirm that the system has a valid output device selected.
- See the main `README.md` for troubleshooting and full documentation.
