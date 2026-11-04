# syntax=docker/dockerfile:1

FROM node:26-slim AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

FROM node:26-slim AS runtime
# HTTP dentro da VPC: o TLS termina no CloudFront/ALB (ADR-0029). Em produção o processo exige
# TLS_NA_BORDA=true; ORIGEM_PUBLICA, PROXIES_CONFIAVEIS e IP_CLIENTE_HEADER vêm da task.
ENV NODE_ENV=production HOST=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=deps --chown=root:root /app/node_modules ./node_modules
COPY --chown=root:root package.json ./
COPY --chown=root:root src ./src
COPY --chown=root:root public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "src/server.js"]
