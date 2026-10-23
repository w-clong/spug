import os, sys, json
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django
django.setup()
from apps.ops.models import HostFact
from libs.utils import json_response
from libs import JsonParser, Argument
from apps.ops.views import _to_bool

form, error = JsonParser(Argument('with_meta', default=False, handler=_to_bool)).parse({'with_meta': '1'})
result = {}
for item in HostFact.objects.all():
    entry = result.setdefault(item.host_id, {'facts': {}, 'updated_at': None})
    entry['facts'][item.fact_key] = json.loads(item.fact_value)
    updated = item.updated_at.strftime('%Y-%m-%d %H:%M:%S')
    if not entry['updated_at'] or updated > entry['updated_at']:
        entry['updated_at'] = updated
resp = json_response(result)
raw = resp.content.decode()
print('RAW JSON (first 300):', raw[:300])
data = json.loads(raw)['data']
print('data keys:', list(data.keys()), [type(k).__name__ for k in data.keys()])
