/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react'
import { Form, Input, Radio, Select, Switch, message } from 'antd'
import HostSelector from 'pages/host/Selector'
import { http, t } from 'libs'

function Artifact(props) {
  const [form] = Form.useForm()
  const [credentials, setCredentials] = useState([])
  const [authType, setAuthType] = useState(props.node.auth_type || 'none')

  useEffect(() => {
    props.setHandler(() => handleSave)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    form.resetFields()
    setAuthType(props.node.auth_type || 'none')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.node])

  useEffect(() => {
    http.get('/api/credential/').then(setCredentials).catch(() => {})
  }, [])

  function handleSave() {
    const data = form.getFieldsValue()
    if (!data.name) return message.error(t('请输入节点名称'))
    if (!data.condition) return message.error(t('请选择节点的执行条件'))
    if (!data.targets || data.targets.length === 0) return message.error(t('请选择执行主机'))
    if (!data.base_url) return message.error(t('请输入制品源地址'))
    if ((data.source_type || 'raw') === 'raw' && !data.dest_path) {
      return message.error(t('请输入目标路径'))
    }
    if ((data.source_type || 'raw') !== 'raw' && !data.package) {
      return message.error(t('请输入包名'))
    }
    if ((data.auth_type || 'none') !== 'none' && !data.credential_id) {
      return message.error(t('请选择认证凭据'))
    }
    return { ...data, source_type: data.source_type || 'raw' }
  }

  return (
    <Form form={form} layout="vertical" initialValues={{ ...props.node, source_type: props.node.source_type || 'raw' }}>
      <Form.Item required name="name" label={t('节点名称')}>
        <Input placeholder={t('请输入节点名称')}/>
      </Form.Item>
      <Form.Item required name="condition" label={t('执行条件')}
                 tooltip={t('当该节点为流程的起始节点时该条件会被忽略')}>
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
      <Form.Item name="source_type" label={t('制品源类型')}>
        <Select options={[
          { value: 'raw', label: t('raw 文件源（HTTP）') },
          { value: 'rpm', label: t('rpm 源（yum/dnf）') },
          { value: 'deb', label: t('deb 源（apt）') },
          { value: 'oci', label: t('OCI 镜像源（后续版本）'), disabled: true },
        ]}/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(p, c) => p.source_type !== c.source_type}>
        {({getFieldValue}) => getFieldValue('source_type') === 'deb' ? (
          <>
            <Form.Item name="suite" label={t('套件（suite）')} extra={t('例如 noble / jammy / ./')}>
              <Input placeholder="noble"/>
            </Form.Item>
            <Form.Item name="component" label={t('组件（component）')}>
              <Input placeholder="main"/>
            </Form.Item>
          </>
        ) : null}
      </Form.Item>
      <Form.Item required name="base_url" label={t('制品源地址')}
                 extra={t('支持 Jinja 变量；rpm/deb 请填到仓库根，例如 https://host/rpm')}>
        <Input placeholder="https://nora.example.com/raw"/>
      </Form.Item>
      <Form.Item name="repo_name" label={t('仓库名称')}>
        <Input placeholder="{{ repo_name }}"/>
      </Form.Item>
      <Form.Item name="package" label={t('包名 / 路径')} extra={t('支持 Jinja，例如 apps/{{ app_name }}')}>
        <Input placeholder="apps/myapp"/>
      </Form.Item>
      <Form.Item name="version" label={t('版本号')}>
        <Input placeholder="{{ app_version }}"/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(p, c) => p.source_type !== c.source_type}>
        {({getFieldValue}) => getFieldValue('source_type') === 'raw' ? (
          <>
            <Form.Item required name="dest_path" label={t('目标路径')}
                       extra={t('远端保存路径；以 / 结尾时自动拼接文件名')}>
              <Input placeholder="/data/artifacts/"/>
            </Form.Item>
            <Form.Item name="overwrite" label={t('覆盖已有文件')} valuePropName="checked">
              <Switch/>
            </Form.Item>
          </>
        ) : null}
      </Form.Item>
      <Form.Item name="auth_type" label={t('认证方式')} initialValue="none">
        <Select onChange={setAuthType} options={[
          { value: 'none', label: t('无认证') },
          { value: 'bearer', label: 'Bearer Token' },
          { value: 'basic', label: 'Basic Auth' },
        ]}/>
      </Form.Item>
      {authType !== 'none' && (
        <Form.Item name="credential_id" label={t('认证凭据')}
                   extra={t('凭据仅在后端使用，日志不会输出 token/账号密码')}>
          <Select showSearch optionFilterProp="label" placeholder={t('选择系统凭据')}
                  options={credentials.map(x => ({ value: x.id, label: `${x.name}（${x.type_alias}）` }))}/>
        </Form.Item>
      )}
      <Form.Item name="dry_run" label={t('Dry-run 预览')} valuePropName="checked">
        <Switch/>
      </Form.Item>
      <div style={{ color: '#999' }}>
        {t('raw：curl 下载到目标路径，按大小/覆盖策略幂等；rpm/deb：写入远端源配置后用包管理器安装；'
           + 'OCI 后续支持。Dry-run 只探测/预览，不修改主机。')}
      </div>
    </Form>
  )
}

export default Artifact
