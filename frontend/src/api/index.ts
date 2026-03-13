import axios from 'axios'
import { useEffect, useRef, useCallback, useState } from 'react'
import type {
  AccountPaymentLinksResult,
  Config,
  LogEntry,
  ConvertRequest,
  ConvertResult,
  ConvertibleRun,
  MailboxCodeResult,
  RefreshAccountTokensResult,
} from '../types'

const api = axios.create({ baseURL: '/api' })

export const getConfig = () => api.get<Config>('/config')
export const updateConfig = (data: Config) => api.put('/config', data)
export const startTask = (params?: {
  total_accounts?: number
  max_workers?: number
  proxy?: string
  use_containers?: boolean
  container_count?: number
}) =>
  api.post('/tasks/start', params || {})
export const stopTask = () => api.post('/tasks/stop')
export const getTaskStatus = () => api.get('/tasks/status')
export const getTaskHistory = () => api.get('/tasks/history')
export const getAccounts = (runId?: string) =>
  api.get('/accounts', { params: runId ? { run_id: runId } : {} })
export const refreshAccountTokens = (data: {
  accounts: Array<{ run_id: string; email: string; refresh_token: string; line_no?: number }>
  proxy?: string
}) =>
  api.post<RefreshAccountTokensResult>('/accounts/refresh-tokens', data)
export const getAccountPaymentLinks = (data: {
  email: string
  password: string
  run_id?: string
  line_no?: number
  mail_token?: string
  access_token?: string
  refresh_token?: string
  id_token?: string
  proxy?: string
}) =>
  api.post<AccountPaymentLinksResult>('/accounts/payment-links', data)
export const queryMailboxCode = (data: { mail_token: string; timeout?: number }) =>
  api.post<MailboxCodeResult>('/mailbox/code', data)
export const getStats = () => api.get('/stats')
export const convertToSub2Api = (data: ConvertRequest) => api.post<ConvertResult>('/convert', data)
export const getConvertibleRuns = () => api.get<ConvertibleRun[]>('/convert/runs')
export const uploadBackfillAccounts = () => api.post('/upload/backfill')
export const getDockerContainers = (service = 'worker') =>
  api.get<string[]>('/docker/containers', { params: { service } })

export function useLogWebSocket(
  onMessage: (entry: LogEntry) => void,
  options?: { source?: 'app' | 'container'; service?: string; container?: string; tail?: number },
) {
  const wsRef = useRef<WebSocket | null>(null)
  const onMessageRef = useRef(onMessage)
  const [connected, setConnected] = useState(false)
  onMessageRef.current = onMessage

  const source = options?.source || 'app'
  const service = options?.service || 'worker'
  const container = options?.container || ''
  const tail = options?.tail || 200

  const endpoint = source === 'container'
    ? `/ws/container-logs?service=${encodeURIComponent(service)}&container=${encodeURIComponent(container)}&tail=${tail}`
    : '/ws/logs'

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}${endpoint}`)

    ws.onopen = () => setConnected(true)
    ws.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data) as LogEntry
        onMessageRef.current(entry)
      } catch {}
    }
    ws.onclose = () => {
      setConnected(false)
      setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()
    wsRef.current = ws
  }, [endpoint])

  useEffect(() => {
    connect()
    return () => { wsRef.current?.close() }
  }, [connect])

  return { connected }
}

export default api
