# GetMailGo

GetMailGo 是一个完全独立的 Go 项目，用来接收现有注册流程生成的 `mail_token`，查询对应 Resend 随机邮箱的最新邮件，并尽量从正文中提取 6 位验证码。

它不依赖 Python 运行时，也不需要引用当前仓库根目录的 `chatgpt_register.py`。只要配置好 Resend 和 token secret，这个目录单独拎出去就可以直接运行。

## 功能

- 兼容当前 Python 项目生成的 `mail_token`
- 查询 Resend Receiving API 的最新入站邮件
- 返回验证码、主题、接收时间和最近邮件摘要
- 自带独立 Web 页面
- 静态资源已嵌入二进制，部署时只需要可执行文件和配置文件

## 目录结构

```text
GetMailGo/
├── README.md
├── config.example.json
├── config.go
├── go.mod
├── main.go
├── service.go
├── token.go
├── token_test.go
├── service_test.go
└── web
    ├── app.js
    ├── index.html
    └── styles.css
```

## 运行前提

必须具备以下条件：

- 一个可读取 Resend Receiving API 的 `RESEND_API_KEY`
- 正确的 `RESEND_DOMAIN`
- 与原 Python 项目一致的 `MAILBOX_QUERY_TOKEN_SECRET`

如果你要继续使用原项目生成的历史 `mail_token`，必须把原仓库里的 `.mailbox_query_token_secret` 一并复制过来，或者设置环境变量 `MAILBOX_QUERY_TOKEN_SECRET`。否则旧 token 会因为签名不一致而失效。

## 配置方式

优先级从高到低：

1. 环境变量
2. `GETMAIL_CONFIG` 指向的配置文件
3. 当前目录或可执行文件所在目录下的 `config.json`

支持的配置项：

- `resend_api_base`
- `resend_api_key`
- `resend_domain`
- `getmail_host`
- `getmail_port`

推荐先复制示例配置：

```bash
cp config.example.json config.json
```

## 环境变量

- `GETMAIL_CONFIG`
  - 指定 `config.json` 路径
- `GETMAIL_HOST`
  - 覆盖监听地址，默认 `0.0.0.0`
- `GETMAIL_PORT`
  - 覆盖监听端口，默认 `8021`
- `RESEND_API_BASE`
  - 默认 `https://api.resend.com`
- `RESEND_API_KEY`
  - Resend Receiving API Key
- `RESEND_DOMAIN`
  - Resend 收件域名
- `MAILBOX_QUERY_TOKEN_SECRET`
  - 直接指定 token 签名密钥
- `MAILBOX_QUERY_TOKEN_SECRET_FILE`
  - 指定 secret 文件路径

如果没有设置 `MAILBOX_QUERY_TOKEN_SECRET`，服务会尝试读取 `.mailbox_query_token_secret`。如果文件不存在，会在当前项目目录自动生成一份新的 secret。

## 启动

### 直接运行

```bash
go run .
```

### 编译后运行

```bash
go build -o getmail
./getmail
```

默认地址：

- 页面: [http://127.0.0.1:8021](http://127.0.0.1:8021)
- 健康检查: [http://127.0.0.1:8021/api/health](http://127.0.0.1:8021/api/health)

## 接口

### `GET /api/health`

返回当前服务状态与基础配置：

```json
{
  "status": "ok",
  "project_root": "/path/to/GetMailGo",
  "resend_api_base": "https://api.resend.com",
  "resend_domain": "ilkoxpra.resend.app",
  "receiving_ready": true,
  "token_secret_source": "file"
}
```

### `POST /api/mailbox/lookup`

请求体：

```json
{
  "mail_token": "mbx_xxx.yyy",
  "timeout": 15,
  "limit": 10
}
```

成功时会返回：

- `status`
- `email`
- `verification_code`
- `latest_subject`
- `latest_received_at`
- `latest_message_id`
- `message_count`
- `messages`
- `message`
- `hint`
- `polled_seconds`

## 与旧项目的兼容关系

这个 Go 版本兼容原 Python 版 `mail_token` 的签名格式和接口返回结构，前端页面也沿用原来的 `GetMail/static` 页面。你可以把它单独部署，也可以让旧主面板通过 HTTP 调这个独立服务。

## 验证

```bash
go test ./...
go build .
```
