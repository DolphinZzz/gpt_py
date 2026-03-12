import { useEffect, useState } from 'react'
import { Card, Col, Progress, Row, Space, Spin, Statistic, Tag, theme, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, TeamOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { getStats } from '../api'
import type { Stats } from '../types'

const { Text, Title } = Typography

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const { token } = theme.useToken()
  const isDark = token.colorBgBase === '#000'

  const fetchStats = () => {
    getStats().then(r => setStats(r.data)).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchStats()
    const t = setInterval(fetchStats, 10000)
    return () => clearInterval(t)
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
  if (!stats) return null

  const safeRuns = stats.total_runs || 1
  const averagePerRun = Number((stats.total_accounts / safeRuns).toFixed(1))

  const pieData = [
    { type: '成功', value: stats.total_success },
    { type: '失败', value: stats.total_fail },
  ]

  const dailyTotalData = stats.daily.map(d => ({
    date: d.date,
    total: d.success + d.fail,
    successRate: d.success + d.fail > 0 ? (d.success / (d.success + d.fail)) * 100 : 0,
  }))

  let rollingSuccess = 0
  let rollingFail = 0
  const cumulativeData = stats.daily.map(d => {
    rollingSuccess += d.success
    rollingFail += d.fail
    return {
      date: d.date,
      success: rollingSuccess,
      fail: rollingFail,
      total: rollingSuccess + rollingFail,
    }
  })
  const recentDays = dailyTotalData.slice(-7).reverse()
  const latestCumulative = cumulativeData[cumulativeData.length - 1]

  const statCards = [
    {
      title: '总注册数',
      value: stats.total_accounts,
      prefix: <TeamOutlined />,
      valueStyle: { color: isDark ? '#95de64' : '#163d2f' },
      background: isDark
        ? 'linear-gradient(135deg, rgba(39, 117, 76, 0.35) 0%, rgba(27, 76, 53, 0.26) 100%)'
        : 'linear-gradient(135deg, #e9f9f1 0%, #f7fffb 100%)',
      border: isDark ? '1px solid #2b5d45' : '1px solid #bbe7cf',
    },
    {
      title: '成功',
      value: stats.total_success,
      prefix: <CheckCircleOutlined />,
      valueStyle: { color: isDark ? '#73d13d' : '#237804' },
      background: isDark
        ? 'linear-gradient(135deg, rgba(73, 130, 40, 0.35) 0%, rgba(53, 96, 29, 0.24) 100%)'
        : 'linear-gradient(135deg, #f0ffe9 0%, #fbfff8 100%)',
      border: isDark ? '1px solid #406b31' : '1px solid #c7ebb3',
    },
    {
      title: '失败',
      value: stats.total_fail,
      prefix: <CloseCircleOutlined />,
      valueStyle: { color: isDark ? '#ff7875' : '#a8071a' },
      background: isDark
        ? 'linear-gradient(135deg, rgba(147, 56, 55, 0.34) 0%, rgba(109, 41, 40, 0.25) 100%)'
        : 'linear-gradient(135deg, #fff1f0 0%, #fffafa 100%)',
      border: isDark ? '1px solid #703939' : '1px solid #f2bfc4',
    },
    {
      title: '成功率',
      value: stats.success_rate,
      suffix: '%',
      prefix: <ThunderboltOutlined />,
      valueStyle: { color: stats.success_rate >= 50 ? (isDark ? '#73d13d' : '#237804') : (isDark ? '#ff7875' : '#a8071a') },
      background: isDark
        ? 'linear-gradient(135deg, rgba(50, 95, 157, 0.34) 0%, rgba(36, 67, 110, 0.24) 100%)'
        : 'linear-gradient(135deg, #eef6ff 0%, #f9fcff 100%)',
      border: isDark ? '1px solid #395679' : '1px solid #bfd9ff',
    },
    {
      title: '累计运行次数',
      value: stats.total_runs,
      prefix: <ThunderboltOutlined />,
      valueStyle: { color: isDark ? '#85a5ff' : '#1d39c4' },
      background: isDark
        ? 'linear-gradient(135deg, rgba(62, 84, 165, 0.36) 0%, rgba(43, 58, 115, 0.24) 100%)'
        : 'linear-gradient(135deg, #edf2ff 0%, #f9fbff 100%)',
      border: isDark ? '1px solid #40538a' : '1px solid #c7d5ff',
    },
  ]

  return (
    <div
      style={{
        background: isDark
          ? 'linear-gradient(180deg, #101723 0%, #121b2a 45%, #0f1722 100%)'
          : 'linear-gradient(180deg, #f5f9ff 0%, #f8fbff 40%, #ffffff 100%)',
        padding: 8,
        borderRadius: 12,
      }}
    >
      <Card
        style={{ borderRadius: 14, marginBottom: 16, border: isDark ? '1px solid #2f3d4d' : '1px solid #d9e7ff' }}
        styles={{ body: { padding: 18 } }}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <Title level={4} style={{ margin: 0 }}>注册任务总览</Title>
              <Text type="secondary">每 10 秒自动刷新，帮助你快速观察注册质量和波动。</Text>
            </div>
            <Tag color="blue">实时刷新</Tag>
          </div>
          <Progress
            percent={Number(stats.success_rate.toFixed(1))}
            strokeColor={{ from: '#1d39c4', to: '#52c41a' }}
            format={(percent?: number) => `当前成功率 ${percent ?? 0}%`}
          />
          <Text type="secondary">平均每次运行产出：{averagePerRun} 个账号</Text>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        {statCards.map(item => (
          <Col xs={12} sm={8} lg={4} xl={4} key={item.title}>
            <Card style={{ background: item.background, border: item.border }} styles={{ body: { padding: 16 } }}>
              <Statistic
                title={item.title}
                value={item.value}
                prefix={item.prefix}
                suffix={item.suffix}
                valueStyle={item.valueStyle}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={16}>
          <Card title="最近 7 天成功/失败趋势" style={{ borderRadius: 12 }}>
            {recentDays.length > 0 ? (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                {recentDays.map((item) => (
                  <div key={item.date} style={{ padding: '8px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, gap: 12, flexWrap: 'wrap' }}>
                      <Text strong>{item.date}</Text>
                      <Space size={8} wrap>
                        <Tag color="green">成功 {stats.daily.find((d) => d.date === item.date)?.success ?? 0}</Tag>
                        <Tag color="red">失败 {stats.daily.find((d) => d.date === item.date)?.fail ?? 0}</Tag>
                        <Tag color="blue">总计 {item.total}</Tag>
                      </Space>
                    </div>
                    <Progress
                      percent={Number(item.successRate.toFixed(1))}
                      strokeColor={{ from: '#1677ff', to: '#52c41a' }}
                      format={(percent?: number) => `${percent ?? 0}%`}
                    />
                  </div>
                ))}
              </Space>
            ) : (
              <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>暂无数据</div>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card title="成功/失败比例" style={{ borderRadius: 12, height: '100%' }}>
            {stats.total_accounts > 0 ? (
              <Space direction="vertical" size="large" style={{ width: '100%' }}>
                {pieData.map((item) => {
                  const percent = stats.total_accounts > 0 ? Number(((item.value / stats.total_accounts) * 100).toFixed(1)) : 0
                  return (
                    <div key={item.type}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <Text strong>{item.type}</Text>
                        <Text>{item.value} 个</Text>
                      </div>
                      <Progress
                        percent={percent}
                        strokeColor={item.type === '成功' ? '#52c41a' : '#ff4d4f'}
                        format={(value?: number) => `${value ?? 0}%`}
                      />
                    </div>
                  )
                })}
              </Space>
            ) : (
              <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>暂无数据</div>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="每日注册总量" style={{ borderRadius: 12 }}>
            {dailyTotalData.length > 0 ? (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                {dailyTotalData.slice(-10).reverse().map((item) => (
                  <div key={item.date}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <Text>{item.date}</Text>
                      <Text strong>{item.total} 个</Text>
                    </div>
                    <Progress
                      percent={Math.min(100, Math.max(8, item.total))}
                      showInfo={false}
                      strokeColor="#1677ff"
                    />
                  </div>
                ))}
              </Space>
            ) : (
              <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>暂无数据</div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="累计成功/失败走势" style={{ borderRadius: 12 }}>
            {cumulativeData.length > 0 ? (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <Card size="small" style={{ background: isDark ? '#111b26' : '#f7fbff' }}>
                  <Space size="large" wrap>
                    <Statistic title="累计成功" value={latestCumulative?.success ?? 0} valueStyle={{ color: '#389e0d' }} />
                    <Statistic title="累计失败" value={latestCumulative?.fail ?? 0} valueStyle={{ color: '#cf1322' }} />
                    <Statistic title="累计总量" value={latestCumulative?.total ?? 0} />
                  </Space>
                </Card>
                {cumulativeData.slice(-7).reverse().map((item) => (
                  <div key={item.date} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <Text>{item.date}</Text>
                    <Space size={8} wrap>
                      <Tag color="green">累计成功 {item.success}</Tag>
                      <Tag color="red">累计失败 {item.fail}</Tag>
                      <Tag>累计总量 {item.total}</Tag>
                    </Space>
                  </div>
                ))}
              </Space>
            ) : (
              <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>暂无数据</div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
