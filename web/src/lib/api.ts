// Server-side base URL for FastAPI. Client components should call `/api/...` instead.
export const API_URL = process.env.API_URL ?? "http://localhost:8000";
