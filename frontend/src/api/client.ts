/**
 * frontend/src/api/client.ts - API 客户端
 * 封装 axios，统一处理请求/响应，拦截器自动解包 response.data
 */
import axios, { type AxiosRequestConfig } from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8138";

const instance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 响应拦截器：自动解包 response.data，错误统一处理
instance.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.message || error.message || "请求失败";
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
