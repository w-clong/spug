/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react'
import { observer } from 'mobx-react';
import { Dropdown } from 'antd';
import { MoreOutlined, DeleteOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import Icon from './Icon';
import { clsNames, t } from 'libs';
import css from './node.module.less';
import S from './store';

function Node(props) {
  function handleNodeClick(e) {
    e.stopPropagation()
    S.node = props.node
  }

  function handleActionClick(e) {
    e.stopPropagation()
    S.actionNode = props.node
  }

  // ---- 画布拖拽：把节点拖到另一个节点上，调整为它的下游 ----
  function handleDragStart(e) {
    if (!props.onDragStart) return
    e.stopPropagation()
    e.dataTransfer.effectAllowed = 'move'
    // Firefox 必须写入数据才会触发 drag 流程
    e.dataTransfer.setData('text/plain', String(props.node.id))
    props.onDragStart(props.node)
  }

  function handleDragOver(e) {
    if (!props.canDrop) return
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'move'
  }

  function handleDragEnter(e) {
    if (!props.canDrop) return
    e.preventDefault()
    props.onDragEnter && props.onDragEnter(props.node)
  }

  function handleDragLeave(e) {
    e.stopPropagation()
    props.onDragLeave && props.onDragLeave()
  }

  function handleDrop(e) {
    if (!props.canDrop) return
    e.preventDefault()
    e.stopPropagation()
    props.onDrop && props.onDrop(props.node)
  }

  const menus = [
    {
      key: 'upstream',
      label: t('添加上游节点'),
      icon: <ArrowUpOutlined/>,
      onClick: props.onAction
    },
    {
      key: 'downstream',
      label: t('添加下游节点'),
      icon: <ArrowDownOutlined/>,
      onClick: props.onAction
    },
    {
      key: 'delete',
      danger: true,
      label: t('删除此节点'),
      icon: <DeleteOutlined/>,
      onClick: props.onAction
    }
  ]

  function dropdownRender(menus) {
    return (
      <div onMouseDown={e => e.stopPropagation()}>
        {menus}
      </div>
    )
  }

  const node = props.node
  switch (node) {
    case '  ':
      return <div className={css.box}/>
    case ' -':
      return <div className={clsNames(css.box, css.line)}/>
    case '--':
      return <div className={clsNames(css.box, css.line, css.line2)}/>
    case ' 7':
      return <div className={clsNames(css.box, css.angle)}/>
    case '-7':
      return <div className={clsNames(css.box, css.angle, css.angle2)}/>
    case ' |':
      return (
        <div className={clsNames(css.box, css.arrow)}>
          <div className={css.triangle}/>
        </div>
      )
    default:
      return (
        <React.Fragment>
          <div className={clsNames(css.box, css.node, S.node.id === node.id && css.active,
                                   props.isOver && css.dropTarget)}
               draggable
               title={t('拖拽到其他节点可调整上下游；Tab 加下游 / Enter 加同级 / Delete 删除')}
               onDragStart={handleDragStart}
               onDragEnd={props.onDragEnd}
               onDragOver={handleDragOver}
               onDragEnter={handleDragEnter}
               onDragLeave={handleDragLeave}
               onDrop={handleDrop}
               onMouseDown={handleNodeClick}>
            <Icon size={36} module={node.module}/>
            {node.name ? (
              <div className={css.title}>{node.name}</div>
            ) : (
              <div className={css.title} style={{color: '#595959'}}>{t('请选择节点模块')}</div>
            )}
            <Dropdown dropdownRender={dropdownRender} className={css.action}
                      trigger="click" menu={{items: menus}} onMouseDown={handleActionClick}>
              <MoreOutlined/>
            </Dropdown>
          </div>
          <div className={css.blank}/>
        </React.Fragment>
      )
  }
}

export default observer(Node)