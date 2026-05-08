import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:5000";

export default function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("admin@care.ai");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || "Login failed"); return; }
      localStorage.setItem("care_token", data.token);
      localStorage.setItem("care_user", JSON.stringify(data.user));
      onLogin(data.user);
    } catch (err) {
      setError("Cannot reach server. Is Flask running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-4">
            <div className="w-12 h-12 bg-cyan-500 rounded-xl flex items-center justify-center shadow-lg shadow-cyan-500/30">
              <span className="text-black font-bold text-xl">C</span>
            </div>
            <div className="text-left">
              <p className="text-white font-bold text-2xl tracking-tight">CARE</p>
              <p className="text-gray-400 text-xs">Call Audit & Conduct Risk Engine</p>
            </div>
          </div>
          <h1 className="text-gray-100 text-2xl font-semibold">Sign in to your account</h1>
          <p className="text-gray-500 text-sm mt-1">Company Finance · QA Platform</p>
        </div>

        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-8 shadow-xl">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Email address</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition-colors"
                placeholder="you@company.ai"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition-colors"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-3 text-sm text-red-300 flex items-center gap-2">
                <span>⚠</span> {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-800 disabled:cursor-not-allowed text-black font-semibold py-3 rounded-lg transition-colors text-sm"
            >
              {loading ? "Signing in…" : "Sign In"}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-gray-800">
            <p className="text-xs text-gray-500 text-center mb-2">Default credentials</p>
            <div className="flex justify-center gap-2">
              <span className="font-mono bg-gray-800 text-gray-300 text-xs px-3 py-1.5 rounded-lg">admin@care.ai</span>
              <span className="text-gray-600 text-xs py-1.5">/</span>
              <span className="font-mono bg-gray-800 text-gray-300 text-xs px-3 py-1.5 rounded-lg">care@2025</span>
            </div>
          </div>
        </div>

        <p className="text-center text-xs text-gray-600 mt-6">
          Company Finance · CARE v1.0 · Confidential
        </p>
      </div>
    </div>
  );
}