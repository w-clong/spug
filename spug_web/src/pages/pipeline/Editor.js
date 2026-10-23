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
  // 画布拖拽：拖动一个节点放到另一个节点上，即把前者调整为后者的下游
  const [dragNode, setDragNode] = useState(null)
  const [overId, setOverId] = useState(null)

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

  // 连续快速添加时 Date.now() 可能重复，碰撞会让 upstream/downstream 指向同一个 id
  function _newNodeID() {
    const used = new Set((S.record.nodes || []).map(x => x.id))
    let id = Date.now()
    while (used.has(id)) id += 1
    return id
  }

  function handleAddUpstream() {
    const oldID = S.actionNode.id
    const newID = _newNodeID()
    const newNode = {id: newID, downstream: [oldID]}
    const [index, upNode, streamIdx] = _findIndexAndUpNode()
    if (upNode) upNode.downstream.splice(streamIdx, 1, newID)
    S.record.nodes.splice(index, 0, newNode)
    S.record = {...S.record}
    S.node = newNode
  }

  function handleAddDownstream() {
    const oldID = S.actionNode.id
    const newID = _newNodeID()
    // 必须复用 newID：两次取时间戳跨毫秒时上游 downstream 会指向不存在的节点
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

  // 同级节点：与当前节点共用同一个上游（XMind 里 Enter 的行为）
  function handleAddSibling() {
    const cur = S.node
    const nodes = S.record.nodes || []
    const index = nodes.findIndex(x => x.id === cur.id)
    if (index < 0) return
    const parent = nodes.find(x => (x.downstream || []).includes(cur.id))
    if (!parent) {
      // 起始节点没有上游，没有“同级”可言，退化为添加下游
      return handleAddDownstream()
    }
    const newID = _newNodeID()
    const newNode = {id: newID}
    parent.downstream = [...(parent.downstream || []), newID]
    nodes.splice(index + 1, 0, newNode)
    S.record = {...S.record}
    S.node = newNode
  }

  // ---- 键盘快捷键：先点选节点，再 Tab/Enter/Delete 操作 ----
  useEffect(() => {
    function isEditing(el) {
      if (!el) return false
      const tag = (el.tagName || '').toLowerCase()
      return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable
    }

    function onKeyDown(e) {
      if (isEditing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return
      // 弹窗/抽屉/下拉里的按键交给控件自己处理，避免误删节点
      if (e.target.closest && e.target.closest('.ant-modal-root, .ant-drawer, .ant-dropdown, .ant-select-dropdown')) return
      const node = S.node || {}
      if (node.id === undefined || node.id === null) return
      if (e.key === 'Tab') {
        e.preventDefault()
        S.actionNode = node
        if (e.shiftKey) {
          handleAddUpstream()
        } else {
          handleAddDownstream()
        }
      } else if (e.key === 'Enter') {
        e.preventDefault()
        S.actionNode = node
        handleAddSibling()
      } else if (e.key === 'Delete') {
        e.preventDefault()
        S.actionNode = node
        handleDelNode()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleDragStart(node) {
    setDragNode(node)
  }

  function handleDragEnd() {
    setDragNode(null)
    setOverId(null)
  }

  // 收集某个节点能到达的所有下游节点 id（用于环检测）
  function _collectDescendants(id, acc = new Set()) {
    const node = (S.record.nodes || []).find(x => x.id === id)
    if (!node) return acc
    for (const key of node.downstream || []) {
      if (!acc.has(key)) {
        acc.add(key)
        _collectDescendants(key, acc)
      }
    }
    return acc
  }

  function handleDrop(targetNode) {
    const source = dragNode
    setDragNode(null)
    setOverId(null)
    if (!source || !targetNode || source.id === targetNode.id) return
    const allNodes = S.record.nodes || []
    const sourceNode = allNodes.find(x => x.id === source.id)
    const target = allNodes.find(x => x.id === targetNode.id)
    if (!sourceNode || !target) return
    // 起始节点（数组第一项）是流程入口，必须没有上游
    if (allNodes[0] && allNodes[0].id === sourceNode.id) {
      return message.error(t('起始节点不能调整为其他节点的下游'))
    }
    if (_collectDescendants(sourceNode.id).has(target.id)) {
      return message.error(t('不能形成循环依赖'))
    }
    // 每个节点只保留一个上游：先从所有上游中摘除 source，再挂到 target 下
    for (const item of allNodes) {
      if (item.downstream) {
        item.downstream = item.downstream.filter(x => x !== sourceNode.id)
      }
    }
    target.downstream = [...(target.downstream || []).filter(x => x !== sourceNode.id), sourceNode.id]
    S.record = {...S.record}
    // 新建但尚未保存的流水线没有 id，先只更新本地画布，保存时一并提交
    if (S.record.id) S.updateRecord()
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
        <span className={css.tip}>
          {t('拖拽节点可调整上下游；选中节点后：Tab 加下游 / Enter 加同级 / Shift+Tab 加上游 / Delete 删除')}
        </span>
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
                <Node
                  key={typeof item === 'string' ? `p-${idx}` : item.id}
                  node={item}
                  onAction={handleAction}
                  onDragStart={handleDragStart}
                  onDragEnd={handleDragEnd}
                  onDragEnter={node => setOverId(node.id)}
                  onDragLeave={() => setOverId(null)}
                  onDrop={handleDrop}
                  canDrop={!!dragNode && dragNode.id !== item.id}
                  isOver={typeof item !== 'string' && overId === item.id}/>
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