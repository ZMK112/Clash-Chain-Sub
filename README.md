# Clash Subscription Proxy

`subscription_proxy.py` rewrites an upstream Clash subscription and serves the rewritten YAML over HTTP.

It is designed for workflows where:

- the upstream subscription may only be reachable for a short time
- you want to inject one or more manual exit nodes
- you want to expose a stable local or LAN subscription URL for Clash Verge

## Features

- No real subscription URL or node credentials are embedded in the script.
- All prompts and logs are in English.
- By default, the HTTP server listens on `0.0.0.0`, so LAN access is enabled.
- The script removes metadata-only proxy entries such as expiry or reset markers.
- The latest successful rewritten subscription is cached in memory and can still be served if the upstream temporarily fails.
- UTF-8 and UTF-8 BOM are preserved to avoid breaking emoji, flags, or non-ASCII text.

## Requirements

- Python 3.11+
- `PyYAML`

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

Run an interactive local/LAN subscription server:

```bash
python3 subscription_proxy.py --serve --public-host 192.168.1.23
```

Then use the printed URL in Clash Verge, for example:

```text
http://192.168.1.23:8990/subscription.yaml
```

## Environment Variable

Instead of passing the upstream subscription URL every time, you can use:

```bash
export CLASH_SUBSCRIPTION_URL='https://example.com/your/upstream/subscription'
```

## Common Usage

Generate a rewritten YAML file once:

```bash
python3 subscription_proxy.py
```

Run the local/LAN HTTP subscription server:

```bash
python3 subscription_proxy.py --serve --public-host 192.168.1.23
```

Run fully non-interactively:

```bash
python3 subscription_proxy.py \
  --serve \
  --public-host 192.168.1.23 \
  --subscription-url 'https://example.com/your/upstream/subscription' \
  --chain-node-url 'vmess://...' \
  --chain-node-url 'ss://...' \
  --chain-node-dialer 'Japan 01' \
  --chain-node-dialer 'Japan 02' \
  --active-exit 2 \
  --listener-port 17891 \
  --no-interactive
```

Write the rewritten output to a file on each successful refresh:

```bash
python3 subscription_proxy.py \
  --serve \
  --public-host 192.168.1.23 \
  -o ./subscription.generated.yaml
```

## Security Notes

- Anyone who can reach the HTTP server can fetch the rewritten subscription.
- If you do not want LAN access, bind to localhost explicitly:

```bash
python3 subscription_proxy.py --serve --serve-host 127.0.0.1
```

- If LAN clients cannot connect, allow inbound Python connections through the local firewall.

## Health Check

The server exposes:

```text
http://127.0.0.1:8990/healthz
```

## Files

- `subscription_proxy.py`: main script
- `requirements.txt`: Python dependency list
- `.gitignore`: ignores Python cache files and generated YAML output
