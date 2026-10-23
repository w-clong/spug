import os, sys, json, traceback
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
os.makedirs(os.environ['SPUG_DATA_DIR'], exist_ok=True)
import django
django.setup()
from django.core.management import call_command
call_command('migrate', verbosity=0, interactive=False)

from apps.account.models import User
from apps.host.models import Host
from apps.ops.kernel.facts_runner import refresh
from apps.ops.kernel import facts as fk

u = User.objects.create(username='d', nickname='d', password_hash='x', is_supper=True)
for ip, usr, pwd in (('10.0.0.77','root','1'), ('10.0.0.11','root','1'), ('10.0.0.128','wcl','123456')):
    h = Host.objects.create(name=ip, hostname=ip, username=usr, password=pwd, port=22, created_by=u)
    print('===', ip)
    try:
        r = refresh([h], on_event=lambda hid,k,m: print('   event', k, m))
        print('   result keys:', list(r.keys()))
        print('   os_family:', r.get(h.id, {}).get('os_family'), 'version:', r.get(h.id, {}).get('os_version'))
        print('   raw facts keys:', sorted(r.get(h.id, {}).keys()))
    except Exception:
        traceback.print_exc()
