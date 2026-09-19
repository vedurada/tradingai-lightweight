import json, os
BASE = '/opt/tradingai_new'
def load_json(path):
    with open(os.path.join(BASE, path)) as f: return json.load(f)
instruments = load_json('config/instruments.json')
settings = load_json('config/settings.json')
