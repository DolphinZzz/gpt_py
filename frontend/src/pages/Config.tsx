import { useEffect, useState } from 'react'
import { Card, Form, Input, InputNumber, Switch, Button, message, Spin } from 'antd'
import { SaveOutlined, ReloadOutlined } from '@ant-design/icons'
import { getConfig, updateConfig } from '../api'
import type { Config as ConfigType } from '../types'

export default function Config() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const fetchConfig = () => {
    setLoading(true)
    getConfig()
      .then(r => form.setFieldsValue(r.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchConfig() }, [])

  const onSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await updateConfig(values as ConfigType)
      message.success('配置已保存')
    } catch (e: any) {
      message.error('保存失败: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <Card title="参数配置" extra={
      <div style={{ display: 'flex', gap: 8 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchConfig}>重置</Button>
        <Button type="primary" icon={<SaveOutlined />} onClick={onSave} loading={saving}>保存</Button>
      </div>
    }>
      <Form form={form} layout="vertical" style={{ maxWidth: 700 }}>
        <Card type="inner" title="注册参数" style={{ marginBottom: 16 }}>
          <Form.Item label="注册数量" name="total_accounts">
            <InputNumber min={1} max={1000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="并发数" name="max_workers">
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="使用容器模式" name="use_containers" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="容器数量" name="container_count">
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="代理地址" name="proxy">
            <Input placeholder="例如: http://127.0.0.1:7890" />
          </Form.Item>
        </Card>

        <Card type="inner" title="容器编排配置" style={{ marginBottom: 16 }}>
          <Form.Item label="Compose 工作目录" name="docker_project_dir">
            <Input placeholder="例如: /root/warp" />
          </Form.Item>
          <Form.Item label="Compose 文件" name="docker_compose_file">
            <Input placeholder="例如: docker-compose.yml" />
          </Form.Item>
          <Form.Item label="Worker 服务名" name="docker_worker_service">
            <Input placeholder="例如: worker" />
          </Form.Item>
          <Form.Item label="WARP 服务名" name="docker_warp_service">
            <Input placeholder="例如: warp" />
          </Form.Item>
        </Card>

        <Card type="inner" title="DuckMail 配置" style={{ marginBottom: 16 }}>
          <Form.Item label="API 地址" name="duckmail_api_base">
            <Input />
          </Form.Item>
          <Form.Item label="Bearer Token" name="duckmail_bearer">
            <Input.Password />
          </Form.Item>
        </Card>

        <Card type="inner" title="OAuth 配置" style={{ marginBottom: 16 }}>
          <Form.Item label="启用 OAuth" name="enable_oauth" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="OAuth 必须成功" name="oauth_required" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="OAuth Issuer" name="oauth_issuer">
            <Input />
          </Form.Item>
          <Form.Item label="Client ID" name="oauth_client_id">
            <Input />
          </Form.Item>
          <Form.Item label="Redirect URI" name="oauth_redirect_uri">
            <Input />
          </Form.Item>
        </Card>

        <Card type="inner" title="输出配置">
          <Form.Item label="输出文件" name="output_file">
            <Input />
          </Form.Item>
          <Form.Item label="AK 文件" name="ak_file">
            <Input />
          </Form.Item>
          <Form.Item label="RK 文件" name="rk_file">
            <Input />
          </Form.Item>
          <Form.Item label="Token 目录" name="token_json_dir">
            <Input />
          </Form.Item>
          <Form.Item label="结果目录" name="results_dir">
            <Input />
          </Form.Item>
        </Card>

        <Card type="inner" title="Sub2API 自动导入" style={{ marginTop: 16 }}>
          <Form.Item label="任务结束后自动导入" name="sub2api_auto_upload" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="导入地址" name="sub2api_upload_url">
            <Input placeholder="https://www.codex.hair/api/v1/admin/accounts/data" />
          </Form.Item>
          <Form.Item
            label="中转站 Bearer Token"
            name="sub2api_upload_bearer"
            tooltip="Token 过期后可在这里手动粘贴最新值"
          >
            <Input.Password placeholder="粘贴最新 Bearer Token（可随时手动更新）" />
          </Form.Item>
          <Form.Item
            label="Cloudflare Cookie"
            name="sub2api_upload_cookie"
            tooltip="如果报 403 Just a moment，请粘贴浏览器请求中的 cf_clearance=..."
          >
            <Input.Password placeholder="例如: cf_clearance=xxxx;" />
          </Form.Item>
          <Form.Item
            label="上传 User-Agent"
            name="sub2api_upload_user_agent"
            tooltip="可选，建议粘贴你浏览器里的完整 User-Agent"
          >
            <Input placeholder="Mozilla/5.0 ..." />
          </Form.Item>
          <Form.Item
            label="上传代理(可选)"
            name="sub2api_upload_proxy"
            tooltip="默认不走代理；仅在你确认需要时填写"
          >
            <Input placeholder="例如: http://127.0.0.1:7890" />
          </Form.Item>
          <Form.Item label="skip_default_group_bind" name="sub2api_skip_default_group_bind" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="自动分组" name="sub2api_auto_group_bind" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="分组ID" name="sub2api_group_id" tooltip="上传后会对新账号执行批量分组">
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
        </Card>
      </Form>
    </Card>
  )
}
