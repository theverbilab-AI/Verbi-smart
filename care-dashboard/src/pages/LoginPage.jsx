import { useState, useEffect } from "react";
import { API_ROOT } from "../config.js";
import BrandLogo from "../components/BrandLogo";
import { COMPANY_NAME } from "../config/branding.js";
import { getAuthConfig } from "../services/api";

const API = API_ROOT;

export default function LoginPage({ onLogin }) {
  const [mode, setMode] = useState("otp"); // otp | password
  const [passwordAllowed, setPasswordAllowed] = useState(false);
  const [step, setStep] = useState("email"); // email | code
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [expiresIn, setExpiresIn] = useState(0);

  useEffect(() => {
    getAuthConfig()
      .then((cfg) => {
        setPasswordAllowed(Boolean(cfg.password_enabled));
        if (!cfg.otp_enabled && cfg.password_enabled) setMode("password");
      })
      .catch(() => {});
  }, []);

  const finishLogin = (data) => {
    localStorage.setItem("care_token", data.token);
    localStorage.setItem("care_user", JSON.stringify(data.user));
    onLogin(data.user);
  };

  const handleSendOtp = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const res = await fetch(`${API}/api/auth/otp/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Could not send code");
        return;
      }
      setStep("code");
      setExpiresIn(data.expires_in || 300);
      setInfo(data.message || "Check your email for the verification code.");
      if (data.dev_code) {
        setInfo(`Email could not be sent — use this code: ${data.dev_code}`);
      }
    } catch {
      setError("Cannot reach server. Check backend API URL.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/auth/otp/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          code: code.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Invalid code");
        return;
      }
      finishLogin(data);
    } catch {
      setError("Cannot reach server.");
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordLogin = async (e) => {
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
      if (!res.ok) {
        setError(data.error || "Login failed");
        return;
      }
      finishLogin(data);
    } catch {
      setError("Cannot reach server. Please check backend API.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex justify-center mb-6">
            <BrandLogo size="lg" stacked />
          </div>
          <h1 className="text-gray-100 text-2xl font-semibold">Sign in to your account</h1>
          <p className="text-gray-500 text-sm mt-1">Company Finance · QA Platform</p>
        </div>

        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-8 shadow-xl">
          <div className="flex gap-2 mb-6 p-1 bg-gray-800 rounded-lg">
            <button
              type="button"
              onClick={() => { setMode("otp"); setStep("email"); setError(""); }}
              className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                mode === "otp" ? "bg-cyan-500 text-black" : "text-gray-400 hover:text-white"
              }`}
            >
              Email OTP
            </button>
            {passwordAllowed && (
              <button
                type="button"
                onClick={() => { setMode("password"); setError(""); }}
                className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                  mode === "password" ? "bg-cyan-500 text-black" : "text-gray-400 hover:text-white"
                }`}
              >
                Password
              </button>
            )}
          </div>

          {mode === "otp" ? (
            step === "email" ? (
              <form onSubmit={handleSendOtp} className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1.5">Work email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
                    placeholder="you@company.ai"
                  />
                </div>
                {error && <ErrorBox message={error} />}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-800 text-black font-semibold py-3 rounded-lg text-sm"
                >
                  {loading ? "Sending…" : "Send verification code"}
                </button>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp} className="space-y-5">
                <p className="text-sm text-gray-400">
                  Code sent to <span className="text-gray-200">{email}</span>
                  {expiresIn ? (
                    <span className="text-gray-500"> · expires in {Math.round(expiresIn / 60)} min</span>
                  ) : null}
                </p>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1.5">6-digit code</label>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={8}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    required
                    autoFocus
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-lg tracking-[0.4em] text-center font-mono focus:outline-none focus:border-cyan-500"
                    placeholder="••••••"
                  />
                </div>
                {info && <div className="text-sm text-cyan-300/90 bg-cyan-950/40 border border-cyan-800/50 rounded-lg px-4 py-3">{info}</div>}
                {error && <ErrorBox message={error} />}
                <button
                  type="submit"
                  disabled={loading || code.length < 4}
                  className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-800 text-black font-semibold py-3 rounded-lg text-sm"
                >
                  {loading ? "Verifying…" : "Verify & sign in"}
                </button>
                <button
                  type="button"
                  onClick={() => { setStep("email"); setCode(""); setError(""); }}
                  className="w-full text-sm text-gray-500 hover:text-gray-300"
                >
                  ← Use a different email
                </button>
              </form>
            )
          ) : (
            <form onSubmit={handlePasswordLogin} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1.5">Email address</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-cyan-500"
                  placeholder="admin@care.ai"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1.5">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-cyan-500"
                />
              </div>
              {error && <ErrorBox message={error} />}
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-cyan-500 hover:bg-cyan-400 disabled:bg-cyan-800 text-black font-semibold py-3 rounded-lg text-sm"
              >
                {loading ? "Signing in…" : "Sign In"}
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-xs text-gray-600 mt-6">
          Sign-in codes are sent via AWS SES · {COMPANY_NAME}
        </p>
      </div>
    </div>
  );
}

function ErrorBox({ message }) {
  return (
    <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-3 text-sm text-red-300 flex items-center gap-2">
      <span>⚠</span> {message}
    </div>
  );
}
