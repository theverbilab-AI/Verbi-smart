/** API base URL — set VITE_API_URL at build time, or use same-origin /api (Amplify proxy → EC2). */
export const API_ROOT =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? "" : "http://localhost:5000");
