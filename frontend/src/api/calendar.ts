/**
 * frontend/src/api/calendar.ts - 事件日历 API
 */
import client from "./client";

export interface CalendarCtfEvent {
  id: string;
  name: string;
  status: string;
  ctftime_url?: string;
  official_url?: string;
  format?: string;
  location?: string;
  weight?: number;
  start_time?: string | null;
  end_time?: string | null;
}

export interface CalendarIntelItem {
  title: string;
  platform: string;
  category: string;
  brief: string;
  link: string;
  links?: string[];
  status: string;
  push_time: string;
  event_date?: string | null;
  timeline?: Array<{ label: string; date: string; time?: string }>;
  /** 该卡片因 timeline 节点出现在当天时的节点信息；主事件打点为 null/undefined */
  timeline_node?: { label: string; time?: string } | null;
}

export interface CalendarDayData {
  ctf: CalendarCtfEvent[];
  intel: CalendarIntelItem[];
}

export interface CalendarResponse {
  success: boolean;
  month: string;
  days: Record<string, CalendarDayData>;
  totals: { ctf: number; intel: number };
}

export const calendarApi = {
  getCalendar: (month: string) =>
    client.get<CalendarResponse>("/api/v1/calendar", { params: { month } }),
};
