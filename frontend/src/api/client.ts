/**
 * frontend/src/api/client.ts - API 客户端
 * 封装 axios，统一处理请求/响应，拦截器自动解包 response.data
 */
import axios, { type AxiosRequestConfig } from "axios";

/** 后端 REST 地址：VITE_API_BASE_URL 优先，默认本机 8138（websocket.ts 复用其推导 WS 地址） */
export const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8138";

const instance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 响应拦截器：自动解包 response.data，错误统一处理
// 错误文案优先取业务字段 message，其次取 FastAPI HTTPException 的 detail，
// 最后才退回 axios 的 "Request failed with status code 500" 这类无信息量文案
instance.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const data = error.response?.data;
    // FastAPI 422 校验错误的 detail 是 [{loc,msg,input},...] 数组，
    // 直接拼进字符串会变成 [object Object]；这里提取每条 msg 拼成可读文案。
    let detailMsg = "";
    if (Array.isArray(data?.detail)) {
      detailMsg = data.detail
        .map((d: { msg?: string; loc?: unknown[] }) =>
          d?.msg ? `${Array.isArray(d.loc) ? d.loc.slice(1).join(".") + ": " : ""}${d.msg}` : "")
        .filter(Boolean)
        .join("；");
    } else if (typeof data?.detail === "string") {
      detailMsg = data.detail;
    }
    const message = data?.message || detailMsg || error.message || "请求失败";
    return Promise.reject(new Error(message));
  }
);

/** 类型安全的 API 客户端，泛型 T 表示解包后的返回数据类型 */
const api = {
  get: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    instance.get(url, config) as Promise<T>,
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> =>
    instance.post(url, data, config) as Promise<T>,
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> =>
    instance.put(url, data, config) as Promise<T>,
  delete: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    instance.delete(url, config) as Promise<T>,
};

export default api;
