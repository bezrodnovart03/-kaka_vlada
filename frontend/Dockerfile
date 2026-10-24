# syntax=docker/dockerfile:1

# ── сборка SPA ────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ── nginx: SPA + прокси /api и /admin на Django ───────────
FROM nginx:1.27-alpine
# Шаблон обрабатывается envsubst при старте: подставляется CLIENT_MAX_BODY_SIZE.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV CLIENT_MAX_BODY_SIZE=12m
EXPOSE 80
