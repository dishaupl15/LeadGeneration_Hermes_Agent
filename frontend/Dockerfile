# ─────────────────────────────────────────────────────────────────────────────
#  LeadCRM Frontend — Production Docker image
#
#  Stage 1: Build the Vite/React app
#  Stage 2: Serve the static output with Nginx (includes SPA fallback)
#
#  Required build args / environment variables:
#    VITE_API_URL          — Backend API URL  (e.g. https://api.your-domain.com)
#    VITE_PUBLIC_APP_URL   — Frontend public URL (e.g. https://your-domain.com)
#
#  Build:
#    docker build \
#      --build-arg VITE_API_URL=https://api.your-domain.com \
#      --build-arg VITE_PUBLIC_APP_URL=https://your-domain.com \
#      -t leadcrm-frontend .
#
#  Run:
#    docker run -p 80:80 leadcrm-frontend
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency manifests first (layer cache optimisation)
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Copy the rest of the source
COPY . .

# Vite bakes env vars into the bundle at build time — pass them as build args
ARG VITE_API_URL
ARG VITE_PUBLIC_APP_URL
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_PUBLIC_APP_URL=$VITE_PUBLIC_APP_URL

RUN npm run build

# ── Stage 2: serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove default Nginx config and replace with our SPA config
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from Stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
