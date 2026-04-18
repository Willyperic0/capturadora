import cv2
import sounddevice as sd

def list_video_devices():
    print("--- Buscando Dispositivos de Video (HDMI/Webcams) ---")
    index = 0
    arr = []
    while index < 5: # Probamos los primeros 5 índices
        cap = cv2.VideoCapture(index)
        if cap.read()[0]:
            print(f"ID {index}: Dispositivo detectado y funcionando.")
            arr.append(index)
            cap.release()
        index += 1
    return arr

def list_audio_devices():
    print("\n--- Buscando Entradas de Audio (Jack/Micrófonos) ---")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            print(f"ID {i}: {dev['name']} (Canales de entrada: {dev['max_input_channels']})")

if __name__ == "__main__":
    list_video_devices()
    list_audio_devices()