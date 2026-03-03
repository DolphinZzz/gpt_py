import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { getTaskHistory } from '../api'
import type { HistoryRun } from '../types'

export default function History() {
  const [data, setData] = useState<HistoryRun[]>([])
  const [loading, setLoading] = useState(true)

  const fetchHistory = () => {
    setLoading(true)
    getTaskHistory()
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchHistory() }, [])

  const download = (runId: string, fileType: string) => {
    window.open(`/api/accounts/${runId}/download/${fileType}`, '_blank')
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
    },
    {
      title: '批次 ID',
      dataIndex: 'run_id',
      key: 'run_id',
      width: 160,
    },
    {
      title: '总数',
      dataIndex: 'total_accounts',
      key: 'total_accounts',
      width: 80,
      align: 'center' as const,
    },
    {
      title: '成功',
      dataIndex: 'success_count',
      key: 'success_count',
      width: 80,
      align: 'center' as const,
      render: (v: number) => <Tag color="green">{v}</Tag>,
    },
    {
      title: '失败',
      dataIndex: 'fail_count',
      key: 'fail_count',
      width: 80,
      align: 'center' as const,
      render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : <Tag>{v}</Tag>,
    },
    {
      title: '成功率',
      key: 'rate',
      width: 100,
      align: 'center' as const,
      render: (_: unknown, r: HistoryRun) => {
        const rate = r.total_accounts > 0 ? Math.round(r.success_count / r.total_accounts * 100) : 0
        return <Tag color={rate >= 50 ? 'green' : 'red'}>{rate}%</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, r: HistoryRun) => (
        <Space size="small">
          <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r.run_id, 'ak')}>AK</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r.run_id, 'rk')}>RK</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r.run_id, 'accounts')}>账号</Button>
        </Space>
      ),
    },
  ]

  return (
    <Card title="历史记录" extra={
      <Button icon={<ReloadOutlined />} onClick={fetchHistory}>刷新</Button>
    }>
      <Table
        dataSource={data}
        columns={columns}
        rowKey="run_id"
        loading={loading}
        pagination={{ pageSize: 15 }}
        size="middle"
      />
    </Card>
  )
}
