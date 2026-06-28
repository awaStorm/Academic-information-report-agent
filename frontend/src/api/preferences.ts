/**
 * frontend/src/api/preferences.ts - 偏好设置 API
 */
import client from "./client";

export const preferencesApi = {
  get: () => client.get<{ success: boolean; data: { categories: string[] } }>("/api/v1/preferences/"),
  update: (categories: string[]) =>
    client.post<{ success: boolean; data: { categories: string[] } }>("/api/v1/preferences/", { categories }),
};
