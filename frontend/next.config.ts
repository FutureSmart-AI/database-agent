import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * Where `next dev` forwards `/nl2sql/api/*`.
 *
 * Server-side only (no `NEXT_PUBLIC_`), and only read by the dev server: a
 * static export has no server at request time, so in every deployed build the
 * browser calls `/nl2sql/api/*` on the origin that served the page and the
 * CDN routes it. See `docs/configuration.md`.
 */
const NL2SQL_API_ORIGIN =
  process.env.NL2SQL_API_ORIGIN || "https://app.futuresmart.ai";

/**
 * Database Agent UI — a static export shipped to S3 + CloudFront, so no
 * server runtime exists at request time. Dynamic route segments would need
 * `generateStaticParams`; this app uses flat routes plus a `?agentId=` query
 * parameter instead.
 */
export default function nextConfig(phase: string): NextConfig {
  const config: NextConfig = {
    trailingSlash: true,
    output: "export",
    /**
     * Assets are requested from `/database-agent/_next/…`, not `/_next/…`.
     *
     * On a shared host every product is a path, and a CloudFront behaviour per
     * product points at that product's bucket. An unprefixed `/_next/static/…`
     * would not match this product's behaviour and would be served from
     * another build. The prefix keeps a page and its own JavaScript together.
     *
     * `basePath` is deliberately *not* used: the routes already live under
     * `src/app/database-agent/`, so a base path would nest them twice.
     * The deploy workflow uploads `out/` under the same prefix.
     */
    assetPrefix: "/database-agent",
    images: { unoptimized: true },
    compiler: {
      removeConsole:
        process.env.NODE_ENV === "production"
          ? { exclude: ["error", "warn"] }
          : false,
    },
    experimental: {
      optimizePackageImports: [
        "lodash-es",
        "@tanstack/react-query",
        "dayjs",
        "recharts",
      ],
    },
  };

  if (phase !== PHASE_DEVELOPMENT_SERVER) return config;

  /**
   * Development only: the page's own origin answers `/nl2sql/api/*` by
   * proxying it, which is what CloudFront does in production. The request —
   * cookies included — is forwarded as the browser sent it, so it
   * authenticates only when the browser holds a FutureSmart session, i.e.
   * when dev is served from a `futuresmart.ai` host (`bun run dev:secure`).
   */
  return {
    ...config,
    output: undefined,
    // API paths are canonicalized by FastAPI; redirecting them here loops.
    skipTrailingSlashRedirect: true,
    async rewrites() {
      return [
        {
          source: "/nl2sql/api/:path*",
          destination: `${NL2SQL_API_ORIGIN}/nl2sql/api/:path*`,
        },
      ];
    },
  };
}
