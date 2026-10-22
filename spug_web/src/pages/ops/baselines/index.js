/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Space, Table, Tag, Typography, message } from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { AuthDiv, Breadcrumb } from 'components'
import HostSelector from 'pages/host/Selector'
import StateForm from 'pages/exec/task/StateForm'
import { http, t } from 'libs'

export default function Baselines() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [visible, setVisible] = useState(false)
  const [form] = Form.useForm()
  const [current, setCurrent] = useState(null)
  const [runVisible, setRunVisible] = useState(false)
  const [runTarget, setRunTarget] = useState(null)
  const [hostIds, setHostIds] = useState([])
  const [dryRun, setDryRun] = useState(false)
  const [modules, setModules] = useState({})
  const [nodes, setNodes] = useState([])

  function fetch() {
    setLoading(true)
    http.get('/api/ops/baselines/').then(setItems).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetch()
    http.get('/api/ops/modules/').then(setModules)
  }, [])

  function handleEdit(record) {
    setCurrent(record || null)
    form.setFieldsValue({
      name: record ? record.name : '',
      description: record ? record.description : '',
    })
    setNodes(record && Array.isArray(record.nodes) ? record.nodes : [])
    setVisible(true)
  }

  function addNode() {
    setNodes(old => [...old, { state_module: 'pkg', state_params: {} }])
  }

  function removeNode(index) {
    setNodes(old => old.filter((_, i) => i !== index))
  }

  function updateNode(index, patch) {
    setNodes(old => old.map((item, i) => i === index ? { ...item, ...patch } : item))
  }

  function handleSave() {
    form.validateFields().then(values => {
      if (!nodes.length) return message.error(t('请至少添加一个状态模块节点'))
      http.post('/api/ops/baselines/', {
        id: current ? current.id : undefined,
        name: values.name,
        description: values.description,
        nodes,
      }).then(() => {
        message.success(t('保存成功'))
        setVisible(false)
        fetch()
      })
    })
  }

  function handleRun(record, dry) {
    setRunTarget(record)
    setDryRun(dry)
    setHostIds([])
    setRunVisible(true)
  }

  function doRun() {
    if (!hostIds.length) return message.error(t('请选择目标主机'))
    http.post('/api/ops/baselines/run/', {
      id: runTarget.id, host_ids: hostIds, dry_run: dryRun,
    }).then(() => {
      message.success(dryRun ? t('巡检任务已下发') : t('收敛任务已下发'))
      setRunVisible(false)
    })
  }

  return (
    <AuthDiv auth="pipeline.pipeline.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('运维增强')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('基线管理')}</Breadcrumb.Item>
      </Breadcrumb>
      <Card bordered={false}>
        <Button type="primary" icon={<PlusOutlined/>} style={{ marginBottom: 16 }}
                onClick={() => handleEdit(null)}>{t('新建基线')}</Button>
        <Table rowKey="id" size="middle" loading={loading} dataSource={items} pagination={false}>
          <Table.Column title={t('基线名称')} dataIndex="name"/>
          <Table.Column title={t('说明')} dataIndex="description"/>
          <Table.Column title={t('节点数')} width={90} render={x => (x.nodes || []).length}/>
          <Table.Column title={t('更新时间')} dataIndex="updated_at" width={180}/>
          <Table.Column title={t('操作')} width={260} render={x => (
            <Space>
              <Typography.Link onClick={() => handleRun(x, false)}>{t('一键收敛')}</Typography.Link>
              <Typography.Link onClick={() => handleRun(x, true)}>{t('一键巡检')}</Typography.Link>
              <Typography.Link onClick={() => handleEdit(x)}>{t('编辑')}</Typography.Link>
            </Space>
          )}/>
        </Table>
      </Card>
      <Modal width={880} visible={visible} title={current ? t('编辑基线') : t('新建基线')}
             onCancel={() => setVisible(false)} onOk={handleSave} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={t('基线名称')} rules={[{ required: true }]}>
            <Input placeholder="nginx 基线 / 系统加固基线"/>
          </Form.Item>
          <Form.Item name="description" label={t('说明')}>
            <Input/>
          </Form.Item>
          <div style={{ maxHeight: '55vh', overflow: 'auto', paddingRight: 4 }}>
            {nodes.map((node, index) => (
              <Card
                key={index}
                size="small"
                style={{ marginBottom: 12 }}
                title={`${t('节点')} ${index + 1}: ${(modules[node.state_module] || {}).title || node.state_module || t('未选择')}`}
                extra={<MinusCircleOutlined onClick={() => removeNode(index)}/>}>
                <StateForm
                  modules={modules}
                  moduleKey={node.state_module || ''}
                  params={node.state_params || {}}
                  onModuleChange={key => updateNode(index, { state_module: key, state_params: {} })}
                  onParamChange={(name, value) => updateNode(index, {
                    state_params: { ...(node.state_params || {}), [name]: value },
                  })}/>
              </Card>
            ))}
            <Button type="dashed" block icon={<PlusOutlined/>} onClick={addNode}>
              {t('添加状态模块节点')}
            </Button>
          </div>
        </Form>
      </Modal>
      <Modal width={640} visible={runVisible} title={t('选择目标主机')}
             onCancel={() => setRunVisible(false)} onOk={doRun}>
        <Form layout="vertical">
          <Form.Item label={t('执行模式')}>
            <Tag color={dryRun ? 'blue' : 'orange'}>{dryRun ? 'Dry-run 巡检' : '收敛变更'}</Tag>
          </Form.Item>
          <Form.Item required label={t('目标主机')}>
            <HostSelector type="button" value={hostIds} onChange={setHostIds}/>
          </Form.Item>
        </Form>
      </Modal>
    </AuthDiv>
  )
}
