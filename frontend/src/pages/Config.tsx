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
          <Form.Item label="代理地址" name="proxy" tooltip="留空表示直连；如果填写本机代理，请先确认对应端口已启动监听">
            <Input placeholder="例如: http://127.0.0.1:7890；留空=直连" />
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

        <Card type="inner" title="Resend 收件配置" style={{ marginBottom: 16 }}>
          <Form.Item label="API 地址" name="resend_api_base">
            <Input />
          </Form.Item>
          <Form.Item label="API Key" name="resend_api_key" tooltip="必须是可读取 Receiving API 的 key；只允许发信的 key 无法拉取验证码邮件">
            <Input.Password />
          </Form.Item>
          <Form.Item label="接收域名" name="resend_domain" tooltip="可填自定义收件域名，或 Resend 托管域如 ilkoxpra.resend.app；如果是自定义域，需先完成 Receiving DNS/MX 配置">
            <Input placeholder="例如: ilkoxpra.resend.app" />
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

        <Card type="inner" title="付款资料" style={{ marginBottom: 16 }}>
          <Form.Item
            label="持卡人"
            name="payment_cardholder_name"
            tooltip="用于日志提示和敏感复制页"
          >
            <Input placeholder="例如: DUCK MAIL LTD" />
          </Form.Item>
          <Form.Item
            label="完整卡号"
            name="payment_card_number"
            tooltip="仅用于敏感复制页，不会进入日志"
          >
            <Input.Password placeholder="例如: 4242424242424242" />
          </Form.Item>
          <Form.Item
            label="到期月"
            name="payment_card_exp_month"
            tooltip="仅用于敏感复制页；日志可自动用月/年生成有效期"
          >
            <Input placeholder="例如: 12" />
          </Form.Item>
          <Form.Item
            label="到期年"
            name="payment_card_exp_year"
            tooltip="仅用于敏感复制页；支持 2029 或 29"
          >
            <Input placeholder="例如: 2029" />
          </Form.Item>
          <Form.Item
            label="CVV"
            name="payment_card_cvc"
            tooltip="仅用于敏感复制页，不会进入日志"
          >
            <Input.Password placeholder="例如: 123" />
          </Form.Item>
          <Form.Item
            label="卡号(仅掩码/尾号)"
            name="payment_card_number_masked"
            tooltip="用于日志展示；留空时会自动从完整卡号推导掩码"
          >
            <Input placeholder="例如: **** **** **** 4242" />
          </Form.Item>
          <Form.Item
            label="有效期"
            name="payment_card_expiry"
            tooltip="用于日志展示；留空时会自动从月/年推导"
          >
            <Input placeholder="例如: 12/29" />
          </Form.Item>
          <Form.Item
            label="付款备注"
            name="payment_card_note"
            tooltip="可选，例如账单地址要求、发卡行提示等"
          >
            <Input.TextArea rows={3} placeholder="例如: 韩国账单地址，手机号可留空" />
          </Form.Item>
          <Form.Item
            label="账号付款映射(JSON)"
            name="payment_profiles_json"
            tooltip="按账号精确匹配付款资料；敏感复制页和付款日志都会优先取这里的资料，未命中时才回退到上面的默认资料"
          >
            <Input.TextArea
              rows={8}
              placeholder={'例如:\n[\n  {\n    "account": "foo@example.com",\n    "cardholder_name": "DUCK MAIL LTD",\n    "card_number": "4242424242424242",\n    "exp_month": "12",\n    "exp_year": "2029",\n    "payment_card_cvc": "123",\n    "note": "KR billing"\n  }\n]'}
            />
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
