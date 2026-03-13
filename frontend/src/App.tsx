import { useState } from 'react'
import { Layout, Menu, theme, Typography } from 'antd'
import type { MenuProps } from 'antd'
import {
  DashboardOutlined,
  SettingOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
  HistoryOutlined,
  TeamOutlined,
  SwapOutlined,
  LockOutlined,
} from '@ant-design/icons'

import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import TaskControl from './pages/TaskControl'
import Logs from './pages/Logs'
import History from './pages/History'
import Accounts from './pages/Accounts'
import Convert from './pages/Convert'
import SensitiveCopy from './pages/SensitiveCopy'

const { Sider, Content, Header } = Layout
const { Title } = Typography

const menuItems = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: '仪表板' },
  { key: 'task', icon: <PlayCircleOutlined />, label: '任务控制' },
  { key: 'logs', icon: <FileTextOutlined />, label: '实时日志' },
  { key: 'config', icon: <SettingOutlined />, label: '参数配置' },
  { key: 'sensitive-copy', icon: <LockOutlined />, label: '敏感复制' },
  { key: 'convert', icon: <SwapOutlined />, label: 'Sub2API 转换' },
  { key: 'history', icon: <HistoryOutlined />, label: '历史记录' },
  { key: 'accounts', icon: <TeamOutlined />, label: '账号列表' },
]

const pages: Record<string, React.ReactNode> = {
  dashboard: <Dashboard />,
  task: <TaskControl />,
  logs: <Logs />,
  config: <Config />,
  'sensitive-copy': <SensitiveCopy />,
  convert: <Convert />,
  history: <History />,
  accounts: <Accounts />,
}

type MenuClickKey = Parameters<NonNullable<MenuProps['onClick']>>[0]['key']

export default function App() {
  const [current, setCurrent] = useState('dashboard')
  const [collapsed, setCollapsed] = useState(false)
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={200}
      >
        <div style={{ height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '8px 0' }}>
          <Title level={4} style={{ color: '#fff', margin: 0, fontSize: collapsed ? 16 : 18 }}>
            {collapsed ? 'GPT' : 'GPT 注册工具'}
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[current]}
          onClick={({ key }) => setCurrent(String(key as MenuClickKey))}
          items={menuItems}
        />
      </Sider>
      <Layout style={{ background: '#141414' }}>
        <Header style={{ padding: '0 24px', background: colorBgContainer, display: 'flex', alignItems: 'center' }}>
          <Title level={4} style={{ margin: 0 }}>
            {menuItems.find(m => m.key === current)?.label}
          </Title>
        </Header>
        <Content style={{ margin: 16, padding: 24, background: colorBgContainer, borderRadius: borderRadiusLG, overflow: 'auto' }}>
          {pages[current]}
        </Content>
      </Layout>
    </Layout>
  )
}
