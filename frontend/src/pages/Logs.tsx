import { useState, useCallback, useEffect } from 'react'
import { Card, Button, Space, Switch, Tag, Select } from 'antd'
import { ClearOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons'
import { getDockerContainers, useLogWebSocket } from '../api'
import LogConsole from '../components/LogConsole'
import type { LogEntry } from '../types'

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState<string>('all')
  const [source, setSource] = useState<'app' | 'container'>('app')
  const [service, setService] = useState('worker')
  const [container, setContainer] = useState('')
  const [containerOptions, setContainerOptions] = useState<Array<{ value: string; label: string }>>([])

  const onMessage = useCallback((entry: LogEntry) => {
    setLogs(prev => {
      const next = [...prev, entry]
      return next.length > 5000 ? next.slice(-5000) : next
    })
  }, [])

  const { connected } = useLogWebSocket(onMessage, { source, service, container, tail: 0 })

  useEffect(() => {
    setLogs([])
  }, [source, service, container])

  useEffect(() => {
    if (source !== 'container') {
      setContainer('')
      setContainerOptions([])
      return
    }
    getDockerContainers(service)
      .then((r) => {
        let names = (r.data || []) as string[]
        if (service === 'worker' && names.length === 0) {
          names = ['warp-worker-1', 'warp-worker-2', 'warp-worker-3']
        }
        const opts = names.map((name) => ({ value: name, label: name }))
        setContainerOptions(opts)
        if (opts.length === 0) {
          setContainer('')
          return
        }
        setContainer((prev) => (opts.some((o) => o.value === prev) ? prev : opts[0].value))
      })
      .catch(() => {
        setContainerOptions([])
        setContainer('')
      })
  }, [source, service])

  const filteredLogs = filter === 'all' ? logs : logs.filter(l => l.level === filter)

  return (
    <Card
      title={
        <Space>
          实时日志
          <Tag color={connected ? 'green' : 'red'}>{connected ? '已连接' : '未连接'}</Tag>
          <Tag>{logs.length} 条</Tag>
        </Space>
      }
      extra={
        <Space>
          <Select
            value={filter}
            onChange={setFilter}
            style={{ width: 100 }}
            options={[
              { value: 'all', label: '全部' },
              { value: 'info', label: '信息' },
              { value: 'success', label: '成功' },
              { value: 'warning', label: '待处理' },
              { value: 'error', label: '错误' },
            ]}
          />
          <Select
            value={source}
            onChange={(v: 'app' | 'container') => setSource(v)}
            style={{ width: 110 }}
            options={[
              { value: 'app', label: '应用日志' },
              { value: 'container', label: '容器日志' },
            ]}
          />
          {source === 'container' && (
            <>
              <Select
                value={service}
                onChange={setService}
                style={{ width: 110 }}
                options={[
                  { value: 'worker', label: 'worker' },
                  { value: 'warp', label: 'warp' },
                  { value: 'bot', label: 'bot' },
                ]}
              />
              <Select
                value={container || undefined}
                onChange={(v?: string) => setContainer(v || '')}
                style={{ width: 170 }}
                allowClear
                placeholder="全部容器"
                options={containerOptions}
              />
            </>
          )}
          <Switch
            checked={autoScroll}
            onChange={setAutoScroll}
            checkedChildren={<VerticalAlignBottomOutlined />}
            unCheckedChildren="滚动"
          />
          <Button icon={<ClearOutlined />} onClick={() => setLogs([])}>清空</Button>
        </Space>
      }
      styles={{ body: { padding: 0, height: 'calc(100vh - 220px)' } }}
    >
      <LogConsole logs={filteredLogs} autoScroll={autoScroll} />
    </Card>
  )
}
