export interface Config {
  total_accounts: number
  duckmail_api_base: string
  duckmail_bearer: string
  proxy: string
  output_file: string
  enable_oauth: boolean
  oauth_required: boolean
  oauth_issuer: string
  oauth_client_id: string
  oauth_redirect_uri: string
  ak_file: string
  rk_file: string
  token_json_dir: string
  results_dir: string
  max_workers: number
  use_containers: boolean
  container_count: number
  docker_project_dir: string
  docker_compose_file: string
  docker_worker_service: string
  docker_warp_service: string
  sub2api_auto_upload: boolean
  sub2api_upload_url: string
  sub2api_upload_bearer: string
  sub2api_upload_cookie: string
  sub2api_upload_user_agent: string
  sub2api_upload_proxy: string
  sub2api_skip_default_group_bind: boolean
  sub2api_auto_group_bind: boolean
  sub2api_group_id: number
}

export interface TaskStatus {
  status: 'idle' | 'running' | 'stopping' | 'finished' | 'stopped'
  mode?: 'local' | 'containers'
  task_id: string | null
  start_time: string | null
  success_count: number
  fail_count: number
  total_target: number
  container_target?: number
  container_running?: number
  elapsed_seconds: number | null
}

export interface LogEntry {
  timestamp: string
  level: 'info' | 'success' | 'error'
  tag: string
  message: string
}

export interface HistoryRun {
  run_id: string
  timestamp: string
  total_accounts: number
  success_count: number
  fail_count: number
  path: string
}

export interface Account {
  email: string
  password: string
  email_password: string
  oauth_status: string
  access_token?: string
  refresh_token?: string
  id_token?: string
}

export interface Stats {
  total_accounts: number
  total_success: number
  total_fail: number
  success_rate: number
  total_runs: number
  daily: { date: string; success: number; fail: number }[]
}

export interface ConvertRequest {
  source: 'auto' | 'codex_tokens' | 'ak_rk' | 'results_file'
  run_id?: string
  proxy: string
  proxy_name: string
  concurrency: number
  priority: number
  rate_multiplier: number
  auto_pause_on_expired: boolean
  output_filename: string
}

export interface ConvertResult {
  status: string
  accounts_count: number
  output_path: string
  proxy_key: string
}

export interface ConvertibleRun {
  run_id: string
  label: string
  sources: string[]
}
