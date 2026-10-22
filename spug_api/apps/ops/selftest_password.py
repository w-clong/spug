# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""主机密码认证 API 自检（会连接一台真实测试机，需按需修改地址/账号）。"""
import json
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

from apps.account.models import User  # noqa: E402
from apps.host.models import Group, Host  # noqa: E402

TOKEN = 'b' * 32
HOST = os.environ.get('SPUG_TEST_HOST', '10.0.0.35')
USER = os.environ.get('SPUG_TEST_USER', 'wcl')
PASSWORD = os.environ.get('SPUG_TEST_PASSWORD', '123456')


def main():
    user = User.objects.filter(username='pwd-tester').first()
    if user is None:
        user = User.objects.create(username='pwd-tester', nickname='pwd', password_hash='x', is_supper=True)
    user.access_token = TOKEN
    user.token_expired = int(time.time()) + 3600
    user.last_ip = '127.0.0.1'
    user.save()
    group, _ = Group.objects.get_or_create(name='pwd-test-group')
    Host.objects.filter(name='pwd-test-host').delete()

    client = Client(HTTP_X_TOKEN=TOKEN, HTTP_X_REAL_IP='127.0.0.1')
    body = json.dumps({
        'name': 'pwd-test-host', 'hostname': HOST, 'username': USER, 'port': 22,
        'password': PASSWORD, 'use_password': True, 'group_ids': [group.id],
    })
    resp = client.post('/api/host/', data=body, content_type='application/json').json()
    assert resp.get('error') in (None, ''), resp
    host = Host.objects.get(name='pwd-test-host')
    assert host.password == PASSWORD and not host.pkey, (host.password, host.pkey)
    print('create with password ok:', host.id, 'has_password=', host.to_view()['has_password'])

    # 编辑时不传密码，应保留原密码
    body = json.dumps({
        'id': host.id, 'name': 'pwd-test-host', 'hostname': HOST, 'username': USER,
        'port': 22, 'use_password': True, 'group_ids': [group.id], 'desc': 'edited',
    })
    resp = client.post('/api/host/', data=body, content_type='application/json').json()
    assert resp.get('error') in (None, ''), resp
    host.refresh_from_db()
    assert host.password == PASSWORD
    print('update keeps password ok:', host.desc)

    host.delete()
    group.delete()
    print('password auth selftest passed')


if __name__ == '__main__':
    main()
