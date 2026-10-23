import os, sys, json, time
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django
django.setup()
from django.test import Client
from apps.account.models import User
from apps.host.models import Host
from apps.ops.models import HostFact

u = User.objects.filter(username='d').first()
u.is_supper = True
u.access_token = 'a'*32
u.token_expired = time.time() + 3600
u.save()
h = Host.objects.filter(hostname='10.0.0.77').first()
print('host', h.id, 'facts rows', HostFact.objects.filter(host_id=h.id).count())
print('sample fact:', list(HostFact.objects.filter(host_id=h.id).values_list('fact_key','fact_value')[:3]))

c = Client()
r = c.get('/ops/facts/', {'with_meta': 1}, HTTP_X_TOKEN='a'*32)
print('status', r.status_code)
print('body', r.content.decode()[:400])
r2 = c.get('/ops/facts/', {'with_meta': '1'}, HTTP_X_TOKEN='a'*32)
print('with string 1:', r2.content.decode()[:200])
