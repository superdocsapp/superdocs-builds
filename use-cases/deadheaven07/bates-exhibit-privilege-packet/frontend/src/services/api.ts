import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';
import { toast } from '@/components/ui/use-toast';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: any) => void;
  reject: (reason: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(() => api(originalRequest));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // In a real app, you'd refresh the token here
        // For now, we'll just redirect to login
        toast({
          title: 'Session expired',
          description: 'Please log in again',
          variant: 'destructive',
        });
        window.location.href = '/login';
        return Promise.reject(error);
      } catch (err) {
        return Promise.reject(err);
      } finally {
        isRefreshing = false;
        processQueue(null);
      }
    }

    if (error.response?.status && error.response.status >= 500) {
      toast({
        title: 'Server error',
        description: 'An unexpected error occurred. Please try again.',
        variant: 'destructive',
      });
    }

    return Promise.reject(error);
  }
);

export default api;