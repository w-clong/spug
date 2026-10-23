import os, sys, json
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django
django.setup()
from apps.ops.models import HostFact
from apps.ops.views import FactView, _to_bool
from libs import JsonParser, Argument

# 复刻 FactView.get 的解析与组装逻辑
class Req:
    GET = {'with_meta': '1'}
form, error = JsonParser(
    Argument('host_id', type=int, required=False),
    Argument('with_meta', default=False, handler=_to_bool),
).parse(Req.GET)
print('parse error:', error, 'with_meta =', repr(form.with_meta), type(form.with_meta))

result = {}
for item in HostFact.objects.all():
    entry = result.setdefault(item.host_id, {} if not form.with_meta else {'facts': {}, 'updated_at': None})
    if form.with_meta:
        entry['facts'][item.fact_key] = json.loads(item.fact_value)
        updated = item.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        if not entry['updated_at'] or updated > entry['updated_at']:
            entry['updated_at'] = updated
print('host ids in result:', list(result.keys()))
for hid, e in result.items():
    print(' host', hid, 'facts keys', len(e.get('facts', {})), 'updated', e.get('updated_at'))
    print('  os_family=', e.get('facts', {}).get('os_family'), 'os_version=', e.get('facts', {}).get('os_version'))
