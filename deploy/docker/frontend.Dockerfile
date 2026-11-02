ARG NGINX_IMAGE=m.daocloud.io/docker.io/library/nginx:1.28-alpine
FROM ${NGINX_IMAGE}
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY frontend/web /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
