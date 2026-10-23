import os, sys, time
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
os.environ['SPUG_FRONTEND_DIR'] = r'C:\Users\wcl\Downloads\spug\spug_web\build'
import django; django.setup()
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
import apps.deploy.views as V

# 取 auth 装饰器包装前的原函数
raw = V.do_upload.__wrapped__

class Req:
    def __init__(self, did, content=b'PK\x03\x04test'):
        self.FILES = {'file': SimpleUploadedFile('pkg.zip', content, content_type='application/zip')}
        self.POST = {'deploy_id': did}

d = os.path.join(settings.REPOS_DIR, '1')
print('1st:', raw(Req('1')).content.decode())
for i in range(12):
    raw(Req('1', b'PK' + bytes([i])))
    time.sleep(1.05)
files = sorted(os.listdir(d))
print('total after 13 uploads:', len(files))
print(files)
