# /utils/config_manager.py

import json
import os

CONFIG_FILE = "config.json"

def save_config(video_name, audio_name):
    config = {
        "video_device_name": video_name,
        "audio_device_name": audio_name
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return None