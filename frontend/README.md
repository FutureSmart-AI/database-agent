# Database Agent UI

Follow the [root install guide](../README.md) to run this Next.js UI with the
backend and datastores. The default Docker build uses standalone login and
proxies API requests through Nginx to the backend service named `api`.

For development use Bun 1.4.0, run `bun install --frozen-lockfile`, copy
`.env.example` to `.env.local`, and run `bun run dev`. Start the backend on
port 18000. `bun run build` creates the static `out/` directory.

Public frontend settings are compiled into browser assets. Never put provider
keys or private API credentials there. See [configuration](../docs/configuration.md)
and [AWS deployment](../docs/aws-deployment.md) for authentication and hosting.
