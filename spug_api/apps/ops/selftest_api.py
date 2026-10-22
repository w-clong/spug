# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""批量执行状态模块 API 自检（不连接真实主机）。"""
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
from apps.exec.models import ExecHistory  # noqa: E402
from apps.host.models import Host  # noqa: E402
from libs.memredis import get_redis_connection  # noqa: E402

TOKEN = 'a' * 32


def main():
    user = User.objects.filter(username='api-tester').first()
    if user is None:
        user = User.objects.create(username='api-tester', nickname='api-tester',
                                   password_hash='x', is_supper=True)
    user.access_token = TOKEN
    user.token_expired = int(time.time()) + 3600
    user.last_ip = '127.0.0.1'
    user.save()

    host = Host.objects.filter(name='api-host').first()
    if host is None:
        host = Host.objects.create(name='api-host', hostname='10.0.0.8', port=22,
                                   username='root', pkey='x', created_by=user)

    client = Client(HTTP_X_TOKEN=TOKEN, HTTP_X_REAL_IP='127.0.0.1', REMOTE_ADDR='127.0.0.1')
    body = json.dumps({
        'host_ids': [host.id], 'kind': 'state', 'module': 'file',
        'params': {'path': '/tmp/x', 'content': 'hello'}, 'dry_run': True,
    })
    resp = client.post('/api/exec/do/', data=body, content_type='application/json')
    data = resp.json()
    assert data.get('error') in (None, ''), data
    token = data['data']
    record = ExecHistory.objects.get(digest=token)
    assert record.kind == 'state' and record.module == 'file' and record.dry_run is True
    print('POST ok: task created', token)

    # 错误模块应被拒绝
    bad = json.dumps({'host_ids': [host.id], 'kind': 'state', 'module': 'nope'})
    resp = client.post('/api/exec/do/', data=bad, content_type='application/json')
    assert '不支持的状态模块' in resp.json().get('error', '')
    print('invalid module rejected')

    # PATCH 触发下发：消息进入 STATE_WORKER_KEY
    rds = get_redis_connection()
    rds.delete('spug:state:worker')
    resp = client.patch('/api/exec/do/', data=json.dumps({'token': token}),
                        content_type='application/json')
    assert resp.json().get('error') in (None, ''), resp.json()
    job = rds.lindex('spug:state:worker', 0)
    assert job, 'job not queued'
    payload = json.loads(job)
    assert payload['module'] == 'file' and payload['dry_run'] is True
    assert payload['params']['path'] == '/tmp/x'
    print('PATCH ok: job queued ->', payload['module'], payload['host_ids'])

    # ---- 新增 ops API ----
    resp = client.get('/api/ops/modules/')
    modules = resp.json()['data']
    assert 'pkg' in modules and 'service' in modules, modules.keys()
    print('modules ok:', ','.join(modules))

    resp = client.post('/api/ops/variables/',
                       data=json.dumps({'scope': 'host', 'target_id': host.id,
                                        'key': 'nginx_port', 'value': '8080'}),
                       content_type='application/json')
    assert resp.json()['error'] in (None, ''), resp.json()
    resp = client.get('/api/ops/variables/', {'scope': 'host', 'id': host.id})
    assert any(x['key'] == 'nginx_port' for x in resp.json()['data'])
    print('host variables ok')

    resp = client.post('/api/ops/templates/',
                       data=json.dumps({'name': 'nginx.conf', 'content': 'port {{ nginx_port }};'}),
                       content_type='application/json')
    template_id = resp.json()['data']
    resp = client.get('/api/ops/templates/', {'id': template_id})
    detail = resp.json()['data']
    assert detail['versions'] and detail['name'] == 'nginx.conf'
    print('template ok: id=%s version=%s' % (template_id, detail['versions'][0]['version']))

    resp = client.post('/api/ops/baselines/',
                       data=json.dumps({'name': 'web-base', 'nodes': [{'module': 'pkg'}]}),
                       content_type='application/json')
    assert resp.json()['error'] in (None, ''), resp.json()
    assert any(x['name'] == 'web-base' for x in client.get('/api/ops/baselines/').json()['data'])
    print('baseline ok')

    resp = client.get('/api/ops/changes/', {'page': 1, 'page_size': 10})
    assert 'total' in resp.json()['data']
    print('changelog ok: total=%s' % resp.json()['data']['total'])

    resp = client.get('/api/ops/facts/', {'host_id': host.id})
    assert isinstance(resp.json()['data'], dict)
    print('facts api ok')

    # 主机 JSON 备份导入/导出
    Host.objects.filter(name='json-import-host').delete()
    resp = client.get('/api/host/export/json/')
    assert resp['Content-Type'].startswith('application/json')
    assert isinstance(json.loads(resp.content), list)
    resp = client.post('/api/host/import/json/', data=json.dumps([
        {'name': 'json-import-host', 'hostname': '10.0.0.99', 'port': 22,
         'username': 'root', 'groups': ['json-import-group']},
    ]), content_type='application/json')
    assert resp.json()['data']['created'] == 1, resp.json()
    assert Host.objects.filter(name='json-import-host').exists()
    Host.objects.filter(name='json-import-host').delete()
    print('host json backup ok')

    # 变量上下文 API
    from apps.pipeline.models import Pipeline
    Pipeline.objects.filter(name='ctx-api-pipe').delete()
    pipe = Pipeline.objects.create(name='ctx-api-pipe', created_by=user, nodes=json.dumps([
        {'id': 1, 'module': 'parameter', 'static_params': [['api_var', 'v1']]},
        {'id': 2, 'module': 'ssh_exec', 'targets': [host.id]},
    ]))
    resp = client.get('/api/ops/context/', {'pipeline_id': pipe.id, 'host_id': host.id})
    data = resp.json()['data']
    assert any(x['name'] == 'api_var' and x['value'] == 'v1' for x in data['variables']), data
    resp = client.get('/api/ops/pipeline-hosts/', {'pipeline_id': pipe.id})
    assert any(x['id'] == host.id for x in resp.json()['data'])
    pipe.delete()
    print('context api ok')

    # 定时任务：创建状态模块任务
    from apps.schedule.models import Task
    Task.objects.filter(name='api-state-task').delete()
    resp = client.post('/api/schedule/', data=json.dumps({
        'type': '巡检', 'name': 'api-state-task', 'kind': 'state', 'module': 'directory',
        'command': json.dumps({'path': '/opt/app'}), 'targets': [host.id],
        'trigger': 'interval', 'trigger_args': '3600', 'rst_notify': {'mode': '0'},
        'dry_run': True,
    }), content_type='application/json')
    assert resp.json()['error'] in (None, ''), resp.json()
    task = Task.objects.get(name='api-state-task')
    assert task.kind == 'state' and task.module == 'directory' and task.dry_run is True
    print('schedule state task ok: id=%s' % task.id)

    # 动态分组 API
    from apps.host.models import Group
    Group.objects.filter(name='api-dyn-group').delete()
    group = Group.objects.create(name='api-dyn-group')
    resp = client.post('/api/ops/dynamic-groups/', data=json.dumps({
        'group_id': group.id, 'name': 'api-dyn-rule', 'enabled': True, 'match_all': True,
        'rules': [{'key': 'os_family', 'op': 'eq', 'value': 'Debian'}],
    }), content_type='application/json')
    assert resp.json()['error'] in (None, ''), resp.json()
    rules = client.get('/api/ops/dynamic-groups/').json()['data']
    assert any(x['group_id'] == group.id for x in rules)
    group.refresh_from_db()
    assert group.is_dynamic is True
    print('dynamic group api ok')

    # 清理
    group.delete()


if __name__ == '__main__':
    main()
