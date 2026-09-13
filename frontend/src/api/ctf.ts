/**
 * frontend/src/api/ctf.ts - CTFtime API
 */
import client from "./client";

export type CtfStatus = "upcoming" | "running" | "recently_ended";

export interface CtfEvent {
  id: string;
  name: string;
  ctftime_url: string;
  official_url: string;
  date: string;
  start_time: string;
  end_time: string | null;
  format: string;
  location: string;
  weight: number;
  notes: string;
  status: CtfStatus;
}

export interface CtfResponse {
  success: boolean;
  data: CtfEvent[];
  total: number;
  pinned_count: number;
  last_refresh: string | null;
  message?: string;
}

export type SortOption =
  | "default"
  | "weight_desc"
  | "weight_asc"
  | "format_jeopardy"
  | "format_ad"
  | "format_hackquest";

export interface RefreshStatusResponse {
  success: boolean;
  refreshing: boolean;
  phase: string;
  message: string;
}

export const ctfApi = {
  getEvents: (params?: {
    sort?: SortOption;
    format_filter?: string;
    min_weight?: number;
    status_filter?: string;
  }) =>
    client.get<CtfResponse>("/api/v1/ctf/events", { params }),

  refresh: () =>
    client.post<{
      success: boolean;
      refreshing: boolean;
      message?: string;
    }>("/api/v1/ctf/refresh"),

  /** v5 新增：轮询异步刷新进度 */
  refreshStatus: () =>
    client.get<RefreshStatusResponse>("/api/v1/ctf/refresh/status"),

  togglePin: (eventId: string) =>
    client.post<{
      success: boolean;
      action: "pinned" | "unpinned";
      pinned_ids: string[];
    }>(`/api/v1/ctf/pin/${eventId}`),

  getPins: () =>
    client.get<{ success: boolean; pinned_ids: string[] }>("/api/v1/ctf/pins"),
};
