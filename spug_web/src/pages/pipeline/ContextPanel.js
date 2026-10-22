/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Button, Select, Table, Tag, message } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { http, t } from 'libs'

const COLORS = {
  global: 'default',
  env: 'blue',
  pipeline: 'purple',
  host: 'orange',
  fact: 'green',
}

export default function ContextPanel({ pipelineId }) {
  const [open, setOpen] = useState(false)
  const [hosts, setHosts] = useState([])
  const [hostId, setHostId] = useState()
  const [data, setData] = useState({ variables: [] })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (pipelineId && pipelineId !== 'new') {
      http.get('/api/ops/pipeline-hosts/', { params: { pipeline_id: pipelineId } })
        .then(setHosts).catch(() => {})
    }
  }, [pipelineId])

  useEffect(() => {
    if (!open || !pipelineId || pipelineId === 'new') return
    setLoading(true)
    http.get('/api/ops/context/', { params: { pipeline_id: pipelineId, host_id: hostId || undefined } })
      .then(setData)
      .finally(() => setLoading(false))
  }, [open, hostId, pipelineId])

  function insertVariable(name) {
    const el = document.activeElement
    if (!el || !('value' in el)) {
      return message.warning(t('请先点击要插入的输入框'))
    }
    const text = `{{ ${name} }}`
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? start
    const next = el.value.slice(0, start) + text + el.value.slice(end)
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (!setter) return message.warning(t('当前输入框不支持插入'))
    setter.call(el, next)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.focus()
    el.setSelectionRange(start + text.length, start + text.length)
  }

  if (!pipelineId || pipelineId === 'new') return null

  return (
    <div style={{
      flexShrink: 0,
      display: 'flex',
      alignItems: 'flex-start',
      borderLeft: '1px solid #eee',
      background: '#fff',
    }}>
      <Button
        type="text"
        size="small"
        onClick={() => setOpen(!open)}
        style={{ marginTop: 12 }}
        icon={open ? <RightOutlined/> : <LeftOutlined/>}/>
      {open && (
        <div style={{
          width: 340,
          maxHeight: '100%',
          overflow: 'auto',
          padding: 12,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{t('可用变量')}</div>
          <Select
            allowClear
            style={{ width: '100%' }}
            placeholder={t('选择预览主机（不选=只看变量定义）')}
            value={hostId}
            onChange={setHostId}
            options={hosts.map(x => ({ value: x.id, label: `${x.name}（${x.hostname}）` }))}/>
          <div style={{ color: '#999', fontSize: 12, margin: '8px 0' }}>
            {t('预览基于最近缓存的 Facts 快照；如需最新系统信息，请执行「刷新Facts」节点')}
          </div>
          <Table
            size="small"
            rowKey="name"
            loading={loading}
            pagination={false}
            dataSource={data.variables || []}
            onRow={record => ({
              onClick: () => insertVariable(record.name),
              style: { cursor: 'pointer' },
            })}>
            <Table.Column title={t('变量')} dataIndex="name"
                          render={v => <code>{`{{ ${v} }}`}</code>}/>
            <Table.Column title={t('当前值')} dataIndex="value" ellipsis/>
            <Table.Column title={t('来源')} dataIndex="source_label" width={72}
                          render={(v, row) => <Tag color={COLORS[row.source]}>{v}</Tag>}/>
          </Table>
          {data.facts_updated_at && (
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              {t('Facts 更新时间：{}', data.facts_updated_at)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
