FROM node:24.19.0-bookworm-slim AS dependencies

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24.19.0-bookworm-slim AS builder

WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8001/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24.19.0-bookworm-slim AS runtime

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
RUN groupadd --gid 10001 disastermonitor \
    && useradd --uid 10001 --gid disastermonitor --create-home disastermonitor
COPY --from=builder --chown=disastermonitor:disastermonitor /app/.next/standalone ./
COPY --from=builder --chown=disastermonitor:disastermonitor /app/.next/static ./.next/static
USER disastermonitor

EXPOSE 3000
CMD ["node", "server.js"]
