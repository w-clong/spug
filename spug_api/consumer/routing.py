# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path
from channels.routing import URLRouter
from consumer.consumers import *

ws_router = URLRouter([
    path('ws/ssh/<int:id>/', SSHConsumer.as_asgi()),
    path('ws/subscribe/<str:token>/', PubSubConsumer.as_asgi()),
    path('ws/<str:module>/<str:token>/', ComConsumer.as_asgi()),
    path('ws/notify/', NotifyConsumer.as_asgi()),
    # 前端统一通过 /api/ws/... 连接（官方由 Nginx 剥离 /api 前缀后转发到 daphne），
    # 单进程部署没有 Nginx，这里直接提供带 /api 前缀的路由别名
    path('api/ws/ssh/<int:id>/', SSHConsumer.as_asgi()),
    path('api/ws/subscribe/<str:token>/', PubSubConsumer.as_asgi()),
    path('api/ws/<str:module>/<str:token>/', ComConsumer.as_asgi()),
    path('api/ws/notify/', NotifyConsumer.as_asgi()),
])
