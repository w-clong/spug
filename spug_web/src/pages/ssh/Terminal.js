/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState, useRef, useLayoutEffect } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { Select, Button, message } from 'antd';
import { StarOutlined } from '@ant-design/icons';
import { X_TOKEN, t } from 'libs';
import 'xterm/css/xterm.css';
import styles from './index.module.less';
import gStore from 'gStore';

const FAV_KEY = 'spug_cmd_favorites';

function loadFavorites() {
  try {
    return JSON.parse(localStorage.getItem(FAV_KEY) || '[]')
  } catch (e) {
    return []
  }
}

function WebSSH(props) {
  const container = useRef();
  const socketRef = useRef();
  const lineRef = useRef('');
  const [term] = useState(new Terminal());
  const [fitPlugin] = useState(new FitAddon());
  const [favorites, setFavorites] = useState(loadFavorites);

  useEffect(() => {
    term.loadAddon(fitPlugin);
    term.options.fontSize = gStore.terminal.fontSize;
    term.options.fontFamily = gStore.terminal.fontFamily;
    term.options.theme = gStore.terminal.styles;
    term.attachCustomKeyEventHandler((arg) => {
      if (arg.code === 'PageUp' && arg.type === 'keydown') {
        term.scrollPages(-1)
        return false
      } else if (arg.code === 'PageDown' && arg.type === 'keydown') {
        term.scrollPages(1)
        return false
      }
      return true
    })
    term.open(container.current);
    term.write('WebSocket connecting ... ');
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/ssh/${props.id}/?x-token=${X_TOKEN}`);
    socketRef.current = socket;
    socket.onmessage = e => term.write(e.data)
    socket.onopen = () => {
      term.write('ok')
      term.focus();
      fitTerminal();
    };
    socket.onclose = e => {
      setTimeout(() => term.write('\r\n\r\n\x1b[31mConnection is closed.\x1b[0m\r\n'), 200)
    };
    term.onData(data => {
      socket.send(JSON.stringify({data}));
      // 维护当前输入行，用于「收藏常用命令」；忽略方向键等控制序列
      if (data === '\r' || data === '\n') {
        lineRef.current = ''
      } else if (data === '\x7f') {
        lineRef.current = lineRef.current.slice(0, -1)
      } else if (!data.startsWith('\x1b')) {
        lineRef.current += data
      }
    });
    term.onResize(({cols, rows}) => {
      if (socket.readyState === 1) {
        socket.send(JSON.stringify({resize: [cols, rows]}))
      }
    });
    window.addEventListener('resize', fitTerminal)

    return () => {
      window.removeEventListener('resize', fitTerminal);
      if (socket) socket.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    term.options.fontSize = gStore.terminal.fontSize;
    term.options.fontFamily = gStore.terminal.fontFamily;
    term.options.theme = gStore.terminal.styles;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gStore.terminal])

  useEffect(() => {
    if (props.vId === props.activeId) {
      setTimeout(() => term.focus())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.activeId])

  useLayoutEffect(fitTerminal)

  function fitTerminal() {
    if (props.vId === props.activeId) {
      const dims = fitPlugin.proposeDimensions();
      if (!dims || !term || !dims.cols || !dims.rows) return;
      if (term.rows !== dims.rows || term.cols !== dims.cols) {
        term._core._renderService.clear();
        term.resize(dims.cols, dims.rows);
      }
    }
  }

  function handleSend(value) {
    const socket = socketRef.current;
    if (socket && socket.readyState === 1) {
      socket.send(JSON.stringify({data: value + '\r'}));
      term.focus();
    }
  }

  function handleFavorite() {
    const command = lineRef.current.trim();
    if (!command) return message.warning(t('请先输入要收藏的命令'));
    const next = Array.from(new Set([command, ...favorites])).slice(0, 50);
    localStorage.setItem(FAV_KEY, JSON.stringify(next));
    setFavorites(next);
    message.success(t('已收藏'));
  }

  return (
    <div className={styles.terminal} style={{position: 'relative'}}>
      <div ref={container} style={{width: '100%', height: '100%'}}/>
      <div style={{position: 'absolute', top: 8, right: 24, zIndex: 10, display: 'flex', gap: 8}}>
        <Select
          size="small"
          style={{width: 240}}
          placeholder={t('常用命令')}
          showSearch
          value={undefined}
          options={favorites.map(x => ({value: x, label: x}))}
          onChange={handleSend}/>
        <Button size="small" icon={<StarOutlined/>} onClick={handleFavorite}>{t('收藏')}</Button>
      </div>
    </div>
  )
}

export default WebSSH
