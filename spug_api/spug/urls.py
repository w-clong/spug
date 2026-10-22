"""spug URL Configuration
# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve as static_serve


def frontend_view(request, path):
    """
    前端 SPA 托管：命中编译产物中的真实文件则返回文件，否则回退 index.html。
    与官方 Nginx 配置的 `try_files $uri /index.html` 行为一致。
    """
    doc_root = settings.FRONTEND_DIR
    if not path:
        path = 'index.html'
    target = (doc_root / path).resolve()
    try:
        target.relative_to(doc_root.resolve())
    except ValueError:
        # 路径穿越防护：一律回退 index.html
        return static_serve(request, 'index.html', document_root=doc_root)
    if target.is_file():
        return static_serve(request, path, document_root=doc_root)
    return static_serve(request, 'index.html', document_root=doc_root)

urlpatterns = [
    path('account/', include('apps.account.urls')),
    path('host/', include('apps.host.urls')),
    path('exec/', include('apps.exec.urls')),
    path('schedule/', include('apps.schedule.urls')),
    path('monitor/', include('apps.monitor.urls')),
    path('alarm/', include('apps.alarm.urls')),
    path('setting/', include('apps.setting.urls')),
    path('config/', include('apps.config.urls')),
    path('app/', include('apps.app.urls')),
    path('deploy/', include('apps.deploy.urls')),
    path('repository/', include('apps.repository.urls')),
    path('home/', include('apps.home.urls')),
    path('notify/', include('apps.notify.urls')),
    path('file/', include('apps.file.urls')),
    path('credential/', include('apps.credential.urls')),
    path('pipeline/', include('apps.pipeline.urls')),
    path('ops/', include('apps.ops.urls')),
    path('apis/', include('apps.apis.urls')),
    # ---- 前端静态托管（官方由 Nginx 承担，单进程部署直接在 Django 内完成）----
    # /static/* -> 编译产物的 static 目录
    re_path(r'^static/(?P<path>.*)$', static_serve,
            {'document_root': str(settings.FRONTEND_DIR / 'static')}),
    # 其余路径：命中真实文件（favicon.ico / manifest.json / logo.png 等）则返回文件，
    # 否则回退 index.html（SPA 前端路由）
    re_path(r'^(?P<path>.*)$', frontend_view),
]
