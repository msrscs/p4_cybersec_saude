# Caddy sem a file capability cap_net_bind_service da imagem oficial: só usa portas altas, e com
# ela o kernel recusa executar o binário sob cap_drop: ALL (ADR-0013).
FROM caddy:2.11-alpine
RUN setcap -r /usr/bin/caddy
USER 65532:65532
