"use client";

const ADMIN_TOKEN_KEY = "mone:adminToken";

export function getAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

export function saveAdminToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export function adminAuthHeaders(token?: string): Record<string, string> {
  const value = token || getAdminToken();
  return value ? { Authorization: `Bearer ${value}` } : {};
}
