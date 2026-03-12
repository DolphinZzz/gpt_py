# GetMail

GetMail 是一个独立的邮件查询 Web，用来配合当前仓库的注册项目使用。它接收主项目生成的 `mail_token`，查询对应 Resend 随机邮箱的最新邮件，并尽量从正文中提取 6 位验证码。

这个目录是一个独立项目，目标是把“查邮件/查验证码”能力从主面板里拆出来，单独启动、单独访问、单独部署。

## 功能概览

- 用 `mail_token` 查询对应邮箱，不需要直接暴露邮箱地址。
- 支持等待轮询，适合刚触发验证码、邮件还没到的时候直接盯着看。
- 返回最新验证码、最新主题、最近若干封邮件摘要。
- 自带简单的健康检查接口和 Swagger 文档。
- 前端采用原生 HTML/CSS/JS，无额外打包步骤，部署简单。

## 目录结构

```text
GetMail/
├── __init__.py
├── app.py
├── mail_service.py
├── README.md
├── requirements.txt
└── static
    ├── app.js
    ├── index.html
    └── styles.css
```

## 工作原理

1. 主注册项目在创建 Resend 随机邮箱时，会生成一个带签名的 `mail_token`。
2. GetMail 收到这个 `mail_token` 后，会调用根目录的 `chatgpt_register.py` 来：
   - 解析 token
   - 获取对应邮箱
   - 拉取 Resend Receiving API 的入站邮件
   - 提取正文中的 6 位验证码
3. 页面展示查询结果和最近邮件摘要。

换句话说，GetMail 是一个独立入口，但底层复用了当前仓库已经跑通的 Resend 查询逻辑。

## 运行前提

必须满足以下条件，否则页面能打开，但查不到邮件：

- 根目录的 `config.json` 已正确配置 `resend_api_base`、`resend_api_key`、`resend_domain`
- 或者你通过环境变量显式提供了这些值
- `mail_token` 必须由当前仓库的主项目生成，或者你在外部环境里使用了同一份签名密钥

## 安装依赖

推荐在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r GetMail/requirements.txt
```

如果你已经给主项目装过依赖，通常不需要重复安装。

## 启动方式

### 方式一：直接运行

```bash
python3 GetMail/app.py
```

默认监听：

- Host: `0.0.0.0`
- Port: `8021`

启动后访问：

- 页面: [http://127.0.0.1:8021](http://127.0.0.1:8021)
- Swagger: [http://127.0.0.1:8021/docs](http://127.0.0.1:8021/docs)

### 方式二：用 uvicorn 启动

```bash
uvicorn GetMail.app:app --host 0.0.0.0 --port 8021
```

## 环境变量

### GetMail 自身

- `GETMAIL_HOST`
  - 默认值：`0.0.0.0`
  - 说明：服务监听地址

- `GETMAIL_PORT`
  - 默认值：`8021`
  - 说明：服务监听端口

- `GETMAIL_PROJECT_ROOT`
  - 默认值：当前仓库根目录
  - 说明：如果你把 `GetMail/` 单独拎出来运行，可以手动指定主项目根目录，让它找到 `chatgpt_register.py`

### 复用主项目的配置

GetMail 会直接使用主项目已经存在的配置来源：

- `config.json`
- `RESEND_API_BASE`
- `RESEND_API_KEY`
- `RESEND_DOMAIN`

### 关于 `MAILBOX_QUERY_TOKEN_SECRET`

`mail_token` 是签名过的。签名密钥的来源规则如下：

1. 如果设置了环境变量 `MAILBOX_QUERY_TOKEN_SECRET`，优先使用它
2. 否则使用仓库根目录里的 `.mailbox_query_token_secret`

这意味着：

- 如果主项目和 GetMail 跑在同一份仓库里，通常不需要额外处理
- 如果你要把 GetMail 单独部署到其他机器，必须同步这份密钥，否则旧 token 会失效

## 页面使用方法

1. 从主项目的结果文件或账号列表中拿到 `mail_token`
2. 打开 GetMail 页面
3. 把 `mail_token` 粘贴进输入框
4. 选择等待秒数
5. 点击“查询邮箱”
6. 页面会返回：
   - 最新验证码
   - 对应邮箱
   - 最新邮件主题
   - 最近邮件摘要列表

### 自动轮询

如果勾选“自动轮询”，页面会每 8 秒自动重查一次。适合以下场景：

- 刚触发注册验证码
- 邮件正在路上
- 你希望单开一个页面盯着结果刷新

## API 说明

### `GET /api/health`

返回当前服务状态和基础配置是否就绪。

示例响应：

```json
{
  "status": "ok",
  "project_root": "/path/to/gpt_py",
  "resend_api_base": "https://api.resend.com",
  "resend_domain": "ilkoxpra.resend.app",
  "receiving_ready": true,
  "token_secret_source": "file"
}
```

### `POST /api/mailbox/lookup`

按 `mail_token` 查询邮箱。

请求体：

```json
{
  "mail_token": "mbx_xxx.yyy",
  "timeout": 15,
  "limit": 10
}
```

字段说明：

- `mail_token`
  - 必填
  - 主项目生成的邮箱查询 token

- `timeout`
  - 可选，默认 `15`
  - 取值范围 `0-120`
  - 表示最多等待多少秒

- `limit`
  - 可选，默认 `10`
  - 取值范围 `1-20`
  - 表示返回最近多少封邮件摘要

成功命中验证码时，响应示例：

```json
{
  "status": "ok",
  "email": "abc123@ilkoxpra.resend.app",
  "verification_code": "123456",
  "latest_subject": "Your verification code",
  "latest_received_at": "2026-03-13T00:10:20.000Z",
  "latest_message_id": "4f2d...",
  "message_count": 3,
  "messages": [
    {
      "id": "4f2d...",
      "subject": "Your verification code",
      "from": "OpenAI <noreply@tm.openai.com>",
      "to": "abc123@ilkoxpra.resend.app",
      "received_at": "2026-03-13T00:10:20.000Z",
      "verification_code": "123456",
      "preview": "Verification code: 123456"
    }
  ],
  "message": "已提取到最新验证码",
  "hint": "",
  "polled_seconds": 2.1
}
```

未命中验证码时，响应示例：

```json
{
  "status": "pending",
  "email": "abc123@ilkoxpra.resend.app",
  "verification_code": null,
  "latest_subject": "",
  "latest_received_at": null,
  "latest_message_id": null,
  "message_count": 0,
  "messages": [],
  "message": "暂未收到任何邮件",
  "hint": "Resend Receiving API 当前未看到发给 abc123@ilkoxpra.resend.app 的入站邮件。",
  "polled_seconds": 15.0
}
```

## 与主项目的配合方式

GetMail 依赖主项目生成的 `mail_token`。当前仓库里，`mail_token` 会写进 `registered_accounts.txt`，格式类似：

```text
邮箱----密码----空邮箱密码----mail_token=mbx_xxx.yyy----oauth=ok----access_token=...
```

如果你是从主项目面板里复制，也可以直接拿账号列表中的 `Mail Token` 字段。

## 常见问题

### 1. 页面能打开，但一直查不到邮件

优先检查：

- `RESEND_API_KEY` 是否有 Receiving API 读取权限
- `RESEND_DOMAIN` 是否和生成邮箱时使用的域名一致
- 验证码邮件是否真的发到了这个完整地址
- Resend 后台的 Receiving Domain 是否可用

### 2. 提示 `mail_token 无效`

常见原因：

- token 被截断了
- 复制时混入了空格或换行
- GetMail 使用的签名密钥和主项目生成 token 时的不一致

### 3. 为什么换机器后旧 token 失效

因为 `mail_token` 是签名的。如果你在新机器上没有同步：

- `.mailbox_query_token_secret`
- 或环境变量 `MAILBOX_QUERY_TOKEN_SECRET`

那么旧 token 无法被验证。

### 4. 为什么看到邮件了，但没有提取出验证码

当前逻辑只会提取正文里的常见 6 位验证码格式。如果目标邮件模板发生变化，可能需要在根目录的 `chatgpt_register.py` 里补充匹配规则。

## 安全建议

- 不要把 `.mailbox_query_token_secret` 提交到代码仓库
- 不要把 `RESEND_API_KEY` 暴露到浏览器端
- 如果 GetMail 要公网部署，建议挂到内网或加鉴权
- 如果要跨机器部署，固定 `MAILBOX_QUERY_TOKEN_SECRET`，避免 token 因密钥漂移失效

## 开发说明

### 本地校验建议

后端语法检查：

```bash
PYTHONPYCACHEPREFIX=/tmp/getmail_pycache python3 -m py_compile GetMail/app.py GetMail/mail_service.py
```

### 页面改动

前端是纯静态资源，直接修改以下文件即可：

- `GetMail/static/index.html`
- `GetMail/static/styles.css`
- `GetMail/static/app.js`

不需要打包，不需要构建。

## 后续可扩展项

- 增加邮件详情抽屉，直接查看完整正文
- 增加单条消息原文复制
- 增加 token 历史记录
- 增加简单鉴权
- 增加 Dockerfile 和反向代理示例
