# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
内存版 Redis 模拟层（免 Redis 部署用）。

Spug 4.x 官方架构依赖 Redis 承担四类职责：
  1. 任务队列：worker 通过 BLPOP 消费 exec/schedule/monitor 三类任务（rpush/lpush -> blpop/brpop）
  2. 调度命令同步：视图写入 SCHEDULE_KEY，调度器 BRPOP 接收 add/modify/remove 指令
  3. 控制台输出流：执行器把输出 rpush 到 list / publish 到 pubsub，前端经 WebSocket 回放
  4. 监控计数：monitor 用 hash 记录失败次数与告警时间

本模块用进程内字典 + 线程安全原语实现 redis-py 的调用子集，
配合「单进程一体化」启动方式（API + WebSocket + 调度器 + worker 全部跑在一个进程里），
使上述机制在内存中即可闭环，业务代码只需把
    from libs.memredis import get_redis_connection
替换为
    from libs.memredis import get_redis_connection
即可，其余调用语义与 redis-py 保持一致（返回值统一为 bytes）。

适用边界：单进程、单机、小规模使用。多进程/多实例部署仍应使用真实 Redis。
"""
import threading
import time
from collections import deque
from queue import Empty, Queue

__all__ = ['MemRedis', 'get_redis_connection']

_lock = threading.RLock()
# key -> {'type': 'str'|'list'|'hash', 'data': ...}；键一律存 bytes
_store = {}
# key -> 过期时间（time.monotonic() 截止点）
_expires = {}
# channel -> 订阅者队列集合
_subscribers = {}
# 用于阻塞式弹取（blpop/brpop）的通知
_cond = threading.Condition(_lock)

_NOW = time.monotonic


def _now():
    return _NOW()


def _purge(key):
    """惰性清理过期键；返回该键当前是否仍存在。"""
    exp = _expires.get(key)
    if exp is not None and exp <= _now():
        _store.pop(key, None)
        _expires.pop(key, None)
        return False
    return key in _store


def _enc(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode('utf-8')
    if isinstance(value, (int, float)):
        return str(value).encode('utf-8')
    raise TypeError(f'unsupported value type: {type(value)!r}')


def _enc_key(key):
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode('utf-8')
    raise TypeError(f'unsupported key type: {type(key)!r}')


def _get_entry(key):
    if not _purge(key):
        return None
    return _store.get(key)


def _set_entry(key, entry, ttl=None):
    _store[key] = entry
    if ttl is not None:
        _expires[key] = _now() + ttl
    elif key in _expires:
        _expires.pop(key, None)


class PubSub:
    """极简 pub/sub 对象，语义对齐 redis-py 的 PubSub。"""

    def __init__(self, ignore_subscribe_messages=False):
        self._channels = set()
        self._queue = Queue()
        self._ignore_subscribe = ignore_subscribe_messages

    def subscribe(self, *channels):
        with _lock:
            for channel in channels:
                c = _enc_key(channel)
                if c not in self._channels:
                    self._channels.add(c)
                    _subscribers.setdefault(c, set()).add(self._queue)

    def unsubscribe(self, *channels):
        with _lock:
            for channel in channels:
                c = _enc_key(channel)
                self._channels.discard(c)
                q = _subscribers.get(c)
                if q and self._queue in q:
                    q.remove(self._queue)
                    if not q:
                        _subscribers.pop(c, None)

    def get_message(self, ignore_subscribe_messages=False, timeout=None):
        try:
            item = self._queue.get(timeout=timeout)
        except Empty:
            return None
        return item

    def close(self):
        with _lock:
            for c in list(self._channels):
                self.unsubscribe(c)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MemRedis:
    """内存版 redis 客户端，实现 Spug 实际使用的 redis-py 调用子集。"""

    def __init__(self):
        pass

    # ---------- 通用 ----------

    def close(self):
        pass

    def ping(self):
        return True

    def delete(self, *keys):
        with _lock:
            count = 0
            for key in keys:
                k = _enc_key(key)
                if _purge(k):
                    _store.pop(k, None)
                    _expires.pop(k, None)
                    count += 1
            return count

    def exists(self, key):
        with _lock:
            return 1 if _purge(_enc_key(key)) else 0

    def expire(self, key, ttl):
        with _lock:
            k = _enc_key(key)
            if not _purge(k):
                return 0
            _expires[k] = _now() + max(0, int(ttl))
            return 1

    def ttl(self, key):
        with _lock:
            k = _enc_key(key)
            if not _purge(k):
                return -2
            exp = _expires.get(k)
            if exp is None:
                return -1
            # 与 Redis 一致：按毫秒四舍五入到秒（如剩余 0.99s 返回 1）
            remaining_ms = (exp - _now()) * 1000.0
            return max(0, int((remaining_ms + 500) // 1000))

    # ---------- string ----------

    def set(self, name, value, ex=None, px=None, nx=False, xx=False, keepttl=False, *args, **kwargs):
        with _lock:
            k = _enc_key(name)
            if nx and _purge(k):
                return None
            if xx and not _purge(k):
                return None
            ttl = ex if ex is not None else (px / 1000.0 if px is not None else None)
            _set_entry(k, {'type': 'str', 'data': _enc(value)}, ttl)
            return True

    def setex(self, name, time, value):
        return self.set(name, value, ex=int(time))

    def get(self, name):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'str':
                return None
            return entry['data']

    def append(self, key, value):
        with _lock:
            k = _enc_key(key)
            data = _enc(value)
            entry = _get_entry(k)
            if not entry or entry['type'] != 'str':
                _set_entry(k, {'type': 'str', 'data': data})
            else:
                entry['data'] += data
            return len(entry['data'])

    def incr(self, name, amount=1):
        with _lock:
            k = _enc_key(name)
            entry = _get_entry(k)
            cur = 0 if not entry else int(entry['data'])
            new = cur + int(amount)
            _set_entry(k, {'type': 'str', 'data': _enc(new)})
            return new

    # ---------- list ----------

    def rpush(self, name, *values):
        with _lock:
            k = _enc_key(name)
            entry = _get_entry(k)
            if not entry or entry['type'] != 'list':
                entry = {'type': 'list', 'data': deque()}
                _set_entry(k, entry)
            for v in values:
                entry['data'].append(_enc(v))
            with _cond:
                _cond.notify_all()
            return len(entry['data'])

    def lpush(self, name, *values):
        with _lock:
            k = _enc_key(name)
            entry = _get_entry(k)
            if not entry or entry['type'] != 'list':
                entry = {'type': 'list', 'data': deque()}
                _set_entry(k, entry)
            for v in reversed(values):
                entry['data'].appendleft(_enc(v))
            with _cond:
                _cond.notify_all()
            return len(entry['data'])

    def llen(self, name):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'list':
                return 0
            return len(entry['data'])

    def lrange(self, name, start, stop):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'list':
                return []
            d = entry['data']
            length = len(d)
            if start < 0:
                start = max(0, length + start)
            if stop < 0:
                stop = length + stop
            if stop < start:
                return []
            items = list(d)
            return items[start:stop + 1]

    def lindex(self, name, index):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'list':
                return None
            d = entry['data']
            length = len(d)
            if index < 0:
                index = length + index
            if index < 0 or index >= length:
                return None
            return d[index]

    def _blocking_pop(self, keys, timeout, from_right):
        keys = [_enc_key(k) for k in keys]
        deadline = None if timeout is None else _now() + timeout
        with _cond:
            while True:
                for k in keys:
                    if _purge(k):
                        entry = _store.get(k)
                        if entry and entry['type'] == 'list' and entry['data']:
                            d = entry['data']
                            v = d.pop() if from_right else d.popleft()
                            if not d:
                                _store.pop(k, None)
                                _expires.pop(k, None)
                            return (k, v)
                if deadline is not None:
                    remaining = deadline - _now()
                    if remaining <= 0:
                        return None
                    _cond.wait(remaining)
                else:
                    _cond.wait()

    def blpop(self, keys, timeout=0):
        return self._blocking_pop(keys, None if timeout == 0 else timeout, from_right=False)

    def brpop(self, keys, timeout=0):
        return self._blocking_pop(keys, None if timeout == 0 else timeout, from_right=True)

    # ---------- hash ----------

    def hset(self, name, key=None, value=None, mapping=None, *args, **kwargs):
        with _lock:
            k = _enc_key(name)
            entry = _get_entry(k)
            if not entry or entry['type'] != 'hash':
                entry = {'type': 'hash', 'data': {}}
                _set_entry(k, entry)
            if mapping is not None:
                for f, v in mapping.items():
                    entry['data'][_enc_key(f)] = _enc(v)
            elif key is not None:
                entry['data'][_enc_key(key)] = _enc(value)
            return 1

    def hget(self, name, key):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'hash':
                return None
            return entry['data'].get(_enc_key(key))

    def hmget(self, name, keys, *args):
        if isinstance(keys, (list, tuple)):
            ks = list(keys) + list(args)
        else:
            ks = [keys] + list(args)
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'hash':
                return [None] * len(ks)
            return [entry['data'].get(_enc_key(k)) for k in ks]

    def hgetall(self, name):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'hash':
                return {}
            return dict(entry['data'])

    def hincrby(self, name, key, amount=1):
        with _lock:
            k = _enc_key(name)
            entry = _get_entry(k)
            if not entry or entry['type'] != 'hash':
                entry = {'type': 'hash', 'data': {}}
                _set_entry(k, entry)
            f = _enc_key(key)
            cur = int(entry['data'][f]) if f in entry['data'] else 0
            new = cur + int(amount)
            entry['data'][f] = _enc(new)
            return new

    def hdel(self, name, *keys):
        with _lock:
            entry = _get_entry(_enc_key(name))
            if not entry or entry['type'] != 'hash':
                return 0
            count = 0
            for key in keys:
                f = _enc_key(key)
                if f in entry['data']:
                    del entry['data'][f]
                    count += 1
            return count

    # ---------- pub/sub ----------

    def publish(self, channel, message):
        with _lock:
            c = _enc_key(channel)
            payload = _enc(message)
            queues = _subscribers.get(c)
            if not queues:
                return 0
            item = {'type': 'message', 'pattern': None, 'channel': c, 'data': payload}
            for q in list(queues):
                q.put(item)
            return len(queues)

    def pubsub(self, ignore_subscribe_messages=False, **kwargs):
        return PubSub(ignore_subscribe_messages=ignore_subscribe_messages)


_singleton = None


def get_redis_connection(alias='default', **kwargs):
    """返回进程内共享的 MemRedis 实例（对应原 django_redis.get_redis_connection）。"""
    global _singleton
    if _singleton is None:
        _singleton = MemRedis()
    return _singleton
