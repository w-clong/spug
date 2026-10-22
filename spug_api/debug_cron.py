import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa

django.setup()

from apps.host.models import Host
from apps.ops.kernel.runner import StateRunner

host = Host.objects.get(name='e2e-10.0.0.35')
summary = StateRunner([host], 'crontab', {
    'command': '/bin/true', 'cron_name': 'spug-dbg', 'minute': '0', 'hour': '3',
}, record=False).run()
for item in summary.results:
    print('changed', item.changed, 'failed', item.failed)
    print('msg:', (item.msg or '')[:800])
    print('diff:', (item.diff or '')[:800])
