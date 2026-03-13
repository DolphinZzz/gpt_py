import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Alert, Button, Card, Col, Empty, Input, Row, Space, Tag, Typography, message } from 'antd'
import { CopyOutlined, EyeInvisibleOutlined, EyeTwoTone, ReloadOutlined } from '@ant-design/icons'
import { getConfig } from '../api'
import type { Config } from '../types'

const { Text, Paragraph } = Typography

type PaymentProfile = {
  account: string
  cardholder: string
  cardNumber: string
  expMonth: string
  expYear: string
  expiry: string
  cvc: string
  masked: string
  note: string
}

async function copyToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
  } finally {
    document.body.removeChild(textarea)
  }
}

function buildExpiry(month: string, year: string, fallback: string) {
  const mm = String(month || '').trim()
  const yy = String(year || '').trim()
  if (mm && yy) {
    const shortYear = yy.length >= 2 ? yy.slice(-2) : yy
    return `${mm.padStart(2, '0')}/${shortYear}`
  }
  return String(fallback || '').trim()
}

function maskNumber(number: string, fallback: string) {
  const masked = String(fallback || '').trim()
  if (masked) return masked
  const digits = String(number || '').replace(/\D/g, '')
  if (!digits) return ''
  return `**** **** **** ${digits.slice(-4)}`
}

function normalizeProfile(raw: Record<string, unknown>): PaymentProfile {
  const cardNumber = String(raw.payment_card_number || raw.card_number || '').trim()
  const expMonth = String(raw.payment_card_exp_month || raw.exp_month || '').trim()
  const expYear = String(raw.payment_card_exp_year || raw.exp_year || '').trim()
  const expiry = buildExpiry(
    expMonth,
    expYear,
    String(raw.payment_card_expiry || raw.expiry || '').trim(),
  )

  return {
    account: String(raw.account || raw.email || raw['账号'] || '').trim().toLowerCase(),
    cardholder: String(raw.payment_cardholder_name || raw.cardholder_name || raw.name || '').trim(),
    cardNumber,
    expMonth,
    expYear,
    expiry,
    cvc: String(raw.payment_card_cvc || raw.cvc || '').trim(),
    masked: maskNumber(cardNumber, String(raw.payment_card_number_masked || raw.card_number_masked || '').trim()),
    note: String(raw.payment_card_note || raw.note || raw['备注'] || '').trim(),
  }
}

function hasSensitiveData(profile: PaymentProfile | null) {
  if (!profile) return false
  return Boolean(
    profile.cardholder ||
    profile.cardNumber ||
    profile.expMonth ||
    profile.expYear ||
    profile.expiry ||
    profile.cvc ||
    profile.note,
  )
}

function parseProfiles(raw: string) {
  const text = String(raw || '').trim()
  if (!text) return [] as PaymentProfile[]
  try {
    const data = JSON.parse(text)
    if (!Array.isArray(data)) return [] as PaymentProfile[]
    return data
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
      .map(normalizeProfile)
      .filter((item) => Boolean(item.account))
  } catch {
    return [] as PaymentProfile[]
  }
}

function CopyRow({
  label,
  value,
  secret = false,
}: {
  label: string
  value: string
  secret?: boolean
}) {
  const text = String(value || '')

  const copy = async () => {
    if (!text) {
      message.warning(`${label} 为空`)
      return
    }
    try {
      await copyToClipboard(text)
      message.success(`${label} 已复制`)
    } catch {
      message.error(`${label} 复制失败`)
    }
  }

  return (
    <Space.Compact style={{ width: '100%' }}>
      {secret ? (
        <Input.Password
          readOnly
          value={text}
          placeholder={`${label} 未配置`}
          iconRender={(visible) => (visible ? <EyeTwoTone /> : <EyeInvisibleOutlined />)}
        />
      ) : (
        <Input readOnly value={text} placeholder={`${label} 未配置`} />
      )}
      <Button icon={<CopyOutlined />} onClick={() => void copy()}>
        复制
      </Button>
    </Space.Compact>
  )
}

export default function SensitiveCopy() {
  const [config, setConfig] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [accountInput, setAccountInput] = useState('')

  const fetchConfig = () => {
    setLoading(true)
    getConfig()
      .then((r) => {
        setConfig(r.data)
        const profiles = parseProfiles(String(r.data?.payment_profiles_json || ''))
        if (!accountInput && profiles.length === 1) {
          setAccountInput(profiles[0].account)
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchConfig()
  }, [])

  const profiles = parseProfiles(String(config?.payment_profiles_json || ''))
  const defaultProfile = config ? normalizeProfile(config as unknown as Record<string, unknown>) : null
  const normalizedAccount = accountInput.trim().toLowerCase()
  const matchedProfile = normalizedAccount
    ? profiles.find((item) => item.account === normalizedAccount) || null
    : null

  const usingMappedProfile = Boolean(matchedProfile)
  const profile = matchedProfile || (!profiles.length && hasSensitiveData(defaultProfile) ? defaultProfile : null)
  const showNoMatch = Boolean(normalizedAccount) && !matchedProfile

  const combinedBlock = profile ? [
    profile.cardholder ? `持卡人: ${profile.cardholder}` : '',
    profile.cardNumber ? `卡号: ${profile.cardNumber}` : '',
    profile.expiry ? `有效期: ${profile.expiry}` : '',
    profile.cvc ? `CVV: ${profile.cvc}` : '',
    profile.note ? `备注: ${profile.note}` : '',
  ].filter(Boolean).join('\n') : ''

  const copyCombined = async () => {
    if (!combinedBlock) {
      message.warning('暂无可复制内容')
      return
    }
    try {
      await copyToClipboard(combinedBlock)
      message.success('整块付款信息已复制')
    } catch {
      message.error('复制失败')
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        loading={loading}
        title="敏感信息复制"
        extra={<Button icon={<ReloadOutlined />} onClick={fetchConfig}>刷新</Button>}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message="此页按账号显示对应的付款资料"
            description="优先匹配“账号付款映射(JSON)”里的账号；如果未配置映射，则回退到默认付款资料。敏感字段不会进入运行日志。"
          />
          <Input
            value={accountInput}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setAccountInput(e.target.value)}
            allowClear
            placeholder="输入账号邮箱，例如 foo@example.com"
          />
          {profiles.length > 0 && (
            <Space wrap>
              <Text type="secondary">快捷选择:</Text>
              {profiles.slice(0, 12).map((item) => (
                <Tag
                  key={item.account}
                  color={item.account === normalizedAccount ? 'blue' : 'default'}
                  onClick={() => setAccountInput(item.account)}
                  style={{ cursor: 'pointer' }}
                >
                  {item.account}
                </Tag>
              ))}
            </Space>
          )}
        </Space>
      </Card>

      {showNoMatch && (
        <Alert
          type="error"
          showIcon
          message="未找到该账号对应的付款资料"
          description="请检查邮箱是否精确匹配，或到参数配置页补充“账号付款映射(JSON)”。"
        />
      )}

      {!profile && !showNoMatch && (
        <Card>
          <Empty
            description={profiles.length > 0 ? '请输入或选择账号后查看对应资料' : '当前还没有可用的敏感付款资料'}
          />
        </Card>
      )}

      {profile && (
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={14}>
            <Card
              title={usingMappedProfile ? `逐项复制: ${profile.account}` : '逐项复制: 默认资料'}
              extra={usingMappedProfile ? <Tag color="blue">账号映射</Tag> : <Tag>默认资料</Tag>}
            >
              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                <div>
                  <Text type="secondary">持卡人</Text>
                  <CopyRow label="持卡人" value={profile.cardholder} />
                </div>
                <div>
                  <Text type="secondary">卡号</Text>
                  <CopyRow label="卡号" value={profile.cardNumber} secret />
                </div>
                <Row gutter={12}>
                  <Col span={12}>
                    <Text type="secondary">到期月</Text>
                    <CopyRow label="到期月" value={profile.expMonth} />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">到期年</Text>
                    <CopyRow label="到期年" value={profile.expYear} />
                  </Col>
                </Row>
                <div>
                  <Text type="secondary">有效期</Text>
                  <CopyRow label="有效期" value={profile.expiry} />
                </div>
                <div>
                  <Text type="secondary">CVV</Text>
                  <CopyRow label="CVV" value={profile.cvc} secret />
                </div>
                <div>
                  <Text type="secondary">备注</Text>
                  <CopyRow label="备注" value={profile.note} />
                </div>
              </Space>
            </Card>
          </Col>

          <Col xs={24} xl={10}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Card title="日志预览">
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Paragraph style={{ marginBottom: 0 }}>
                    <Text type="secondary">日志展示卡号</Text>
                    <br />
                    <Text copyable={profile.masked ? { text: profile.masked } : undefined}>{profile.masked || '-'}</Text>
                  </Paragraph>
                  <Paragraph style={{ marginBottom: 0 }}>
                    <Text type="secondary">日志展示有效期</Text>
                    <br />
                    <Text copyable={profile.expiry ? { text: profile.expiry } : undefined}>{profile.expiry || '-'}</Text>
                  </Paragraph>
                </Space>
              </Card>

              <Card
                title="整块复制"
                extra={<Button icon={<CopyOutlined />} type="primary" onClick={() => void copyCombined()}>复制整块</Button>}
              >
                <Input.TextArea
                  readOnly
                  value={combinedBlock}
                  autoSize={{ minRows: 8, maxRows: 12 }}
                  placeholder="暂无可复制内容"
                />
              </Card>
            </Space>
          </Col>
        </Row>
      )}
    </Space>
  )
}
