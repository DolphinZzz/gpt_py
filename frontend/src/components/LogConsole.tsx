import { useEffect, useRef } from 'react'
import type { LogEntry } from '../types'

const levelColors: Record<string, string> = {
  success: '#52c41a',
  error: '#ff4d4f',
  info: '#8c8c8c',
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
        <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          <span style={{ color: '#666' }}>{log.timestamp}</span>
          {' '}
          {log.tag && <span style={{ color: '#569cd6' }}>[{log.tag}]</span>}
          {' '}
          <span style={{ color: levelColors[log.level] || '#d4d4d4' }}>{log.message}</span>
        </div>
      ))}
    </div>
  )
}
