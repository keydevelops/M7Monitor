# M7Monitor

Heart rate monitor/overlay for Mi Band 7 watches.

## Requirements

- **Python 3.10+**
- **Mi Band 7 / Smart Band 7**
- **Bluetooth adapter**

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/keydevelops/M7Monitor.git
cd M7Monitor
```

### 2. Install dependencies

```bash
pip install bleak cryptography
```

### 3. Get your authentication key

You need the auth key from the Mi Fitness app:

Follow this guide: [Huami/Xiaomi server pairing](https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/)

### 4. Configure

Copy the example config and edit:

```bash
cp .env.example .env
```

Edit `.env` and set your `AUTH_KEY`:

```bash
TARGET_NAME_KEY=Smart Band
AUTH_KEY=YOUR_AUTH_KEY
OVERLAY_HOST=127.0.0.1
OVERLAY_PORT=8765
DEBUG=False
DISABLE_COLORS=False
```

## Usage

### Start the overlay server

```bash
python main.py
```

You should see:

```
[web] overlay: http://127.0.0.1:8765/
[web] state:   http://127.0.0.1:8765/api/state
[state] scanning
[state] connecting
[state] authenticating
```

### The first authentication attempt will **fail** regardless of the key!

## Endpoints

### `GET /`
Returns the HTML overlay page.

### `GET /api/state`
Returns JSON with current state:

```json
{
  "status": "polling",
  "heart_rate": {
    "value": 72,
    "timestamp": "2026-06-10T11:09:46.530Z",
    "source": "activity-fetch",
    "age_seconds": 5,
    "stale": false
  },
  "stale": false,
  "last_error": null,
  "settings": {
    "debug": false,
    "disableColors": false
  }
}
```

### `GET /health`
Health check endpoint (returns `ok`).

## Will it work with Mi Band 6/8 and others?

I don't think so. But I think Xiaomi changed the protocols or something like that. I don't have them, so I cannot test it. 

## Credits

Thanks to [patyork](https://github.com/patyork) for the [miband-7-monitor](https://github.com/patyork/miband-7-monitor) implementation.

Thanks to [Freeyourgadget](https://codeberg.org/Freeyourgadget) for the [GadgetBridge](https://codeberg.org/Freeyourgadget/Gadgetbridge/) app.

## License

MIT License - see LICENSE file for details.
