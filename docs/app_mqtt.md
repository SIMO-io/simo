SIMO Mobile MQTT Integration
============================

Overview
--------
SIMO exposes a real‑time feed and control plane over MQTT (WebSockets). Each user gets a private feed and control topics per instance they belong to. Use your SIMO account email as the MQTT username and a per‑user MQTT secret as the password.

Connection
----------
- WebSocket URL: `wss://<hub-host>/mqtt/`
- Protocol: MQTT over WebSockets
- Keepalive: 30 seconds (strict)
- Authentication:
  - `username = <user email>`
  - `password = <user MQTT secret>`

Getting credentials
-------------------
Use the authenticated REST endpoint to fetch the user’s MQTT secret.

- Get credentials
  - `GET /users/mqtt-credentials/`
  - Response: `{ "username": "<email>", "password": "<secret>", "user_id": <user_id> }`

Treat the MQTT secret like a password: store securely in the app keychain/secure storage.

Initial sync
------------
Before subscribing, fetch the initial snapshot via REST (authenticated):
- `GET /api/<instance-slug>/core/states`

This returns zones, categories, component values and users for that instance. Use it to build initial UI and caches.
Also fetch the instance UID for MQTT topic prefixes:
- `GET /api/<instance-slug>/core/info` → `{ "uid": "<instance-uid>" }`

Subscriptions (live updates)
----------------------------
Subscribe to your per‑user feed for each instance you are a member of. Replace placeholders as indicated (use instance UID, not slug):

- `SIMO/user/<user_id>/feed/<instance-uid>/InstanceUser/+`
- `SIMO/user/<user_id>/feed/<instance-uid>/Zone/+`
- `SIMO/user/<user_id>/feed/<instance-uid>/Category/+`
- `SIMO/user/<user_id>/feed/<instance-uid>/Component/+`

Notes
- All feed messages are JSON and retained.
- The server enforces permissions; you only receive data for instances you belong to and components you can read.
 - Discover IDs: your `user_id` is included in REST responses (e.g., `core/states.users[].id`). Use `instance-uid` from `/api/<instance-slug>/core/info` in MQTT topic prefixes.

Payloads
--------
Common fields for feed messages:
- `obj_ct_pk`, `obj_pk`, `timestamp`, `dirty_fields`
- Component: `value`, `last_change`, `arm_status`, `battery_level`, `alive`, `meta`
- InstanceUser: `at_home`, `last_seen`, `phone_on_charge`
- Zone: `name`
- Category: `name`, `last_modified`

Permission changes
------------------
Subscribe to your personal permission topic and refresh local state if it fires:
- `SIMO/user/<user_id>/perms-changed`
- On message: re‑fetch `core/states` for the instance(s) you display.

Control (write) actions
-----------------------
Publish controller actions to your per‑user command topic:
- Topic: `SIMO/user/<user_id>/control/<instance-uid>/Component/<component-id>`
- Payload (JSON):
  - `request_id` (string, required for response correlation)
  - `method` (string) — controller method name (e.g., `toggle`, `send`)
  - `args` (array, optional)
  - `kwargs` (object, optional)
  - `subcomponent_id` (int, optional) — target a slave component
- Response topic (from hub): `SIMO/user/<user_id>/control-resp/<request_id>`
  - `{ "ok": true, "result": ... }` or `{ "ok": false, "error": "..." }`

Authorization
- You can publish only if you have write permission for the target component on that instance. Otherwise, your publish is ignored.

Reconnect policy
----------------
- Use exponential backoff with jitter on disconnects.
- Re‑subscribe after reconnect.
- Keepalive must be 30s to ensure timely liveness checks.

iOS/Android
- Use any MQTT client that supports WebSockets and username/password auth.
- Set keepalive to 30s, enable automatic reconnect, and subscribe/publish as above.

Best practices
--------------
- Store the MQTT secret in the platform’s secure storage (Keychain/Keystore).
- Use QoS 0 (default) for feed/control. Feed messages are retained; you’ll receive the latest retained state on subscribe.

Troubleshooting
---------------
- Connection refused: verify email/secret and that the user has access to the instance.
- No messages after subscribe: confirm you’re using your own user id and the correct instance UID in topic prefixes.
- Publish ignored: ensure the user has write permission for that component.
