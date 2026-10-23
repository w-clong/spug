/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, Dropdown, Button, Avatar, Tooltip, Space, Tag, Radio, Input, message, Drawer, Card } from 'antd';
import { PlusOutlined, DownOutlined, SyncOutlined, FormOutlined, ExportOutlined, FileTextOutlined, AppstoreOutlined, ReloadOutlined } from '@ant-design/icons';
import { Action, TableCard, AuthButton, AuthFragment } from 'components';
import IPAddress from './IPAddress';
import { http, hasPermission, blobToExcel, humanDate, t, X_TOKEN } from 'libs';
import store from './store';
import icons from './icons';
import moment from 'moment';

function ComTable() {
  const [loading, setLoading] = useState(false)
  const [facts, setFacts] = useState(null)
  const [factsHost, setFactsHost] = useState(null)
  const [factsMeta, setFactsMeta] = useState({})
  const [cardVisible, setCardVisible] = useState(false)

  useEffect(() => {
    loadFacts()
  }, [])

  function loadFacts() {
    http.get('/api/ops/facts/', { params: { with_meta: 1 } }).then(res => setFactsMeta(res || {}))
  }

  function handleRefreshFacts() {
    const ids = store.dataSource.map(x => x.id)
    if (!ids.length) return message.warning(t('暂无主机'))
    setLoading(true)
    http.post('/api/ops/facts/', { host_ids: ids })
      .then(() => {
        message.success(t('已开始采集系统信息，请稍后查看'))
        setTimeout(loadFacts, 4000)
      })
      .finally(() => setLoading(false))
  }

  function showFacts(host) {
    http.get('/api/ops/facts/', { params: { host_id: host.id } }).then(res => {
      setFactsHost(host)
      setFacts(res)
    })
  }

  function handleDelete(text) {
    Modal.confirm({
      title: t('删除确认'),
      content: t('确定要删除【{}】?', text['name']),
      onOk: () => {
        return http.delete('/api/host/', {params: {id: text.id}})
          .then(() => {
            message.success(t('删除成功'));
            store.fetchRecords()
          })
      }
    })
  }

  function handleImport(menu) {
    if (menu.key === 'excel') {
      store.importVisible = true
    } else if (menu.key === 'json') {
      handleJsonImport()
    } else if (menu.key === 'form') {
      store.showForm({group_ids: [store.group.value]})
    } else {
      store.cloudImport = menu.key
    }
  }

  function handleJsonImport() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,application/json'
    input.onchange = () => {
      const file = input.files[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => {
        try {
          const data = JSON.parse(reader.result)
          http.post('/api/host/import/json/', data).then(res => {
            message.success(t('导入完成：新增 {} 台，跳过 {} 台', res.created, res.skipped))
            store.fetchRecords()
          })
        } catch (e) {
          message.error(t('JSON 解析失败'))
        }
      }
      reader.readAsText(file)
    }
    input.click()
  }

  function handleExport() {
    setLoading(true)
    http.post('/api/host/export/', {ids: store.dataSource.map(x => x.id)}, {responseType: 'blob', timeout: 60000})
      .then(res => blobToExcel(res.data, `${humanDate()}_${t('主机列表')}.xlsx`))
      .finally(() => setLoading(false))
  }

  function ExpTime(props) {
    if (!props.value) return null
    let value = moment(props.value)
    const days = value.diff(moment(), 'days')
    if (days > 30) {
      return <span>{t('剩余')} <b style={{color: '#389e0d'}}>{days}</b> {t('天')}</span>
    } else if (days > 7) {
      return <span>{t('剩余')} <b style={{color: '#faad14'}}>{days}</b> {t('天')}</span>
    } else if (days >= 0) {
      return <span>{t('剩余')} <b style={{color: '#d9363e'}}>{days}</b> {t('天')}</span>
    } else {
      return <span>{t('过期')} <b style={{color: '#d9363e'}}>{Math.abs(days)}</b> {t('天')}</span>
    }
  }

  return (
    <>
    <TableCard
      tKey="hi"
      rowKey="id"
      title={<Input allowClear value={store.f_word} placeholder={t('输入名称/IP检索')} style={{maxWidth: 250}}
                    onChange={e => store.f_word = e.target.value}/>}
      loading={store.isFetching}
      dataSource={store.dataSource}
      onReload={store.fetchRecords}
      actions={[
        <AuthFragment auth="host.host.add">
          <Dropdown menu={{
            onClick: handleImport,
            items: [
              {
                key: 'form',
                label: (
                  <Space>
                    <FormOutlined style={{fontSize: 16, marginRight: 4, color: '#1890ff'}}/>
                    <span>{t('新建主机')}</span>
                  </Space>
                )
              },
              {
                key: 'excel',
                label: (
                  <Space>
                    <Avatar shape="square" size={20} src={icons.excel}/>
                    <span>Excel</span>
                  </Space>
                )
              },
              {
                key: 'json',
                label: (
                  <Space>
                    <FileTextOutlined style={{fontSize: 16, marginRight: 4, color: '#1890ff'}}/>
                    <span>{t('JSON 备份')}</span>
                  </Space>
                )
              },
              {
                key: 'ali',
                label: (
                  <Space>
                    <Avatar shape="square" size={20} src={icons.alibaba}/>
                    <span>{t('阿里云')}</span>
                  </Space>
                )
              },
              {
                key: 'tencent',
                label: (
                  <Space>
                    <Avatar shape="square" size={20} src={icons.tencent}/>
                    <span>{t('腾讯云')}</span>
                  </Space>
                )
              }
            ]
          }}>
            <Button type="primary" icon={<PlusOutlined/>}>{t('新建')} <DownOutlined/></Button>
          </Dropdown>
        </AuthFragment>,
        <AuthButton
          auth="host.host.view"
          type="primary"
          loading={loading}
          icon={<ExportOutlined/>}
          onClick={handleExport}>{t('导出')}</AuthButton>,
        <AuthButton
          auth="host.host.view"
          type="primary"
          icon={<ExportOutlined/>}
          onClick={() => window.open(`/api/host/export/json/?x-token=${X_TOKEN}`)}>
          {t('导出 JSON')}
        </AuthButton>,
        <AuthButton
          auth="host.host.add"
          type="primary"
          icon={<SyncOutlined/>}
          onClick={() => store.showSync()}>{t('验证')}</AuthButton>,
        <AuthButton
          auth="host.host.view"
          type="primary"
          icon={<ReloadOutlined/>}
          loading={loading}
          onClick={handleRefreshFacts}>{t('刷新Facts')}</AuthButton>,
        <AuthButton
          auth="host.host.view"
          type="primary"
          icon={<AppstoreOutlined/>}
          onClick={() => setCardVisible(true)}>{t('卡片')}</AuthButton>,
        <Radio.Group value={store.f_status} onChange={e => store.f_status = e.target.value}>
          <Radio.Button value="">{t('全部')}</Radio.Button>
          <Radio.Button value={false}>{t('未验证')}</Radio.Button>
        </Radio.Group>
      ]}
      pagination={{
        showSizeChanger: true,
        showLessItems: true,
        hideOnSinglePage: true,
        showTotal: total => t('共 {} 条', total),
        pageSizeOptions: ['10', '20', '50', '100']
      }}>
      <Table.Column
        showSorterTooltip={false}
        title={t('主机名称')}
        render={info => <Action.Button onClick={() => store.showDetail(info)}>{info.name}</Action.Button>}
        sorter={(a, b) => a.name.localeCompare(b.name)}/>
      <Table.Column title={t('IP地址')} render={info => (
        <div>
          <IPAddress ip={info.public_ip_address} isPublic/>
          <IPAddress ip={info.private_ip_address}/>
        </div>
      )}/>
      <Table.Column title={t('配置信息')} render={info => (
        <Space>
          <Tooltip title={info.os_name}>
            <Avatar shape="square" size={16} src={icons[info.os_type]}/>
          </Tooltip>
          <span>{t('{}核 {}GB', info.cpu, info.memory)}</span>
        </Space>
      )}/>
      <Table.Column title={t('系统')} width={210} render={info => {
        const meta = factsMeta[info.id]
        const f = meta && meta.facts
        if (!f) return <span style={{color: '#999'}}>{t('未采集')}</span>
        return (
          <div>
            <div>{f.os_family} {f.os_version}</div>
            <div style={{color: '#999', fontSize: 12}}>
              {f.memory_total_mb ? `${(f.memory_total_mb / 1024).toFixed(1)} GB` : ''}
              {meta.updated_at ? ` · ${meta.updated_at.slice(5, 16)}` : ''}
            </div>
          </div>
        )
      }}/>
      <Table.Column hide title={t('到期信息')} dataIndex="expired_time" render={v => <ExpTime value={v}/>}/>
      <Table.Column hide title={t('备注信息')} dataIndex="desc"/>
      <Table.Column
        title={t('状态')}
        dataIndex="is_verified"
        render={v => v ? <Tag color="green">{t('已验证')}</Tag> : <Tag color="orange">{t('未验证')}</Tag>}/>
      {hasPermission('host.host.edit|host.host.del|host.host.console') && (
        <Table.Column width={160} title={t('操作')} render={info => (
          <Action>
            <Action.Button auth="host.host.view" onClick={() => showFacts(info)}>{t('Facts')}</Action.Button>
            <Action.Button auth="host.host.edit" onClick={() => store.showForm(info)}>{t('编辑')}</Action.Button>
            <Action.Button danger auth="host.host.del" onClick={() => handleDelete(info)}>{t('删除')}</Action.Button>
          </Action>
        )}/>
      )}
    </TableCard>
    <Drawer width={520} title={factsHost ? `${factsHost.name} · ${t('Facts')}` : t('Facts')}
            visible={!!facts} onClose={() => setFacts(null)}>
      {facts && (
        <Table size="small" rowKey="key" pagination={false}
               dataSource={Object.entries(facts).map(([key, value]) => ({
                 key,
                 value: typeof value === 'object' ? JSON.stringify(value) : String(value),
               }))}>
          <Table.Column title={t('键')} dataIndex="key" width={180}/>
          <Table.Column title={t('值')} dataIndex="value"/>
        </Table>
      )}
      {facts && Object.keys(facts).length === 0 && (
        <div style={{ color: '#999' }}>{t('暂无 Facts 缓存，可在批量执行/流水线中触发刷新')}</div>
      )}
    </Drawer>
    <Modal width={1020} visible={cardVisible} footer={null} title={t('主机卡片')}
           onCancel={() => setCardVisible(false)}>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
        gap: 16, maxHeight: '70vh', overflow: 'auto', paddingRight: 4,
      }}>
        {store.dataSource.map(info => {
          const meta = factsMeta[info.id]
          const f = meta && meta.facts
          return (
            <Card key={info.id} size="small" hoverable>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                <b>{info.name}</b>
                <Tag color={info.is_verified ? 'green' : 'orange'}>
                  {info.is_verified ? t('已验证') : t('未验证')}
                </Tag>
              </div>
              <div style={{color: '#666', marginTop: 6}}>
                {info.username}@{info.hostname}:{info.port || 22}
              </div>
              <div style={{marginTop: 8}}>
                {f ? `${f.os_family || ''} ${f.os_version || ''}` : <span style={{color: '#999'}}>{t('未采集 Facts')}</span>}
              </div>
              <div style={{color: '#999', fontSize: 12, minHeight: 18}}>
                {f && f.memory_total_mb ? `${(f.memory_total_mb / 1024).toFixed(1)} GB · ` : ''}
                {meta && meta.updated_at ? t('采集于 {}', meta.updated_at.slice(5, 16)) : ''}
              </div>
              <Space style={{marginTop: 12}}>
                <Button size="small" onClick={() => store.showDetail(info)}>{t('详情')}</Button>
                <Button size="small" onClick={() => showFacts(info)}>{t('Facts')}</Button>
                <Button size="small" onClick={() => store.showForm(info)}>{t('编辑')}</Button>
              </Space>
            </Card>
          )
        })}
      </div>
    </Modal>
    </>
  )
}

export default observer(ComTable)
