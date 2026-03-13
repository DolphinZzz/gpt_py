import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography, message } from 'antd'
import { getAccounts, getTaskHistory, queryMailboxCode, refreshAccountTokens } from '../api'
import type { Account, HistoryRun, MailboxCodeResult, RefreshAccountTokenItem } from '../types'

const { Text } = Typography
const ALL_RUNS_VALUE = '__all__'

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [runs, setRuns] = useState<HistoryRun[]>([])
  const [selectedRun, setSelectedRun] = useState<string>(ALL_RUNS_VALUE)
  const [search, setSearch] = useState('')
  const [mailTokenInput, setMailTokenInput] = useState('')
  const [mailQueryResult, setMailQueryResult] = useState<MailboxCodeResult | null>(null)
  const [queryingMailCode, setQueryingMailCode] = useState(false)
  const [refreshingAllTokens, setRefreshingAllTokens] = useState(false)
  const [refreshingRowKeys, setRefreshingRowKeys] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getTaskHistory().then(r => {
      setRuns(r.data)
    })
  }, [])

  useEffect(() => {
    setLoading(true)
    getAccounts(selectedRun === ALL_RUNS_VALUE ? undefined : selectedRun)
      .then(r => setAccounts(r.data))
      .finally(() => setLoading(false))
  }, [selectedRun])

  const getAccountKey = (account: Pick<Account, 'email' | 'run_id' | 'line_no'>) =>
    `${account.run_id || 'all'}:${account.line_no ?? 'na'}:${account.email}`

  const filtered = search
    ? accounts.filter(a => {
      const keyword = search.toLowerCase()
      return [a.email, a.run_id, a.run_timestamp].some(v => String(v || '').toLowerCase().includes(keyword))
    })
    : accounts

  const applyRefreshResults = (items: RefreshAccountTokenItem[]) => {
    const nextByKey = new Map(
      items
        .filter(item => item.status === 'ok')
        .map(item => [`${item.run_id}:${item.line_no ?? 'na'}:${item.email}`, item]),
    )
    if (!nextByKey.size) {
      return
    }

    setAccounts(prev => prev.map(account => {
      const matched = nextByKey.get(getAccountKey(account))
      if (!matched) {
        return account
      }
      return {
        ...account,
        access_token: matched.access_token || account.access_token,
        refresh_token: matched.refresh_token || account.refresh_token,
        id_token: matched.id_token || account.id_token,
      }
    }))
  }

  const handleRefreshTokens = async (targetAccounts: Account[], rowKey?: string) => {
    const refreshable = targetAccounts
      .filter(account => account.run_id && account.email && account.refresh_token)
      .map(account => ({
        run_id: String(account.run_id),
        email: account.email,
        refresh_token: String(account.refresh_token),
        line_no: account.line_no,
      }))

    if (!refreshable.length) {
      message.warning('当前没有可更新 Token 的账号')
      return
    }

    if (rowKey) {
      setRefreshingRowKeys(prev => ({ ...prev, [rowKey]: true }))
    } else {
      setRefreshingAllTokens(true)
    }

    try {
      const { data } = await refreshAccountTokens({ accounts: refreshable })
      applyRefreshResults(data.items || [])

      if (data.proxy_warning) {
        message.warning(data.proxy_warning)
      }

      if (data.fail_count > 0) {
        const failedEmails = (data.items || [])
          .filter(item => item.status === 'error')
          .map(item => item.email)
          .slice(0, 3)
          .join('，')
        message.warning(`已更新 ${data.success_count} 个账号，失败 ${data.fail_count} 个${failedEmails ? `：${failedEmails}` : ''}`)
      } else {
        message.success(`已更新 ${data.success_count} 个账号的 Token`)
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail || '更新 Token 失败'
      message.error(detail)
    } finally {
      if (rowKey) {
        setRefreshingRowKeys(prev => {
          const next = { ...prev }
          delete next[rowKey]
          return next
        })
      } else {
        setRefreshingAllTokens(false)
      }
    }
  }

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
      title: '批次',
      dataIndex: 'run_id',
      key: 'run_id',
      width: 220,
      render: (_: string, record: Account) => (
        <Space direction="vertical" size={4}>
          <Tag color="blue">{record.run_id || '未归档'}</Tag>
          {record.run_timestamp ? <Text type="secondary">{record.run_timestamp}</Text> : null}
        </Space>
      ),
    },
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
    {
      title: '操作',
      key: 'actions',
      width: 120,
      fixed: 'right' as const,
      render: (_: unknown, record: Account) => {
        const rowKey = getAccountKey(record)
        return (
          <Button
            size="small"
            type="primary"
            ghost
            loading={!!refreshingRowKeys[rowKey]}
            disabled={!record.refresh_token || refreshingAllTokens}
            onClick={() => void handleRefreshTokens([record], rowKey)}
          >
            更新 Token
          </Button>
        )
      },
    },
  ]

  return (
    <Card title="账号列表" extra={
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <Select
          value={selectedRun}
          onChange={setSelectedRun}
          style={{ width: 200 }}
          placeholder="选择批次"
          options={[
            { value: ALL_RUNS_VALUE, label: '全部批次' },
            ...runs.map(r => ({ value: r.run_id, label: `${r.timestamp} (${r.total_accounts})` })),
          ]}
        />
        <Button
          type="primary"
          loading={refreshingAllTokens}
          disabled={!filtered.some(account => account.run_id && account.refresh_token)}
          onClick={() => void handleRefreshTokens(filtered)}
        >
          一键更新当前列表 Token
        </Button>
        <Input.Search
          placeholder="搜索邮箱 / 批次"
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
        rowKey={getAccountKey}
        loading={loading}
        pagination={{ pageSize: 20 }}
        size="middle"
        scroll={{ x: 1500 }}
      />
    </Card>
  )
}
