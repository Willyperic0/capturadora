# /core/audio_sync.py
import re
import sounddevice as sd
from pygrabber.dshow_graph import FilterGraph

def extract_hw_id(name):
    """
    Extrae VID y PID del nombre del dispositivo usando regex.
    Busca patrones como VID_XXXX&PID_YYYY
    """
    match = re.search(r'VID_([0-9A-F]{4})&PID_([0-9A-F]{4})', name.upper())
    if match:
        return match.group(1), match.group(2)
    return None, None

def find_audio_by_hw_id(video_index):
    """
    Encuentra el dispositivo de audio correspondiente al dispositivo de video
    basado en Hardware ID (VID/PID) o matching inteligente por nombre.
    """
    graph = FilterGraph()
    video_devices = graph.get_input_devices()
    
    if video_index < 0 or video_index >= len(video_devices):
        return 0
    
    v_name = video_devices[video_index]
    v_vid, v_pid = extract_hw_id(v_name)
    
    if not v_vid:
        # Matching inteligente por nombre
        devices = sd.query_devices()
        v_upper = v_name.upper()
        best_match = None
        best_score = 0
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                a_upper = dev['name'].upper()
                score = 0
                # Si contiene "USB" y video también, +10
                if "USB" in v_upper and "USB" in a_upper:
                    score += 10
                # Si contiene "DIGITAL" y video contiene "USB", +5
                if "DIGITAL" in a_upper and "USB" in v_upper:
                    score += 5
                # Si contiene palabras del video
                words = v_upper.split()
                for word in words:
                    if len(word) > 3 and word in a_upper:  # palabras de al menos 4 letras
                        score += 1
                if score > best_score:
                    best_score = score
                    best_match = i
        if best_match is not None:
            return best_match
        return 0
    
    # Buscar audio con el mismo VID/PID
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            a_vid, a_pid = extract_hw_id(dev['name'])
            if a_vid == v_vid and a_pid == v_pid:
                return i
    
    # Si no encuentra exacto, buscar por VID solo (mismo fabricante)
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            a_vid, a_pid = extract_hw_id(dev['name'])
            if a_vid == v_vid:
                return i
    
    # Fallback final: primer dispositivo USB
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0 and "USB" in dev['name'].upper():
            return i
    
    return 0