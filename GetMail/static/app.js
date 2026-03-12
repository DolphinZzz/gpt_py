const elements = {
  form: document.getElementById('lookup-form'),
  token: document.getElementById('mail-token'),
  timeout: document.getElementById('timeout'),
  limit: document.getElementById('limit'),
  autoRefresh: document.getElementById('auto-refresh'),
  lookupButton: document.getElementById('lookup-btn'),
  copyTokenButton: document.getElementById('copy-token-btn'),
  clearButton: document.getElementById('clear-btn'),
  banner: document.getElementById('banner'),
  lastUpdated: document.getElementById('last-updated'),
  healthStatus: document.getElementById('health-status'),
  healthMeta: document.getElementById('health-meta'),
  summaryStatus: document.getElementById('summary-status'),
  summaryEmail: document.getElementById('summary-email'),
  summaryCode: document.getElementById('summary-code'),
  summaryCount: document.getElementById('summary-count'),
  summarySubject: document.getElementById('summary-subject'),
  summaryHint: document.getElementById('summary-hint'),
  messagesBody: document.getElementById('messages-body'),
}

let autoRefreshTimer = null
let lastPayload = null

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function setBanner(type, html) {
  elements.banner.className = `banner banner-${type}`
  elements.banner.innerHTML = html
}

function formatValue(value, fallback = '-') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function setLoading(loading) {
  elements.lookupButton.disabled = loading
  elements.lookupButton.textContent = loading ? '查询中...' : '查询邮箱'
}

function renderSummary(data) {
  elements.summaryStatus.textContent = data ? formatValue(data.status) : '未查询'
  elements.summaryEmail.textContent = data ? formatValue(data.email) : '-'
  elements.summaryCode.innerHTML = data?.verification_code
    ? `<span class="code-pill">${escapeHtml(data.verification_code)}</span>`
    : '-'
  elements.summaryCount.textContent = data ? String(data.message_count ?? 0) : '0'
  elements.summarySubject.textContent = data ? formatValue(data.latest_subject) : '-'
  elements.summaryHint.textContent = data ? formatValue(data.hint || data.message) : '等待查询'
}

function renderMessages(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    elements.messagesBody.innerHTML = '<tr class="empty-row"><td colspan="5">暂无邮件</td></tr>'
    return
  }

  elements.messagesBody.innerHTML = messages.map((message) => `
    <tr>
      <td>${escapeHtml(formatValue(message.received_at))}</td>
      <td>${escapeHtml(formatValue(message.subject))}</td>
      <td>${message.verification_code ? `<span class="code-pill">${escapeHtml(message.verification_code)}</span>` : '-'}</td>
      <td>${escapeHtml(formatValue(message.from))}</td>
      <td>${escapeHtml(formatValue(message.preview))}</td>
    </tr>
  `).join('')
}

function updateLastUpdated() {
  const now = new Date()
  elements.lastUpdated.textContent = `最近查询：${now.toLocaleString('zh-CN')}`
}

async function copyText(text, successText) {
  const value = String(text ?? '').trim()
  if (!value) {
    setBanner('warning', '当前没有可复制的内容。')
    return
  }

  try {
    await navigator.clipboard.writeText(value)
    setBanner('success', escapeHtml(successText))
  } catch {
    setBanner('error', '复制失败，请检查浏览器剪贴板权限。')
  }
}

async function fetchHealth() {
  try {
    const response = await fetch('/api/health')
    const data = await response.json()
    elements.healthStatus.textContent = data.receiving_ready ? '已就绪' : '待配置'
    elements.healthMeta.textContent = `域名：${formatValue(data.resend_domain)} | API：${formatValue(data.resend_api_base)}`
  } catch {
    elements.healthStatus.textContent = '不可用'
    elements.healthMeta.textContent = '健康检查失败，请确认服务已启动。'
  }
}

async function lookupMailbox() {
  const mailToken = elements.token.value.trim()
  const timeout = Number(elements.timeout.value || 15)
  const limit = Number(elements.limit.value || 10)

  if (!mailToken) {
    setBanner('warning', '请先输入 <code>mail_token</code>。')
    return
  }

  setLoading(true)
  try {
    const response = await fetch('/api/mailbox/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mail_token: mailToken, timeout, limit }),
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || '查询失败')
    }

    lastPayload = data
    renderSummary(data)
    renderMessages(data.messages)
    updateLastUpdated()

    if (data.status === 'ok' && data.verification_code) {
      setBanner(
        'success',
        `已命中验证码 <code>${escapeHtml(data.verification_code)}</code>，邮箱 <code>${escapeHtml(data.email)}</code>。`,
      )
    } else {
      setBanner('warning', escapeHtml(data.message || '暂未获取到验证码。'))
    }
  } catch (error) {
    lastPayload = null
    renderSummary(null)
    renderMessages([])
    setBanner('error', escapeHtml(error.message || '查询失败'))
  } finally {
    setLoading(false)
  }
}

function resetView() {
  lastPayload = null
  elements.token.value = ''
  renderSummary(null)
  renderMessages([])
  elements.lastUpdated.textContent = '尚未查询'
  setBanner('neutral', '输入 <code>mail_token</code> 后即可查询，页面会优先展示最新可提取的 6 位验证码。')
}

function applyQueryParams() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('mail_token')
  const timeout = params.get('timeout')
  const limit = params.get('limit')
  if (token) {
    elements.token.value = token
  }
  if (timeout) {
    elements.timeout.value = timeout
  }
  if (limit) {
    elements.limit.value = limit
  }
}

function restartAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }

  if (!elements.autoRefresh.checked) {
    return
  }

  autoRefreshTimer = window.setInterval(() => {
    if (elements.token.value.trim()) {
      void lookupMailbox()
    }
  }, 8000)
}

elements.form.addEventListener('submit', (event) => {
  event.preventDefault()
  void lookupMailbox()
})

elements.copyTokenButton.addEventListener('click', () => {
  void copyText(elements.token.value, 'mail_token 已复制到剪贴板。')
})

elements.clearButton.addEventListener('click', () => {
  resetView()
})

elements.autoRefresh.addEventListener('change', restartAutoRefresh)

document.addEventListener('keydown', (event) => {
  const isMetaEnter = (event.metaKey || event.ctrlKey) && event.key === 'Enter'
  if (isMetaEnter) {
    event.preventDefault()
    void lookupMailbox()
  }
})

applyQueryParams()
renderSummary(null)
renderMessages([])
restartAutoRefresh()
void fetchHealth()

