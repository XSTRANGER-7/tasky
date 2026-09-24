# syntax=docker/dockerfile:1.7
# Build the SPA with Vite, serve it with an unprivileged nginx. Production uses Vercel;
# this image is what `docker compose up` and the E2E job run.

# ---------------------------------------------------------------- build
FROM node:26.9-alpine AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
