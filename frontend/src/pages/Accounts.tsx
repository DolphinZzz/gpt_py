import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Card, Table, Select, Input, Tag, Typography } from 'antd'
import { getAccounts, getTaskHistory } from '../api'
import type { Account, HistoryRun } from '../types'

const { Text } = Typography

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [runs, setRuns] = useState<HistoryRun[]>([])
  const [selectedRun, setSelectedRun] = useState<string | undefined>()
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getTaskHistory().then(r => {
      setRuns(r.data)
      if (r.data.length > 0) {
        setSelectedRun(r.data[0].run_id)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedRun) { setLoading(false); return }
    setLoading(true)
    getAccounts(selectedRun)
      .then(r => setAccounts(r.data))
      .finally(() => setLoading(false))
  }, [selectedRun])

  const filtered = search
    ? accounts.filter(a => a.email.toLowerCase().includes(search.toLowerCase()))
    : accounts

  const columns = [
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      width: 250,
      render: (v: string) => <Text copyable={{ text: v }}>{v}</Text>,
    },
    {
      title: '密码',
      dataIndex: 'password',
      key: 'password',
      width: 160,
      render: (v: string) => <Text copyable={{ text: v }}>{v}</Text>,
    },
    {
      title: 'OAuth',
      dataIndex: 'oauth_status',
      key: 'oauth_status',
      width: 80,
      align: 'center' as const,
      render: (v: string) => <Tag color={v === 'ok' ? 'green' : 'red'}>{v}</Tag>,
    },
    {
      title: 'Access Token',
      dataIndex: 'access_token',
      key: 'access_token',
      ellipsis: true,
      render: (v?: string) => v ? <Text copyable={{ text: v }} ellipsis style={{ maxWidth: 200 }}>{v.slice(0, 30)}...</Text> : '-',
    },
    {
      title: 'Refresh Token',
      dataIndex: 'refresh_token',
      key: 'refresh_token',
      ellipsis: true,
      render: (v?: string) => v ? <Text copyable={{ text: v }} ellipsis style={{ maxWidth: 200 }}>{v.slice(0, 30)}...</Text> : '-',
    },
  ]

  return (
    <Card title="账号列表" extra={
      <div style={{ display: 'flex', gap: 8 }}>
        <Select
          value={selectedRun}
          onChange={setSelectedRun}
          style={{ width: 200 }}
          placeholder="选择批次"
          options={runs.map(r => ({ value: r.run_id, label: `${r.timestamp} (${r.total_accounts})` }))}
        />
        <Input.Search
          placeholder="搜索邮箱"
          value={search}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
          style={{ width: 200 }}
          allowClear
        />
      </div>
    }>
      <Table
        dataSource={filtered}
        columns={columns}
        rowKey="email"
        loading={loading}
        pagination={{ pageSize: 20 }}
        size="middle"
        scroll={{ x: 900 }}
      />
    </Card>
  )
}
