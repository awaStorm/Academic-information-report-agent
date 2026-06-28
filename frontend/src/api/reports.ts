/**
 * frontend/src/api/reports.ts - 报告管理 API
 */
import client from "./client";

export const reportsApi = {
  list: () => client.get<{ success: boolean; data: string[] }>("/api/v1/reports/"),
  get: (filename: string) =>
    client.get<{ success: boolean; data: { filename: string; content: string } }>(`/api/v1/reports/${filename}`),
};
