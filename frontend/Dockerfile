FROM node:22-alpine AS build
WORKDIR /w
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
WORKDIR /srv
COPY --from=build --chown=node:node /w/package.json ./
COPY --from=build --chown=node:node /w/node_modules ./node_modules
COPY --from=build --chown=node:node /w/.next ./.next
COPY --from=build --chown=node:node /w/public ./public
COPY --from=build --chown=node:node /w/next.config.ts ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s CMD wget -qO- http://127.0.0.1:$PORT/ >/dev/null || exit 1
CMD ["npm", "start"]
