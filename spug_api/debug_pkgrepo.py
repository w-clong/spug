import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa

django.setup()

from apps.account.models import User
from apps.host.models import Host
from apps.pipeline.models import Pipeline
from apps.pipeline.utils import NodeExecutor
from libs.memredis import get_redis_connection


class RecordingHelper:
    def __init__(self):
        self.logs = []

    def send(self, key, data=None, **kw):
        self.logs.append((key, data))

    def send_info(self, key, msg, *a, **kw):
        self.logs.append((key, msg))

    def send_success(self, key, msg, *a, **kw):
        self.logs.append((key, msg))

    def send_error(self, key, msg, *a, **kw):
        self.logs.append((key, msg))

    def send_status(self, key, status):
        self.logs.append((key, status))

    def clear(self):
        pass


user = User.objects.filter(username='pkgrepo-tester').first() or User.objects.create(
    username='pkgrepo-tester', nickname='pkgrepo', password_hash='x', is_supper=True)
host, _ = Host.objects.update_or_create(
    name='pkgrepo-rocky',
    defaults=dict(hostname='10.0.0.34', port=22, username='root', password='1',
                  pkey=None, created_by=user))
Pipeline.objects.filter(name='pkgrepo-dbg').delete()
pipe = Pipeline.objects.create(name='pkgrepo-dbg', created_by=user, nodes='[]')

node = {
    'id': 9100, 'module': 'artifact', 'name': '制品安装', 'condition': 'success',
    'targets': [host.id], 'source_type': 'rpm',
    'base_url': 'http://192.168.10.240:4000/rpm', 'repo_name': 'myrepo',
    'package': 'accountsservice', 'version': '', 'dest_path': '',
    'overwrite': False, 'auth_type': 'none', 'dry_run': False,
}
ex = NodeExecutor(get_redis_connection(), 'dbg-token', [node], pipeline_id=pipe.id)
ex.helper = RecordingHelper()
ex.run()
print('states:', ex.states)
for k, v in ex.helper.logs:
    print('LOG', k, repr(v)[:600])
pipe.delete()
