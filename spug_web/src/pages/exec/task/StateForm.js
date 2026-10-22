/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Form, Input, Select, Switch, InputNumber, Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { http, t } from 'libs'

const { TextArea } = Input

// 统一紧凑间距，避免模块字段多时表单过长
const ITEM_STYLE = { marginBottom: 12 }

function Field({ field, params, onChange, templates }) {
  const value = params[field.name]
  const label = field.help ? (
    <span>
      {field.label}
      <Tooltip title={field.help}>
        <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }}/>
      </Tooltip>
    </span>
  ) : field.label

  switch (field.type) {
    case 'template':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <Select allowClear showSearch optionFilterProp="label" value={value} onChange={onChange}
                  placeholder={t('可选：选择后按主机变量/Facts 渲染并推送')}
                  options={(templates || []).map(x => ({ value: x.id, label: x.name }))}/>
        </Form.Item>
      )
    case 'boolean':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <Switch checked={value !== undefined ? !!value : !!field.default} onChange={onChange}/>
        </Form.Item>
      )
    case 'select':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <Select value={value !== undefined ? value : field.default} onChange={onChange}
                  options={(field.options || []).map(x => ({ value: x.value, label: x.label }))}/>
        </Form.Item>
      )
    case 'textarea':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <TextArea rows={4} value={value || ''} placeholder={field.placeholder}
                    onChange={e => onChange(e.target.value)}/>
        </Form.Item>
      )
    case 'password':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <Input.Password value={value || ''} placeholder={field.placeholder}
                          onChange={e => onChange(e.target.value)}/>
        </Form.Item>
      )
    case 'number':
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <InputNumber value={value} onChange={onChange} style={{ width: '100%' }}
                       placeholder={field.placeholder}/>
        </Form.Item>
      )
    default:
      return (
        <Form.Item label={label} style={ITEM_STYLE}>
          <Input value={value || ''} placeholder={field.placeholder}
                 onChange={e => onChange(e.target.value)}/>
        </Form.Item>
      )
  }
}

export default function StateForm({ modules, moduleKey, params, onModuleChange, onParamChange }) {
  const meta = modules[moduleKey]
  const [templates, setTemplates] = useState([])

  useEffect(() => {
    http.get('/api/ops/templates/').then(setTemplates).catch(() => {})
  }, [])

  return (
    <>
      <Form.Item label={t('状态模块')} required style={ITEM_STYLE}>
        <Select
          value={moduleKey}
          placeholder={t('选择要执行的状态模块')}
          showSearch
          optionFilterProp="label"
          onChange={onModuleChange}
          options={Object.entries(modules).map(([key, item]) => ({
            value: key,
            label: `${item.title}（${item.desc}）`,
          }))}/>
      </Form.Item>
      {meta && meta.fields.map(field => (
        <Field
          key={field.name}
          field={field}
          params={params}
          templates={templates}
          onChange={value => onParamChange(field.name, value)}/>
      ))}
    </>
  )
}
