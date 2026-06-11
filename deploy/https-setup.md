## HTTPS setup for `savetory.ru`

This repository ships:

- `deploy/nginx.conf`: bootstrap config used by `docker-compose.prod.yml` before the certificate exists
- `deploy/nginx.https.conf`: final production HTTPS config
- `deploy/nginx.http-only.conf`: explicit copy of the bootstrap variant if you want to keep both files on the server

### Volumes used by `docker-compose.prod.yml`

- `/opt/savetory/letsencrypt` -> `/etc/letsencrypt`
- `/opt/savetory/certbot/www` -> `/var/www/certbot`

Create them on the server before first start:

```bash
sudo mkdir -p /opt/savetory/letsencrypt
sudo mkdir -p /opt/savetory/certbot/www
```

### First certificate issuance

1. On the server, temporarily replace the mounted nginx config with the bootstrap one:

```bash
docker-compose -f docker-compose.prod.yml up -d web nginx
```

2. Run certbot on the server:

```bash
docker run --rm \
  -v /opt/savetory/letsencrypt:/etc/letsencrypt \
  -v /opt/savetory/certbot/www:/var/www/certbot \
  certbot/certbot certonly --webroot \
  --webroot-path /var/www/certbot \
  --non-interactive --agree-tos \
  -m <email> \
  -d savetory.ru -d www.savetory.ru
```

3. Replace the mounted nginx config with the final HTTPS config and reload nginx:

```bash
cp deploy/nginx.https.conf deploy/nginx.conf
docker-compose -f docker-compose.prod.yml up -d nginx
docker-compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### Renewal

Run periodically on the server:

```bash
docker run --rm \
  -v /opt/savetory/letsencrypt:/etc/letsencrypt \
  -v /opt/savetory/certbot/www:/var/www/certbot \
  certbot/certbot renew --webroot --webroot-path /var/www/certbot
docker-compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### Recommended Django env on the server

Set these only in the server production env:

```env
DJANGO_SECURE_PROXY_SSL_HEADER=1
DJANGO_USE_X_FORWARDED_HOST=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
```
