FROM oven/bun:1.4.0 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_AUTH_MODE=standalone
ARG NEXT_PUBLIC_AUTH_URL=https://auth.futuresmart.ai
ARG NEXT_PUBLIC_PUBLIC_HOST=https://agent.futuresmart.ai
ENV NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE}
ENV NEXT_PUBLIC_AUTH_URL=${NEXT_PUBLIC_AUTH_URL}
ENV NEXT_PUBLIC_PUBLIC_HOST=${NEXT_PUBLIC_PUBLIC_HOST}
# Optional hosted public client token: keep it out of build arguments and logs.
RUN --mount=type=secret,id=voice_gateway_key \
    NEXT_PUBLIC_VOICE_GATEWAY_KEY="$(cat /run/secrets/voice_gateway_key 2>/dev/null || true)" bun run build

FROM nginx:1.27.4-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/out /usr/share/nginx/html
EXPOSE 80
