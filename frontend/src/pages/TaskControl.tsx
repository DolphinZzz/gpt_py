import { useEffect, useState } from 'react'
import { Card, Button, Tag, Progress, Descriptions, Space, message, InputNumber, Input, Switch } from 'antd'
import { PlayCircleOutlined, StopOutlined, SyncOutlined } from '@ant-design/icons'
import { startTask, stopTask, getTaskStatus, getConfig } from '../api'
import type { Config, TaskStatus } from '../types'

const statusMap: Record<string, { color: string; label: string }> = {
  idle: { color: 'default', label: '空闲' },
  running: { color: 'processing', label: '运行中' },
  stopping: { color: 'warning', label: '停止中' },
  finished: { color: 'success', label: '已完成' },
  stopped: { color: 'error', label: '已停止' },
}

export default function TaskControl() {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [startOptions, setStartOptions] = useState({
    total_accounts: 3,
    max_workers: 3,
    proxy: '',
    use_containers: false,
    container_count: 1,
  })
  const [useSavedConfig, setUseSavedConfig] = useState(true)

  const fetchStatus = () => {
    getTaskStatus().then(r => setStatus(r.data))
  }

  useEffect(() => {
    getConfig().then((r) => {
      const cfg = r.data as Partial<Config>
      setStartOptions(prev => ({
        ...prev,
        total_accounts: cfg.total_accounts ?? prev.total_accounts,
        max_workers: cfg.max_workers ?? prev.max_workers,
        proxy: cfg.proxy ?? prev.proxy,
        use_containers: cfg.use_containers ?? prev.use_containers,
        container_count: cfg.container_count ?? prev.container_count,
      }))
    }).catch(() => {})
    fetchStatus()
    const t = setInterval(fetchStatus, 2000)
    return () => clearInterval(t)
  }, [])

  const handleStart = async () => {
    try {
      if (useSavedConfig) {
        await startTask()
      } else {
        await startTask(startOptions)
      }
      message.success('任务已启动')
      fetchStatus()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
    }
  }

  const handleStop = async () => {
    try {
      await stopTask()
      message.info('正在停止任务...')
      fetchStatus()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '停止失败')
    }
  }

  const s = status
  const running = s?.status === 'running'
  const stopping = s?.status === 'stopping'
  const total = s?.total_target || 0
  const done = (s?.success_count || 0) + (s?.fail_count || 0)
  const shownDone = total > 0 ? Math.min(done, total) : done
  const percent = total > 0 ? Math.round(shownDone / total * 100) : 0
  const info = statusMap[s?.status || 'idle'] || statusMap.idle
  const isContainerMode = (s?.mode || (startOptions.use_containers ? 'containers' : 'local')) === 'containers'

  return (
    <div>
      <Card title="任务控制">
        <Space style={{ marginBottom: 16 }} wrap>
          <Space>
            <span>使用已保存配置启动</span>
            <Switch checked={useSavedConfig} onChange={setUseSavedConfig} />
          </Space>
          <InputNumber
            min={1}
            max={100000}
            addonBefore="目标"
            value={startOptions.total_accounts}
            onChange={(v) => setStartOptions(p => ({ ...p, total_accounts: v || 1 }))}
            disabled={useSavedConfig}
          />
          <InputNumber
            min={1}
            max={200}
            addonBefore="容器内并发"
            value={startOptions.max_workers}
            onChange={(v) => setStartOptions(p => ({ ...p, max_workers: v || 1 }))}
            disabled={useSavedConfig}
          />
          <Space>
            <span>容器模式</span>
            <Switch
              checked={startOptions.use_containers}
              onChange={(checked) => setStartOptions(p => ({ ...p, use_containers: checked }))}
              disabled={useSavedConfig}
            />
          </Space>
          {startOptions.use_containers && (
            <InputNumber
              min={1}
              max={100}
              addonBefore="容器数量"
              value={startOptions.container_count}
              onChange={(v) => setStartOptions(p => ({ ...p, container_count: v || 1 }))}
              disabled={useSavedConfig}
            />
          )}
          <Input
            style={{ width: 320 }}
            placeholder="代理地址，可选"
            value={startOptions.proxy}
            onChange={(e) => setStartOptions(p => ({ ...p, proxy: e.target.value }))}
            disabled={useSavedConfig}
          />
        </Space>

        <Space size="middle" style={{ marginBottom: 24 }}>
          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            onClick={handleStart}
            disabled={running || stopping}
          >
            启动注册
          </Button>
          <Button
            danger
            size="large"
            icon={<StopOutlined />}
            onClick={handleStop}
            disabled={!running}
          >
            停止任务
          </Button>
          <Button icon={<SyncOutlined />} onClick={fetchStatus}>刷新</Button>
        </Space>

        <Descriptions bordered column={2}>
          <Descriptions.Item label="状态">
            <Tag color={info.color}>{info.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="执行模式">
            <Tag color={isContainerMode ? 'blue' : 'default'}>{isContainerMode ? '容器' : '本地'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="任务 ID">{s?.task_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{s?.start_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="已用时间">
            {s?.elapsed_seconds != null ? `${s.elapsed_seconds}s` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="目标数量">{total}</Descriptions.Item>
          <Descriptions.Item label="已完成">{shownDone} / {total}</Descriptions.Item>
          <Descriptions.Item label="成功">
            <span style={{ color: '#3f8600', fontWeight: 600 }}>{s?.success_count || 0}</span>
          </Descriptions.Item>
          <Descriptions.Item label="失败">
            <span style={{ color: '#cf1322', fontWeight: 600 }}>{s?.fail_count || 0}</span>
          </Descriptions.Item>
          {isContainerMode && (
            <Descriptions.Item label="容器运行数">
              {(s?.container_running ?? 0)} / {(s?.container_target ?? startOptions.container_count)}
            </Descriptions.Item>
          )}
        </Descriptions>

        {(running || stopping) && (
          <div style={{ marginTop: 24 }}>
            <Progress
              percent={percent}
              status={stopping ? 'exception' : 'active'}
              format={() => `${shownDone}/${total}`}
              strokeColor={stopping ? '#ff4d4f' : undefined}
            />
          </div>
        )}
      </Card>
    </div>
  )
}
