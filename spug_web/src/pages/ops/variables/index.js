/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Popconfirm, Radio, Select, Space, Table, Typography, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { AuthDiv, Breadcrumb } from 'components'
import { http, t } from 'libs'

export default function Variables() {
  const [scope, setScope] = useState('host')
  const [targets, setTargets] = useState([])
  const [targetId, setTargetId] = useState()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [visible, setVisible] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    if (scope === 'host') {
      http.get('/api/host/').then(res => {
        setTargets(res.map(x => ({ value: x.id, label: `${x.name}（${x.hostname}）` })))
        setTargetId(undefined)
      })
    } else {
      http.get('/api/host/group/').then(res => {
        const tree = (res && res.treeData) || []
        setTargets(tree.map(x => ({ value: x.value, label: x.title })))
        setTargetId(undefined)
      })
    }
  }, [scope])

  useEffect(() => {
    if (!targetId) {
      setItems([])
      return
    }
    fetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, targetId])

  function fetch() {
    setLoading(true)
    http.get('/api/ops/variables/', { params: { scope, id: targetId } })
      .then(setItems).finally(() => setLoading(false))
  }

  function handleSave() {
    form.validateFields().then(values => {
      http.post('/api/ops/variables/', { ...values, scope, target_id: targetId })
        .then(() => {
          message.success(t('保存成功'))
          setVisible(false)
          form.resetFields()
          fetch()
        })
    })
  }

  return (
    <AuthDiv auth="host.host.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('运维增强')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('变量管理')}</Breadcrumb.Item>
      </Breadcrumb>
      <Card bordered={false}>
        <Space style={{ marginBottom: 16 }} wrap>
          <Radio.Group value={scope} onChange={e => setScope(e.target.value)} buttonStyle="solid">
            <Radio.Button value="host">{t('主机变量')}</Radio.Button>
            <Radio.Button value="group">{t('分组变量')}</Radio.Button>
          </Radio.Group>
          <Select style={{ width: 320 }} showSearch optionFilterProp="label"
                  placeholder={t('选择主机/分组')} value={targetId} onChange={setTargetId}
                  options={targets}/>
          <Button type="primary" icon={<PlusOutlined/>} disabled={!targetId}
                  onClick={() => setVisible(true)}>{t('新增变量')}</Button>
        </Space>
        <Table rowKey="id" size="middle" loading={loading} dataSource={items} pagination={false}>
          <Table.Column title={t('变量名')} dataIndex="key"/>
          <Table.Column title={t('值')} dataIndex="value"/>
          <Table.Column title={t('更新时间')} dataIndex="updated_at" width={180}/>
          <Table.Column title={t('操作')} width={100} render={x => (
            <Popconfirm title={t('确认删除该变量？')} onConfirm={() => {
              http.delete('/api/ops/variables/', { params: { scope, id: x.id } }).then(fetch)
            }}>
              <Typography.Link type="danger">{t('删除')}</Typography.Link>
            </Popconfirm>
          )}/>
        </Table>
      </Card>
      <Modal visible={visible} title={t('新增变量')} onCancel={() => setVisible(false)} onOk={handleSave}
             destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="key" label={t('变量名')} rules={[{ required: true }]}>
            <Input placeholder="nginx_port"/>
          </Form.Item>
          <Form.Item name="value" label={t('值')}>
            <Input placeholder="8080"/>
          </Form.Item>
          <div style={{ color: '#999' }}>
            {t('模板/状态模块中可直接使用变量名；脚本执行时会注入 _SPUG_VAR_变量名 环境变量。')}
          </div>
        </Form>
      </Modal>
    </AuthDiv>
  )
}
