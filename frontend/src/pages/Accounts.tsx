import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { DownloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import { exportStripeLinks, getAccountPaymentLinks, getAccounts, getTaskHistory, queryMailboxCode, refreshAccountTokens } from '../api'
import type { Account, AccountPaymentLinksResult, ExportStripeLinksResult, HistoryRun, MailboxCodeResult, RefreshAccountTokenItem } from '../types'

const { Paragraph, Text } = Typography
const ALL_RUNS_VALUE = '__all__'

function escapeCsvCell(value: unknown) {
  const text = String(value ?? '').replace(/\r?\n/g, ' ').trim()
  if (!text) {
    return ''
  }
  if (/[",]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

async function copyText(value: string, label: string) {
  const text = String(value || '').trim()
  if (!text) {
    message.warning(`${label} 不存在`)
    return false
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      message.success(`${label} 已复制`)
      return true
    }
  } catch {
    // Ignore and fallback below.
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()

  try {
    document.execCommand('copy')
    message.success(`${label} 已复制`)
    return true
  } catch {
    message.error(`${label} 复制失败`)
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}

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
  const [paymentLinkRowKeys, setPaymentLinkRowKeys] = useState<Record<string, boolean>>({})
  const [exportingStripeLinks, setExportingStripeLinks] = useState(false)
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

  const handleCopySecret = async (value: string | undefined, label: string) => {
    await copyText(String(value || ''), label)
  }

  const handleExportCsv = () => {
    if (!filtered.length) {
      message.warning('当前没有可导出的账号')
      return
    }

    const headers = [
      'run_id',
      'run_timestamp',
      'line_no',
      'email',
      'password',
      'email_password',
      'oauth_status',
      'mail_token',
      'access_token',
      'refresh_token',
      'id_token',
    ]

    const rows = filtered.map(account => ([
      account.run_id,
      account.run_timestamp,
      account.line_no,
      account.email,
      account.password,
      account.email_password,
      account.oauth_status,
      account.mail_token,
      account.access_token,
      account.refresh_token,
      account.id_token,
    ].map(escapeCsvCell).join(',')))

    const csvContent = `\uFEFF${headers.join(',')}\n${rows.join('\n')}`
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    const runPart = selectedRun === ALL_RUNS_VALUE ? 'all-runs' : selectedRun
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    link.href = url
    link.download = `accounts-${runPart}-${stamp}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success(`已导出 ${filtered.length} 条账号记录`)
  }

  const showPaymentLinkModal = async (
    title: string,
    url: string,
    result: AccountPaymentLinksResult,
  ) => {
    let copied = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url)
        copied = true
      }
    } catch {
      copied = false
    }

    Modal.info({
      title,
      width: 720,
      content: (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Text type="secondary">
            {copied ? '链接已自动复制到剪贴板。' : '已获取链接，可直接复制使用。'}
          </Text>
          <Paragraph copyable={{ text: url }} style={{ marginBottom: 0, wordBreak: 'break-all' }}>
            {url}
          </Paragraph>
          {result.output ? <Text type="secondary">输出文件: {result.output}</Text> : null}
        </Space>
      ),
    })
  }

  const showStripeExportResult = (result: ExportStripeLinksResult) => {
    const content = (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Text>成功 {result.success_count} 条，失败 {result.fail_count} 条</Text>
        {result.items.map(item => (
          <Space key={item.run_id} direction="vertical" size={2} style={{ width: '100%' }}>
            <Text strong>{item.run_id}</Text>
            <Text type="secondary">输出文件: {item.output_file || '未生成'}</Text>
            <Text type="secondary">成功 {item.success_count} / 失败 {item.fail_count}</Text>
          </Space>
        ))}
      </Space>
    )

    Modal.info({
      title: selectedRun === ALL_RUNS_VALUE ? '所有批次 Stripe 链接导出结果' : '当前批次 Stripe 链接导出结果',
      width: 720,
      content,
    })
  }

  const handleExportStripeLinks = async () => {
    const hasRunnableAccounts = filtered.some(account => account.run_id && account.password)
    if (!hasRunnableAccounts) {
      message.warning('当前没有可导出的批次账号')
      return
    }

    setExportingStripeLinks(true)
    try {
      const { data } = await exportStripeLinks(
        selectedRun === ALL_RUNS_VALUE ? {} : { run_id: selectedRun },
      )
      if (data.proxy_warning) {
        message.warning(data.proxy_warning)
      }
      showStripeExportResult(data)
    } catch (e: any) {
      const detail = e.response?.data?.detail || '导出 Stripe 链接失败'
      message.error(detail)
    } finally {
      setExportingStripeLinks(false)
    }
  }

  const handleFetchPaymentLink = async (record: Account, target: 'stripe' | 'openai') => {
    const rowKey = getAccountKey(record)
    setPaymentLinkRowKeys(prev => ({ ...prev, [rowKey]: true }))

    try {
      const { data } = await getAccountPaymentLinks({
        email: record.email,
        password: record.password,
        run_id: record.run_id,
        line_no: record.line_no,
        mail_token: record.mail_token,
        access_token: record.access_token,
        refresh_token: record.refresh_token,
        id_token: record.id_token,
      })

      if (data.proxy_warning) {
        message.warning(data.proxy_warning)
      }

      const url = target === 'stripe'
        ? String(data.stripe_hosted_url || '').trim()
        : String(data.checkout_url || '').trim()

      if (!url) {
        const fallback = target === 'stripe' ? 'Stripe' : 'OpenAI'
        message.error(`${fallback} 付款链接获取失败`)
        return
      }

      await showPaymentLinkModal(
        target === 'stripe' ? 'Stripe 付款链接' : 'OpenAI 付款链接',
        url,
        data,
      )
    } catch (e: any) {
      const detail = e.response?.data?.detail || '获取付款链接失败'
      message.error(detail)
    } finally {
      setPaymentLinkRowKeys(prev => {
        const next = { ...prev }
        delete next[rowKey]
        return next
      })
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
      width: 170,
      render: (v?: string) => v ? (
        <Space direction="vertical" size={4}>
          <Button size="small" onClick={() => void handleCopySecret(v, 'Mail Token')}>
            复制 Mail Token
          </Button>
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
      width: 130,
      render: (v?: string) => v ? (
        <Button size="small" onClick={() => void handleCopySecret(v, 'Access Token')}>
          复制 Access
        </Button>
      ) : '-',
    },
    {
      title: 'Refresh Token',
      dataIndex: 'refresh_token',
      key: 'refresh_token',
      width: 130,
      render: (v?: string) => v ? (
        <Button size="small" onClick={() => void handleCopySecret(v, 'Refresh Token')}>
          复制 Refresh
        </Button>
      ) : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, record: Account) => {
        const rowKey = getAccountKey(record)
        return (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
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
            <Button
              size="small"
              loading={!!paymentLinkRowKeys[rowKey]}
              onClick={() => void handleFetchPaymentLink(record, 'stripe')}
            >
              Stripe 链接
            </Button>
            <Button
              size="small"
              loading={!!paymentLinkRowKeys[rowKey]}
              onClick={() => void handleFetchPaymentLink(record, 'openai')}
            >
              OpenAI 链接
            </Button>
          </Space>
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
        <Button
          loading={exportingStripeLinks}
          disabled={!filtered.some(account => account.run_id && account.password)}
          onClick={() => void handleExportStripeLinks()}
        >
          {selectedRun === ALL_RUNS_VALUE ? '导出所有批次 Stripe 链接' : '导出当前批次 Stripe 链接'}
        </Button>
        <Button icon={<DownloadOutlined />} onClick={handleExportCsv} disabled={!filtered.length}>
          导出当前列表 CSV
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
