/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Drawer, Form, Input, Modal, Popconfirm, Space, Table, Typography, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { AuthDiv, Breadcrumb } from 'components'
import { http, t } from 'libs'

function lineDiff(oldText, newText) {
  const a = (oldText || '').split('\n')
  const b = (newText || '').split('\n')
  if (a.length * b.length > 40000) {
    return [{ type: 'info', text: '内容过大，已跳过逐行对比' }]
  }
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out = []
  let i = 0, j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ type: 'same', text: a[i] }); i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: 'del', text: a[i] }); i++
    } else {
      out.push({ type: 'add', text: b[j] }); j++
    }
  }
  while (i < a.length) out.push({ type: 'del', text: a[i++] })
  while (j < b.length) out.push({ type: 'add', text: b[j++] })
  return out
}

export default function Templates() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [visible, setVisible] = useState(false)
  const [form] = Form.useForm()
  const [versions, setVersions] = useState([])
  const [versionVisible, setVersionVisible] = useState(false)
  const [versionContent, setVersionContent] = useState('')
  const [diff, setDiff] = useState(null)
  const [current, setCurrent] = useState(null)

  function fetch() {
    setLoading(true)
    http.get('/api/ops/templates/').then(setItems).finally(() => setLoading(false))
  }

  useEffect(fetch, [])

  function handleEdit(record) {
    setCurrent(record || null)
    http.get('/api/ops/templates/', { params: { id: record.id } }).then(res => {
      form.setFieldsValue({ name: res.name, description: res.description, content: res.content })
      setVisible(true)
    })
  }

  function handleCreate() {
    setCurrent(null)
    form.resetFields()
    setVisible(true)
  }

  function handleSave() {
    form.validateFields().then(values => {
      http.post('/api/ops/templates/', { ...values, id: current ? current.id : undefined })
        .then(() => {
          message.success(t('保存成功'))
          setVisible(false)
          fetch()
        })
    })
  }

  function handleVersions(record) {
    http.get('/api/ops/templates/', { params: { id: record.id } }).then(res => {
      setCurrent(res)
      setVersions(res.versions || [])
      setVersionVisible(true)
      setDiff(null)
    })
  }

  function handleVersion(version) {
    http.get('/api/ops/templates/', { params: { id: current.id, version: version.version } }).then(res => {
      setVersionContent(res.content)
      setDiff(lineDiff(res.content, current.content))
    })
  }

  return (
    <AuthDiv auth="pipeline.pipeline.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('运维增强')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('配置模板')}</Breadcrumb.Item>
      </Breadcrumb>
      <Card bordered={false}>
        <Button type="primary" icon={<PlusOutlined/>} style={{ marginBottom: 16 }} onClick={handleCreate}>
          {t('新建模板')}
        </Button>
        <Table rowKey="id" size="middle" loading={loading} dataSource={items} pagination={false}>
          <Table.Column title={t('模板名称')} dataIndex="name"/>
          <Table.Column title={t('说明')} dataIndex="description"/>
          <Table.Column title={t('更新时间')} dataIndex="updated_at" width={180}/>
          <Table.Column title={t('操作')} width={240} render={x => (
            <Space>
              <Typography.Link onClick={() => handleEdit(x)}>{t('编辑')}</Typography.Link>
              <Typography.Link onClick={() => handleVersions(x)}>{t('历史版本')}</Typography.Link>
              <Popconfirm title={t('确认删除该模板？')} onConfirm={() => {
                http.delete('/api/ops/templates/', { params: { id: x.id } }).then(fetch)
              }}>
                <Typography.Link type="danger">{t('删除')}</Typography.Link>
              </Popconfirm>
            </Space>
          )}/>
        </Table>
      </Card>
      <Modal width={860} visible={visible} title={current ? t('编辑模板') : t('新建模板')}
             onCancel={() => setVisible(false)} onOk={handleSave} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={t('模板名称')} rules={[{ required: true }]}>
            <Input placeholder="nginx.conf.j2"/>
          </Form.Item>
          <Form.Item name="description" label={t('说明')}>
            <Input/>
          </Form.Item>
          <Form.Item name="content" label={t('模板内容（Jinja2，可引用 Facts / 主机变量 / 分组变量）')}>
            <Input.TextArea rows={16} style={{ fontFamily: 'monospace' }}/>
          </Form.Item>
        </Form>
      </Modal>
      <Drawer width={860} visible={versionVisible} title={t('历史版本')} onClose={() => setVersionVisible(false)}>
        <Table rowKey="id" size="small" pagination={false} dataSource={versions}>
          <Table.Column title={t('版本')} dataIndex="version" width={80}/>
          <Table.Column title={t('说明')} dataIndex="comment"/>
          <Table.Column title={t('时间')} dataIndex="created_at" width={180}/>
          <Table.Column title={t('操作')} width={100} render={x => (
            <Typography.Link onClick={() => handleVersion(x)}>{t('对比当前')}</Typography.Link>
          )}/>
        </Table>
        {diff && (
          <pre style={{ marginTop: 16, background: '#1e1e1e', padding: 12, maxHeight: 420, overflow: 'auto' }}>
            {diff.map((line, index) => (
              <div key={index} style={{
                color: line.type === 'add' ? '#7ec699' : line.type === 'del' ? '#ff7b72' : '#ccc',
              }}>
                {line.type === 'add' ? '+ ' : line.type === 'del' ? '- ' : '  '}{line.text}
              </div>
            ))}
          </pre>
        )}
      </Drawer>
    </AuthDiv>
  )
}
