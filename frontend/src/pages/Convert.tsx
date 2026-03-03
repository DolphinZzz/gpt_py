import { useEffect, useState } from 'react'
import { Card, Form, Input, InputNumber, Select, Switch, Button, Alert, Space, Descriptions, message } from 'antd'
import { SwapOutlined, UploadOutlined } from '@ant-design/icons'
import { convertToSub2Api, getConvertibleRuns, getConfig, uploadBackfillAccounts } from '../api'
import type { ConvertRequest, ConvertResult, ConvertibleRun } from '../types'

const sourceOptions = [
  { value: 'auto', label: '自动检测 (推荐)' },
  { value: 'codex_tokens', label: 'Codex Tokens (JSON 文件)' },
  { value: 'results_file', label: '注册结果文件' },
  { value: 'ak_rk', label: 'AK + RK 文件' },
]

export default function Convert() {
  const [form] = Form.useForm()
  const [runs, setRuns] = useState<ConvertibleRun[]>([])
  const [loading, setLoading] = useState(false)
  const [backfillLoading, setBackfillLoading] = useState(false)
  const [result, setResult] = useState<ConvertResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getConvertibleRuns().then(r => setRuns(r.data))
    getConfig().then(r => {
      form.setFieldsValue({ proxy: r.data.proxy || '' })
    })
  }, [form])

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
    label: r.run_id ? `${r.label} [${r.sources.join(', ')}]` : `${r.label} [${r.sources.join(', ')}]`,
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
          source: 'auto',
          run_id: '',
          proxy: '',
          proxy_name: 'default',
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

        <Form.Item label="数据源类型" name="source">
          <Select options={sourceOptions} />
        </Form.Item>

        <Form.Item label="代理地址" name="proxy" tooltip="留空将从 config.json 读取，支持格式: host:port 或 http://host:port">
          <Input placeholder="127.0.0.1:7897" />
        </Form.Item>

        <Form.Item label="代理名称" name="proxy_name">
          <Input placeholder="default" />
        </Form.Item>

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
          <Descriptions.Item label="代理 Key">{result.proxy_key}</Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  )
}
