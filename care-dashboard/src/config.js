/** API base URL — set VITE_API_URL at build time (EC2 / api.care.verbilab.com). */
export const API_ROOT =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? "https://api.care.verbilab.com" : "http://localhost:5000");
