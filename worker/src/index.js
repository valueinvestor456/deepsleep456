const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
};

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin");
    const headers = corsHeaders(env, origin);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers });
    }

    try {
      const url = new URL(request.url);
      const response = await routeRequest(request, env, url, ctx);
      for (const [key, value] of Object.entries(headers)) {
        response.headers.set(key, value);
      }
      return response;
    } catch (error) {
      console.error(JSON.stringify({ event: "request_error", message: error.message }));
      const status = error instanceof HttpError ? error.status : 500;
      const message = status < 500 ? error.message : "เกิดข้อผิดพลาดภายในระบบ";
      return json({ error: message }, status, headers);
    }
  },
};

async function routeRequest(request, env, url) {
  if (url.pathname === "/api/health" && request.method === "GET") {
    return json({ ok: true, service: "deepsleep456-booking-api" });
  }

  if (url.pathname === "/api/availability" && request.method === "GET") {
    return getAvailability(env, url.searchParams);
  }

  if (url.pathname === "/api/promotions" && request.method === "GET") {
    return getPromotions(env);
  }

  if (url.pathname === "/api/bookings" && request.method === "POST") {
    return createBooking(request, env);
  }

  if (url.pathname === "/api/admin/bookings" && request.method === "GET") {
    await requireAdmin(request, env);
    return listBookings(env, url.searchParams);
  }

  if (url.pathname === "/api/admin/blocked-dates" && request.method === "GET") {
    await requireAdmin(request, env);
    return listBlockedDates(env, url.searchParams);
  }

  if (url.pathname === "/api/admin/blocked-dates" && request.method === "POST") {
    await requireAdmin(request, env);
    return createBlockedDate(request, env);
  }

  const statusMatch = url.pathname.match(/^\/api\/admin\/bookings\/([^/]+)\/status$/);
  if (statusMatch && request.method === "PATCH") {
    await requireAdmin(request, env);
    return updateBookingStatus(request, env, statusMatch[1]);
  }

  const blockedDateMatch = url.pathname.match(/^\/api\/admin\/blocked-dates\/(\d{4}-\d{2}-\d{2})$/);
  if (blockedDateMatch && request.method === "DELETE") {
    await requireAdmin(request, env);
    return deleteBlockedDate(env, blockedDateMatch[1]);
  }

  return json({ error: "ไม่พบเส้นทางที่เรียก" }, 404);
}

async function getAvailability(env, params) {
  const checkIn = params.get("checkIn");
  const checkOut = params.get("checkOut");
  const dates = validateDateRange(checkIn, checkOut);

  const [booked, blocked] = await Promise.all([
    env.DB.prepare(
      "SELECT night_date FROM booking_nights WHERE night_date >= ?1 AND night_date < ?2"
    ).bind(dates.checkIn, dates.checkOut).all(),
    env.DB.prepare(
      "SELECT date, reason FROM blocked_dates WHERE date >= ?1 AND date < ?2 ORDER BY date"
    ).bind(dates.checkIn, dates.checkOut).all(),
  ]);

  const bookedDates = (booked.results || []).map((row) => row.night_date);
  const blockedDates = blocked.results || [];
  return json({
    available: bookedDates.length === 0 && blockedDates.length === 0,
    checkIn: dates.checkIn,
    checkOut: dates.checkOut,
    bookedDates,
    blockedDates,
  });
}

async function createBooking(request, env) {
  const body = await readJson(request);
  const required = ["customerName", "customerPhone", "guests", "checkIn", "checkOut"];
  if (required.some((field) => body[field] === undefined || body[field] === "")) {
    return json({ error: "กรุณากรอกข้อมูลการจองให้ครบถ้วน" }, 400);
  }

  const dates = validateDateRange(body.checkIn, body.checkOut);
  const guests = Number(body.guests);
  if (!Number.isInteger(guests) || guests < 1 || guests > 10) {
    return json({ error: "จำนวนผู้เข้าพักต้องอยู่ระหว่าง 1 ถึง 10 คน" }, 400);
  }

  const nights = dateRange(dates.checkIn, dates.checkOut);
  if (nights.length > 30) {
    return json({ error: "การจองต้องไม่เกิน 30 คืนต่อรายการ" }, 400);
  }

  const availability = await availabilityForNights(env, nights);
  if (!availability.available) {
    return json({
      error: "ช่วงวันที่เลือกไม่ว่าง",
      bookedDates: availability.bookedDates,
      blockedDates: availability.blockedDates,
    }, 409);
  }

  const bookingId = crypto.randomUUID();
  const booking = {
    id: bookingId,
    customerName: String(body.customerName).trim().slice(0, 120),
    customerPhone: String(body.customerPhone).trim().slice(0, 40),
    customerLineId: body.customerLineId ? String(body.customerLineId).trim().slice(0, 120) : null,
    guests,
    checkIn: dates.checkIn,
    checkOut: dates.checkOut,
    note: body.note ? String(body.note).trim().slice(0, 1000) : null,
    totalAmount: Number.isInteger(body.totalAmount) ? body.totalAmount : null,
  };

  const statements = [
    env.DB.prepare(
      `INSERT INTO bookings
       (id, customer_name, customer_phone, customer_line_id, guests, check_in, check_out, note, total_amount)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)`
    ).bind(
      booking.id,
      booking.customerName,
      booking.customerPhone,
      booking.customerLineId,
      booking.guests,
      booking.checkIn,
      booking.checkOut,
      booking.note,
      booking.totalAmount,
    ),
    ...nights.map((night) => env.DB.prepare(
      "INSERT INTO booking_nights (night_date, booking_id) VALUES (?1, ?2)"
    ).bind(night, booking.id)),
  ];

  try {
    await env.DB.batch(statements);
  } catch (error) {
    console.error(JSON.stringify({ event: "booking_insert_failed", bookingId, message: error.message }));
    return json({ error: "ช่วงเวลานี้เพิ่งถูกจอง กรุณาตรวจสอบวันว่างอีกครั้ง" }, 409);
  }

  return json({ bookingId, status: "pending", checkIn: booking.checkIn, checkOut: booking.checkOut }, 201);
}

async function listBookings(env, params) {
  const from = params.get("from") || "1900-01-01";
  const to = params.get("to") || "2999-12-31";
  validateDateRange(from, to);
  const result = await env.DB.prepare(
    `SELECT id, customer_name, customer_phone, customer_line_id, guests,
            check_in, check_out, status, note, total_amount, created_at, updated_at
     FROM bookings
     WHERE check_in < ?2 AND check_out > ?1
     ORDER BY check_in ASC`
  ).bind(from, to).all();
  return json({ bookings: result.results || [] });
}

async function listBlockedDates(env, params) {
  const from = params.get("from") || "1900-01-01";
  const to = params.get("to") || "2999-12-31";
  validateDateRange(from, to);
  const result = await env.DB.prepare(
    "SELECT date, reason, created_at FROM blocked_dates WHERE date >= ?1 AND date < ?2 ORDER BY date"
  ).bind(from, to).all();
  return json({ blockedDates: result.results || [] });
}

async function createBlockedDate(request, env) {
  const body = await readJson(request);
  const date = validateDate(body.date);
  const existingBooking = await env.DB.prepare(
    "SELECT booking_id FROM booking_nights WHERE night_date = ?1"
  ).bind(date).first();
  if (existingBooking) {
    return json({ error: "วันที่นี้มีรายการจองอยู่แล้ว" }, 409);
  }

  try {
    await env.DB.prepare(
      "INSERT INTO blocked_dates (date, reason) VALUES (?1, ?2)"
    ).bind(date, body.reason ? String(body.reason).trim().slice(0, 200) : null).run();
  } catch {
    return json({ error: "วันที่นี้ถูกปิดไว้แล้ว" }, 409);
  }
  return json({ date, status: "blocked" }, 201);
}

async function deleteBlockedDate(env, date) {
  validateDate(date);
  await env.DB.prepare("DELETE FROM blocked_dates WHERE date = ?1").bind(date).run();
  return json({ date, status: "available" });
}

async function updateBookingStatus(request, env, bookingId) {
  const body = await readJson(request);
  const status = body.status;
  if (!['pending', 'confirmed', 'cancelled'].includes(status)) {
    return json({ error: "สถานะการจองไม่ถูกต้อง" }, 400);
  }

  const booking = await env.DB.prepare(
    "SELECT id, status FROM bookings WHERE id = ?1"
  ).bind(bookingId).first();
  if (!booking) {
    return json({ error: "ไม่พบรายการจอง" }, 404);
  }
  if (booking.status === "cancelled" && status !== "cancelled") {
    return json({ error: "ไม่สามารถเปิดรายการยกเลิกกลับมาอัตโนมัติได้" }, 409);
  }

  if (status === "cancelled") {
    await env.DB.batch([
      env.DB.prepare("DELETE FROM booking_nights WHERE booking_id = ?1").bind(bookingId),
      env.DB.prepare(
        "UPDATE bookings SET status = ?1, updated_at = datetime('now') WHERE id = ?2"
      ).bind(status, bookingId),
    ]);
  } else {
    await env.DB.prepare(
      "UPDATE bookings SET status = ?1, updated_at = datetime('now') WHERE id = ?2"
    ).bind(status, bookingId).run();
  }

  return json({ bookingId, status });
}

async function getPromotions(env) {
  const result = await env.DB.prepare(
    `SELECT id, name, description, discount_type, discount_value, min_nights, starts_on, ends_on
     FROM promotions
     WHERE active = 1
       AND (starts_on IS NULL OR starts_on <= date('now'))
       AND (ends_on IS NULL OR ends_on >= date('now'))
     ORDER BY min_nights ASC, discount_value DESC`
  ).all();
  return json({ promotions: result.results || [] });
}

async function availabilityForNights(env, nights) {
  const placeholders = nights.map(() => "?").join(",");
  const [booked, blocked] = await Promise.all([
    env.DB.prepare(`SELECT night_date FROM booking_nights WHERE night_date IN (${placeholders})`).bind(...nights).all(),
    env.DB.prepare(`SELECT date, reason FROM blocked_dates WHERE date IN (${placeholders})`).bind(...nights).all(),
  ]);
  return {
    available: booked.results.length === 0 && blocked.results.length === 0,
    bookedDates: booked.results.map((row) => row.night_date),
    blockedDates: blocked.results,
  };
}

function validateDateRange(checkIn, checkOut) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(checkIn || "") || !/^\d{4}-\d{2}-\d{2}$/.test(checkOut || "")) {
    throw new HttpError("รูปแบบวันที่ต้องเป็น YYYY-MM-DD", 400);
  }
  const start = Date.parse(`${checkIn}T00:00:00Z`);
  const end = Date.parse(`${checkOut}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    throw new HttpError("วันเช็กเอาต์ต้องอยู่หลังวันเช็กอิน", 400);
  }
  return { checkIn, checkOut };
}

function validateDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) {
    throw new HttpError("รูปแบบวันที่ต้องเป็น YYYY-MM-DD", 400);
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new HttpError("วันที่ไม่ถูกต้อง", 400);
  }
  return value;
}

function dateRange(checkIn, checkOut) {
  const dates = [];
  const current = new Date(`${checkIn}T00:00:00Z`);
  const end = new Date(`${checkOut}T00:00:00Z`);
  while (current < end) {
    dates.push(current.toISOString().slice(0, 10));
    current.setUTCDate(current.getUTCDate() + 1);
  }
  return dates;
}

async function requireAdmin(request, env) {
  const authorization = request.headers.get("Authorization") || "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
  if (!env.ADMIN_TOKEN || !(await tokensMatch(token, env.ADMIN_TOKEN))) {
    throw new HttpError("ไม่ได้รับอนุญาต", 401);
  }
}

async function tokensMatch(left, right) {
  const [leftHash, rightHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(left)),
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(right)),
  ]);
  const a = new Uint8Array(leftHash);
  const b = new Uint8Array(rightHash);
  let difference = a.length ^ b.length;
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    difference |= (a[index] || 0) ^ (b[index] || 0);
  }
  return difference === 0;
}

async function readJson(request) {
  try {
    const body = await request.json();
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("JSON body must be an object");
    }
    return body;
  } catch {
    throw new HttpError("ข้อมูล JSON ไม่ถูกต้อง", 400);
  }
}

function corsHeaders(env, origin) {
  const allowedOrigin = origin === env.CORS_ORIGIN ? origin : env.CORS_ORIGIN;
  return {
    "access-control-allow-origin": allowedOrigin,
    "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "access-control-allow-headers": "Content-Type, Authorization",
    "access-control-max-age": "86400",
  };
}

function json(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

class HttpError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
