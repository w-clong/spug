/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Form, Input, Select, Modal, Button, Radio, Switch } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import { LinkButton, ACEditor, Container } from 'components';
import TemplateSelector from '../exec/task/TemplateSelector';
import StateForm from '../exec/task/StateForm';
import { cleanCommand, http, t, docsUrl } from 'libs';
import store from './store';

export default observer(function (props) {
  const [form] = Form.useForm();
  const [showTmp, setShowTmp] = useState(false);
  const [command, setCommand] = useState(store.record.command || '');
  const [kind, setKind] = useState(store.record.kind || 'command');
  const [modules, setModules] = useState({});
  const [moduleKey, setModuleKey] = useState(store.record.module || '');
  const [params, setParams] = useState(() => {
    if (store.record.kind === 'state' && store.record.command) {
      try {
        return JSON.parse(store.record.command);
      } catch (e) {
        return {};
      }
    }
    return {};
  });
  const [dryRun, setDryRun] = useState(!!store.record.dry_run);

  useEffect(() => {
    http.get('/api/ops/modules/').then(setModules);
  }, []);

  function handleAddZone() {
    let type;
    Modal.confirm({
      icon: <ExclamationCircleOutlined/>,
      title: t('添加任务类型'),
      content: (
        <Form layout="vertical" style={{marginTop: 24}}>
          <Form.Item required label={t('任务类型')}>
            <Input onChange={e => type = e.target.value}/>
          </Form.Item>
        </Form>
      ),
      onOk: () => {
        if (type) {
          store.types.push(type);
          form.setFieldsValue({type})
        }
      },
    })
  }

  function canNext() {
    const formData = form.getFieldsValue()
    if (!formData.type || !formData.name) return true
    if (kind === 'state') return !moduleKey
    return kind === 'facts' ? false : !command
  }

  function handleNext() {
    store.page += 1;
    const data = {kind, module: kind === 'state' ? moduleKey : null, dry_run: dryRun};
    if (kind === 'state') {
      data.command = JSON.stringify(params);
    } else if (kind === 'facts') {
      data.command = '{}';
    } else {
      data.command = cleanCommand(command);
    }
    Object.assign(store.record, form.getFieldsValue(), data)
  }

  function handleSelect(tpl) {
    const {interpreter, body} = tpl;
    setCommand(body)
    form.setFieldsValue({interpreter})
  }

  let modePlaceholder;
  switch (store.record.rst_notify.mode) {
    case '0':
      modePlaceholder = t('已关闭')
      break
    case '1':
      modePlaceholder = 'https://oapi.dingtalk.com/robot/send?access_token=xxx'
      break
    case '3':
      modePlaceholder = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'
      break
    case '4':
      modePlaceholder = 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx'
      break
    default:
      modePlaceholder = t('请输入')
  }

  return (
    <Container visible={props.visible}>
      <Form form={form} initialValues={store.record} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required label={t('任务类型')} style={{marginBottom: 0}}>
          <Form.Item name="type" style={{display: 'inline-block', width: '80%'}}>
            <Select placeholder={t('请选择任务类型')}>
              {store.types.map(item => (
                <Select.Option value={item} key={item}>{item}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item style={{display: 'inline-block', width: '20%', textAlign: 'right'}}>
            <Button type="link" onClick={handleAddZone}>{t('添加类型')}</Button>
          </Form.Item>
        </Form.Item>
        <Form.Item required name="name" label={t('任务名称')}>
          <Input placeholder={t('请输入任务名称')}/>
        </Form.Item>
        <Form.Item required label={t('任务内容')}
                   extra={kind === 'command' ? (
                     <LinkButton onClick={() => setShowTmp(true)}>{t('从模板添加')}</LinkButton>
                   ) : null}>
          <Radio.Group buttonStyle="solid" style={{marginBottom: 12}} value={kind} onChange={e => setKind(e.target.value)}>
            <Radio.Button value="command" style={{width: 90, textAlign: 'center'}}>{t('脚本')}</Radio.Button>
            <Radio.Button value="state" style={{width: 100, textAlign: 'center'}}>{t('状态模块')}</Radio.Button>
            <Radio.Button value="facts" style={{width: 100, textAlign: 'center'}}>{t('Facts刷新')}</Radio.Button>
          </Radio.Group>
          {kind === 'command' && (
            <>
              <Form.Item noStyle name="interpreter">
                <Radio.Group buttonStyle="solid" style={{marginBottom: 12}}>
                  <Radio.Button value="sh" style={{width: 80, textAlign: 'center'}}>Shell</Radio.Button>
                  <Radio.Button value="python" style={{width: 80, textAlign: 'center'}}>Python</Radio.Button>
                </Radio.Group>
              </Form.Item>
              <ACEditor mode={form.getFieldValue('interpreter')} value={command} width="100%" height="150px"
                        onChange={setCommand}/>
            </>
          )}
          {kind === 'state' && (
            <>
              <StateForm
                modules={modules}
                moduleKey={moduleKey}
                params={params}
                onModuleChange={key => {
                  setModuleKey(key)
                  setParams({})
                }}
                onParamChange={(name, value) => setParams(old => ({...old, [name]: value}))}/>
              <Form.Item label="Dry-run 巡检" labelCol={{span: 6}}>
                <Switch checked={dryRun} onChange={setDryRun}/>
                <span style={{marginLeft: 8, color: '#999'}}>{t('只检测漂移，不修改主机')}</span>
              </Form.Item>
            </>
          )}
          {kind === 'facts' && (
            <div style={{color: '#999', marginBottom: 12}}>
              {t('定时刷新目标主机的静态 Facts 缓存（系统/版本/架构/内存等）')}
            </div>
          )}
        </Form.Item>
        <Form.Item label={t('通知')} extra={(
          <span>
            {t('状态模块任务：无变更时不通知，有变更/失败时汇总一条；脚本任务失败时告警。')}
            <a target="_blank" rel="noopener noreferrer"
               href={docsUrl('use-problem#use-dd')}>{t('钉钉收不到通知？')}</a>
          </span>)}>
          <Input
            value={store.record.rst_notify.value}
            onChange={e => store.record.rst_notify.value = e.target.value}
            addonBefore={(
              <Select style={{width: 100}} value={store.record.rst_notify.mode}
                      onChange={v => store.record.rst_notify.mode = v}>
                <Select.Option value="0">{t('关闭')}</Select.Option>
                <Select.Option value="1">{t('钉钉')}</Select.Option>
                <Select.Option value="4">{t('飞书')}</Select.Option>
                <Select.Option value="3">{t('企业微信')}</Select.Option>
                <Select.Option value="2">Webhook</Select.Option>
              </Select>
            )}
            disabled={store.record.rst_notify.mode === '0'}
            placeholder={modePlaceholder}/>
        </Form.Item>
        <Form.Item name="desc" label={t('备注信息')}>
          <Input.TextArea placeholder={t('请输入模板备注信息')}/>
        </Form.Item>
        <Form.Item shouldUpdate wrapperCol={{span: 14, offset: 6}}>
          {() => <Button disabled={canNext()} type="primary" onClick={handleNext}>{t('下一步')}</Button>}
        </Form.Item>
        {showTmp && <TemplateSelector onOk={handleSelect} onCancel={() => setShowTmp(false)}/>}
      </Form>
    </Container>
  )
})
