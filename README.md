# Clash Chain Subscription Proxy

This project rewrites an upstream Clash/Clash Verge subscription into a chain-routing subscription.

It is useful when you want Clash Verge to keep using a normal subscription URL, but the YAML needs extra local rules every time it refreshes.

## What It Does

- Fetches an upstream subscription URL or reads a local YAML file.
- Adds one or more manual exit nodes parsed from `vless://`, `vmess://`, `ss://`, or `socks://` URLs.
- Optionally adds normal proxy nodes that do not use chain routing.
- Adds the managed route group `Claude-专用链路`.
- Adds region route groups `HK_PROXY`, `JP_PROXY`, and `TW_PROXY` when matching upstream nodes exist.
- Adds the local SOCKS listener `cac-docker-socks`.
- Adds three Claude-related rules for `claude.ai`, `anthropic.com`, and the `claude` keyword.
- Adds Docker and developer/common service rules to `HK_PROXY`, and Google core-service rules to `JP_PROXY`, when those groups exist.
- Removes metadata-only proxy entries such as plan expiry/reset markers.
- Preserves UTF-8/UTF-8 BOM and non-ASCII YAML content, including Chinese names, emoji, and flags.
- Saves successful choices locally so later runs can only refresh the upstream subscription.
- Caches the last raw upstream YAML locally, so later runs can work without entering a subscription URL.
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
7. Optionally add normal proxy nodes; press Enter or answer no to skip.
8. Use the printed HTTP URL as the subscription URL in Clash Verge.

## Interactive Server

Run a LAN-accessible subscription server with Chinese prompts:

```bash
./run.sh
```

Then use the printed URL in Clash Verge, for example:

```text
http://192.168.1.23:8990/subscription.yaml
```

LAN access is enabled by default because the server binds to `0.0.0.0`. If other devices cannot connect, allow inbound Python connections in the local firewall.

`run.sh` defaults to:

```bash
uv run --with PyYAML subscription_proxy.py --serve --lang zh --use-saved
```

Pass custom options after `--`:

```bash
./run.sh -- --serve --lang zh --public-host 192.168.1.23
```

## One-Line Remote Run

You can run the interactive tool without cloning this repository:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh)
```

The launcher downloads the latest script into `.clash-chain-sub/` under the current directory and runs it with `uv`. If `uv` is missing, the launcher installs it with the official installer.

Arguments after the launcher are passed to `subscription_proxy.py`:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh) -- --serve --lang zh --use-saved
```

If your shell does not support process substitution, use:

```bash
curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh | bash
```

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
  --chain-node-url 'vless://...' \
  --normal-node-url 'socks://...' \
  --chain-node-dialer 'Japan 01' \
  --active-exit 1 \
  --listener-port 17891 \
  --no-interactive
```

Reuse the last successful saved choices and only refresh upstream content:

```bash
python3 subscription_proxy.py \
  --serve \
  --lang zh \
  --use-saved \
  --subscription-url 'https://example.com/your/upstream/subscription'
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

## Saved Choices

After a successful one-time generation or successful server refresh, the script writes local choices to `.clash-chain-state.json` by default.

The saved file may contain the upstream subscription URL and private node URLs, so it is ignored by Git. After a successful interactive run, the script asks whether to save the choices. On the next interactive run, the script asks whether to reuse them. If reused, the upstream subscription is fetched again, but manual exits, normal nodes, selected `dialer-proxy`, active exit, and listener port remain unchanged.

## Raw Upstream YAML Cache

When a subscription URL fetch succeeds, the unmodified upstream YAML is cached to `.clash-chain-sub/last-upstream.yaml` by default. If a later run does not provide `--subscription-url`, `CLASH_SUBSCRIPTION_URL`, or `--input-file`, press Enter at the subscription URL prompt to use this cached raw YAML as the upstream input. In non-interactive mode, the cache is used automatically when available.

This cache is intentionally separate from `.clash-chain-state.json`: the state file stores your choices, while the YAML cache stores the last original upstream subscription content. Both files are ignored by Git because they may contain private data.

Useful options:

- `--use-saved`: reuse saved choices without asking. Required for non-interactive reuse.
- `--no-save`: do not write the state file or ask whether to save.
- `--state-file PATH`: use a different state file path.
- `--upstream-cache-file PATH`: use a different raw upstream YAML cache path.
- `--no-upstream-cache`: disable reading and writing the raw upstream YAML cache.

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
- 从 `vless://`、`vmess://`、`ss://`、`socks://` URL 解析手动出口节点。
- 可选增加普通节点；普通节点不参与链式转发。
- 自动加入 `Claude-专用链路` 策略组。
- 当存在匹配的上游节点时，自动加入 `HK_PROXY`、`JP_PROXY`、`TW_PROXY` 地区策略组。
- 自动加入 `cac-docker-socks` 本地 SOCKS 监听器。
- 自动维护 3 条 Claude 规则：`claude.ai`、`anthropic.com`、`claude` 关键字。
- 当对应地区组存在时，自动把 Docker 与开发/常用服务规则指向 `HK_PROXY`，把 Google 基础服务规则指向 `JP_PROXY`。
- 自动删除套餐到期、套餐重置、订阅获取时间等无用元信息节点。
- 完整保留 UTF-8/UTF-8 BOM、中文、图标、国旗和其他非 ASCII 内容。
- 成功生成后可把用户选择固化到本地，下次只刷新上游订阅内容。
- 自动缓存上次原始上游 YAML，下次不传订阅地址时也可以继续生成。
- 支持一次性生成 YAML，也支持启动本地/局域网 HTTP 订阅服务。

仓库中不会内置真实订阅地址或节点凭据。

## 链式代理说明

链式代理指的是让流量先进入一个手动添加的出口节点，再由这个出口节点通过订阅中已有的上游节点继续拨出。这个项目生成的关键链路是：

```text
应用或本地服务
  -> cac-docker-socks
  -> Claude-专用链路
  -> 静态住宅-落地出口
  -> dialer-proxy 指定的上游订阅节点
  -> 目标网站
```

其中 `静态住宅-落地出口` 是脚本从你输入的 `vless://`、`vmess://`、`ss://` 或 `socks://` URL 解析出来的手动出口节点；`dialer-proxy` 是订阅文件中已经存在的节点名称。Clash 会让手动出口节点通过 `dialer-proxy` 指定的上游节点建立连接，而不是直接从本机网络连接目标出口。

这样做的主要原因：

- 保持目标服务看到的最终出口相对固定，例如让 Claude 相关流量走固定的手动出口。
- 复用订阅中已有的稳定中转节点，例如优先选择日本节点作为第一跳。
- 把 Claude 相关规则、策略组和监听端口自动化维护，避免每次订阅更新后手动修改 YAML。
- 通过本地 HTTP 服务提供一个稳定的新订阅地址，让 Clash Verge 刷新订阅时自动拿到修订后的配置。
- 将链式转发只限定到指定规则或本地监听器，减少对原订阅其他规则和节点的影响。

## 普通节点和固化选择

普通节点是额外加入到 `proxies` 的非链式节点。脚本会把它们命名为 `普通节点`、`普通节点2` 等，并创建 `手动普通节点` 策略组。普通节点不会带 `dialer-proxy`，不会影响 `Claude-专用链路` 的链式出口；如果不需要，交互时选择跳过即可。

脚本成功生成 YAML 或服务端成功刷新一次后，会询问是否把这次选择写入 `.clash-chain-state.json`。这个文件可能包含上游订阅地址和手动节点 URL，所以已被 `.gitignore` 忽略，不应提交到仓库。

下次交互运行时，如果检测到已固化选择，脚本会询问是否复用。复用后只重新获取上游订阅，手动出口、普通节点、`dialer-proxy` 选择、当前出口和监听端口都保持不变，从而减少重复输入。

## 地区策略组

脚本会扫描上游订阅节点名称，并自动维护以下地区策略组：

- `HK_PROXY`：匹配 `HK`、`Hong Kong`、`香港`、`🇭🇰`。
- `JP_PROXY`：匹配 `JP`、`Japan`、`日本`、`东京`、`東京`、`大阪`、`🇯🇵`。
- `TW_PROXY`：匹配 `TW`、`Taiwan`、`台湾`、`台灣`、`🇹🇼`。

每次刷新都会先删除旧的地区策略组，再基于当前上游订阅重新生成。只有匹配到节点时才生成对应策略组；没有匹配节点时不会生成空组。

## 服务规则

当 `HK_PROXY` 存在时，脚本会自动增加 Docker 相关规则并指向 `HK_PROXY`，覆盖 Docker Hub、registry、auth、Cloudflare CDN、download 和 desktop 域名。

当 `HK_PROXY` 存在时，脚本也会自动增加开发/常用服务规则并指向 `HK_PROXY`，覆盖 Homebrew、GitHub、Git、npm/node、PyPI、Rust/crates、Go、VS Code/Microsoft dev、JetBrains 相关域名。

当 `JP_PROXY` 存在时，脚本会自动增加 Google 基础服务规则并指向 `JP_PROXY`，覆盖 `google.com`、`googleapis.com`、`gstatic.com`、`googleusercontent.com`、`ggpht.com`、`gmail.com`、`android.com`、`googleblog.com`、`withgoogle.com`、`google.dev`。

当 `JP_PROXY` 存在时，脚本会自动增加 ChatGPT/OpenAI 相关规则并指向 `JP_PROXY`，覆盖 `chatgpt.com`、`openai.com`、`oaistatic.com`、`oaiusercontent.com`、LiveKit、Auth0、Arkose、Statsig、LaunchDarkly、Intercom、Sentry、Stripe 等前端和登录依赖域名。

脚本会自动增加 Tailscale 相关规则并指向 `DIRECT`，覆盖 `tailscale.com`、`tailscale.io`、`ts.net`、`login.tailscale.com`、`controlplane.tailscale.com`、`derp.tailscale.com`、`log.tailscale.io`。

按当前策略，YouTube、Google 广告和 Google 统计域名不会加入 `JP_PROXY` 托管规则。

按当前策略，`cloudflare.com`、`amazonaws.com`、`azureedge.net`、`fastly.net` 这类大范围平台/CDN 域名不会被整体加入开发/常用服务托管规则，避免误伤非开发流量。

## 原始上游 YAML 缓存

每次通过订阅地址成功获取 YAML 后，脚本会把“未注入任何链式配置之前”的原始上游 YAML 缓存到 `.clash-chain-sub/last-upstream.yaml`。如果下次运行时没有提供 `--subscription-url`、没有设置 `CLASH_SUBSCRIPTION_URL`，也没有提供 `--input-file`，可以在订阅地址提示处直接回车，脚本会使用这个缓存文件作为上游输入。非交互模式下，如果缓存存在，会自动使用缓存。

这个缓存与 `.clash-chain-state.json` 分开：状态文件保存你的选择，原始 YAML 缓存保存上次订阅内容。两者都可能包含私密信息，已被 Git 忽略，不应提交。

常用参数：

- `--use-saved`：直接使用已固化选择，不再询问；非交互复用时必须显式提供。
- `--no-save`：本次运行不写入固化文件，也不询问是否保存。
- `--state-file PATH`：指定其他固化文件路径。
- `--upstream-cache-file PATH`：指定其他原始上游 YAML 缓存路径。
- `--no-upstream-cache`：禁用原始上游 YAML 缓存的读取和写入。

## 中文操作步骤

1. 安装依赖：`python3 -m pip install -r requirements.txt`，或直接使用 `uv`。
2. 运行服务：`./run.sh`。
3. 按提示输入上游订阅地址，或提前设置 `CLASH_SUBSCRIPTION_URL`。
4. 按提示输入一个或多个手动出口节点 URL。
5. 从列表中选择每个出口使用的上游 `dialer-proxy` 节点，默认优先日本节点。
6. 选择 `Claude-专用链路` 实际使用哪个手动出口。
7. 确认监听端口，默认 `17891`。
8. 按需增加普通节点；不需要时直接跳过。
9. 把脚本打印出来的订阅 URL 填入 Clash Verge。

`./run.sh` 默认等价于：

```bash
uv run --with PyYAML subscription_proxy.py --serve --lang zh --use-saved
```

如需传入额外参数：

```bash
./run.sh -- --serve --lang zh --public-host 192.168.1.23
```

## 中文常用命令

远程一键启动交互式服务，不需要手动 clone 项目：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh)
```

这个启动脚本会把最新版 `subscription_proxy.py` 下载到当前目录下的 `.clash-chain-sub/`，然后用 `uv` 运行。默认参数是 `--serve --lang zh`，也就是启动中文交互式订阅服务。

如果需要传入脚本参数，在启动命令后使用 `--`：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh) -- --serve --lang zh --use-saved
```

如果当前 shell 不支持 `<(...)`，可以使用：

```bash
curl -fsSL https://raw.githubusercontent.com/ZMK112/Clash-Chain-Sub/main/install-run.sh | bash
```

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

复用上次已固化选择，只刷新订阅：

```bash
python3 subscription_proxy.py --serve --lang zh --use-saved
```

## Files

- `subscription_proxy.py`: main script
- `requirements.txt`: Python dependency list
- `.gitignore`: ignores Python cache files and generated YAML output
