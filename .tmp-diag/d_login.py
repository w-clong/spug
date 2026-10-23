import os, sys, json, time
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django; django.setup()
from django.test import Client
from apps.account.models import User, History
from django.contrib.auth.hashers import make_password

u = User.objects.first()
u.password_hash = make_password('test123')
u.is_active = True
u.is_supper = True
u.save()
History.objects.all().delete()

c = Client()
r = c.post('/account/login/', json.dumps({'username': u.username, 'password': 'test123'}),
           content_type='application/json', HTTP_USER_AGENT='Mozilla/5.0')
print('login status', r.status_code)
print('body:', r.content.decode()[:200])
print('history rows:', list(History.objects.values_list('username','type','is_success')))
