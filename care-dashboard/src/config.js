/** API base URL — set VITE_API_URL in Amplify at build time (https://api.care.verbilab.com). */
export const API_ROOT =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? "https://api.care.verbilab.com" : "http://localhost:5000");
