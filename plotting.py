# amg_app/plotting.py
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QDialog, QVBoxLayout


def _max_pool_for_plot(values, target_points):
    if values is None:
        return None
    if target_points <= 0 or len(values) <= target_points:
        return values

    edges = np.linspace(0, len(values), target_points + 1, dtype=int)
    pooled = np.empty(target_points, dtype=float)
    for i in range(target_points):
        start = edges[i]
        end = max(edges[i + 1], start + 1)
        pooled[i] = np.max(values[start:end])
    return pooled


def _preview_signal(audio):
    if getattr(audio, "ndim", 1) == 1:
        return audio
    return np.mean(audio, axis=1)


class PlotPopupDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 700)

        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        if parent is not None:
            parent_geom = parent.geometry()
            dialog_geom = self.frameGeometry()
            dialog_geom.moveCenter(parent_geom.center())
            self.move(dialog_geom.topLeft())

    def render_time_plot(self, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf):
        ax = self.figure.add_subplot(111)
        update_time_plot(ax, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def render_right_plot(self, current_audio, current_fs, show_spectrogram, show_fft, prf):
        update_right_plot(self.figure, current_audio, current_fs, show_spectrogram, show_fft, prf)
        self.figure.tight_layout()
        self.canvas.draw_idle()


def open_time_plot_popup(parent, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf=1000.0):
    dialog = PlotPopupDialog(parent, "Time Plot")
    dialog.render_time_plot(current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def open_right_plot_popup(parent, current_audio, current_fs, show_spectrogram, show_fft, prf=None):
    dialog = PlotPopupDialog(parent, "Spectral Plot")
    dialog.render_right_plot(current_audio, current_fs, show_spectrogram, show_fft, prf)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog

def update_time_plot(ax, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf=1000.0):
    if zoom_view:
        if prf > 0:
            zoom_ms = 3 * (1000.0 / float(prf))
        else:
            zoom_ms = 10
        title = f"PRF Envelope Zoom (First 3 PRIs) – {zoom_ms:.3f} ms – Ramp = {float(ramp_len_text) / 1000:.6f} s" if ramp_len_text else f"PRF Envelope Zoom (First 3 PRIs) – {zoom_ms:.3f} ms"
    else:
        zoom_ms = len(current_audio) / current_fs * 1000
        title = f"Full Burst View – Ramp = {float(ramp_len_text) / 1000:.6f} s" if ramp_len_text else "Full Burst View"

    zoom_samples = int(zoom_ms * current_fs / 1000)
    zoom_samples = min(zoom_samples, len(current_audio))

    t_zoom = current_time[:zoom_samples] * 1000
    wave_zoom = _preview_signal(current_audio[:zoom_samples])  # Plot stereo preview as mono

    # Upsample plot resolution for smoother display on same x-span
    if zoom_samples > 2:
        upsample_factor = 10
        interp_points = min(int(zoom_samples * upsample_factor), 20000)
        t_interp = np.linspace(t_zoom[0], t_zoom[-1], interp_points)
        gate_source = current_gate[:zoom_samples] if current_gate is not None else None
        bg_source = current_bg_audio[:zoom_samples] if current_bg_audio is not None else None

        wave_zoom = np.interp(t_interp, t_zoom, wave_zoom)
        if gate_source is not None:
            if zoom_view:
                gate_zoom = np.interp(t_interp, t_zoom, gate_source)
            else:
                gate_zoom = _max_pool_for_plot(gate_source, interp_points)
        if bg_source is not None:
            bg_zoom = np.interp(t_interp, t_zoom, bg_source)

        t_zoom = t_interp
    else:
        if current_gate is not None:
            gate_zoom = current_gate[:zoom_samples]
        if current_bg_audio is not None:
            bg_zoom = current_bg_audio[:zoom_samples]

    # UPDATED: Always use single overlaid plot (no separate subplots)
    ax.clear()
    if current_gate is not None or current_bg_audio is None:
        ax.plot(t_zoom, wave_zoom, color='C0', lw=1.2, label='Waveform + noise')
    if current_gate is not None:
        ax.plot(t_zoom, gate_zoom * 0.5, color='C3', lw=2.5, alpha=0.8, label='Envelope (gate)')
    if current_bg_audio is not None:
        ax.plot(t_zoom, bg_zoom, color='C2', lw=1.2, alpha=0.7, label='Background')
    ax.set_title(title, fontsize=8)  # Smaller font
    ax.set_xlabel("Time (ms)", fontsize=6)
    ax.set_ylabel("Amplitude", fontsize=6)
    ax.set_ylim(-1.1, 1.1)
    ax.set_xlim(0, zoom_ms)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=6)  # Smaller legend
    ax.tick_params(labelsize=6)  # Smaller tick labels
    ax.text(0.01, 0.02, "Visual display only — waveform may appear aliased at high carrier frequencies",
            transform=ax.transAxes, fontsize=10, color='gray', alpha=0.7, va='bottom')

def update_right_plot(fig, current_audio, current_fs, show_spectrogram, show_fft, prf=None):
    signal = _preview_signal(current_audio)
    fs = current_fs

    fig.clear()
    if show_spectrogram:
        ax = fig.add_subplot(111)
        ax.specgram(signal, Fs=fs, cmap='viridis', NFFT=1024, noverlap=512)
        ax.set_title("Spectrogram Preview", fontsize=8)
        ax.set_xlabel("Time (s)", fontsize=6)
        ax.set_ylabel("Frequency (Hz)", fontsize=6)
        ax.tick_params(labelsize=6)
    elif show_fft:
        n = len(signal)
        fft = np.fft.fft(signal)
        freqs = np.fft.fftfreq(n, 1/fs)
        magnitude = np.abs(fft[:n//2]) / (n / 2)
        magnitude_db = 20 * np.log10(magnitude + 1e-10)

        # First non-zero frequency bin as log x-min
        freq_resolution = fs / n
        x_min = freq_resolution

        ax1 = fig.add_subplot(211)
        ax1.plot(freqs[:n//2], magnitude_db)
        ax1.set_title("Spectral Preview — 0 to 9000 Hz", fontsize=7)
        ax1.set_xlabel("Frequency (Hz)", fontsize=6)
        ax1.set_ylabel("Magnitude (dBFS)", fontsize=6)
        ax1.set_xscale('log')
        ax1.set_xlim(x_min, 9000)
        ax1.set_ylim(-80, 0)
        ax1.grid(True, which='both', alpha=0.4)
        ax1.grid(True, which='minor', alpha=0.2)
        ax1.tick_params(labelsize=6)

        ax2 = fig.add_subplot(212)
        ax2.plot(freqs[:n//2], magnitude_db)
        ax2.set_title("Spectral Preview — 0 to 16 kHz", fontsize=7)
        ax2.set_xlabel("Frequency (Hz)", fontsize=6)
        ax2.set_ylabel("Magnitude (dBFS)", fontsize=6)
        ax2.set_xscale('log')
        ax2.set_xlim(x_min, 16000)
        ax2.set_ylim(-80, 0)
        ax2.grid(True, which='both', alpha=0.4)
        ax2.grid(True, which='minor', alpha=0.2)
        ax2.tick_params(labelsize=6)
