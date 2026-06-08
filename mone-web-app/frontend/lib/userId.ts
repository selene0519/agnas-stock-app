/**
 * 익명 사용자 ID 관리.
 * localStorage에 UUID를 저장해 브라우저별 보유종목 데이터를 분리한다.
 * 로그인 기능 구현 시 이 ID를 실제 사용자 ID로 교체하면 된다.
 */
const STORAGE_KEY = "mone:userId";
const USER_TOKEN_KEY = "mone:userToken";
const USER_PROFILE_KEY = "mone:userProfile";

export type MoneUserProfile = {
  userId: string;
  provider?: string;
  email?: string;
  name?: string;
  expiresAt?: number;
};

function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function getUserId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = generateId();
      localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    return "";
  }
}

export function setAuthenticatedUser(profile: MoneUserProfile, token: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, profile.userId);
    localStorage.setItem(USER_TOKEN_KEY, token);
    localStorage.setItem(USER_PROFILE_KEY, JSON.stringify(profile));
  } catch {}
}

export function getUserProfile(): MoneUserProfile | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_PROFILE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function getUserToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(USER_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function clearAuthenticatedUser(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(USER_TOKEN_KEY);
    localStorage.removeItem(USER_PROFILE_KEY);
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

export function clearUserId(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}
