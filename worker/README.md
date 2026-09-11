# Deepsleep456 Booking API

Cloudflare Worker API and D1 schema for the single-house booking system.

## Local setup

1. Install Wrangler and authenticate with Cloudflare.
2. Replace `REPLACE_WITH_D1_DATABASE_ID` in `wrangler.jsonc` after creating the D1 database.
3. Apply the migration locally:

```bash
npx wrangler d1 migrations apply deepsleep456-bookings --local
```

4. Set the admin token as a secret:

```bash
npx wrangler secret put ADMIN_TOKEN
```

5. Start the Worker:

```bash
npx wrangler dev
```

## Deploy

```bash
npx wrangler d1 migrations apply deepsleep456-bookings --remote
npx wrangler deploy
```

## API

- `GET /api/health`
- `GET /api/availability?checkIn=YYYY-MM-DD&checkOut=YYYY-MM-DD`
- `GET /api/promotions`
- `POST /api/bookings`
- `GET /api/admin/bookings?from=YYYY-MM-DD&to=YYYY-MM-DD` with `Authorization: Bearer <ADMIN_TOKEN>`
- `PATCH /api/admin/bookings/:id/status` with `{ "status": "confirmed" | "pending" | "cancelled" }`
- `GET /api/admin/blocked-dates?from=YYYY-MM-DD&to=YYYY-MM-DD` with `Authorization: Bearer <ADMIN_TOKEN>`
- `POST /api/admin/blocked-dates` with `{ "date": "YYYY-MM-DD", "reason": "maintenance" }`
- `DELETE /api/admin/blocked-dates/YYYY-MM-DD`

Booking requests reserve each night in `booking_nights`. Its primary key prevents two requests from reserving the same night, including concurrent requests. Cancelling a booking releases those nights.

The public site should call the deployed Worker through an API URL configured in its frontend. Do not put `ADMIN_TOKEN` in the public website.

The admin UI is available at `/admin/` (with `/booking-admin/` retained as the implementation route).
