/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { observer } from 'mobx-react';
import { Button, Popconfirm, message, Modal, Input } from 'antd';
import { RollbackOutlined, EditOutlined, ThunderboltOutlined, SaveOutlined } from '@ant-design/icons';
import NodeConfig from './NodeConfig';
import Console from './console';
import ContextPanel from './ContextPanel';
import PipeForm from './Form';
import Node from './Node';
import { transfer } from './utils';
import { history, t, http } from 'libs';
import S from './store';
import lds from 'lodash';
import css from './editor.module.less';

function Editor(props) {
  const params = useParams()
  const [nodes, setNodes] = useState([])
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (params.id === 'new') {
      S.record = {name: t('新建流水线'), nodes: []}
      handleAddDownstream()
    } else {
      S.fetchRecord(params.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if ((S.record?.nodes ?? []).length) {
      const data = transfer(S.record.nodes)
      setNodes(data)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [S.record])

  function handleAction({key, domEvent}) {
    domEvent.stopPropagation()
    switch (key) {
      case 'upstream':
        return handleAddUpstream()
      case 'downstream':
        return handleAddDownstream()
      case 'delete':
        return handleDelNode()
      default:
        return
    }
  }

  function _findIndexAndUpNode() {
    let index
    let [upNode, streamIdx] = [null, null]
    const id = S.actionNode.id
    for (let idx in S.record.nodes) {
      const node = S.record.nodes[idx]
      if (node.id === id) {
        index = Number(idx)
      }
      if (node.downstream) {
        idx = node.downstream.indexOf(id)
        if (idx >= 0) {
          upNode = node
          streamIdx = idx
        }
      }
    }
    return [index, upNode, streamIdx]
  }

  function handleAddUpstream() {
    const oldID = S.actionNode.id
    const newID = new Date().getTime()
    const newNode = {id: newID, downstream: [oldID]}
    const [index, upNode, streamIdx] = _findIndexAndUpNode()
    if (upNode) upNode.downstream.splice(streamIdx, 1, newID)
    S.record.nodes.splice(index, 0, newNode)
    S.record = {...S.record}
    S.node = newNode
  }

  function handleAddDownstream() {
    const oldID = S.actionNode.id
    const newID = new Date().getTime()
    // 必须复用 newID：两次 getTime() 跨毫秒时上游 downstream 会指向不存在的节点
    const newNode = {id: newID}
    if (S.record.nodes.length) {
      const idx = lds.findIndex(S.record.nodes, {id: oldID})
      if (S.record.nodes[idx].downstream) {
        S.record.nodes[idx].downstream.push(newID)
      } else {
        S.record.nodes[idx].downstream = [newID]
      }
      S.record.nodes.splice(idx + 1, 0, newNode)
    } else {
      S.record.nodes = [newNode]
    }
    S.record = {...S.record}
    S.node = newNode
  }

  function handleDelNode() {
    const {downstream} = S.actionNode
    const [index, upNode, streamIdx] = _findIndexAndUpNode()
    if (index === 0 && downstream && downstream.length > 1) {
      return message.error(t('该节点为起始节点且有多个下游节点无法删除'))
    }
    if (upNode) {
      upNode.downstream.splice(streamIdx, 1)
      if (downstream) {
        for (let item of downstream.slice().reverse()) {
          upNode.downstream.splice(streamIdx, 0, item)
        }
      }
    }
    S.record.nodes.splice(index, 1)
    S.record = {...S.record}
    S.updateRecord()
  }

  function handleRefresh(node) {
    const index = lds.findIndex(S.record.nodes, {id: node.id})
    S.record.nodes.splice(index, 1, node)
    return S.updateRecord()
  }

  function handleSaveBaseline() {
    const stateNodes = (S.record.nodes || []).filter(x => x.module === 'state' && x.state_module)
    if (!stateNodes.length) return message.error(t('当前流水线没有状态模块节点'))
    let name = `${S.record.name} 基线`
    Modal.confirm({
      title: t('保存为基线'),
      content: <Input defaultValue={name} onChange={e => name = e.target.value}/>,
      onOk: () => {
        if (!name) return message.error(t('请输入基线名称'))
        return http.post('/api/ops/baselines/', {
          name,
          description: t('从流水线 {} 导入', S.record.name),
          nodes: stateNodes.map(x => ({
            state_module: x.state_module,
            state_params: x.state_params || {},
          })),
        }).then(() => message.success(t('已保存到基线管理')))
      }
    })
  }

  return (
    <div className={css.container} onMouseDown={() => S.node = {}}>
      <div className={css.header}>
        <div className={css.title}>{S.record.name}</div>
        <EditOutlined className={css.edit} onClick={() => setVisible(true)}/>
        <div style={{flex: 1}}/>
        <Button className={css.back} type="link" icon={<SaveOutlined/>}
                onClick={handleSaveBaseline}>{t('存为基线')}</Button>
        <Popconfirm title={t('确定要执行吗？')} onConfirm={() => S.showConsole(S.record)}>
          <Button  className={css.back} type="link" icon={<ThunderboltOutlined/>}/>
        </Popconfirm>
        <Button className={css.back} type="link" icon={<RollbackOutlined/>}
                onClick={() => history.goBack()}>{t('返回列表')}</Button>
      </div>
      <div className={css.body}>
        <div className={css.nodes}>
          {nodes.map((row, idx) => (
            <div key={idx} className={css.row}>
              {row.map((item, idx) => (
                <Node key={idx} node={item} onAction={handleAction}/>
              ))}
            </div>
          ))}
        </div>
        <NodeConfig doRefresh={handleRefresh}/>
        <ContextPanel pipelineId={params.id}/>
      </div>
      {visible && <PipeForm onCancel={() => setVisible(false)}/>}
      <Console/>
    </div>
  )
}

export default observer(Editor)