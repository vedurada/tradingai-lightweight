import json, os
BASE = '/opt/tradingai_new'
def load_json(path):
    with open(os.path.join(BASE, path)) as f: return json.load(f)
_instruments_data = load_json('config/instruments.json')
instruments = _instruments_data['instruments'] if isinstance(_instruments_data, dict) and 'instruments' in _instruments_data else _instruments_data
settings = load_json('config/settings.json')
