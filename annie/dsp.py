"""
Annie Audio DSP — Audio Enhancement & AGC (Automatic Gain Control)
Inspired by WebRTC AGC used in Notion AI & modern speech recognition.
Boosts quiet whispers, normalizes dynamic range, cuts low-frequency rumble, and prevents clipping.
"""
import numpy as np

class AudioEnhancer:
    """
    Real-time audio pre-processing and dynamic gain control.
    Makes the microphone sensitive to quiet voices and distant sounds
    while protecting against loud bursts and clipping.
    """
    def __init__(self, target_level=9000.0, max_gain=12.0, min_gain=1.0, noise_floor=12.0):
        self.target_level = target_level      # Target RMS level for speech (~ -14 dBFS)
        self.max_gain = max_gain              # Maximum boost factor for quiet whispers / distant lectures
        self.min_gain = min_gain              # Minimum gain for normal/loud sounds
        self.noise_floor = noise_floor        # Minimum threshold to catch faint whisper
        self.current_gain = 3.0               # Initial baseline gain
        self.alpha_attack = 0.30              # Fast attenuation on loud bursts
        self.alpha_decay = 0.05               # Smooth amplification on quiet speech
        self._prev_sample = 0.0               # High-pass filter state
        self._prev_filtered = 0.0

    def process(self, pcm_bytes) -> bytes:
        """
        Process raw 16-bit PCM mono audio bytes:
        1. High-pass filter (remove DC offset & sub-80Hz rumble)
        2. Dynamic AGC (boost quiet audio, smooth transitions)
        3. Soft-knee limiter (prevent distortion/clipping)
        """
        if pcm_bytes is None or len(pcm_bytes) == 0:
            return pcm_bytes

        if isinstance(pcm_bytes, np.ndarray):
            pcm_bytes = pcm_bytes.tobytes()

        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if len(samples) == 0:
                return pcm_bytes

            # 1. High-Pass Filter (DC-blocker / 80Hz rumble cutoff)
            # y[n] = x[n] - x[n-1] + 0.95 * y[n-1]
            hp_samples = np.empty_like(samples)
            prev = self._prev_sample
            filtered = self._prev_filtered
            for i in range(len(samples)):
                curr = samples[i]
                filtered = curr - prev + 0.95 * filtered
                hp_samples[i] = filtered
                prev = curr
            self._prev_sample = prev
            self._prev_filtered = filtered

            # 2. Calculate RMS energy
            rms = np.sqrt(np.mean(hp_samples ** 2) + 1e-6)

            # 3. Dynamic AGC adaptation
            if rms > self.noise_floor:
                # Active speech detected
                desired_gain = self.target_level / rms
                desired_gain = max(self.min_gain, min(self.max_gain, desired_gain))

                if desired_gain < self.current_gain:
                    # Attack (got louder) -> lower gain quickly
                    self.current_gain += self.alpha_attack * (desired_gain - self.current_gain)
                else:
                    # Decay (got quieter) -> raise gain smoothly
                    self.current_gain += self.alpha_decay * (desired_gain - self.current_gain)
            else:
                # Ambient silence -> slowly return to nominal gain
                self.current_gain += 0.02 * (2.0 - self.current_gain)

            # 4. Apply Gain
            boosted = hp_samples * self.current_gain

            # 5. Soft Limiting (tanh saturation if exceeding safe peak)
            peak = np.max(np.abs(boosted))
            if peak > 30000.0:
                boosted = np.tanh(boosted / 32767.0) * 32767.0
            else:
                boosted = np.clip(boosted, -32768.0, 32767.0)

            return boosted.astype(np.int16).tobytes()

        except Exception:
            return pcm_bytes
