# Home Assistant integration

`GET /api/ha/summary` is a read-only endpoint designed for a Home Assistant `rest` sensor.
It needs a **bearer device token** (cookies are rejected, kiosk devices get 403).

## 1. Create a token

Use a dedicated member account (for example `homeassistant`) and request a device token:

```bash
curl -s https://pantry.example.com/api/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"homeassistant","password":"...","device_name":"Home Assistant","platform":"homeassistant"}'
```

Store the returned `token` in HA's `secrets.yaml`:

```yaml
pantrynanny_bearer: "Bearer <token>"
```

Tokens last 365 days and slide with use. Revoke them under Admin -> Devices.

## 2. Response

```json
{
  "household": "Hjemmet",
  "generated_at": "2026-10-19T12:00:00+00:00",
  "products_in_stock": 42, "items_total": 97,
  "low_stock_count": 2, "low_stock": ["Mælk", "Smør"],
  "expiring_soon_count": 1,
  "expiring_soon": [{"name": "Hakket oksekød", "expires_at": "2026-10-21", "days_left": 2, "quantity": 1}],
  "expired_count": 0, "expired": [],
  "shopping_open_count": 5, "unknown_count": 1
}
```

Lists are capped at 25 entries. "Soon" uses the household setting `expiry_soon_days`.

## 3. `configuration.yaml`

```yaml
rest:
  - resource: https://pantry.example.com/api/ha/summary
    scan_interval: 300
    headers:
      Authorization: !secret pantrynanny_bearer
    sensor:
      - name: "Pantry low stock"
        value_template: "{{ value_json.low_stock_count }}"
        json_attributes_path: "$"
        json_attributes: [low_stock]
      - name: "Pantry expiring soon"
        value_template: "{{ value_json.expiring_soon_count }}"
        json_attributes_path: "$"
        json_attributes: [expiring_soon]
      - name: "Pantry shopping list"
        value_template: "{{ value_json.shopping_open_count }}"
      - name: "Pantry unknown products"
        value_template: "{{ value_json.unknown_count }}"
```

Example automation (notify when something expires within 2 days):

```yaml
automation:
  - alias: Pantry expiry reminder
    trigger:
      - platform: numeric_state
        entity_id: sensor.pantry_expiring_soon
        above: 0
    action:
      - service: notify.notify
        data:
          message: >
            Expiring soon: {{ state_attr('sensor.pantry_expiring_soon','expiring_soon')
              | map(attribute='name') | join(', ') }}
```
