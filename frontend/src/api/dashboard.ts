/**
 * frontend/src/api/dashboard.ts - 仪表盘 API
 */
import client from "./client";

export interface DashboardRecord {
  title: string;
  platform: string;
  category: string;
  brief: string;
  link: string;
  status: string;
  push_time: string;
}

export interface DashboardStats {
  today: number;
  week: number;
  wechat: number;
  chaoxing: number;
}

export const dashboardApi = {
  getRecords: (params: { start_date?: string; end_date?: string; platform?: string }) =>
    client.get<{ success: boolean; data: DashboardRecord[]; total: number }>("/api/v1/dashboard/records", { params }),
  getStats: () => client.get<{ success: boolean; data: DashboardStats }>("/api/v1/dashboard/stats"),
};
