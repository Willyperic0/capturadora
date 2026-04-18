# /core/audio_engine.py
import sounddevice as sd

class AudioEngine:
    def __init__(self, partial_name):
        self.device_index = self._find_device_by_name(partial_name)
        self.stream = None

    def _find_device_by_name(self, name):
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if name in dev['name'] and dev['max_input_channels'] > 0:
                return i
        return 0

    def start_bridge(self):
        # Callback para pasar audio de entrada a salida (audífonos)
        def callback(indata, outdata, frames, time, status):
            outdata[:] = indata 

        self.stream = sd.Stream(device=(self.device_index, None), callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream: self.stream.stop()