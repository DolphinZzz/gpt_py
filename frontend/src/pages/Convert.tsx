import { useEffect, useState } from 'react'
import { Card, Form, Input, InputNumber, Select, Switch, Button, Alert, Space, Descriptions, message } from 'antd'
import { SwapOutlined, UploadOutlined } from '@ant-design/icons'
import { convertToSub2Api, getConvertibleRuns, uploadBackfillAccounts } from '../api'
import type { ConvertRequest, ConvertResult, ConvertibleRun } from '../types'

const sourceLabels: Record<string, string> = {
  sub2api_json: 'Sub2API JSON',
  codex_tokens: 'Codex Tokens',
  results_file: '注册结果文件',
  ak_rk: 'AK/RK',
}

export default function Convert() {
  const [form] = Form.useForm()
  const [runs, setRuns] = useState<ConvertibleRun[]>([])
  const [loading, setLoading] = useState(false)
  const [backfillLoading, setBackfillLoading] = useState(false)
  const [result, setResult] = useState<ConvertResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getConvertibleRuns().then(r => setRuns(r.data))
  }, [])

  const onFinish = async (values: ConvertRequest) => {
    setLoading(true)
    setResult(null)
    setError('')
    try {
      const res = await convertToSub2Api(values)
      setResult(res.data)
      message.success(`转换完成: ${res.data.accounts_count} 个账号`)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '转换失败'
      setError(msg)
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }

  const runOptions = runs.map(r => ({
    value: r.run_id,
    label: `${r.label} [${r.sources.map(source => sourceLabels[source] || source).join(', ')}]`,
  }))

  const handleBackfillUpload = async () => {
    setBackfillLoading(true)
    try {
      const res = await uploadBackfillAccounts()
      const data = res.data as {
        uploaded_now?: number
        skipped_uploaded?: number
        skipped_duplicate?: number
        scanned?: number
        message?: string
      }
      message.success(
        data.message || `补传完成: 上传 ${data.uploaded_now || 0}，跳过已上传 ${data.skipped_uploaded || 0}，跳过重复 ${data.skipped_duplicate || 0}`,
      )
      setError('')
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '补传失败'
      setError(msg)
      message.error(msg)
    } finally {
      setBackfillLoading(false)
    }
  }

  return (
    <Card title="Sub2API 格式转换" extra={
      <span style={{ color: '#888', fontSize: 12 }}>将已注册的 Token 转换为 Sub2API 兼容格式</span>
    }>
      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        initialValues={{
          run_id: '',
          concurrency: 10,
          priority: 1,
          rate_multiplier: 1,
          auto_pause_on_expired: true,
          output_filename: 'sub2api_accounts.json',
        }}
        style={{ maxWidth: 700 }}
      >
        <Form.Item label="数据来源批次" name="run_id">
          <Select
            placeholder="选择批次（留空使用项目根目录）"
            options={[{ value: '', label: '项目根目录' }, ...runOptions]}
            allowClear
          />
        </Form.Item>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="转换会优先直接复用批次里的 sub2api_accounts.json；如果不存在，再自动回退到 tokens、注册结果文件和 AK/RK。"
        />

        <Space size="large" wrap>
          <Form.Item label="并发数" name="concurrency">
            <InputNumber min={1} max={100} />
          </Form.Item>
          <Form.Item label="优先级" name="priority">
            <InputNumber min={0} max={100} />
          </Form.Item>
          <Form.Item label="速率倍数" name="rate_multiplier">
            <InputNumber min={0.1} max={10} step={0.1} />
          </Form.Item>
        </Space>

        <Form.Item label="过期自动暂停" name="auto_pause_on_expired" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item label="输出文件名" name="output_filename">
          <Input placeholder="sub2api_accounts.json" />
        </Form.Item>

        <Form.Item>
          <Space wrap>
            <Button type="primary" htmlType="submit" loading={loading} icon={<SwapOutlined />} size="large">
              执行转换
            </Button>
            <Button
              type="default"
              loading={backfillLoading}
              icon={<UploadOutlined />}
              size="large"
              onClick={handleBackfillUpload}
            >
              补传历史未上传账号
            </Button>
          </Space>
        </Form.Item>
      </Form>

      {error && <Alert type="error" message={error} showIcon style={{ marginTop: 16 }} />}

      {result && (
        <Descriptions
          title="转换结果"
          bordered
          column={1}
          size="small"
          style={{ marginTop: 16 }}
        >
          <Descriptions.Item label="状态">{result.status}</Descriptions.Item>
          <Descriptions.Item label="账号数量">{result.accounts_count}</Descriptions.Item>
          <Descriptions.Item label="输出路径">{result.output_path}</Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  )
}
