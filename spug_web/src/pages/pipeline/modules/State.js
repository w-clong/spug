/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useRef, useState } from 'react'
import { Form, Input, Radio, Switch, message } from 'antd'
import HostSelector from 'pages/host/Selector'
import StateForm from 'pages/exec/task/StateForm'
import { http, t } from 'libs'

function State(props) {
  const [form] = Form.useForm()
  const [modules, setModules] = useState({})
  const [moduleKey, setModuleKey] = useState(props.node.state_module || '')
  const [params, setParams] = useState(props.node.state_params || {})
  const [dryRun, setDryRun] = useState(!!props.node.dry_run)
  const latest = useRef({})
  latest.current = { moduleKey, params, dryRun }

  useEffect(() => {
    http.get('/api/ops/modules/').then(setModules)
  }, [])

  useEffect(() => {
    form.resetFields()
    setModuleKey(props.node.state_module || '')
    setParams(props.node.state_params || {})
    setDryRun(!!props.node.dry_run)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.node])

  useEffect(() => {
    props.setHandler(() => handleSave)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleSave() {
    const data = form.getFieldsValue()
    if (!data.name) return message.error(t('请输入节点名称'))
    if (!data.condition) return message.error(t('请选择节点的执行条件'))
    if (!data.targets || data.targets.length === 0) return message.error(t('请选择执行主机'))
    const { moduleKey, params, dryRun } = latest.current
    if (!moduleKey) return message.error(t('请选择状态模块'))
    return {
      ...data,
      state_module: moduleKey,
      state_params: params,
      dry_run: dryRun,
    }
  }

  return (
    <Form layout="vertical" form={form} initialValues={props.node}>
      <Form.Item required name="name" label={t('节点名称')}>
        <Input placeholder={t('请输入节点名称')}/>
      </Form.Item>
      <Form.Item required name="condition" label={t('执行条件')}
                 tooltip={t('当该节点为流程的起始节点时该条件会被忽略；changed 用于变更后执行（Ansible Handler）')}>
        <Radio.Group>
          <Radio.Button value="success">{t('上游成功时')}</Radio.Button>
          <Radio.Button value="changed">{t('上游有变更时')}</Radio.Button>
          <Radio.Button value="unchanged">{t('上游无变更时')}</Radio.Button>
          <Radio.Button value="error">{t('上游失败时')}</Radio.Button>
          <Radio.Button value="always">{t('总是执行')}</Radio.Button>
        </Radio.Group>
      </Form.Item>
      <Form.Item required name="targets" label={t('选择主机')}>
        <HostSelector type="button"/>
      </Form.Item>
      <StateForm
        modules={modules}
        moduleKey={moduleKey}
        params={params}
        onModuleChange={key => {
          setModuleKey(key)
          setParams({})
        }}
        onParamChange={(name, value) => setParams(old => ({ ...old, [name]: value }))}/>
      <Form.Item label="Dry-run 预览">
        <Switch checked={dryRun} onChange={setDryRun}/>
        <span style={{ marginLeft: 8, color: '#999' }}>{t('仅输出将要下发的变更，不修改主机')}</span>
      </Form.Item>
    </Form>
  )
}

export default State
