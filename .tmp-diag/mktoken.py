import os, sys, time
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django; django.setup()
from apps.account.models import User
u = User.objects.get(username='d')
u.access_token = 'b'*32; u.token_expired = time.time()+7200; u.is_supper=True
u.save()
print('ok')
