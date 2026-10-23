# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""纯 Python 构建（Windows 无 bash）自检：GitPython 归档 + tarfile 打包。"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa

django.setup()

import apps.repository.utils as ru  # noqa


class FakeHelper:
    def __init__(self):
        self.logs = []

    def send_info(self, key, msg, **kw):
        self.logs.append(('info', msg))

    def send_success(self, key, msg, **kw):
        self.logs.append(('success', msg))

    def send_warn(self, key, msg, **kw):
        self.logs.append(('warn', msg))

    def send_error(self, key, msg, **kw):
        self.logs.append(('error', msg))

    def parse_filter_rule(self, data, env=None):
        # 与官方行为保持一致：返回需要包含/排除的相对路径列表
        return [x.strip().lstrip('/') for x in data.splitlines() if x.strip()]

    def set_cross_env(self, key, env):
        pass


def make_git_repo(workdir):
    subprocess.run(['git', 'init', '-q'], cwd=workdir, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=workdir, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=workdir, check=True)
    (Path(workdir) / 'a.txt').write_text('hello a')
    (Path(workdir) / 'b.log').write_text('log data')
    subprocess.run(['git', 'add', '.'], cwd=workdir, check=True)
    subprocess.run(['git', 'commit', '-qm', 'init'], cwd=workdir, check=True)


class FakeExtend:
    dst_dir = '/tmp/x'
    hook_pre_server = ''
    hook_post_server = ''
    git_repo = 'http://x'
    filter_rule = '{"type": "exclude", "data": "b.log"}'


class FakeDeploy:
    extend_obj = FakeExtend()


class FakeRepo:
    deploy = FakeDeploy()
    deploy_id = 'test-deploy'
    spug_version = 'build1'


def main():
    workdir = os.path.join(os.getcwd(), '.tmp-build-test')
    os.makedirs(workdir, exist_ok=True)
    # _build_python 使用 REPOS_DIR/<deploy_id> 作为仓库目录
    repo_dir = os.path.join(workdir, FakeRepo.deploy_id)
    os.makedirs(repo_dir, exist_ok=True)
    make_git_repo(repo_dir)

    rep = FakeRepo()
    helper = FakeHelper()

    # 让 fetch_repo 不联网，直接指向本地仓库
    ru.REPOS_DIR = workdir
    original_fetch = ru.fetch_repo
    ru.fetch_repo = lambda *a, **kw: None
    original_BUILD = ru.BUILD_DIR
    ru.BUILD_DIR = workdir
    try:
        # 1) exclude 模式：排除 b.log
        ru._build_python(rep, helper, {'SPUG_GIT_TAG': 'HEAD'})
        tar_file = os.path.join(workdir, 'build1.tar.gz')
        with tarfile.open(tar_file) as tf:
            names = tf.getnames()
        print('exclude mode ->', names)
        assert 'build1/a.txt' in names and 'build1/b.log' not in names, names

        # 2) include 模式：只保留 a.txt
        FakeExtend.filter_rule = '{"type": "include", "data": "a.txt"}'
        ru._build_python(rep, helper, {'SPUG_GIT_TAG': 'HEAD'})
        with tarfile.open(tar_file) as tf:
            names = tf.getnames()
        print('include mode ->', names)
        assert 'build1/a.txt' in names and 'build1/b.log' not in names, names
        assert not any(m for m in names if m.endswith('.log')), names
    finally:
        ru.fetch_repo = original_fetch
        ru.BUILD_DIR = original_BUILD
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    print('python build selftest passed')


if __name__ == '__main__':
    main()
