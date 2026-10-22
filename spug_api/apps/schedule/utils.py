# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from libs.utils import human_datetime
from libs.spug import Notification
import json


def send_fail_notify(task, msg=None):
    rst_notify = json.loads(task.rst_notify)
    mode = rst_notify.get('mode')
    url = rst_notify.get('value')
    if mode != '0' and url:
        _do_notify(task, mode, url, msg)


def send_summary_notify(task, title, content):
    """状态模块/巡检任务的汇总通知：仅在存在变更或失败时调用。"""
    rst_notify = json.loads(task.rst_notify or '{}')
    mode = rst_notify.get('mode')
    url = rst_notify.get('value')
    if mode == '0' or not url:
        return
    lines = content.splitlines()
    if mode == '1':
        texts = [f'## <font color="#1296db">{title}</font>'] + lines + ['> 来自 Spug 运维平台']
        Notification.handle_request(url, {
            'msgtype': 'markdown',
            'markdown': {'title': title, 'text': '\n\n'.join(texts)},
            'at': {'isAtAll': False},
        }, 'dd')
    elif mode == '2':
        Notification.handle_request(url, {
            'task_id': task.id,
            'task_name': task.name,
            'task_type': task.type,
            'message': content,
            'created_at': human_datetime(),
        })
    elif mode == '3':
        texts = [f'## {title}'] + lines + ['> 来自 Spug 运维平台']
        Notification.handle_request(url, {
            'msgtype': 'markdown',
            'markdown': {'content': '\n'.join(texts)},
        }, 'wx')
    elif mode == '4':
        post_lines = [[{'tag': 'text', 'text': line}] for line in lines]
        Notification.handle_request(url, {
            'msg_type': 'post',
            'content': {'post': {'zh_cn': {'title': title, 'content': post_lines}}},
        }, 'fs')


def _do_notify(task, mode, url, msg):
    if mode == '1':
        texts = [
            '## <font color="#f90202">任务执行失败通知</font> ## ',
            f'**任务名称：** {task.name} ',
            f'**任务类型：** {task.type} ',
            f'**描述信息：** {msg or "请在任务计划执行历史中查看详情"} ',
            f'**发生时间：** {human_datetime()} ',
            '> 来自 Spug运维平台'
        ]
        data = {
            'msgtype': 'markdown',
            'markdown': {
                'title': '任务执行失败通知',
                'text': '\n\n'.join(texts)
            },
            'at': {
                'isAtAll': True
            }
        }
        Notification.handle_request(url, data, 'dd')
    elif mode == '2':
        data = {
            'task_id': task.id,
            'task_name': task.name,
            'task_type': task.type,
            'message': msg or '请在任务计划执行历史中查看详情',
            'created_at': human_datetime()
        }
        Notification.handle_request(url, data)
    elif mode == '3':
        texts = [
            '## <font color="warning">任务执行失败通知</font>',
            f'任务名称： {task.name}',
            f'任务类型： {task.type}',
            f'描述信息： {msg or "请在任务计划执行历史中查看详情"}',
            f'发生时间： {human_datetime()}',
            '> 来自 Spug运维平台'
        ]
        data = {
            'msgtype': 'markdown',
            'markdown': {
                'content': '\n'.join(texts)
            }
        }
        Notification.handle_request(url, data, 'wx')
    elif mode == '4':
        data = {
            'msg_type': 'post',
            'content': {
                'post': {
                    'zh_cn': {
                        'title': '任务执行失败通知',
                        'content': [
                            [{'tag': 'text', 'text': f'任务名称： {task.name}'}],
                            [{'tag': 'text', 'text': f'任务类型： {task.type}'}],
                            [{'tag': 'text', 'text': f'描述信息： {msg or "请在任务计划执行历史中查看详情"}'}],
                            [{'tag': 'text', 'text': f'发生时间： {human_datetime()}'}],
                            [{'tag': 'at', 'user_id': 'all'}],
                        ]
                    }
                }
            }
        }
        Notification.handle_request(url, data, 'fs')
