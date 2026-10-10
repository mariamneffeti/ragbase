export function getApiUrl() {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const baseUrl = configuredUrl.replace(/\/+$/, "");
  return /\/api\/v1$/i.test(baseUrl) ? baseUrl : `${baseUrl}/api/v1`;
}

export function apiUrl(path: string) {
  return `${getApiUrl()}/${path.replace(/^\/+/, "")}`;
}
