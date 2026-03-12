import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography, message } from 'antd'
import { getAccounts, getTaskHistory, queryMailboxCode } from '../api'
import type { Account, HistoryRun, MailboxCodeResult } from '../types'

const { Text } = Typography

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [runs, setRuns] = useState<HistoryRun[]>([])
  const [selectedRun, setSelectedRun] = useState<string | undefined>()
  const [search, setSearch] = useState('')
  const [mailTokenInput, setMailTokenInput] = useState('')
  const [mailQueryResult, setMailQueryResult] = useState<MailboxCodeResult | null>(null)
  const [queryingMailCode, setQueryingMailCode] = useState(false)
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

  const handleMailCodeQuery = async (rawToken?: string) => {
    const token = String(rawToken ?? mailTokenInput).trim()
    if (!token) {
      message.warning('请先输入 mail_token')
      return
    }

    setQueryingMailCode(true)
    try {
      const { data } = await queryMailboxCode({ mail_token: token, timeout: 15 })
      setMailTokenInput(token)
      setMailQueryResult(data)
      if (data.status === 'ok' && data.verification_code) {
        message.success(`验证码 ${data.verification_code}`)
      } else {
        message.info(data.message || '暂未获取到验证码')
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail || '查询失败'
      message.error(detail)
      setMailQueryResult(null)
    } finally {
      setQueryingMailCode(false)
    }
  }

  const applyMailToken = (token?: string, autoQuery = false) => {
    if (!token) {
      message.warning('该账号还没有 mail_token')
      return
    }
    setMailTokenInput(token)
    if (autoQuery) {
      void handleMailCodeQuery(token)
    }
  }

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
      title: 'Mail Token',
      dataIndex: 'mail_token',
      key: 'mail_token',
      width: 260,
      render: (v?: string) => v ? (
        <Space direction="vertical" size={4}>
          <Text copyable={{ text: v }} ellipsis style={{ maxWidth: 220, display: 'inline-block' }}>{v}</Text>
          <Space size={4}>
            <Button size="small" onClick={() => applyMailToken(v)}>带入</Button>
            <Button size="small" type="primary" ghost onClick={() => void handleMailCodeQuery(v)}>查码</Button>
          </Space>
        </Space>
      ) : '-',
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
      <Card size="small" title="验证码查询" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Input
              placeholder="粘贴 mail_token 后查询该邮箱最新验证码"
              value={mailTokenInput}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setMailTokenInput(e.target.value)}
              allowClear
              style={{ flex: 1, minWidth: 320 }}
            />
            <Button type="primary" loading={queryingMailCode} onClick={() => void handleMailCodeQuery()}>
              查询验证码
            </Button>
          </div>
          {mailQueryResult && (
            <Alert
              showIcon
              type={mailQueryResult.status === 'ok' ? 'success' : 'info'}
              message={
                mailQueryResult.status === 'ok' && mailQueryResult.verification_code
                  ? `验证码：${mailQueryResult.verification_code}`
                  : (mailQueryResult.message || '暂未获取到验证码')
              }
              description={
                <Space size={8} wrap>
                  <Text copyable={{ text: mailQueryResult.email }}>{mailQueryResult.email}</Text>
                  {mailQueryResult.verification_code ? (
                    <Text copyable={{ text: mailQueryResult.verification_code }}>
                      {mailQueryResult.verification_code}
                    </Text>
                  ) : null}
                  {mailQueryResult.received_at ? <Tag>{mailQueryResult.received_at}</Tag> : null}
                  {mailQueryResult.subject ? <Tag color="blue">{mailQueryResult.subject}</Tag> : null}
                  {mailQueryResult.hint ? <Text type="secondary">{mailQueryResult.hint}</Text> : null}
                </Space>
              }
            />
          )}
        </Space>
      </Card>
      <Table
        dataSource={filtered}
        columns={columns}
        rowKey="email"
        loading={loading}
        pagination={{ pageSize: 20 }}
        size="middle"
        scroll={{ x: 1200 }}
      />
    </Card>
  )
}
