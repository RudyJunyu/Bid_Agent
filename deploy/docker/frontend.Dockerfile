ARG NGINX_IMAGE=m.daocloud.io/docker.io/library/nginx@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752
FROM ${NGINX_IMAGE}
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY frontend/web /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
