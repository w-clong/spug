/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Select, Checkbox, Space, Drawer, Typography, message } from 'antd'
import { AuthDiv, Breadcrumb } from 'components'
import { http, t } from 'libs'

const SOURCES = [
  ['', '全部来源'], ['batch', '批量执行'], ['pipeline', '流水线'],
  ['schedule', '定时任务'], ['baseline', '基线'], ['facts', 'Facts采集'],
]

export default function ChangeLog() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [source, setSource] = useState('')
  const [onlyChanged, setOnlyChanged] = useState(false)
  const [onlyFailed, setOnlyFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    setLoading(true)
    http.get('/api/ops/changes/', {
      params: {
        page, page_size: pageSize, source: source || undefined,
        only_changed: onlyChanged || undefined, only_failed: onlyFailed || undefined,
      }
    }).then(res => {
      setItems(res.items)
      setTotal(res.total)
    }).finally(() => setLoading(false))
  }, [page, pageSize, source, onlyChanged, onlyFailed])

  return (
    <AuthDiv auth="host.host.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('运维增强')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('变更日志')}</Breadcrumb.Item>
      </Breadcrumb>
      <Card bordered={false}>
        <Space style={{ marginBottom: 16 }} wrap>
          <Select value={source} style={{ width: 130 }} onChange={setSource}
                  options={SOURCES.map(([value, label]) => ({ value, label }))}/>
          <Checkbox checked={onlyChanged} onChange={e => setOnlyChanged(e.target.checked)}>
            {t('仅看变更')}
          </Checkbox>
          <Checkbox checked={onlyFailed} onChange={e => setOnlyFailed(e.target.checked)}>
            {t('仅看失败')}
          </Checkbox>
        </Space>
        <Table
          rowKey="id"
          size="middle"
          loading={loading}
          dataSource={items}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            onChange: (p, s) => { setPage(p); setPageSize(s) },
            showTotal: x => t('共 {} 条', x),
          }}>
          <Table.Column title={t('时间')} dataIndex="created_at" width={170}/>
          <Table.Column title={t('主机')} dataIndex="host_name" width={160}/>
          <Table.Column title={t('模块')} dataIndex="module" width={110}/>
          <Table.Column title={t('结果')} width={100} render={x => (
            x.failed ? <Tag color="red">{t('失败')}</Tag> :
              x.changed ? <Tag color="orange">{t('变更')}</Tag> : <Tag>{t('正常')}</Tag>
          )}/>
          <Table.Column title={t('来源')} dataIndex="source" width={100}/>
          <Table.Column title={t('操作人')} dataIndex="operator" width={110}/>
          <Table.Column title={t('详情')} render={x => (
            <Typography.Link onClick={() => setDetail(x)}>{t('查看')}</Typography.Link>
          )}/>
        </Table>
      </Card>
      <Drawer width={720} visible={!!detail} title={t('变更详情')} onClose={() => setDetail(null)}>
        {detail && (
          <>
            <p><b>{t('执行信息')}：</b>{detail.msg}</p>
            <p><b>{t('变更命令')}：</b></p>
            <pre style={{ background: '#1e1e1e', color: '#ddd', padding: 12, maxHeight: 420, overflow: 'auto' }}>
              {detail.diff || t('无')}
            </pre>
          </>
        )}
      </Drawer>
    </AuthDiv>
  )
}
