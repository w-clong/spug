import os, sys, io, json
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
os.environ['SPUG_FRONTEND_DIR'] = r'C:\Users\wcl\Downloads\spug\spug_web\build'
import django; django.setup()
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.account.models import User
from django.conf import settings

u = User.objects.first()
u.access_token='d'*32
import time; u.token_expired=time.time()+7200
u.save()

c = Client()
f = SimpleUploadedFile('pkg.zip', b'PK\x03\x04test', content_type='application/zip')
r = c.post('/deploy/request/upload/', {'deploy_id': '1', 'file': f}, HTTP_X_TOKEN='d'*32, HTTP_USER_AGENT='Mozilla/5.0')
print('status', r.status_code)
print('body:', r.content.decode()[:200])
d = os.path.join(settings.REPOS_DIR, '1')
print('dir exists:', os.path.isdir(d), 'files:', os.listdir(d) if os.path.isdir(d) else None)
# 再传 12 次验证只保留 10 个
for i in range(12):
    f = SimpleUploadedFile('x.zip', b'PK', content_type='application/zip')
    c.post('/deploy/request/upload/', {'deploy_id': '1', 'file': f}, HTTP_X_TOKEN='d'*32, HTTP_USER_AGENT='Mozilla/5.0')
    time.sleep(1.05)
print('after 13 uploads, count:', len(os.listdir(d)))
