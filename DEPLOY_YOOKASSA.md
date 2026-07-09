# YooKassa Production Deploy Checklist

After pulling a new commit on the production server, make sure the running
container is rebuilt from the current code:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build web
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py migrate
```

Required production values in `.env.prod`:

```env
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...
YOOKASSA_RETURN_URL=https://savetory.ru/subscriptions/payment/result/
```

Configure YooKassa HTTP notifications in the YooKassa dashboard:

```text
https://savetory.ru/subscriptions/yookassa/webhook/
```

Enable at least these notification events:

```text
payment.succeeded
payment.canceled
payment.waiting_for_capture
```

If a payment succeeded in YooKassa before the subscription was activated, sync it
on the production server by YooKassa payment id:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web \
  python manage.py sync_yookassa_payment <yookassa_payment_id>
```

The sync command verifies the payment through YooKassa, checks `paid=true`,
validates amount/currency/plan/period/user metadata, restores a missing local
`SubscriptionPayment` when safe, and activates the subscription idempotently.
