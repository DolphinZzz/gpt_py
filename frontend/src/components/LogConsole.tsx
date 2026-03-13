import { useEffect, useRef } from 'react'
import type { LogEntry } from '../types'

const levelColors: Record<string, string> = {
  success: '#52c41a',
  error: '#ff4d4f',
  warning: '#faad14',
  info: '#8c8c8c',
}

const levelBackgrounds: Record<string, string> = {
  success: 'rgba(82, 196, 26, 0.08)',
  error: 'rgba(255, 77, 79, 0.12)',
  warning: 'rgba(250, 173, 20, 0.12)',
  info: 'transparent',
}

function renderMessage(message: string) {
  const parts = String(message || '').split(/(https?:\/\/[^\s]+)/g)

  return parts.map((part, index) => {
    if (/^https?:\/\/[^\s]+$/.test(part)) {
      return (
        <a
          key={`${part}-${index}`}
          href={part}
          target="_blank"
          rel="noreferrer"
          style={{ color: '#69b1ff', textDecoration: 'underline' }}
        >
          {part}
        </a>
      )
    }
    return <span key={`${index}-${part.slice(0, 12)}`}>{part}</span>
  })
}

export default function LogConsole({ logs, autoScroll = true }: { logs: LogEntry[]; autoScroll?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs.length, autoScroll])

  return (
    <div
      ref={containerRef}
      style={{
        background: '#1e1e1e',
        color: '#d4d4d4',
        fontFamily: "'Cascadia Code', 'Consolas', 'Courier New', monospace",
        fontSize: 13,
        padding: 16,
        borderRadius: 8,
        height: '100%',
        minHeight: 400,
        overflowY: 'auto',
        lineHeight: 1.6,
      }}
    >
      {logs.length === 0 && (
        <div style={{ color: '#666', textAlign: 'center', paddingTop: 80 }}>
          暂无日志，启动任务后将在此显示实时日志...
        </div>
      )}
      {logs.map((log, i) => (
        <div
          key={i}
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            padding: '6px 10px',
            borderLeft: `3px solid ${levelColors[log.level] || '#2f2f2f'}`,
            background: levelBackgrounds[log.level] || 'transparent',
            marginBottom: 6,
            borderRadius: 6,
          }}
        >
          <span style={{ color: '#666' }}>{log.timestamp}</span>
          {' '}
          {log.tag && <span style={{ color: '#569cd6' }}>[{log.tag}]</span>}
          {' '}
          <span style={{ color: levelColors[log.level] || '#d4d4d4' }}>{renderMessage(log.message)}</span>
        </div>
      ))}
    </div>
  )
}
