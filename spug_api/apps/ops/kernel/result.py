# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""状态模块执行结果的统一数据结构。

所有状态模块（pkg/file/directory/service/user）以及未来的扩展模块，
都必须收敛为 changed / failed / diff / msg 四元组，便于：
  - 批量执行页展示
  - 流水线节点输出变量
  - 全局变更日志入库
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class HostResult:
    host_id: int
    host_name: str
    changed: bool = False
    failed: bool = False
    diff: str = ''
    msg: str = ''
    # 供调试：连接阶段的异常文本
    error: Optional[str] = None

    def to_dict(self):
        return {
            'host_id': self.host_id,
            'host_name': self.host_name,
            'changed': self.changed,
            'failed': self.failed,
            'diff': self.diff,
            'msg': self.msg,
            'error': self.error,
        }


@dataclass
class RunSummary:
    results: List[HostResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed_count(self):
        return sum(1 for x in self.results if x.changed)

    @property
    def failed_count(self):
        return sum(1 for x in self.results if x.failed)

    @property
    def is_success(self):
        return self.failed_count == 0

    def get(self, host_id):
        for item in self.results:
            if item.host_id == host_id:
                return item
        return None
