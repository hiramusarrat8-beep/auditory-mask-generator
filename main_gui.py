# amg_app/main_gui.py

# top of main_gui.py, before any Qt imports
def _check_qt_conflicts():
    import importlib.util
    if importlib.util.find_spec("PyQt5") is not None:
        raise SystemExit(
            "ERROR: PyQt5 is installed alongside PyQt6. "
            "Run 'pip uninstall PyQt5 PyQt5-sip PyQtWebEngine' and try again."
        )

_check_qt_conflicts()

import os
import pathlib

def _fix_qt_plugin_path():
    try:
        import PyQt6.QtCore
        plugins_path = pathlib.Path(PyQt6.QtCore.__file__).parent / "Qt6" / "plugins" / "platforms"
        if plugins_path.exists():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins_path)
    except Exception:
        pass

_fix_qt_plugin_path()

import sys
import copy
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QRadioButton, QButtonGroup, QCheckBox,
    QSlider, QTextEdit, QDoubleSpinBox, QAbstractSpinBox,
    QScrollArea, QToolTip
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QDoubleValidator, QColor, QIntValidator

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import numpy as np

from session_controller import SessionController
import logger as session_logger
import audio_engine
import plotting
import signal_generator
from preset_manager import PresetManager

class BasicMaskGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auditory Mask Generator")
        self.resize(900, 550)

        self.current_audio = None
        self.current_time = None
        self.current_gate = None
        self.current_fs = None
        self.zoom_view = True
        # NEW: Dual mode variables
        self.current_pulse_audio = None
        self.current_bg_audio = None
        self.last_generated_params = None
        self.last_generated_mode = None
        self._plot_popups = []
        # ADDED: Dedicated manager keeps preset save/load logic out of this GUI file.
        self.preset_manager = PresetManager(self)

        self.updating_prp_prf = False
        self.updating_ptrp_ptrf = False
        self.updating_ptrd_num = False

        self.syncing_hybrid_prf = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 1)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        main_layout.addWidget(top_widget)

        params_hbox = QHBoxLayout()
        top_layout.addLayout(params_hbox)

        # Stimulation Matching (unchanged)
        stimulation_group = QGroupBox("Stimulation Matching")
        stimulation_layout = QVBoxLayout(stimulation_group)

        main_form = QFormLayout()
        main_form.setVerticalSpacing(0)  # Reduce vertical spacing
        stimulation_layout.addLayout(main_form)

        self.ptd_input = QLineEdit("")
        self.ptd_input.setValidator(QDoubleValidator(0.001, 600000.0, 3))
        self.ptd_input.textChanged.connect(lambda _: self.validate_input(self.ptd_input))
        self.ptd_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow("Pulse Train Duration (ms):", self.ptd_input)

        self.prp_input = QLineEdit("")
        self.prp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.prp_input.textChanged.connect(lambda _: self.validate_input(self.prp_input))
        self.prp_input.textChanged.connect(self.on_prp_changed)
        main_form.addRow("PRI (ms):", self.prp_input)

        self.prf_input = QLineEdit("")
        self.prf_input.setValidator(QDoubleValidator(1, 10000, 2))  # Allow 2 decimals
        self.prf_input.textChanged.connect(lambda _: self.validate_input(self.prf_input))
        self.prf_input.textChanged.connect(self.on_prf_changed)
        self.prf_input.textChanged.connect(self.sync_hybrid_prf_from_main)
        main_form.addRow("PRF (Hz):", self.prf_input)

        self.pd_input = QLineEdit("")
        self.pd_input.setValidator(QDoubleValidator(0.001, 1000.0, 3))
        self.pd_input.textChanged.connect(lambda _: self.validate_input(self.pd_input))
        self.pd_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow("Pulse Duration (ms):", self.pd_input)

        self.carrier_input = QLineEdit("")
        self.carrier_input.setValidator(QDoubleValidator(1, 20000, 0))
        self.carrier_input.setPlaceholderText("Enable Carrier Wave")
        self.carrier_input.textChanged.connect(lambda _: self.validate_input(self.carrier_input))
        self.carrier_input.textChanged.connect(self.validate_generate_button)
        self.carrier_input.setEnabled(False)

        self.enable_carrier_checkbox = QCheckBox("")
        self.enable_carrier_checkbox.setChecked(False)
        self.enable_carrier_checkbox.toggled.connect(self.update_derived)
        self.enable_carrier_checkbox.toggled.connect(self._on_enable_carrier_toggled)

        carrier_widget = QWidget()
        carrier_layout = QHBoxLayout(carrier_widget)
        carrier_layout.setContentsMargins(0, 0, 0, 0)
        carrier_layout.addWidget(self.enable_carrier_checkbox)
        carrier_layout.addWidget(self.carrier_input)

        main_form.addRow("Carrier Frequency (Hz):", carrier_widget)

        self.ramp_shape_combo = QComboBox()
        self.ramp_shape_combo.addItems(["None", "Linear", "Tukey"])
        self.ramp_shape_combo.currentTextChanged.connect(self.on_ramp_shape_changed)
        main_form.addRow("Ramp Shape:", self.ramp_shape_combo)

        self.ramp_len_label = QLabel("Ramp Length (ms):")
        self.ramp_len_input = QLineEdit("")
        self.ramp_len_input.setValidator(QDoubleValidator(0.0, 1000.0, 3))
        self.ramp_len_input.textChanged.connect(lambda _: self.validate_input(self.ramp_len_input))
        self.ramp_len_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow(self.ramp_len_label, self.ramp_len_input)

        self.snr_checkbox = QCheckBox("Add noise")
        self.snr_input = QLineEdit("")
        self.snr_input.setValidator(QDoubleValidator(0, 100, 2))
        self.snr_input.setEnabled(False)
        self.snr_input.setPlaceholderText("SNR ratio")
        self.snr_input.textChanged.connect(lambda _: self.validate_input(self.snr_input))
        self.snr_checkbox.toggled.connect(self.snr_input.setEnabled)
        self.snr_checkbox.toggled.connect(lambda checked: self.snr_input.setText("1") if checked and not self.snr_input.text() else None)
        snr_widget = QWidget()
        snr_layout = QHBoxLayout(snr_widget)
        snr_layout.setContentsMargins(0, 0, 0, 0)
        snr_layout.addWidget(self.snr_checkbox)
        snr_layout.addWidget(self.snr_input)
        main_form.addRow("Signal-to-Noise Ratio:", snr_widget)

        self.duty_label = QLabel("")
        main_form.addRow("Duty Cycle (%):", self.duty_label)

        self.matching_volume_widget = QWidget()
        matching_volume_layout = QHBoxLayout(self.matching_volume_widget)
        self.matching_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.matching_volume_slider.setRange(0, 100)
        self.matching_volume_slider.setValue(50)
        matching_volume_layout.addWidget(self.matching_volume_slider)
        self.matching_volume_label = QLabel("50")
        self.matching_volume_slider.valueChanged.connect(lambda v: self.matching_volume_label.setText(str(v)))
        matching_volume_layout.addWidget(self.matching_volume_label)
        main_form.addRow("Matching Volume (%):", self.matching_volume_widget)

        self.enable_ptr_checkbox = QCheckBox("Enable Pulse Train Repetition")
        self.enable_ptr_checkbox.toggled.connect(self.on_toggle_ptr)
        stimulation_layout.addWidget(self.enable_ptr_checkbox)

        self.ptr_sub_widget = QWidget()
        ptr_sub_layout = QFormLayout()
        ptr_sub_layout.setVerticalSpacing(0)  # Reduce vertical spacing
        self.ptr_sub_widget.setLayout(ptr_sub_layout)
        stimulation_layout.addWidget(self.ptr_sub_widget)

        self.ptrp_input = QLineEdit("")
        self.ptrp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.ptrp_input.textChanged.connect(lambda _: self.validate_input(self.ptrp_input))
        self.ptrp_input.textChanged.connect(self.on_ptrp_changed)
        ptr_sub_layout.addRow("PTRI (s):", self.ptrp_input)

        self.ptrf_input = QLineEdit("")
        self.ptrf_input.setValidator(QDoubleValidator(0.0001, 1000.0, 4))
        self.ptrf_input.textChanged.connect(lambda _: self.validate_input(self.ptrf_input))
        self.ptrf_input.textChanged.connect(self.on_ptrf_changed)
        ptr_sub_layout.addRow("PTRF (Hz):", self.ptrf_input)

        self.ptrd_input = QLineEdit("")
        self.ptrd_input.setValidator(QDoubleValidator(0.1, 10000.0, 3))
        self.ptrd_input.textChanged.connect(lambda _: self.validate_input(self.ptrd_input))
        self.ptrd_input.textChanged.connect(self.on_ptrd_changed)
        ptr_sub_layout.addRow("PTRD (s):", self.ptrd_input)

        self.num_trains_input = QLineEdit("")
        self.num_trains_input.setValidator(QDoubleValidator(1, 100000, 0))
        self.num_trains_input.textChanged.connect(lambda _: self.validate_input(self.num_trains_input))
        self.num_trains_input.textChanged.connect(self.on_num_trains_changed)
        ptr_sub_layout.addRow("Number of Trains:", self.num_trains_input)

        self.ptr_sub_widget.setVisible(False)

        params_hbox.addWidget(stimulation_group, stretch=1)

        # Background and Layering (unchanged)
        dual_group = QGroupBox("Background and Layering")
        dual_layout = QFormLayout(dual_group)
        dual_layout.setContentsMargins(6, 6, 6, 6)
        dual_layout.setVerticalSpacing(2)
        dual_layout.setHorizontalSpacing(6)
        params_hbox.addWidget(dual_group, stretch=1)

        bg_label = QLabel("Continuous Background Controls")
        dual_layout.addRow(bg_label)

        self.bg_type_combo = QComboBox()
        self.bg_type_combo.addItems(["White Noise", "Narrowband Noise", "Colored Noise", "Hybrid Ultrasound Mask", "Auditory Mondrian"])
        self.bg_type_combo.currentTextChanged.connect(self.on_background_type_changed)
        dual_layout.addRow("Background Type:", self.bg_type_combo)

        self.bg_ramp_shape = QComboBox()
        self.bg_ramp_shape.addItems(["None", "Linear", "Tukey"])
        dual_layout.addRow("Ramp Shape:", self.bg_ramp_shape)

        self.bg_ramp_length_label = QLabel("Ramp Length (ms):")
        self.bg_ramp_length = QDoubleSpinBox()
        self.bg_ramp_length.setRange(0.0, 1000.0)
        self.bg_ramp_length.setDecimals(3)
        self.bg_ramp_length.setSingleStep(1.0)
        self.bg_ramp_length.setValue(10.0)
        self.bg_ramp_length.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        dual_layout.addRow(self.bg_ramp_length_label, self.bg_ramp_length)

        self.bg_ramp_shape.currentTextChanged.connect(self.on_background_ramp_changed)
        self.bg_ramp_length.valueChanged.connect(self.on_background_ramp_changed)

        self.bg_time_input = QLineEdit("5")
        self.bg_time_input.setValidator(QDoubleValidator(0.001, 100000.0, 3))
        self.bg_time_input.textChanged.connect(lambda _: self.validate_input(self.bg_time_input))
        self.bg_time_input.textChanged.connect(lambda _: self.update_derived())
        dual_layout.addRow("Background Time (s):", self.bg_time_input)

        # ADDED: Dedicated narrowband controls independent from the matching-signal carrier.
        self.narrowband_center_label = QLabel("Center Frequency (Hz):")
        self.narrowband_center_input = QLineEdit("1000")
        self.narrowband_center_input.setValidator(QDoubleValidator(1.0, 20000.0, 1))
        self.narrowband_center_input.textChanged.connect(lambda _: self.validate_input(self.narrowband_center_input))
        self.narrowband_center_input.textChanged.connect(self.validate_generate_button)
        dual_layout.addRow(self.narrowband_center_label, self.narrowband_center_input)

        self.narrowband_bandwidth_label = QLabel("Bandwidth (Hz):")
        self.narrowband_bandwidth_input = QLineEdit("100")
        self.narrowband_bandwidth_input.setValidator(QDoubleValidator(1.0, 20000.0, 1))
        self.narrowband_bandwidth_input.textChanged.connect(lambda _: self.validate_input(self.narrowband_bandwidth_input))
        self.narrowband_bandwidth_input.textChanged.connect(self.validate_generate_button)
        dual_layout.addRow(self.narrowband_bandwidth_label, self.narrowband_bandwidth_input)

        # ADDED: Simple named colored-noise selector.
        self.colored_noise_label = QLabel("Color:")
        self.colored_noise_combo = QComboBox()
        self.colored_noise_combo.addItems(["Pink", "Brown", "Blue", "Violet"])
        self.colored_noise_combo.currentTextChanged.connect(self.on_settings_changed)
        dual_layout.addRow(self.colored_noise_label, self.colored_noise_combo)

        self.bg_volume_widget = QWidget()
        bg_volume_layout = QHBoxLayout(self.bg_volume_widget)
        bg_volume_layout.setContentsMargins(0, 0, 0, 0)
        bg_volume_layout.setSpacing(4)
        self.bg_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_volume_slider.setRange(0, 100)
        self.bg_volume_slider.setValue(50)
        bg_volume_layout.addWidget(self.bg_volume_slider)
        self.bg_volume_label = QLabel("50")
        self.bg_volume_slider.valueChanged.connect(lambda v: self.bg_volume_label.setText(str(v)))
        bg_volume_layout.addWidget(self.bg_volume_label)
        dual_layout.addRow("Background Volume (%):", self.bg_volume_widget)

        self.enable_dual_checkbox = QCheckBox("Enable Dual Sound Mode")
        self.enable_dual_checkbox.toggled.connect(self.on_toggle_dual)
        dual_layout.addRow(self.enable_dual_checkbox)

        self.hybrid_mask_group = QGroupBox("Hybrid Mask Settings")
        hybrid_layout = QVBoxLayout(self.hybrid_mask_group)
        hybrid_layout.setContentsMargins(4, 4, 4, 4)
        hybrid_layout.setSpacing(2)

        hybrid_mode_row = QHBoxLayout()
        hybrid_mode_row.setContentsMargins(0, 0, 0, 0)
        hybrid_mode_row.setSpacing(4)
        self.hybrid_auto_radio = QRadioButton("Auto (recommended)")
        self.hybrid_manual_radio = QRadioButton("Manual tuning")
        self.hybrid_auto_radio.setChecked(True)
        self.hybrid_mode_group = QButtonGroup(self)
        self.hybrid_mode_group.addButton(self.hybrid_auto_radio)
        self.hybrid_mode_group.addButton(self.hybrid_manual_radio)
        self.hybrid_auto_radio.toggled.connect(self.on_hybrid_mode_changed)
        self.hybrid_manual_radio.toggled.connect(self.on_hybrid_mode_changed)
        hybrid_mode_row.addWidget(self.hybrid_auto_radio)
        hybrid_mode_row.addWidget(self.hybrid_manual_radio)
        hybrid_mode_row.addStretch(1)
        hybrid_layout.addLayout(hybrid_mode_row)

        self.hybrid_manual_widget = QWidget()
        hybrid_form = QFormLayout(self.hybrid_manual_widget)
        hybrid_form.setContentsMargins(0, 0, 0, 0)
        hybrid_form.setVerticalSpacing(2)
        hybrid_form.setHorizontalSpacing(4)

        self.hybrid_prf_input = QLineEdit("")
        self.hybrid_prf_input.setPlaceholderText("1000")
        self.hybrid_prf_input.setValidator(QDoubleValidator(1, 10000, 2))
        self.hybrid_prf_input.textChanged.connect(self.on_hybrid_prf_changed)
        hybrid_form.addRow("PRF (Hz):", self.hybrid_prf_input)

        self.hybrid_harmonics_input = QLineEdit("10")
        self.hybrid_harmonics_input.setValidator(QIntValidator(1, 1000))
        self.hybrid_harmonics_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_harmonics_input))
        hybrid_form.addRow("PRF Harmonics:", self.hybrid_harmonics_input)

        self.hybrid_bandwidth_input = QLineEdit("200")
        self.hybrid_bandwidth_input.setValidator(QDoubleValidator(1.0, 20000.0, 2))
        self.hybrid_bandwidth_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_bandwidth_input))
        hybrid_form.addRow("Harmonic Bandwidth (Hz):", self.hybrid_bandwidth_input)

        self.hybrid_density_input = QLineEdit("4")
        self.hybrid_density_input.setValidator(QDoubleValidator(0.1, 100.0, 2))
        self.hybrid_density_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_density_input))
        hybrid_form.addRow("Mondrian Density (tones/s):", self.hybrid_density_input)

        self.hybrid_tone_duration_input = QLineEdit("500")
        self.hybrid_tone_duration_input.setValidator(QDoubleValidator(10.0, 10000.0, 1))
        self.hybrid_tone_duration_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_tone_duration_input))
        hybrid_form.addRow("Mondrian Tone Duration (ms):", self.hybrid_tone_duration_input)

        self.hybrid_prf_weight_widget, self.hybrid_prf_weight_slider, self.hybrid_prf_weight_label = self._create_labeled_slider(0, 100, 50)
        hybrid_form.addRow("PRF Mask Weight:", self.hybrid_prf_weight_widget)

        self.hybrid_mondrian_weight_widget, self.hybrid_mondrian_weight_slider, self.hybrid_mondrian_weight_label = self._create_labeled_slider(0, 100, 30)
        hybrid_form.addRow("Mondrian Weight:", self.hybrid_mondrian_weight_widget)

        self.hybrid_broadband_weight_widget, self.hybrid_broadband_weight_slider, self.hybrid_broadband_weight_label = self._create_labeled_slider(0, 100, 20)
        hybrid_form.addRow("Broadband Weight:", self.hybrid_broadband_weight_widget)

        self.hybrid_manual_scroll = QScrollArea()
        self.hybrid_manual_scroll.setWidgetResizable(True)
        self.hybrid_manual_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.hybrid_manual_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hybrid_manual_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hybrid_manual_scroll.setWidget(self.hybrid_manual_widget)
        self.hybrid_manual_scroll.setFixedHeight(162)
        hybrid_layout.addWidget(self.hybrid_manual_scroll)
        dual_layout.addRow(self.hybrid_mask_group)
        self.hybrid_mask_group.setVisible(False)
        self.hybrid_manual_scroll.setVisible(False)

        self.mondrian_mask_group = QGroupBox("Mondrian Mask Settings")
        mondrian_layout = QFormLayout(self.mondrian_mask_group)
        mondrian_layout.setContentsMargins(4, 4, 4, 4)
        mondrian_layout.setVerticalSpacing(2)
        mondrian_layout.setHorizontalSpacing(4)

        self.mondrian_density_input = QLineEdit("8")
        self.mondrian_density_input.setValidator(QDoubleValidator(0.1, 100.0, 2))
        self.mondrian_density_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_density_input))
        mondrian_layout.addRow("Mondrian Density (tones/s):", self.mondrian_density_input)

        self.mondrian_tone_duration_input = QLineEdit("500")
        self.mondrian_tone_duration_input.setValidator(QDoubleValidator(10.0, 10000.0, 1))
        self.mondrian_tone_duration_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_tone_duration_input))
        mondrian_layout.addRow("Tone Duration (ms):", self.mondrian_tone_duration_input)

        self.mondrian_carrier_min_input = QLineEdit("")
        self.mondrian_carrier_min_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_carrier_min_input.setPlaceholderText("optional (default: 20 Hz)")
        self.mondrian_carrier_min_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_carrier_min_input))
        mondrian_layout.addRow("PF min (Hz):", self.mondrian_carrier_min_input)

        self.mondrian_carrier_max_input = QLineEdit("15000")
        self.mondrian_carrier_max_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_carrier_max_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_carrier_max_input))
        mondrian_layout.addRow("PF max (Hz):", self.mondrian_carrier_max_input)

        self.mondrian_prf_min_input = QLineEdit("1000")
        self.mondrian_prf_min_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_prf_min_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_prf_min_input))
        mondrian_layout.addRow("PRF Min (Hz):", self.mondrian_prf_min_input)

        self.mondrian_prf_max_input = QLineEdit("15000")
        self.mondrian_prf_max_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_prf_max_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_prf_max_input))
        mondrian_layout.addRow("PRF Max (Hz):", self.mondrian_prf_max_input)

        self.mondrian_duty_cycle_input = QLineEdit("50")
        self.mondrian_duty_cycle_input.setValidator(QDoubleValidator(1.0, 99.0, 1))
        self.mondrian_duty_cycle_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_duty_cycle_input))
        mondrian_layout.addRow("Duty Cycle (%):", self.mondrian_duty_cycle_input)

        dual_layout.addRow(self.mondrian_mask_group)
        self.mondrian_mask_group.setVisible(False)

        self.pulse_controls_widget = QWidget()
        pulse_controls_layout = QFormLayout(self.pulse_controls_widget)
        pulse_controls_layout.setContentsMargins(0, 0, 0, 0)
        pulse_controls_layout.setVerticalSpacing(2)
        pulse_controls_layout.setHorizontalSpacing(6)
        pulse_label = QLabel("Pulse Mask Timing Controls")
        pulse_controls_layout.addRow(pulse_label)

        self.pulse_start_input = QLineEdit("0")
        self.pulse_start_input.setValidator(QDoubleValidator(0.0, 100000.0, 3))
        self.pulse_start_input.textChanged.connect(lambda _: self.validate_input(self.pulse_start_input))
        self.pulse_start_input.textChanged.connect(lambda _: self.update_derived())
        pulse_controls_layout.addRow("Pulse Start Time (ms):", self.pulse_start_input)

        self.pulse_volume_widget = QWidget()
        pulse_volume_layout = QHBoxLayout(self.pulse_volume_widget)
        pulse_volume_layout.setContentsMargins(0, 0, 0, 0)
        pulse_volume_layout.setSpacing(4)
        self.pulse_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.pulse_volume_slider.setRange(0, 100)
        self.pulse_volume_slider.setValue(100)
        pulse_volume_layout.addWidget(self.pulse_volume_slider)
        self.pulse_volume_label = QLabel("100")
        self.pulse_volume_slider.valueChanged.connect(lambda v: self.pulse_volume_label.setText(str(v)))
        pulse_volume_layout.addWidget(self.pulse_volume_label)
        pulse_controls_layout.addRow("Pulse Volume (%):", self.pulse_volume_widget)

        dual_layout.addRow(self.pulse_controls_widget)
        self.pulse_controls_widget.setVisible(False)

        # Lateralization Mode
        spatial_mode_group = QGroupBox("Lateralization Mode")
        spatial_mode_layout = QFormLayout(spatial_mode_group)

        self.pan_widget = QWidget()
        pan_layout = QHBoxLayout(self.pan_widget)
        self.pan_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_slider.setRange(-100, 100)
        self.pan_slider.setValue(0)
        self.pan_slider.valueChanged.connect(self.on_pan_changed)
        pan_layout.addWidget(self.pan_slider)
        self.pan_value_label = QLabel("0")
        pan_layout.addWidget(self.pan_value_label)
        spatial_mode_layout.addRow("Pan (0 = Center):", self.pan_widget)

        self.pan_levels_label = QLabel("Left: 100%  Right: 100%")
        spatial_mode_layout.addRow("Channel Volumes:", self.pan_levels_label)

        params_hbox.addWidget(spatial_mode_group, stretch=1)

        # Buttons - UPDATED: Added Calibration button
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

        playback_controls = QWidget()
        playback_controls_layout = QHBoxLayout(playback_controls)
        playback_controls_layout.setContentsMargins(0, 0, 0, 0)
        playback_controls_layout.setSpacing(6)

        playback_label = QLabel("Playback Mode:")
        playback_controls_layout.addWidget(playback_label)

        self.playback_mode_combo = QComboBox()
        self.playback_mode_combo.setCurrentIndex(-1)  # No selection initially
        self.playback_mode_combo.currentTextChanged.connect(self.validate_generate_button)
        self.playback_mode_combo.currentTextChanged.connect(self.on_playback_mode_changed)
        self.playback_mode_combo.setFixedWidth(180)
        playback_controls_layout.addWidget(self.playback_mode_combo)

        button_layout.addWidget(playback_controls)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.on_generate)
        button_layout.addWidget(self.generate_btn)

        self.play_btn = QPushButton("Play Audio")
        self.play_btn.clicked.connect(self.on_play)
        self.play_btn.setEnabled(False)
        button_layout.addWidget(self.play_btn)

        self.stop_wav_btn = QPushButton("Stop Audio")
        self.stop_wav_btn.clicked.connect(self.on_stop)
        self.stop_wav_btn.setEnabled(False)
        button_layout.addWidget(self.stop_wav_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)

        # ADDED: Single presets button beside Save for save/load preset actions.
        self.presets_btn = QPushButton("Presets")
        self.presets_btn.clicked.connect(lambda: self.preset_manager.show_menu(self.presets_btn))
        button_layout.addWidget(self.presets_btn)

        # ADDED: Single reset button with scoped reset options.
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(lambda: self.preset_manager.reset_audio_settings())
        button_layout.addWidget(self.reset_btn)

        top_layout.addLayout(button_layout)

        # Bottom visualization - UPDATED: Added spectral toggle
        bottom_hbox = QHBoxLayout()
        main_layout.addLayout(bottom_hbox)

        left_widget = QWidget()
        self.left_layout = QVBoxLayout(left_widget)  # NEW: Made attribute for dynamic updates
        bottom_hbox.addWidget(left_widget, stretch=1)

        toggle_group = QButtonGroup(self)
        zoom_radio = QRadioButton("PRF Envelope Zoom (First 3 PRIs)")
        full_radio = QRadioButton("Full Burst View")
        toggle_group.addButton(zoom_radio)
        toggle_group.addButton(full_radio)
        zoom_radio.setChecked(True)

        toggle_hbox = QHBoxLayout()
        toggle_hbox.addWidget(zoom_radio)
        toggle_hbox.addWidget(full_radio)

        # UPDATED: Add spectral toggle checkbox
        self.show_fft_checkbox = QCheckBox("Show FFT View")
        self.show_fft_checkbox.setChecked(True)
        self.show_fft_checkbox.toggled.connect(self.on_toggle_fft)
        toggle_hbox.addStretch(1)  # Push to right for spacing
        toggle_hbox.addWidget(self.show_fft_checkbox)

        self.show_spectrogram_checkbox = QCheckBox("Show Spectrogram View")
        self.show_spectrogram_checkbox.setChecked(False)
        self.show_spectrogram_checkbox.toggled.connect(self.on_toggle_spectrogram)
        toggle_hbox.addWidget(self.show_spectrogram_checkbox)

        self.left_layout.addLayout(toggle_hbox, stretch=0)

        toggle_group.buttonToggled.connect(self.on_toggle_view)

        self.time_fig = Figure(figsize=(4, 4), dpi=100)
        self.time_canvas = FigureCanvas(self.time_fig)
        self.time_canvas.mpl_connect("button_press_event", self._on_time_canvas_click)
        self.time_ax = self.time_fig.add_subplot(111)
        self.left_layout.addWidget(self.time_canvas, stretch=1)

        self.right_widget = QWidget()  # UPDATED: Made attribute for visibility control
        right_layout = QVBoxLayout(self.right_widget)
        bottom_hbox.addWidget(self.right_widget, stretch=1)

        spacer_label = QLabel("")
        spacer_label.setFixedHeight(zoom_radio.sizeHint().height())
        right_layout.addWidget(spacer_label, stretch=0)

        self.right_fig = Figure(figsize=(4, 4), dpi=100)
        self.right_canvas = FigureCanvas(self.right_fig)
        self.right_canvas.mpl_connect("button_press_event", self._on_right_canvas_click)
        right_layout.addWidget(self.right_canvas, stretch=1)

        self.on_ramp_shape_changed(self.ramp_shape_combo.currentText())
        self.update_background_ramp_visibility()
        self.on_background_type_changed(self.bg_type_combo.currentText())
        self.update_derived()
        self.on_toggle_dual(False)  # Initial state
        self.on_pan_changed(self.pan_slider.value())  # Initial state
        self._connect_dirty_state_tracking()
        # ADDED: Capture the startup defaults so reset returns to the initial app state.
        self.preset_manager.capture_default_states()

    # UPDATED: Toggle Dual Mode (removed separate graphs)
    def on_toggle_dual(self, checked):
        self.pulse_controls_widget.setVisible(checked)
        self.matching_volume_widget.setEnabled(not checked)
        self.playback_mode_combo.clear()
        self.playback_mode_combo.addItems(["Background Only", "Matching Only"])
        if checked:
            self.playback_mode_combo.addItems(["Combined"])
        self.playback_mode_combo.setCurrentText("Combined" if checked else "Matching Only")
        self.validate_generate_button()
        if self.current_audio is not None:
            self._update_time_plot()

    def on_playback_mode_changed(self, text):
        if text == "Matching Only" and self.enable_dual_checkbox.isChecked():
            self.enable_dual_checkbox.setChecked(False)

    def _create_labeled_slider(self, minimum, maximum, value):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        label = QLabel(f"{value / 100:.2f}")
        label.setMinimumWidth(28)
        slider.valueChanged.connect(lambda v, out=label: out.setText(f"{v / 100:.2f}"))
        layout.addWidget(slider)
        layout.addWidget(label)
        return widget, slider, label

    def on_background_type_changed(self, text):
        is_narrowband = text == "Narrowband Noise"
        is_colored_noise = text == "Colored Noise"
        is_hybrid = text == "Hybrid Ultrasound Mask"
        is_mondrian = text == "Auditory Mondrian"
        self.narrowband_center_label.setVisible(is_narrowband)
        self.narrowband_center_input.setVisible(is_narrowband)
        self.narrowband_bandwidth_label.setVisible(is_narrowband)
        self.narrowband_bandwidth_input.setVisible(is_narrowband)
        self.colored_noise_label.setVisible(is_colored_noise)
        self.colored_noise_combo.setVisible(is_colored_noise)
        self.hybrid_mask_group.setVisible(is_hybrid)
        self.mondrian_mask_group.setVisible(is_mondrian)

        self._update_carrier_input_state()

        if is_hybrid or is_mondrian:
            self.enable_dual_checkbox.setChecked(False)
            self.enable_dual_checkbox.setEnabled(False)
            if is_hybrid:
                self.enable_dual_checkbox.setToolTip("Hybrid mask already contains multiple masking layers")
            else:
                self.enable_dual_checkbox.setToolTip("Auditory Mondrian is a standalone masking background")
            # on_toggle_dual forced "Matching Only"; override to "Background Only" since
            # these background types can only be used without a pulse.
            self.playback_mode_combo.setCurrentText("Background Only")
        else:
            self.enable_dual_checkbox.setEnabled(True)
            self.enable_dual_checkbox.setToolTip("")

        self.update_background_ramp_visibility()
        self.on_hybrid_mode_changed()
        self.validate_generate_button()

    def on_hybrid_mode_changed(self, *_):
        is_hybrid = self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask"
        manual = is_hybrid and self.hybrid_manual_radio.isChecked()
        if is_hybrid and self.hybrid_auto_radio.isChecked():
            self.reset_hybrid_defaults()
        self.hybrid_manual_scroll.setVisible(manual)
        self.validate_generate_button()

    def _set_prf_fields(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.prf_input.text() != text:
                self.prf_input.setText(text)
            if self.hybrid_prf_input.text() != text:
                self.hybrid_prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False

    def on_hybrid_prf_changed(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.prf_input.text() != text:
                self.prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False
        self.validate_generate_button()

    def sync_hybrid_prf_from_main(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.hybrid_prf_input.text() != text:
                self.hybrid_prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False

    def _compute_pan_gains(self, pan_norm):
        pan_norm = max(-1.0, min(1.0, pan_norm))
        if pan_norm <= 0:
            left_gain = 1.0
            right_gain = 1.0 + pan_norm
        else:
            left_gain = 1.0 - pan_norm
            right_gain = 1.0
        return left_gain, right_gain

    def reset_hybrid_defaults(self):
        self.hybrid_harmonics_input.setText("10")
        self.hybrid_bandwidth_input.setText("200")
        self.hybrid_density_input.setText("4")
        self.hybrid_tone_duration_input.setText("500")
        self.hybrid_prf_weight_slider.setValue(50)
        self.hybrid_mondrian_weight_slider.setValue(30)
        self.hybrid_broadband_weight_slider.setValue(20)

    def _resolve_prf_value(self, show_notice=False):
        prf_text = self.hybrid_prf_input.text().strip() or self.prf_input.text().strip()
        if prf_text:
            return float(prf_text)

        if show_notice and self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask":
            self._set_prf_fields("1000")
            message = "PRF not specified \u2014 using default 1000 Hz for hybrid mask"
            self.statusBar().showMessage(message, 5000)
            tooltip_pos = self.generate_btn.mapToGlobal(self.generate_btn.rect().center())
            QToolTip.showText(tooltip_pos, message, self.generate_btn, self.generate_btn.rect(), 5000)
        return 1000.0

    def on_pan_changed(self, value):
        self.pan_value_label.setText(str(value))
        pan_norm = value / 100.0
        left_gain, right_gain = self._compute_pan_gains(pan_norm)
        self.pan_levels_label.setText(f"Left: {round(left_gain * 100):.0f}%  Right: {round(right_gain * 100):.0f}%")

    def on_toggle_view(self, button, checked):
        if checked:
            self.zoom_view = button.text() == "PRF Envelope Zoom (First 3 PRIs)"
            if self.current_audio is not None:
                self._update_time_plot()

    # UPDATED: New method for FFT toggle
    def on_toggle_fft(self, checked):
        self.right_widget.setVisible(checked or self.show_spectrogram_checkbox.isChecked())
        if self.current_audio is not None:
            self._update_right_plot()

    # NEW: Method for spectrogram toggle
    def on_toggle_spectrogram(self, checked):
        self.right_widget.setVisible(checked or self.show_fft_checkbox.isChecked())
        if self.current_audio is not None:
            self._update_right_plot()

    def on_ramp_shape_changed(self, text):
        visible = text != "None"
        self.ramp_len_label.setVisible(visible)
        self.ramp_len_input.setVisible(visible)
        if not visible:
            self.ramp_len_input.setText("")
        self.validate_generate_button()
        self.update_derived()

    def update_background_ramp_visibility(self):
        visible = self.bg_ramp_shape.currentText() != "None"
        self.bg_ramp_length_label.setVisible(visible)
        self.bg_ramp_length.setVisible(visible)

    def _is_input_acceptable(self, input_widget):
        text = input_widget.text()
        if not text:
            return False
        validator = input_widget.validator()
        if validator is None:
            return True
        state, _, _ = validator.validate(text, 0)
        return state == validator.State.Acceptable

    def on_background_ramp_changed(self, *_):
        self.update_background_ramp_visibility()

        if self.current_audio is None or self.current_fs is None:
            return

        mode = self.playback_mode_combo.currentText()
        if mode not in ["Background Only", "Combined"]:
            return

        params = self._gather_params()
        duration = len(self.current_bg_audio) / self.current_fs if self.current_bg_audio is not None else len(self.current_audio) / self.current_fs

        bg_audio = signal_generator.generate_continuous_background(
            duration=duration,
            fs=self.current_fs,
            bg_type=params["bg_type"],
            carrier_freq=params["carrier_freq"],
            bg_ramp_shape=params["bg_ramp_shape"],
            bg_ramp_length=params["bg_ramp_length"],
            prf=params["prf"],
            hybrid_settings=params.get("hybrid_mask_settings"),
            mondrian_settings=params.get("mondrian_mask_settings"),
            narrowband_settings={
                "center_freq": params.get("bg_center_freq"),
                "bandwidth": params.get("bg_bandwidth"),
            },
            colored_noise_settings={
                "color": params.get("bg_noise_color"),
            },
        )
        bg_audio = signal_generator.apply_timing_gate(bg_audio, self.current_fs, params["bg_start_ms"], params["bg_end_ms"], duration)
        bg_audio *= params["bg_volume"]

        if mode == "Background Only":
            combined = bg_audio.copy()
            pulse_audio = None
            gate = None
        else:
            pulse_audio = self.current_pulse_audio if self.current_pulse_audio is not None else np.zeros_like(bg_audio)
            combined = 0.5 * (pulse_audio + bg_audio)
            gate = self.current_gate

        max_abs = np.max(np.abs(combined))
        if max_abs > 1.0:
            combined = combined / max_abs
            if pulse_audio is not None:
                pulse_audio = pulse_audio / max_abs
            bg_audio = bg_audio / max_abs

        pan = float(params.get("pan", 0.0))
        pan = max(-1.0, min(1.0, pan))
        if pan <= 0:
            left_gain = 1.0
            right_gain = 1.0 + pan
        else:
            left_gain = 1.0 - pan
            right_gain = 1.0
        stereo_audio = np.column_stack((combined * right_gain, combined * left_gain))

        self.current_audio = stereo_audio
        self.current_bg_audio = bg_audio
        self.current_pulse_audio = pulse_audio
        self.current_gate = gate
        if self.current_time is None or len(self.current_time) != len(combined):
            self.current_time = np.arange(0, len(combined)) / self.current_fs

        self._update_time_plot()
        self._update_right_plot()

    def on_toggle_ptr(self, checked):
        self.ptr_sub_widget.setVisible(checked)
        self.validate_generate_button()
        self.update_derived()

    def on_prp_changed(self, text):
        if self.updating_prp_prf:
            return
        self.updating_prp_prf = True
        try:
            prp = float(text)
            if prp > 0:
                prf = 1000 / prp
                self.prf_input.setText(f"{prf:g}")  # Use g to remove trailing zeros
        except ValueError:
            pass
        self.updating_prp_prf = False
        self.update_derived()

    def on_prf_changed(self, text):
        if self.updating_prp_prf:
            return
        self.updating_prp_prf = True
        try:
            prf = float(text)
            if prf > 0:
                prp = 1000 / prf
                self.prp_input.setText(f"{prp:g}")
        except ValueError:
            pass
        self.updating_prp_prf = False
        self.update_derived()

    def _sync_num_trains_from_ptrd(self):
        if self.updating_ptrd_num:
            return

        ptrd_text = self.ptrd_input.text()
        ptrp_text = self.ptrp_input.text()
        if not ptrd_text or not ptrp_text:
            return

        self.updating_ptrd_num = True
        try:
            ptrd = float(ptrd_text)
            ptrp = float(ptrp_text)
            if ptrd > 0 and ptrp > 0:
                num = ptrd / ptrp
                self.num_trains_input.setText(f"{num:g}")
        except ValueError:
            pass
        finally:
            self.updating_ptrd_num = False

    def on_ptrp_changed(self, text):
        if self.updating_ptrp_ptrf:
            return
        self.updating_ptrp_ptrf = True
        try:
            ptrp = float(text)
            if ptrp > 0:
                ptrf = 1 / ptrp
                self.ptrf_input.setText(f"{ptrf:g}")
        except ValueError:
            pass
        self.updating_ptrp_ptrf = False
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_ptrf_changed(self, text):
        if self.updating_ptrp_ptrf:
            return
        self.updating_ptrp_ptrf = True
        try:
            ptrf = float(text)
            if ptrf > 0:
                ptrp = 1 / ptrf
                self.ptrp_input.setText(f"{ptrp:g}")
        except ValueError:
            pass
        self.updating_ptrp_ptrf = False
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_ptrd_changed(self, text):
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_num_trains_changed(self, text):
        if self.updating_ptrd_num:
            return
        self.updating_ptrd_num = True
        try:
            num = float(text)
            ptrp_text = self.ptrp_input.text()
            if ptrp_text:
                ptrp = float(ptrp_text)
                ptrd = num * ptrp
                self.ptrd_input.setText(f"{ptrd:g}")
        except ValueError:
            pass
        self.updating_ptrd_num = False
        self.update_derived()

    def validate_input(self, sender):
        validator = sender.validator()
        if validator is None:
            return
        state = validator.validate(sender.text(), 0)[0]
        if state == QDoubleValidator.State.Acceptable:
            sender.setStyleSheet("")
        elif state == QDoubleValidator.State.Intermediate:
            sender.setStyleSheet("border: 1px solid yellow;")
        else:
            sender.setStyleSheet("border: 1px solid red;")

    def update_derived(self):
        try:
            prf_str = self.prf_input.text()
            pd_str = self.pd_input.text()
            ramp_str = self.ramp_len_input.text()
            ptd_str = self.ptd_input.text()

            if not prf_str or not pd_str:
                self.duty_label.setText("N/A")
                self.validate_generate_button()
                return

            prf = float(prf_str)
            pd_ms = float(pd_str)
            ramp_ms = float(ramp_str) if ramp_str and self.ramp_shape_combo.currentText() != "None" else 0
            prp_ms = 1000 / prf if prf > 0 else 0

            if prf <= 0:
                raise ValueError("PRF must be positive")

            duty = (pd_ms / prp_ms) * 100 if prp_ms > 0 else 0
            self.duty_label.setText(f"{duty:.2f}")

            if pd_ms > prp_ms:
                self.pd_input.setStyleSheet("border: 1px solid red;")
            else:
                self.validate_input(self.pd_input)

            if ramp_ms > pd_ms / 2:
                self.ramp_len_input.setStyleSheet("border: 1px solid red;")
            else:
                self.validate_input(self.ramp_len_input)

            if ptd_str:
                ptd_ms = float(ptd_str)
                if ptd_ms < pd_ms:
                    self.ptd_input.setStyleSheet("border: 1px solid red;")
                else:
                    self.validate_input(self.ptd_input)
                if prp_ms > ptd_ms:
                    self.prp_input.setStyleSheet("border: 1px solid red;")
                    self.prf_input.setStyleSheet("border: 1px solid red;")
                else:
                    self.validate_input(self.prp_input)
                    self.validate_input(self.prf_input)

            if self.enable_ptr_checkbox.isChecked():
                ptrp_str = self.ptrp_input.text()
                if ptrp_str:
                    ptrp_s = float(ptrp_str)
                    if ptd_str and ptrp_s * 1000 < float(ptd_str):
                        self.ptrp_input.setStyleSheet("border: 1px solid red;")
                        self.ptrf_input.setStyleSheet("border: 1px solid red;")
                    else:
                        self.validate_input(self.ptrp_input)
                        self.validate_input(self.ptrf_input)

            self.validate_generate_button()

        except ValueError:
            self.duty_label.setText("Invalid")

    def validate_generate_button(self):
        mode = self.playback_mode_combo.currentText()
        if not mode:
            self.generate_btn.setEnabled(False)
            return

        core_inputs = []
        if mode in ["Matching Only", "Combined"]:
            core_inputs += [self.ptd_input, self.prf_input, self.pd_input]
            if self.ramp_shape_combo.currentText() != "None":
                core_inputs += [self.ramp_len_input]
        if mode in ["Background Only", "Combined"] and self.bg_type_combo.currentText() == "Narrowband Noise":
            core_inputs += [self.narrowband_center_input, self.narrowband_bandwidth_input]

        valid = all(self._is_input_acceptable(input) for input in core_inputs)

        if self.enable_carrier_checkbox.isChecked():
            valid &= self._is_input_acceptable(self.carrier_input)

        if self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask":
            valid &= bool(self.bg_time_input.text())
            if self.hybrid_manual_radio.isChecked():
                hybrid_inputs = [
                    self.hybrid_harmonics_input,
                    self.hybrid_bandwidth_input,
                    self.hybrid_density_input,
                    self.hybrid_tone_duration_input,
                ]
                valid &= all(self._is_input_acceptable(input) for input in hybrid_inputs)
                weight_sum = (
                    self.hybrid_prf_weight_slider.value()
                    + self.hybrid_mondrian_weight_slider.value()
                    + self.hybrid_broadband_weight_slider.value()
                )
                valid &= weight_sum > 0
        elif self.bg_type_combo.currentText() == "Auditory Mondrian":
            mondrian_inputs = [
                self.mondrian_density_input,
                self.mondrian_tone_duration_input,
                self.mondrian_carrier_max_input,
                self.mondrian_prf_min_input,
                self.mondrian_prf_max_input,
                self.mondrian_duty_cycle_input,
            ]
            valid &= bool(self.bg_time_input.text())
            valid &= all(self._is_input_acceptable(input) for input in mondrian_inputs)
            if self.mondrian_carrier_min_input.text() and not self._is_input_acceptable(self.mondrian_carrier_min_input):
                valid = False
            if all(self._is_input_acceptable(input) for input in mondrian_inputs[3:5]):
                valid &= float(self.mondrian_prf_min_input.text()) < float(self.mondrian_prf_max_input.text())
            if (self.mondrian_carrier_min_input.text() and self._is_input_acceptable(self.mondrian_carrier_min_input)
                    and self._is_input_acceptable(self.mondrian_carrier_max_input)):
                valid &= float(self.mondrian_carrier_min_input.text()) < float(self.mondrian_carrier_max_input.text())
        elif self.bg_type_combo.currentText() == "Narrowband Noise":
            if all(self._is_input_acceptable(input) for input in [self.narrowband_center_input, self.narrowband_bandwidth_input]):
                center = float(self.narrowband_center_input.text())
                bandwidth = float(self.narrowband_bandwidth_input.text())
                valid &= bandwidth < 2 * center

        if self.enable_ptr_checkbox.isChecked():
            train_inputs = [self.ptrp_input, self.num_trains_input]
            valid &= all(self._is_input_acceptable(input) for input in train_inputs)
            if self._is_input_acceptable(self.ptrp_input) and self.ptd_input.text():
                try:
                    if float(self.ptrp_input.text()) * 1000 < float(self.ptd_input.text()):
                        valid = False
                except ValueError:
                    pass

        if self.bg_time_input.text():
            valid &= self._is_input_acceptable(self.bg_time_input)

        if self.enable_dual_checkbox.isChecked():
            valid &= self.pulse_start_input.validator().validate(self.pulse_start_input.text() or "0", 0)[0] == self.pulse_start_input.validator().State.Acceptable

        self.generate_btn.setEnabled(valid)

    def _gather_params(self, show_hybrid_prf_notice=False):
        prf_value = self._resolve_prf_value(show_notice=show_hybrid_prf_notice)
        params = {
            "enable_carrier": self.enable_carrier_checkbox.isChecked(),
            "carrier_freq": float(self.carrier_input.text()) if self.carrier_input.text() else 1000,
            "prf": prf_value,
            "pulse_width": float(self.pd_input.text()) / 1000 if self.pd_input.text() else 0.0003,
            "snr": float(self.snr_input.text()) if self.snr_checkbox.isChecked() and self.snr_input.text() else None,
            "ptr_enabled": self.enable_ptr_checkbox.isChecked(),
            "fs": audio_engine.get_default_sample_rate(),
            "ramp_len": float(self.ramp_len_input.text()) / 1000 if self.ramp_len_input.text() and self.ramp_shape_combo.currentText() != "None" else 0,  # Set to 0 if "None"
            "ramp_shape": self.ramp_shape_combo.currentText(),
            "bg_type": self.bg_type_combo.currentText(),
            "bg_volume": self.bg_volume_slider.value() / 100.0,
            "bg_ramp_shape": self.bg_ramp_shape.currentText(),
            "bg_ramp_length": self.bg_ramp_length.value() / 1000 if self.bg_ramp_shape.currentText() != "None" else 0.0,
            "bg_center_freq": float(self.narrowband_center_input.text()) if self.narrowband_center_input.text() else 1000.0,
            "bg_bandwidth": float(self.narrowband_bandwidth_input.text()) if self.narrowband_bandwidth_input.text() else 100.0,
            "bg_noise_color": self.colored_noise_combo.currentText(),
        }
        params["hybrid_mask_mode"] = "manual" if self.hybrid_manual_radio.isChecked() else "auto"
        params["hybrid_mask_settings"] = {
            "prf_harmonics": int(self.hybrid_harmonics_input.text()) if self.hybrid_harmonics_input.text() else 10,
            "harmonic_bandwidth": float(self.hybrid_bandwidth_input.text()) if self.hybrid_bandwidth_input.text() else 200.0,
            "mondrian_density": float(self.hybrid_density_input.text()) if self.hybrid_density_input.text() else 4.0,
            "mondrian_tone_duration_ms": float(self.hybrid_tone_duration_input.text()) if self.hybrid_tone_duration_input.text() else 500.0,
            "prf_mask_weight": self.hybrid_prf_weight_slider.value() / 100.0,
            "mondrian_weight": self.hybrid_mondrian_weight_slider.value() / 100.0,
            "broadband_weight": self.hybrid_broadband_weight_slider.value() / 100.0,
        }
        params["mondrian_mask_settings"] = {
            "density": float(self.mondrian_density_input.text()) if self.mondrian_density_input.text() else 8.0,
            "tone_duration_ms": float(self.mondrian_tone_duration_input.text()) if self.mondrian_tone_duration_input.text() else 500.0,
            "carrier_min": float(self.mondrian_carrier_min_input.text()) if self.mondrian_carrier_min_input.text() else 20.0,
            "carrier_max": float(self.mondrian_carrier_max_input.text()) if self.mondrian_carrier_max_input.text() else 15000.0,
            "prf_min": float(self.mondrian_prf_min_input.text()) if self.mondrian_prf_min_input.text() else 1000.0,
            "prf_max": float(self.mondrian_prf_max_input.text()) if self.mondrian_prf_max_input.text() else 15000.0,
            "duty_cycle": float(self.mondrian_duty_cycle_input.text()) if self.mondrian_duty_cycle_input.text() else 50.0,
        }
        if self.ptd_input.text():
            params["train_duration"] = float(self.ptd_input.text())
        if self.enable_ptr_checkbox.isChecked():
            params["num_trains"] = float(self.num_trains_input.text()) if self.num_trains_input.text() else 1
            if self.ptrp_input.text():
                ptrp_s = float(self.ptrp_input.text())
                train_dur_ms = params.get("train_duration", 0)
                interval_ms = ptrp_s * 1000 - train_dur_ms
                if interval_ms < 0:
                    raise ValueError("PTRI too small for Pulse Train Duration")
                params["train_interval"] = interval_ms
        else:
            if "train_duration" in params:
                params["num_trains"] = 1
                params["train_interval"] = 0
        params["bg_start_ms"] = 0
        params["bg_end_ms"] = float(self.bg_time_input.text()) * 1000 if self.bg_time_input.text() else -1
        params["pulse_start_ms"] = float(self.pulse_start_input.text()) if self.enable_dual_checkbox.isChecked() and self.pulse_start_input.text() else 0
        params["pulse_end_ms"] = -1  # Computed in on_generate for Combined; defaults to audio end for Matching Only
        if self.enable_dual_checkbox.isChecked():
            params["pulse_volume"] = self.pulse_volume_slider.value() / 100.0
        else:
            params["pulse_volume"] = self.matching_volume_slider.value() / 100.0
        params["pan"] = self.pan_slider.value() / 100.0
        return params

    def on_generate(self):
        try:
            mode = self.playback_mode_combo.currentText()
            if not mode:
                return

            params = self._gather_params(show_hybrid_prf_notice=True)

            if mode in ["Matching Only", "Combined"] and not self.ptd_input.text():
                raise ValueError("Pulse Train Duration required for matching modes")
            params["duration"] = 0.5  # Default fallback

            if mode == "Combined":
                # Pulse runs from pulse_start_ms for PTD ms; background runs from 0 for bg_end_ms.
                # Total duration is whichever ends later.
                ptd_ms = float(self.ptd_input.text()) if self.ptd_input.text() else 0
                pulse_start_ms = params["pulse_start_ms"]
                pulse_end_ms = pulse_start_ms + ptd_ms
                bg_end_ms = params.get("bg_end_ms", 0)
                params["pulse_end_ms"] = pulse_end_ms
                params["duration"] = max(pulse_end_ms, bg_end_ms) / 1000

            controller = SessionController()
            self.current_audio, self.current_time, self.current_gate, self.current_fs, self.current_pulse_audio, self.current_bg_audio = controller.generate(params, mode)
            self.last_generated_params = copy.deepcopy(params)
            self.last_generated_mode = mode

            self._update_time_plot()
            self._update_right_plot()
            self.play_btn.setEnabled(True)
            self.stop_wav_btn.setEnabled(True)
            self.save_btn.setEnabled(True)

        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _update_time_plot(self):
        if self.current_audio is None:
            return

        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else 1000.0
        plotting.update_time_plot(self.time_ax, self.current_time, self.current_audio, self.current_gate, self.current_bg_audio, self.zoom_view, self.ramp_len_input.text(), self.current_fs, prf)

        self.time_fig.tight_layout()
        self.time_canvas.draw_idle()

    def _update_right_plot(self):
        if self.current_audio is None:
            return

        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else None
        plotting.update_right_plot(self.right_fig, self.current_audio, self.current_fs, self.show_spectrogram_checkbox.isChecked(), self.show_fft_checkbox.isChecked(), prf)

        self.right_fig.tight_layout()
        self.right_canvas.draw_idle()

    def clear_generated_output(self):
        self.current_audio = None
        self.current_time = None
        self.current_gate = None
        self.current_fs = None
        self.current_pulse_audio = None
        self.current_bg_audio = None
        self.last_generated_params = None
        self.last_generated_mode = None

        self.time_ax.clear()
        self.time_canvas.draw_idle()

        self.right_fig.clear()
        self.right_canvas.draw_idle()

        self.play_btn.setEnabled(False)
        self.stop_wav_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _track_plot_popup(self, dialog):
        self._plot_popups.append(dialog)
        dialog.finished.connect(lambda *_: self._plot_popups.remove(dialog) if dialog in self._plot_popups else None)

    def _on_time_canvas_click(self, event):
        if not getattr(event, "dblclick", False) or self.current_audio is None:
            return
        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else 1000.0
        dialog = plotting.open_time_plot_popup(
            self,
            self.current_time,
            self.current_audio,
            self.current_gate,
            self.current_bg_audio,
            self.zoom_view,
            self.ramp_len_input.text(),
            self.current_fs,
            prf,
        )
        self._track_plot_popup(dialog)

    def _on_right_canvas_click(self, event):
        if not getattr(event, "dblclick", False) or self.current_audio is None:
            return
        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else None
        dialog = plotting.open_right_plot_popup(
            self,
            self.current_audio,
            self.current_fs,
            self.show_spectrogram_checkbox.isChecked(),
            self.show_fft_checkbox.isChecked(),
            prf,
        )
        self._track_plot_popup(dialog)

    def on_play(self):
        if self.current_audio is None:
            QMessageBox.warning(self, "No audio", "Generate first.")
            return
        try:
            self.stop_wav_btn.setEnabled(True)
            audio_engine.play(self.current_audio, self.current_fs)
        except Exception as e:
            QMessageBox.critical(self, "Playback error", str(e))

    def on_stop(self):
        audio_engine.stop()

    def _default_save_basename(self):
        mode = self.last_generated_mode or self.playback_mode_combo.currentText() or "audio"
        slug = mode.lower().replace(" + ", "_").replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{slug}_{timestamp}"

    def _audio_channel_count(self, audio):
        if audio is None:
            return 0
        if getattr(audio, "ndim", 1) == 1:
            return 1
        return int(audio.shape[1])

    def _build_save_metadata(self, saved_files):
        duration_seconds = 0.0
        if self.current_audio is not None and self.current_fs:
            duration_seconds = len(self.current_audio) / float(self.current_fs)

        metadata = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "playback_mode": self.last_generated_mode or self.playback_mode_combo.currentText(),
            "sample_rate_hz": int(self.current_fs) if self.current_fs is not None else None,
            "duration_seconds": duration_seconds,
            "channels": self._audio_channel_count(self.current_audio),
            "generated_files": saved_files,
            "generation_params": self._filtered_generation_params(self.last_generated_params, self.last_generated_mode),
        }
        return metadata

    def _filtered_generation_params(self, params, mode=None):
        if not params:
            return None

        raw = copy.deepcopy(params)
        bg_type = raw.get("bg_type")
        is_matching = mode in ("Matching Only", "Combined")
        is_background = mode in ("Background Only", "Combined")
        is_combined = mode == "Combined"
        ptr_enabled = raw.get("ptr_enabled", False)

        # PTR-derived values (only meaningful when matching and PTR enabled)
        ptri_seconds = None
        ptrd_seconds = None
        active_train_span_seconds = None
        if is_matching and ptr_enabled and raw.get("train_duration") is not None and raw.get("train_interval") is not None:
            ptri_seconds = (raw.get("train_duration") + raw.get("train_interval")) / 1000
            if raw.get("num_trains") is not None:
                ptrd_seconds = raw.get("num_trains") * ptri_seconds
                active_train_span_seconds = (
                    raw.get("num_trains") * (raw.get("train_duration") / 1000)
                    + max(raw.get("num_trains") - 1, 0) * (raw.get("train_interval") / 1000)
                )

        formatted = {}

        # --- Pulse / Matching parameters ---
        if is_matching:
            formatted["pulse_train_duration_ms"] = raw.get("train_duration")
            formatted["pri_ms"] = 1000 / raw.get("prf") if raw.get("prf") not in (None, 0) else None
            formatted["prf_hz"] = raw.get("prf")
            formatted["pulse_width_ms"] = raw.get("pulse_width", 0) * 1000 if raw.get("pulse_width") is not None else None
            formatted["carrier_frequency_hz"] = raw.get("carrier_freq") if raw.get("enable_carrier") else None
            formatted["ramp_shape"] = raw.get("ramp_shape")
            formatted["ramp_length_ms"] = raw.get("ramp_len", 0) * 1000 if raw.get("ramp_len") is not None and raw.get("ramp_shape") != "None" else None
            formatted["signal_to_noise_ratio"] = raw.get("snr")
            formatted["pulse_train_repetition_enabled"] = ptr_enabled
            if ptr_enabled:
                formatted["pulse_train_repetition_interval_seconds"] = ptri_seconds
                formatted["pulse_train_repetition_duration_seconds"] = ptrd_seconds
                formatted["number_of_trains"] = raw.get("num_trains")

        # --- Background parameters ---
        if is_background:
            formatted["background_type"] = bg_type
            formatted["background_time_seconds"] = None if raw.get("bg_end_ms") in (None, -1) else raw.get("bg_end_ms") / 1000
            formatted["background_volume_percent"] = raw.get("bg_volume", 0) * 100 if raw.get("bg_volume") is not None else None
            formatted["background_ramp_shape"] = raw.get("bg_ramp_shape")
            formatted["background_ramp_length_ms"] = (
                raw.get("bg_ramp_length", 0) * 1000 if raw.get("bg_ramp_length") is not None and raw.get("bg_ramp_shape") != "None" else None
            )
            if bg_type == "Narrowband Noise":
                formatted["background_center_frequency_hz"] = raw.get("bg_center_freq")
                formatted["background_bandwidth_hz"] = raw.get("bg_bandwidth")
            elif bg_type == "Colored Noise":
                formatted["background_noise_color"] = raw.get("bg_noise_color")
            elif bg_type == "White Noise":
                pass
            elif bg_type == "Hybrid Ultrasound Mask":
                hybrid = raw.get("hybrid_mask_settings", {})
                formatted["hybrid_mask_mode"] = raw.get("hybrid_mask_mode")
                formatted["hybrid_mask_settings"] = {
                    "prf_harmonics": hybrid.get("prf_harmonics"),
                    "harmonic_bandwidth_hz": hybrid.get("harmonic_bandwidth"),
                    "mondrian_density_tones_per_second": hybrid.get("mondrian_density"),
                    "mondrian_tone_duration_ms": hybrid.get("mondrian_tone_duration_ms"),
                    "prf_mask_weight_percent": hybrid.get("prf_mask_weight", 0) * 100 if hybrid.get("prf_mask_weight") is not None else None,
                    "mondrian_weight_percent": hybrid.get("mondrian_weight", 0) * 100 if hybrid.get("mondrian_weight") is not None else None,
                    "broadband_weight_percent": hybrid.get("broadband_weight", 0) * 100 if hybrid.get("broadband_weight") is not None else None,
                }
            elif bg_type == "Auditory Mondrian":
                mondrian = raw.get("mondrian_mask_settings", {})
                formatted["mondrian_mask_settings"] = {
                    "density_tones_per_second": mondrian.get("density"),
                    "tone_duration_ms": mondrian.get("tone_duration_ms"),
                    "pf_min_hz": mondrian.get("carrier_min"),
                    "pf_max_hz": mondrian.get("carrier_max"),
                    "prf_min_hz": mondrian.get("prf_min"),
                    "prf_max_hz": mondrian.get("prf_max"),
                    "duty_cycle_percent": mondrian.get("duty_cycle"),
                }

        # --- Pan (all modes) ---
        pan_value = raw.get("pan")
        if pan_value is not None:
            left_gain, right_gain = self._compute_pan_gains(float(pan_value))
            formatted["pan"] = {
                "normalized": pan_value,
                "left_channel_volume_percent": round(left_gain * 100, 2),
                "right_channel_volume_percent": round(right_gain * 100, 2),
            }

        # --- Volume and Combined timing ---
        if is_combined:
            formatted["pulse_start_seconds"] = raw.get("pulse_start_ms", 0) / 1000 if raw.get("pulse_start_ms") is not None else None
            formatted["pulse_end_seconds"] = None if raw.get("pulse_end_ms") in (None, -1) else raw.get("pulse_end_ms") / 1000
            if ptrd_seconds is not None and raw.get("pulse_start_ms") is not None:
                formatted["pulse_train_window_end_seconds"] = raw.get("pulse_start_ms", 0) / 1000 + ptrd_seconds
            if active_train_span_seconds is not None and raw.get("pulse_start_ms") is not None:
                formatted["pulse_train_active_end_seconds"] = raw.get("pulse_start_ms", 0) / 1000 + active_train_span_seconds
            formatted["pulse_volume_percent"] = raw.get("pulse_volume", 0) * 100 if raw.get("pulse_volume") is not None else None
        elif is_matching:
            formatted["matching_volume_percent"] = raw.get("pulse_volume", 0) * 100 if raw.get("pulse_volume") is not None else None

        formatted["sample_rate_hz"] = raw.get("fs")

        return formatted

    def on_save(self):
        if self.current_audio is None:
            QMessageBox.warning(self, "No audio", "Generate first.")
            return

        default_name = self._default_save_basename()
        filepath, _ = QFileDialog.getSaveFileName(self, "Save session", default_name, "WAV files (*.wav)")
        if not filepath:
            return

        target_path = Path(filepath)
        if target_path.suffix.lower() != ".wav":
            target_path = target_path.with_suffix(".wav")

        saved_files = {}

        try:
            audio_engine.save_wav(self.current_audio, self.current_fs, str(target_path))
            saved_files["main_wav"] = target_path.name

            if self.last_generated_mode == "Combined" and self.current_bg_audio is not None:
                bg_path = target_path.with_name(f"{target_path.stem}_background.wav")
                audio_engine.save_wav(self.current_bg_audio, self.current_fs, str(bg_path))
                saved_files["background_wav"] = bg_path.name

            if self.last_generated_mode == "Combined" and self.current_pulse_audio is not None:
                pulse_path = target_path.with_name(f"{target_path.stem}_pulse.wav")
                audio_engine.save_wav(self.current_pulse_audio, self.current_fs, str(pulse_path))
                saved_files["pulse_wav"] = pulse_path.name

            metadata_path = target_path.with_suffix(".json")
            metadata = self._build_save_metadata(saved_files)
            metadata["generated_files"]["metadata_json"] = metadata_path.name
            session_logger.save_session_data(metadata_path, metadata)

            saved_summary = "\n".join(str(target_path.parent / name) for name in saved_files.values())
            QMessageBox.information(self, "Saved", f"Saved files:\n{saved_summary}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def _connect_dirty_state_tracking(self):
        for widget in self.findChildren(QLineEdit):
            widget.textChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QComboBox):
            widget.currentTextChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QSlider):
            widget.valueChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self.on_settings_changed)
        for widget in self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(self.on_settings_changed)

    def _on_enable_carrier_toggled(self, checked):
        if checked and not self.carrier_input.text():
            self.carrier_input.setText("14000")
        self._update_carrier_input_state()

    def _update_carrier_input_state(self):
        self.carrier_input.setEnabled(self.enable_carrier_checkbox.isChecked())

    def on_settings_changed(self, *_):
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(False)
        if hasattr(self, "stop_wav_btn"):
            self.stop_wav_btn.setEnabled(False)
        if hasattr(self, "save_btn"):
            self.save_btn.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BasicMaskGUI()
    window.show()
    sys.exit(app.exec())
