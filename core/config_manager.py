# /core/config_manager.py

import json
import os

CONFIG_FILE = "config.json"

def save_device_config(device_name, delay_ms):
    config = load_all_config()
    config[device_name] = delay_ms
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def load_all_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}