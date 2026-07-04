# Authentication System

JWT-based authentication for the **Orkaive** multi-agent backend. The
implementation lives in `app/routes/auth.py` and `app/services/user_service.py`.

## Features

- **User Registration**: Email + password with bcrypt hashing
- **User Login**: JWT (HS256) tokens, configurable expiry
- **Password Reset**: Email-based recovery via SMTP (`app/utils/email.py`)
- **Current User**: `GET /api/auth/me` reads the JWT from the request

## API endpoints

All endpoints are prefixed with `/api/auth`.

### `POST /api/auth/signup`

```json
{
  "email": "user@example.com",
  "password": "Password123",
  "name": "John Doe"
}
```

Returns the created `UserResponse` (no password).

### `POST /api/auth/login`

```json
{ "email": "user@example.com", "password": "Password123" }
```

Returns `{ "access_token": "<jwt>", "token_type": "bearer", "user": {…} }`.

### `POST /api/auth/forgot-password`

Sends a reset link to the user's email. No body content is leaked in
the response (always returns success).

### `POST /api/auth/reset-password`

```json
{ "token": "<reset-token-from-email>", "new_password": "NewPassword123" }
```

### `GET /api/auth/me`

Requires `Authorization: Bearer <jwt>`. Returns the current user.

## Setup

### Environment variables

Copy `.env.example` to `.env` and set:

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | yes | JWT signing key (≥ 32 chars) |
| `MONGODB_URL` | yes | Defaults to `mongodb://127.0.0.1:27017` |
| `MONGODB_DB` | no | Defaults to `sasefied_agent` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Default 60 |
| `SMTP_HOST` | for password reset | |
| `SMTP_PORT` | for password reset | Default 587 |
| `SMTP_USERNAME` | for password reset | |
| `SMTP_PASSWORD` | for password reset | |
| `FROM_EMAIL` | for password reset | |

### Gmail SMTP

1. Enable 2-factor authentication on the account
2. Create an app password
3. Use the app password as `SMTP_PASSWORD`

## Password rules

- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit

## Security notes

- Passwords are hashed with **bcrypt** (salt per password)
- JWTs are signed with HS256 using `SECRET_KEY`
- Password-reset tokens are single-use and time-limited (1 h)
- `get_current_user` is the only auth dependency; everything else
  requires it
- The frontend's `lib/axios.ts` automatically attaches the JWT and
  redirects to `/signin` on 401

## Mongo collection

Users are stored in the `users` collection:

```json
{
  "_id": ObjectId,
  "email": "user@example.com",
  "name": "John Doe",
  "hashedPassword": "<bcrypt>",
  "createdAt": ISODate,
  "updatedAt": ISODate,
  "isActive": true
}
```

## Frontend integration

The frontend stores the JWT in `localStorage.token` and the global
axios instance attaches it to every `/api/*` request:

```ts
import api from "@/lib/axios";

// login
const { data } = await api.post("/auth/login", { email, password });
localStorage.setItem("token", data.access_token);

// subsequent requests auto-attach the header
const me = await api.get("/auth/me");
```

On 401 the axios response interceptor clears the token and routes the
user to `/signin`. The old `lib/authFetch.ts` is a shim over the same
instance — new code should use `api` directly.
