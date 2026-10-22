/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { AuthDiv, Breadcrumb } from 'components'
import { http, t } from 'libs'

const OPS = [
  ['eq', '等于'], ['ne', '不等于'], ['in', '属于'], ['not_in', '不属于'],
  ['gt', '大于'], ['ge', '大于等于'], ['lt', '小于'], ['le', '小于等于'],
  ['contains', '包含'], ['regex', '正则匹配'],
]

export default function DynamicGroups() {
  const [items, setItems] = useState([])
  const [groups, setGroups] = useState([])
  const [visible, setVisible] = useState(false)
  const [current, setCurrent] = useState(null)
  const [form] = Form.useForm()

  function fetch() {
    http.get('/api/ops/dynamic-groups/').then(setItems)
  }

  useEffect(() => {
    fetch()
    http.get('/api/host/group/').then(res => {
      const tree = (res && res.treeData) || []
      setGroups(tree.map(x => ({ value: x.value, label: x.title })))
    })
  }, [])

  function handleEdit(record) {
    setCurrent(record || null)
    form.resetFields()
    if (record) {
      form.setFieldsValue({
        group_id: record.group_id,
        name: record.name,
        match_all: record.match_all !== false,
        rules: record.rules && record.rules.length ? record.rules : [{ key: 'os_family', op: 'eq', value: '' }],
      })
    } else {
      form.setFieldsValue({ match_all: true, rules: [{ key: 'os_family', op: 'eq', value: '' }] })
    }
    setVisible(true)
  }

  function handleSave() {
    form.validateFields().then(values => {
      http.post('/api/ops/dynamic-groups/', {
        ...values, id: current ? current.id : undefined,
      }).then(() => {
        message.success(t('保存成功'))
        setVisible(false)
        fetch()
      })
    })
  }

  return (
    <AuthDiv auth="host.host.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('运维增强')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('动态分组')}</Breadcrumb.Item>
      </Breadcrumb>
      <Card bordered={false}>
        <Button type="primary" icon={<PlusOutlined/>} style={{ marginBottom: 16 }}
                onClick={() => handleEdit(null)}>{t('新增规则')}</Button>
        <Table rowKey="id" size="middle" dataSource={items} pagination={false}>
          <Table.Column title={t('规则名称')} dataIndex="name"/>
          <Table.Column title={t('分组')} render={x => {
            const g = groups.find(i => i.value === x.group_id)
            return g ? g.label : x.group_id
          }}/>
          <Table.Column title={t('匹配方式')} width={110}
                        render={x => x.match_all ? t('全部满足') : t('任一满足')}/>
          <Table.Column title={t('条件')} render={x => (x.rules || []).map((r, i) => (
            <Tag key={i}>{r.key} {r.op} {Array.isArray(r.value) ? r.value.join(',') : r.value}</Tag>
          ))}/>
          <Table.Column title={t('启用')} width={80} render={x => (
            <Tag color={x.enabled ? 'green' : 'default'}>{x.enabled ? t('启用') : t('停用')}</Tag>
          )}/>
          <Table.Column title={t('操作')} width={160} render={x => (
            <Space>
              <Typography.Link onClick={() => handleEdit(x)}>{t('编辑')}</Typography.Link>
              <Popconfirm title={t('确认删除该规则？')} onConfirm={() => {
                http.delete('/api/ops/dynamic-groups/', { params: { id: x.id } }).then(fetch)
              }}>
                <Typography.Link type="danger">{t('删除')}</Typography.Link>
              </Popconfirm>
            </Space>
          )}/>
        </Table>
      </Card>
      <Modal width={720} visible={visible} title={current ? t('编辑动态分组') : t('新增动态分组')}
             onCancel={() => setVisible(false)} onOk={handleSave} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="group_id" label={t('目标分组')} rules={[{ required: true }]}>
            <Select options={groups} placeholder={t('选择要自动维护成员的分组')}/>
          </Form.Item>
          <Form.Item name="name" label={t('规则名称')}>
            <Input placeholder={t('例如：Debian 系主机')}/>
          </Form.Item>
          <Form.Item name="match_all" label={t('匹配方式')} valuePropName="checked">
            <Switch checkedChildren={t('全部满足')} unCheckedChildren={t('任一满足')}/>
          </Form.Item>
          <Form.List name="rules">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...rest }) => (
                  <Space key={key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item {...rest} name={[name, 'key']} rules={[{ required: true }]}>
                      <Select style={{ width: 170 }} placeholder={t('Facts 键')}
                              options={[
                                { value: 'os_family', label: 'os_family' },
                                { value: 'os', label: 'os' },
                                { value: 'os_version', label: 'os_version' },
                                { value: 'arch', label: 'arch' },
                                { value: 'kernel', label: 'kernel' },
                                { value: 'hostname', label: 'hostname' },
                                { value: 'memory_total_mb', label: 'memory_total_mb' },
                              ]}/>
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'op']} rules={[{ required: true }]}>
                      <Select style={{ width: 130 }} options={OPS.map(([value, label]) => ({ value, label }))}/>
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'value']} rules={[{ required: true }]}>
                      <Input style={{ width: 220 }} placeholder={t('比较值，in 用逗号分隔')}/>
                    </Form.Item>
                    <MinusCircleOutlined onClick={() => remove(name)}/>
                  </Space>
                ))}
                <Button type="dashed" icon={<PlusOutlined/>} onClick={() => add({ key: 'os_family', op: 'eq', value: '' })}>
                  {t('添加条件')}
                </Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>
    </AuthDiv>
  )
}
