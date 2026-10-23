import os
import sys
import time
import json

sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
os.environ['SPUG_FRONTEND_DIR'] = r'C:\Users\wcl\Downloads\spug\spug_web\build'
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from apps.deploy.views import do_upload  # noqa: E402


class FakeRequest:
    def __init__(self, deploy_id, content=b'PK\x03\x04test'):
        self.FILES = {'file': SimpleUploadedFile('pkg.zip', content, content_type='application/zip')}
        self.POST = {'deploy_id': deploy_id}


d = os.path.join(settings.REPOS_DIR, '1')
print('repos dir:', d)

r = do_upload(FakeRequest('1'))
print('1st upload:', r.content.decode())

for i in range(12):
    r = do_upload(FakeRequest('1', b'PK' + bytes([i])))
    time.sleep(1.05)

files = sorted(os.listdir(d))
print('total files after 13 uploads:', len(files))
print('files:', files)
