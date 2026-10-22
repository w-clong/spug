/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react'
import { Form, Input, Radio, message } from 'antd'
import HostSelector from 'pages/host/Selector'
import { t } from 'libs'

function Facts(props) {
  const [form] = Form.useForm()

  useEffect(() => {
    props.setHandler(() => handleSave)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    form.resetFields()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.node])

  function handleSave() {
    const data = form.getFieldsValue()
    if (!data.name) return message.error(t('请输入节点名称'))
    if (!data.condition) return message.error(t('请选择节点的执行条件'))
    if (!data.targets || data.targets.length === 0) return message.error(t('请选择执行主机'))
    return data
  }

  return (
    <Form layout="vertical" form={form} initialValues={props.node}>
      <Form.Item required name="name" label={t('节点名称')}>
        <Input placeholder={t('请输入节点名称')}/>
      </Form.Item>
      <Form.Item required name="condition" label={t('执行条件')}>
        <Radio.Group>
          <Radio.Button value="success">{t('上游成功时')}</Radio.Button>
          <Radio.Button value="error">{t('上游失败时')}</Radio.Button>
          <Radio.Button value="always">{t('总是执行')}</Radio.Button>
        </Radio.Group>
      </Form.Item>
      <Form.Item required name="targets" label={t('选择主机')}>
        <HostSelector type="button"/>
      </Form.Item>
      <div style={{ color: '#999' }}>
        {t('强制实时采集目标主机的静态 Facts 并覆盖缓存，保证后续任务使用最新系统信息')}
      </div>
    </Form>
  )
}

export default Facts
