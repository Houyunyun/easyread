FROM nginx:stable-alpine
RUN apk add --no-cache apache2-utils openssl \
    && addgroup -g 1000 easyread \
    && adduser -D -u 1000 -G easyread easyread \
    && mkdir /auth && chown 1000:1000 /auth
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /usr/local/bin/easyread-gateway
COPY admin.sh /usr/local/bin/easyread-admin
RUN chmod 755 /usr/local/bin/easyread-gateway /usr/local/bin/easyread-admin
USER 1000:1000
VOLUME ["/auth"]
EXPOSE 8080 8081
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --no-check-certificate -q -O /dev/null https://127.0.0.1:8080/healthz
ENTRYPOINT ["/usr/local/bin/easyread-gateway"]
