SIMO Mobile MQTT Integration
============================

Connection
----------
- WebSocket URL: `wss://<hub-host>/mqtt/`
- MQTT protocol over WebSockets
- Keepalive: 30 seconds (strict)
- Auth: Use SIMO SSO access token
  - Set MQTT `username = <user email>` and `password = <SSO access token>`

Handshake/authorization
-----------------------
- The broker validates the SSO token via hub HTTP endpoints.
- If token is invalid or expires, the broker denies subsequent operations and the connection will drop within one keepalive cycle. The app must reconnect with a fresh token.

Initial state and subscriptions
------------------------------
1) Fetch initial snapshot via REST (must be authenticated):
   - `GET /api/<instance-slug>/core/states`
2) Subscribe to your per-user feed (replace placeholders):
  - `SIMO/user/<user-id>/feed/<instance-id>/InstanceUser-+`
  - `SIMO/user/<user-id>/feed/<instance-id>/Zone-+`
  - `SIMO/user/<user-id>/feed/<instance-id>/Category-+`
  - `SIMO/user/<user-id>/feed/<instance-id>/Component-+`

Payloads
--------
All messages are JSON and retained. Common fields:
- `obj_ct_pk`, `obj_pk`, `timestamp`, `dirty_fields`
- Component: `value`, `last_change`, `arm_status`, `battery_level`, `alive`, `meta`
- InstanceUser: `at_home`, `last_seen`, `phone_on_charge`
- Zone: `name`
- Category: `name`, `last_modified`

Dynamic permissions and re-sync
-------------------------------
- Subscribe to your personal perms topic:
  - `SIMO/user/<user-id>/perms-changed`
- On receiving a message, re-fetch `core/states` to update local caches (feed forwarding updates immediately; re-sync ensures local directories stay consistent).

Reconnect policy
----------------
- Refresh SSO tokens proactively (before expiry) and reconnect with the new token.
- If disconnected (network or 401/403 in broker), reconnect with exponential backoff (jitter) and re-subscribe from local cache.

Security notes
--------------
- The broker enforces per-instance and per-component ACLs. Wildcard `Component-+` is not allowed for non-master users.
- Tokens are validated server-side on CONNECT and ACL checks. With 30s keepalive, expired tokens are dropped within ~30s.

Control (write) actions
-----------------------
- Publish controller actions to a per-user command topic:
  - Topic: `SIMO/user/<user-id>/control/<instance-id>/Component-<component-id>`
  - Payload (JSON):
    - `request_id` (string, required for response correlation)
    - `method` (string) — controller method name (e.g., `toggle`, `send`)
    - `args` (array, optional)
    - `kwargs` (object, optional)
    - `subcomponent_id` (int, optional) — target a slave component
- Response (published by hub): `SIMO/user/<user-id>/control-resp/<request_id>`
  - `{ "ok": true, "result": ... }` or `{ "ok": false, "error": "..." }`
- Authorization:
  - Write is permitted only if the user has write permission for that component on the instance.
  - Use your SSO token; the broker & hub enforce identity and perms.
