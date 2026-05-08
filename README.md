# Clash Chain Subscription Proxy

This project rewrites an upstream Clash/Clash Verge subscription into a chain-routing subscription.

It is useful when you want Clash Verge to keep using a normal subscription URL, but the YAML needs extra local rules every time it refreshes.

## What It Does

- Fetches an upstream subscription URL or reads a local YAML file.
- Adds one or more manual exit nodes parsed from `vmess://`, `ss://`, or `socks://` URLs.
- Adds the managed route group `Claude-专用链路`.
- Adds the local SOCKS listener `cac-docker-socks`.
- Adds three Claude-related rules for `claude.ai`, `anthropic.com`, and the `claude` keyword.
- Removes metadata-only proxy entries such as plan expiry/reset markers.
- Preserves UTF-8/UTF-8 BOM and non-ASCII YAML content, including Chinese names, emoji, and flags.
- Can write a generated YAML file once, or run a local/LAN HTTP subscription server.

No real upstream subscription URL or proxy credentials are stored in this repository.

## Requirements

- Python 3.11+
- PyYAML

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Language

Runtime prompts and logs support English and Chinese.

```bash
python3 subscription_proxy.py --lang en
python3 subscription_proxy.py --lang zh
```

You can also set a default language:

```bash
export CLASH_SUB_LANG=zh
```

The language switch only affects prompts, logs, and help text. It does not translate generated YAML names or upstream subscription content.

## Typical Workflow

1. Start the script in server mode.
2. Enter the upstream subscription URL when prompted, or provide it with `--subscription-url`.
3. Enter one or more manual exit node URLs.
4. Select an existing upstream node as `dialer-proxy`; Japan nodes are preferred by default when available.
5. Select which manual exit is used by `Claude-专用链路`.
6. Confirm the listener port, default `17891`.
7. Use the printed HTTP URL as the subscription URL in Clash Verge.

## Interactive Server

Run a LAN-accessible subscription server with Chinese prompts:

```bash
python3 subscription_proxy.py --serve --lang zh --public-host 192.168.1.23
```

Then use the printed URL in Clash Verge, for example:

```text
http://192.168.1.23:8990/subscription.yaml
```

LAN access is enabled by default because the server binds to `0.0.0.0`. If other devices cannot connect, allow inbound Python connections in the local firewall.

## One-Time YAML Generation

Generate a rewritten YAML file once:

```bash
python3 subscription_proxy.py --lang zh -o ./subscription.generated.yaml
```

If `-o/--output` is omitted, the script prompts for the output path and defaults to `subscription.generated.yaml`.

## Non-Interactive Example

Use placeholders for private values:

```bash
python3 subscription_proxy.py \
  --serve \
  --lang en \
  --public-host 192.168.1.23 \
  --subscription-url 'https://example.com/your/upstream/subscription' \
  --chain-node-url 'ss://...' \
  --chain-node-dialer 'Japan 01' \
  --active-exit 1 \
  --listener-port 17891 \
  --no-interactive
```

Write each successful server refresh to a file:

```bash
python3 subscription_proxy.py \
  --serve \
  --lang zh \
  --public-host 192.168.1.23 \
  -o ./subscription.generated.yaml
```

## Environment Variables

Set the upstream subscription URL without putting it in shell history every time:

```bash
export CLASH_SUBSCRIPTION_URL='https://example.com/your/upstream/subscription'
```

Set the default runtime language:

```bash
export CLASH_SUB_LANG=zh
```

## Health Check

When running in server mode:

```text
http://127.0.0.1:8990/healthz
```

## Security Notes

- Anyone who can reach the HTTP server can fetch the rewritten subscription.
- Do not commit generated YAML files because they may contain real proxy credentials.
- If you only need local access, bind to localhost:

```bash
python3 subscription_proxy.py --serve --serve-host 127.0.0.1
```

## 中文说明

本项目用于把上游 Clash/Clash Verge 订阅改写成带链式转发配置的新订阅。

适用场景：你希望 Clash Verge 仍然使用一个普通订阅地址，但每次订阅刷新后，都自动补上固定的手动出口节点、Claude 专用策略组、本地 SOCKS 监听器和 Claude 规则。

## 项目作用

- 从上游订阅地址获取 YAML，或读取本地 YAML 文件。
- 从 `vmess://`、`ss://`、`socks://` URL 解析手动出口节点。
- 自动加入 `Claude-专用链路` 策略组。
- 自动加入 `cac-docker-socks` 本地 SOCKS 监听器。
- 自动维护 3 条 Claude 规则：`claude.ai`、`anthropic.com`、`claude` 关键字。
- 自动删除套餐到期、套餐重置、订阅获取时间等无用元信息节点。
- 完整保留 UTF-8/UTF-8 BOM、中文、图标、国旗和其他非 ASCII 内容。
- 支持一次性生成 YAML，也支持启动本地/局域网 HTTP 订阅服务。

仓库中不会内置真实订阅地址或节点凭据。

## 中文操作步骤

1. 安装依赖：`python3 -m pip install -r requirements.txt`。
2. 运行服务：`python3 subscription_proxy.py --serve --lang zh --public-host 192.168.1.23`。
3. 按提示输入上游订阅地址，或提前设置 `CLASH_SUBSCRIPTION_URL`。
4. 按提示输入一个或多个手动出口节点 URL。
5. 从列表中选择每个出口使用的上游 `dialer-proxy` 节点，默认优先日本节点。
6. 选择 `Claude-专用链路` 实际使用哪个手动出口。
7. 确认监听端口，默认 `17891`。
8. 把脚本打印出来的订阅 URL 填入 Clash Verge。

## 中文常用命令

启动默认支持局域网访问的订阅服务：

```bash
python3 subscription_proxy.py --serve --lang zh --public-host 192.168.1.23
```

一次性生成 YAML 文件：

```bash
python3 subscription_proxy.py --lang zh -o ./subscription.generated.yaml
```

只允许本机访问：

```bash
python3 subscription_proxy.py --serve --serve-host 127.0.0.1 --lang zh
```

## Files

- `subscription_proxy.py`: main script
- `requirements.txt`: Python dependency list
- `.gitignore`: ignores Python cache files and generated YAML output
