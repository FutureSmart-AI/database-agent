"use client";

import { useState, type FormEvent } from "react";

export default function StandaloneLogin() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/nl2sql/api/v1/local-auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      setPassword("");
      if (!response.ok) {
        setError(
          response.status === 401
            ? "Invalid password."
            : "Sign-in failed. Check the standalone server configuration.",
        );
        return;
      }
      const requested = new URLSearchParams(window.location.search).get(
        "redirect",
      );
      const destination = new URL(
        requested || "/database-agent/",
        window.location.origin,
      );
      window.location.assign(
        destination.origin === window.location.origin
          ? destination.href
          : "/database-agent/",
      );
    } catch {
      setError("Cannot reach the Database Agent server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 420, margin: "12vh auto", padding: 24 }}>
      <h1 style={{ fontSize: 28, marginBottom: 12 }}>Database Agent</h1>
      <p style={{ marginBottom: 24 }}>
        Sign in to this standalone installation.
      </p>
      <form onSubmit={login}>
        <label htmlFor="password">Installation password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          style={{
            display: "block",
            width: "100%",
            border: "1px solid #999",
            padding: 12,
            margin: "8px 0 16px",
          }}
        />
        <button
          type="submit"
          disabled={busy}
          style={{
            background: "#151515",
            color: "white",
            padding: "10px 20px",
          }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error && (
          <p role="alert" style={{ marginTop: 16 }}>
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
