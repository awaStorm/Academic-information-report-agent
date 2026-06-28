/**
 * frontend/src/api/config.ts - 配置管理 API
 */
import client from "./client";

export interface ConfigData {
  llm_api_key: string;
  llm_base_url: string;
  llm_model: string;
  temperature: number;
  max_tokens: number;
  wecom_webhook: string;
  serverchan_key: string;
  enable_wecom: boolean;
  enable_console_report: boolean;
  fetch_count: number;
  delay_range: number[];
  wechat_targets: string[];
  scheduler_enabled: boolean;
  run_times: string[];
  failure_alert_threshold: number;
  dashboard_page_size: number;
}

export const configApi = {
  get: () => client.get<{ success: boolean; data: ConfigData }>("/api/v1/config/"),
  update: (data: Partial<ConfigData>) => client.post<{ success: boolean; message: string }>("/api/v1/config/", data),
  testWecom: () => client.post<{ success: boolean; message: string }>("/api/v1/config/test-wecom"),
};
