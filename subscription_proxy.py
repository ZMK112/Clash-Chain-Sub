#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import copy
import ipaddress
import json
import os
import socket
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

import yaml


DEFAULT_OUTPUT_PATH = "subscription.generated.yaml"
DEFAULT_LISTENER_PORT = 17891
SUBSCRIPTION_URL_ENV = "CLASH_SUBSCRIPTION_URL"
MANAGED_EXIT_BASE_NAME = "静态住宅-落地出口"
MANAGED_GROUP_NAME = "Claude-专用链路"
MANAGED_LISTENER_NAME = "cac-docker-socks"
METADATA_PROXY_KEYWORDS = (
    "plan expires",
    "plan resets",
    "subscription fetched at",
    "套餐到期日期",
    "套餐重置日期",
    "订阅获取时间",
)
JP_KEYWORDS = ("japan", "🇯🇵")
FETCH_HEADERS = {
    "User-Agent": "clash-verge/1.0",
    "Accept": "text/yaml, application/x-yaml, text/plain, */*",
}


def build_managed_rules(group_name: str) -> list[str]:
    return [
        f"DOMAIN-SUFFIX,claude.ai,{group_name}",
        f"DOMAIN-SUFFIX,anthropic.com,{group_name}",
        f"DOMAIN-KEYWORD,claude,{group_name}",
    ]


MANAGED_RULES = build_managed_rules(MANAGED_GROUP_NAME)
ALL_MANAGED_RULES = set(MANAGED_RULES)


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)


class SingleQuotedString(str):
    pass


class DoubleQuotedString(str):
    pass


def represent_single_quoted(dumper: yaml.Dumper, data: SingleQuotedString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="'")


def represent_double_quoted(dumper: yaml.Dumper, data: DoubleQuotedString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


NoAliasDumper.add_representer(SingleQuotedString, represent_single_quoted)
NoAliasDumper.add_representer(DoubleQuotedString, represent_double_quoted)


@dataclass
class LoadedText:
    text: str
    encoding: str


@dataclass
class SourceSpec:
    subscription_url: str | None = None
    input_file: Path | None = None


@dataclass
class TransformSettings:
    manual_urls: list[str]
    dialer_proxies: list[str]
    active_exit_name: str
    listener_port: int


@dataclass
class CachedResponse:
    body: bytes
    encoding: str


class UserFacingError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def fail(message: str) -> None:
    raise UserFacingError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a Clash subscription and inject managed chain-routing blocks."
    )
    parser.add_argument(
        "--subscription-url",
        help=(
            "Subscription URL. When omitted, prompt for input or read from "
            f"the {SUBSCRIPTION_URL_ENV} environment variable."
        ),
    )
    parser.add_argument(
        "--input-file",
        help="Read a local YAML file instead of fetching from a subscription URL.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=f"Output file path. When omitted, prompt and default to {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--chain-node-url",
        action="append",
        default=[],
        help="Manual exit URL such as vmess://..., ss://..., or socks://.... Repeat for multiple exits.",
    )
    parser.add_argument(
        "--chain-node-dialer",
        action="append",
        default=[],
        help="Existing upstream proxy name used as dialer-proxy for each manual exit. Repeat in the same order.",
    )
    parser.add_argument(
        "--active-exit",
        help="Which managed exit should be used by the managed route group. Accepts a 1-based index or exact name.",
    )
    parser.add_argument(
        "--listener-port",
        type=int,
        help=f"Listener port for {MANAGED_LISTENER_NAME} (default: {DEFAULT_LISTENER_PORT}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds when fetching a subscription URL.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run a local HTTP server that serves the rewritten YAML as a Clash Verge subscription URL.",
    )
    parser.add_argument(
        "--serve-host",
        default="0.0.0.0",
        help="Local HTTP server bind host (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--allow-lan",
        action="store_true",
        help="Deprecated compatibility flag. LAN access is already enabled by default.",
    )
    parser.add_argument(
        "--public-host",
        help="Advertised host/IP used in printed LAN URLs when serving to other devices, e.g. 192.168.1.23.",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=8990,
        help="Local HTTP server bind port (default: 8990).",
    )
    parser.add_argument(
        "--serve-path",
        default="/subscription.yaml",
        help="HTTP path served as the Clash Verge subscription URL (default: /subscription.yaml).",
    )
    parser.add_argument(
        "--verify-against",
        help="Compare the generated YAML semantically against a reference YAML file.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Do not prompt. Missing values use defaults when available, otherwise exit with an error.",
    )
    return parser.parse_args()


def extract_leading_comments(raw_text: str) -> str:
    lines = raw_text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("#") or not line.strip():
            index += 1
            continue
        break
    return "".join(lines[:index])


def decode_text_bytes(data: bytes) -> LoadedText:
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return LoadedText(data.decode("utf-8-sig"), "utf-8-sig")
        return LoadedText(data.decode("utf-8"), "utf-8")
    except UnicodeDecodeError as exc:
        fail(f"Input is not valid UTF-8 or UTF-8 BOM. Aborting to avoid character corruption: {exc}")


def read_text_file(path: Path) -> LoadedText:
    return decode_text_bytes(path.read_bytes())


def fetch_text(url: str, timeout: float) -> LoadedText:
    req = Request(url, headers=FETCH_HEADERS)
    with urlopen(req, timeout=timeout) as response:
        return decode_text_bytes(response.read())


def prompt_text(prompt: str, default: str | None = None, allow_empty: bool = False) -> str:
    while True:
        suffix = f" [default: {default}]" if default is not None else ""
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            if default is not None:
                log(f"{prompt} not provided. Using default: {default}")
                return default
            if allow_empty:
                return ""
            fail(f"Missing required input for: {prompt}")
        if raw:
            return raw
        if default is not None:
            return default
        if allow_empty:
            return ""
        print("Input cannot be empty. Please try again.", flush=True)


def prompt_manual_urls(args: argparse.Namespace) -> list[str]:
    if args.chain_node_url:
        return args.chain_node_url
    if args.no_interactive:
        fail("Provide at least one --chain-node-url, or run in interactive mode.")

    urls: list[str] = []
    log("Enter at least one manual exit URL. Submit an empty line to finish.")
    while True:
        label = f"Manual exit URL {len(urls) + 1}"
        value = prompt_text(label, allow_empty=bool(urls))
        if not value:
            break
        urls.append(value)
    return urls


def ensure_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field_name} is not a valid YAML mapping.")
    return value


def decode_base64_text(raw: str) -> str:
    payload = unquote(raw).strip()
    padding = "=" * (-len(payload) % 4)
    last_error: Exception | None = None
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder((payload + padding).encode("utf-8"))
            return decoded.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"Could not decode base64 payload: {raw}") from last_error


def split_uri_body(uri: str, expected_scheme: str) -> tuple[str, str]:
    prefix = f"{expected_scheme}://"
    if not uri.lower().startswith(prefix):
        raise ValueError(f"Not a valid {expected_scheme}:// URL")
    payload = uri[len(prefix) :]
    fragment = ""
    if "#" in payload:
        payload, fragment = payload.split("#", 1)
    if "?" in payload:
        payload, _query = payload.split("?", 1)
    return payload, unquote(fragment)


def parse_host_port(host_port_text: str) -> tuple[str, int]:
    parsed = urlsplit(f"//{host_port_text}")
    if not parsed.hostname or parsed.port is None:
        raise ValueError(f"Could not parse host and port from: {host_port_text}")
    return parsed.hostname, parsed.port


def build_exit_name(index: int) -> str:
    return MANAGED_EXIT_BASE_NAME if index == 1 else f"{MANAGED_EXIT_BASE_NAME}{index}"


def is_managed_exit_name(name: str | None) -> bool:
    if not name:
        return False
    if name == MANAGED_EXIT_BASE_NAME:
        return True
    if not name.startswith(MANAGED_EXIT_BASE_NAME):
        return False
    suffix = name[len(MANAGED_EXIT_BASE_NAME) :]
    if suffix.isdigit():
        return True
    return False


def is_metadata_proxy_name(name: str | None) -> bool:
    if not name:
        return False
    normalized = name.casefold()
    return any(keyword in normalized for keyword in METADATA_PROXY_KEYWORDS)


def parse_ss_url(uri: str, name: str, dialer_proxy: str) -> dict[str, Any]:
    payload, _remark = split_uri_body(uri, "ss")
    if "@" in payload:
        encoded_auth, host_port_text = payload.rsplit("@", 1)
        auth_text = encoded_auth if ":" in encoded_auth else decode_base64_text(encoded_auth)
    else:
        decoded = decode_base64_text(payload)
        auth_text, host_port_text = decoded.rsplit("@", 1)

    if ":" not in auth_text:
        raise ValueError("ss:// URL is missing cipher:password")

    cipher, password = auth_text.split(":", 1)
    server, port = parse_host_port(host_port_text)
    return {
        "name": DoubleQuotedString(name),
        "type": "ss",
        "server": server,
        "port": port,
        "cipher": cipher,
        "password": DoubleQuotedString(password),
        "udp": True,
        "dialer-proxy": SingleQuotedString(dialer_proxy),
    }


def parse_socks_url(uri: str, name: str, dialer_proxy: str) -> dict[str, Any]:
    payload, _remark = split_uri_body(uri, "socks")
    if "@" not in payload:
        raise ValueError("socks:// URL is missing credentials or host information.")

    auth_text, host_port_text = payload.rsplit("@", 1)
    auth_decoded = auth_text if ":" in unquote(auth_text) else decode_base64_text(auth_text)
    auth_decoded = unquote(auth_decoded)
    if ":" in auth_decoded:
        username, password = auth_decoded.split(":", 1)
    else:
        username, password = auth_decoded, ""

    server, port = parse_host_port(host_port_text)
    node: dict[str, Any] = {
        "name": DoubleQuotedString(name),
        "type": "socks5",
        "server": server,
        "port": port,
        "udp": True,
        "dialer-proxy": SingleQuotedString(dialer_proxy),
    }
    if username:
        node["username"] = username
    if password:
        node["password"] = password
    return node


def parse_vmess_url(uri: str, name: str, dialer_proxy: str) -> dict[str, Any]:
    payload, _remark = split_uri_body(uri, "vmess")
    try:
        data = json.loads(decode_base64_text(payload))
    except json.JSONDecodeError as exc:
        raise ValueError("The vmess:// base64 payload is not valid JSON.") from exc

    server = data.get("add") or data.get("server")
    port_value = data.get("port")
    uuid = data.get("id") or data.get("uuid")
    if not server or port_value is None or not uuid:
        raise ValueError("A vmess:// URL must include add, port, and id.")

    try:
        port = int(port_value)
    except ValueError as exc:
        raise ValueError("The vmess:// port field is not numeric.") from exc

    alter_id_value = data.get("aid", data.get("alterId", 0))
    try:
        alter_id = int(alter_id_value)
    except ValueError as exc:
        raise ValueError("The vmess:// aid/alterId field is not numeric.") from exc

    node: dict[str, Any] = {
        "name": DoubleQuotedString(name),
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": alter_id,
        "cipher": data.get("scy", data.get("cipher", "auto")),
        "network": data.get("net", data.get("network", "tcp")),
        "dialer-proxy": SingleQuotedString(dialer_proxy),
    }

    tls_value = str(data.get("tls", "")).lower()
    if tls_value in {"tls", "true", "1"}:
        node["tls"] = True

    server_name = data.get("sni") or data.get("servername") or data.get("serverName")
    if server_name:
        node["servername"] = server_name

    host = data.get("host", "")
    path = data.get("path", "")
    if node["network"] == "ws" and (host or path):
        headers: dict[str, str] = {}
        if host:
            headers["Host"] = host
        ws_opts: dict[str, Any] = {}
        if path:
            ws_opts["path"] = path
        if headers:
            ws_opts["headers"] = headers
        if ws_opts:
            node["ws-opts"] = ws_opts

    return node


def parse_manual_proxy_url(uri: str, name: str, dialer_proxy: str) -> dict[str, Any]:
    lowered = uri.lower()
    if lowered.startswith("vmess://"):
        return parse_vmess_url(uri, name, dialer_proxy)
    if lowered.startswith("ss://"):
        return parse_ss_url(uri, name, dialer_proxy)
    if lowered.startswith("socks://"):
        return parse_socks_url(uri, name, dialer_proxy)
    raise ValueError("Only vmess://, ss://, and socks:// manual exit URLs are supported.")


def prefer_japan_proxy(proxy_names: list[str]) -> str:
    for name in proxy_names:
        normalized = name.casefold()
        if any(keyword in normalized for keyword in JP_KEYWORDS):
            return name
    if not proxy_names:
        fail("The upstream configuration does not contain any selectable proxies.")
    return proxy_names[0]


def choose_from_list(
    title: str,
    options: list[str],
    default_option: str,
    no_interactive: bool,
) -> str:
    if default_option not in options:
        fail(f"The default option for '{title}' does not exist: {default_option}")

    print(title, flush=True)
    for index, option in enumerate(options, start=1):
        marker = "  [default]" if option == default_option else ""
        print(f"  {index}. {option}{marker}", flush=True)

    if no_interactive:
        log(f"{title} not provided. Using default: {default_option}")
        return default_option

    while True:
        try:
            choice = input(
                f"Enter a number or full name, or press Enter to use [{default_option}]: "
            ).strip()
        except EOFError:
            log(f"{title} not provided. Using default: {default_option}")
            return default_option
        if not choice:
            return default_option
        if choice.isdigit():
            numeric = int(choice)
            if 1 <= numeric <= len(options):
                return options[numeric - 1]
        if choice in options:
            return choice
        print("Invalid selection. Please try again.", flush=True)


def choose_named_value(
    title: str,
    options: list[str],
    default_option: str,
    provided_value: str | None,
    no_interactive: bool,
) -> str:
    if provided_value:
        if provided_value.isdigit():
            numeric = int(provided_value)
            if 1 <= numeric <= len(options):
                return options[numeric - 1]
        if provided_value in options:
            return provided_value
        fail(f"Invalid value for '{title}': {provided_value}")
    return choose_from_list(title, options, default_option, no_interactive)


def choose_listener_port(args: argparse.Namespace) -> int:
    if args.listener_port is not None:
        if args.listener_port <= 0 or args.listener_port > 65535:
            fail("The listener port must be between 1 and 65535.")
        return args.listener_port

    if args.no_interactive:
        log(f"Listener port not provided. Using default: {DEFAULT_LISTENER_PORT}")
        return DEFAULT_LISTENER_PORT

    while True:
        raw = prompt_text("Enter listener port", default=str(DEFAULT_LISTENER_PORT))
        try:
            port = int(raw)
        except ValueError:
            print("The port must be numeric.", flush=True)
            continue
        if 1 <= port <= 65535:
            return port
        print("The port must be between 1 and 65535.", flush=True)


def choose_output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()

    raw_path = prompt_text("Enter output file path", default=DEFAULT_OUTPUT_PATH)
    return Path(raw_path).expanduser().resolve()


def normalize_serve_path(path: str) -> str:
    normalized = path.strip() or "/subscription.yaml"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def build_public_server_url(host: str, port: int, path: str) -> str:
    return f"http://{host}:{port}{normalize_serve_path(path)}"


def resolve_bind_host(args: argparse.Namespace) -> str:
    if args.allow_lan:
        return "0.0.0.0"
    return args.serve_host


def collect_lan_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()

    try:
        host_name = socket.gethostname()
        for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            host_name, None, family=socket.AF_INET
        ):
            if family != socket.AF_INET:
                continue
            ip = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if ip_obj.is_loopback or ip_obj.is_link_local:
                continue
            addresses.add(ip)
    except socket.gaierror:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.0.1", 80))
            ip = sock.getsockname()[0]
            ip_obj = ipaddress.ip_address(ip)
            if not ip_obj.is_loopback and not ip_obj.is_link_local:
                addresses.add(ip)
    except OSError:
        pass

    return sorted(addresses)


def build_access_urls(
    bind_host: str,
    port: int,
    path: str,
    public_host: str | None = None,
) -> list[str]:
    normalized_path = normalize_serve_path(path)
    if bind_host in {"0.0.0.0", "::"}:
        urls = [f"http://127.0.0.1:{port}{normalized_path}"]
        if public_host:
            urls.append(f"http://{public_host}:{port}{normalized_path}")
        urls.extend(
            f"http://{ip}:{port}{normalized_path}"
            for ip in collect_lan_ipv4_addresses()
        )
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            deduped.append(url)
            seen.add(url)
        return deduped
    return [build_public_server_url(bind_host, port, normalized_path)]


def resolve_source_spec(args: argparse.Namespace) -> SourceSpec:
    if args.input_file:
        return SourceSpec(input_file=Path(args.input_file).expanduser().resolve())

    env_url = os.environ.get(SUBSCRIPTION_URL_ENV, "").strip()
    default_url = args.subscription_url or env_url or None
    if args.subscription_url:
        subscription_url = args.subscription_url
    elif default_url:
        subscription_url = prompt_text("Enter upstream subscription URL", default=default_url)
    else:
        subscription_url = prompt_text("Enter upstream subscription URL")
    return SourceSpec(subscription_url=subscription_url)


def load_source_text(source_spec: SourceSpec, timeout: float, *, announce: bool) -> LoadedText:
    if source_spec.input_file:
        if announce:
            log(f"Loading local input file: {source_spec.input_file}")
        return read_text_file(source_spec.input_file)

    if not source_spec.subscription_url:
        fail("Missing upstream subscription URL.")
    if announce:
        log(f"Fetching upstream subscription URL: {source_spec.subscription_url}")
    try:
        return fetch_text(source_spec.subscription_url, timeout=timeout)
    except HTTPError as exc:
        fail(f"Failed to fetch the upstream subscription: HTTP {exc.code} {exc.reason}")
    except URLError as exc:
        fail(f"Failed to fetch the upstream subscription: {exc.reason}")
    except TimeoutError:
        fail("Failed to fetch the upstream subscription: request timed out")
    return ""


def get_subscription_text(args: argparse.Namespace) -> LoadedText:
    return load_source_text(resolve_source_spec(args), args.timeout, announce=True)


def load_yaml(raw_text: str) -> dict[str, Any]:
    parsed = yaml.safe_load(raw_text)
    if parsed is None:
        return {}
    return ensure_dict(parsed, "YAML document")


def collect_proxy_names(config: dict[str, Any]) -> list[str]:
    proxies = config.get("proxies") or []
    if not isinstance(proxies, list):
        fail("The upstream YAML field 'proxies' is not a list.")
    names: list[str] = []
    for item in proxies:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and not is_managed_exit_name(item.get("name"))
        ):
            names.append(item["name"])
    if not names:
        fail("The upstream YAML does not contain any selectable proxy names.")
    return names


def strip_metadata_proxies(config: dict[str, Any]) -> list[str]:
    proxies = config.get("proxies")
    if not isinstance(proxies, list):
        return []

    removed_names: list[str] = []
    kept_proxies: list[Any] = []
    for item in proxies:
        if isinstance(item, dict) and is_metadata_proxy_name(item.get("name")):
            removed_names.append(str(item.get("name")))
            continue
        kept_proxies.append(item)
    config["proxies"] = kept_proxies

    if not removed_names:
        return []

    removed_set = set(removed_names)
    proxy_groups = config.get("proxy-groups")
    if isinstance(proxy_groups, list):
        for group in proxy_groups:
            if not isinstance(group, dict):
                continue
            group_proxies = group.get("proxies")
            if isinstance(group_proxies, list):
                group["proxies"] = [
                    proxy_name
                    for proxy_name in group_proxies
                    if not (isinstance(proxy_name, str) and proxy_name in removed_set)
                ]

    return removed_names


def ensure_selected_dialers_exist(proxy_names: list[str], dialer_proxies: list[str]) -> None:
    missing = [name for name in dialer_proxies if name not in proxy_names]
    if missing:
        fail("The upstream subscription is missing these dialer-proxy nodes: " + ", ".join(missing))


def resolve_dialer_proxies(
    args: argparse.Namespace,
    proxy_names: list[str],
    manual_urls: list[str],
) -> list[str]:
    provided = list(args.chain_node_dialer)
    if len(provided) > len(manual_urls):
        fail("The number of --chain-node-dialer values cannot exceed the number of --chain-node-url values.")

    default_proxy = prefer_japan_proxy(proxy_names)
    resolved: list[str] = []
    for index, _url in enumerate(manual_urls):
        label = f"Select a dialer-proxy for {build_exit_name(index + 1)}"
        chosen = choose_named_value(
            title=label,
            options=proxy_names,
            default_option=default_proxy,
            provided_value=provided[index] if index < len(provided) else None,
            no_interactive=args.no_interactive,
        )
        resolved.append(chosen)
    return resolved


def build_managed_proxies(manual_urls: list[str], dialer_proxies: list[str]) -> list[dict[str, Any]]:
    managed: list[dict[str, Any]] = []
    for index, manual_url in enumerate(manual_urls, start=1):
        name = build_exit_name(index)
        dialer_proxy = dialer_proxies[index - 1]
        try:
            proxy = parse_manual_proxy_url(manual_url, name=name, dialer_proxy=dialer_proxy)
        except ValueError as exc:
            fail(f"Failed to parse {name}: {exc}")
        managed.append(proxy)
    return managed


def build_transform_settings(args: argparse.Namespace, proxy_names: list[str]) -> TransformSettings:
    manual_urls = prompt_manual_urls(args)
    log(f"Received {len(manual_urls)} manual exit URL(s).")

    dialer_proxies = resolve_dialer_proxies(args, proxy_names, manual_urls)
    ensure_selected_dialers_exist(proxy_names, dialer_proxies)
    managed_proxies = build_managed_proxies(manual_urls, dialer_proxies)
    exit_names = [str(proxy["name"]) for proxy in managed_proxies]
    active_exit_name = choose_named_value(
        title=f"Select which managed exit should be used by {MANAGED_GROUP_NAME}",
        options=exit_names,
        default_option=exit_names[0],
        provided_value=args.active_exit,
        no_interactive=args.no_interactive,
    )
    listener_port = choose_listener_port(args)
    return TransformSettings(
        manual_urls=manual_urls,
        dialer_proxies=dialer_proxies,
        active_exit_name=active_exit_name,
        listener_port=listener_port,
    )


def strip_managed_blocks(config: dict[str, Any]) -> None:
    proxies = config.get("proxies") or []
    if isinstance(proxies, list):
        config["proxies"] = [
            item
            for item in proxies
            if not (isinstance(item, dict) and is_managed_exit_name(item.get("name")))
        ]

    proxy_groups = config.get("proxy-groups") or []
    if isinstance(proxy_groups, list):
        config["proxy-groups"] = [
            item
            for item in proxy_groups
            if not (isinstance(item, dict) and item.get("name") == MANAGED_GROUP_NAME)
        ]

    listeners = config.get("listeners") or []
    if isinstance(listeners, list):
        config["listeners"] = [
            item
            for item in listeners
            if not (isinstance(item, dict) and item.get("name") == MANAGED_LISTENER_NAME)
        ]

    rules = config.get("rules") or []
    if isinstance(rules, list):
        config["rules"] = [
            item
            for item in rules
            if not (isinstance(item, str) and item in ALL_MANAGED_RULES)
        ]


def normalize_rules(config: dict[str, Any]) -> None:
    rules = config.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        fail("The 'rules' field is not a list and cannot be normalized.")

    normalized: list[Any] = []
    for item in rules:
        if isinstance(item, list) and len(item) == 1 and isinstance(item[0], str):
            normalized.append(item[0])
            continue
        normalized.append(item)
    config["rules"] = normalized


def get_rule_insert_index(rules: list[Any]) -> int:
    index = 0
    while index < len(rules):
        item = rules[index]
        if isinstance(item, str) and (
            item.startswith("IP-CIDR,") or item.startswith("IP-CIDR6,")
        ):
            index += 1
            continue
        break
    return index


def inject_managed_blocks(
    config: dict[str, Any],
    managed_proxies: list[dict[str, Any]],
    active_exit_name: str,
    listener_port: int,
) -> None:
    normalize_rules(config)
    strip_managed_blocks(config)

    proxies = config.setdefault("proxies", [])
    if not isinstance(proxies, list):
        fail("The 'proxies' field is not a list and cannot receive managed exits.")
    proxies.extend(managed_proxies)

    proxy_groups = config.setdefault("proxy-groups", [])
    if not isinstance(proxy_groups, list):
        fail("The 'proxy-groups' field is not a list and cannot receive the managed route group.")
    proxy_groups.insert(
        0,
        {
            "name": DoubleQuotedString(MANAGED_GROUP_NAME),
            "type": "select",
            "proxies": [DoubleQuotedString(active_exit_name)],
        },
    )

    listeners = config.setdefault("listeners", [])
    if not isinstance(listeners, list):
        fail("The 'listeners' field is not a list and cannot receive the managed listener.")
    listeners.insert(
        0,
        {
            "name": MANAGED_LISTENER_NAME,
            "type": "socks",
            "listen": "0.0.0.0",
            "port": listener_port,
            "proxy": SingleQuotedString(MANAGED_GROUP_NAME),
        },
    )

    rules = config.setdefault("rules", [])
    if not isinstance(rules, list):
        fail("The 'rules' field is not a list and cannot receive managed rules.")
    insert_at = get_rule_insert_index(rules)
    config["rules"] = rules[:insert_at] + list(MANAGED_RULES) + rules[insert_at:]


def normalize_for_compare(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalize_rules(normalized)
    return normalized


def reorder_top_level_keys(config: dict[str, Any]) -> dict[str, Any]:
    if "listeners" not in config or "rules" not in config:
        return config

    reordered: dict[str, Any] = {}
    for key, value in config.items():
        if key in {"listeners", "rules"}:
            continue
        reordered[key] = value
        if key == "proxy-groups":
            reordered["listeners"] = config["listeners"]
            reordered["rules"] = config["rules"]

    if "listeners" not in reordered:
        reordered["listeners"] = config["listeners"]
    if "rules" not in reordered:
        reordered["rules"] = config["rules"]
    return reordered


def collect_differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    scalar_types = (str, int, float, bool, type(None))
    if isinstance(expected, str) and isinstance(actual, str):
        if str(expected) != str(actual):
            return [f"{path or '<root>'}: value mismatch {expected!r} != {actual!r}"]
        return []
    if isinstance(expected, scalar_types) or isinstance(actual, scalar_types):
        if type(expected) is not type(actual):
            return [f"{path or '<root>'}: type mismatch {type(expected).__name__} != {type(actual).__name__}"]
        if expected != actual:
            return [f"{path or '<root>'}: value mismatch {expected!r} != {actual!r}"]
        return []

    if type(expected) is not type(actual):
        return [f"{path or '<root>'}: type mismatch {type(expected).__name__} != {type(actual).__name__}"]

    if isinstance(expected, dict):
        messages: list[str] = []
        expected_keys = list(expected.keys())
        actual_keys = list(actual.keys())
        if expected_keys != actual_keys:
            messages.append(f"{path or '<root>'}: key order or key set mismatch")
            missing = [key for key in expected_keys if key not in actual]
            extra = [key for key in actual_keys if key not in expected]
            if missing:
                messages.append(f"{path or '<root>'}: missing keys {missing}")
            if extra:
                messages.append(f"{path or '<root>'}: extra keys {extra}")
            if messages:
                return messages
        for key in expected_keys:
            child_path = f"{path}.{key}" if path else key
            child_diff = collect_differences(expected[key], actual[key], child_path)
            if child_diff:
                return child_diff
        return []

    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path or '<root>'}: list length mismatch {len(expected)} != {len(actual)}"]
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=True)):
            child_path = f"{path}[{index}]"
            child_diff = collect_differences(expected_item, actual_item, child_path)
            if child_diff:
                return child_diff
        return []

    if expected != actual:
        return [f"{path or '<root>'}: value mismatch {expected!r} != {actual!r}"]
    return []


def verify_output(output_config: dict[str, Any], reference_path_text: str) -> None:
    reference_path = Path(reference_path_text).expanduser().resolve()
    reference_config = load_yaml(read_text_file(reference_path).text)
    expected = normalize_for_compare(reference_config)
    actual = normalize_for_compare(output_config)
    differences = collect_differences(expected, actual)
    if differences:
        fail(
            "Verification failed. The generated YAML does not match the reference.\n"
            + "\n".join(f"- {message}" for message in differences[:10])
        )
    log(f"Verification passed. The generated YAML matches the reference semantics: {reference_path}")


def tweak_top_level_block_style(yaml_text: str) -> str:
    lines = yaml_text.splitlines()
    result: list[str] = []
    in_listeners = False
    in_rules = False

    for line in lines:
        if line.startswith("listeners:"):
            in_listeners = True
            in_rules = False
            result.append(line)
            continue
        if line.startswith("rules:"):
            in_listeners = False
            in_rules = True
            result.append(line)
            continue
        if line and not line.startswith(" "):
            in_listeners = False
            in_rules = False

        if in_listeners and line:
            result.append(f"  {line}")
            continue
        if in_rules and line.startswith("  "):
            result.append(line[2:])
            continue
        result.append(line)

    return "\n".join(result) + "\n"


def rewrite_managed_config_header(leading_comments: str, managed_url: str) -> str:
    interval_token = "interval=864000"
    lines = leading_comments.splitlines(keepends=True)

    for index, line in enumerate(lines):
        if not line.startswith("#!MANAGED-CONFIG "):
            continue
        parts = line.strip().split()
        for token in parts[2:]:
            if token.startswith("interval="):
                interval_token = token
                break
        lines[index] = f"#!MANAGED-CONFIG {managed_url} {interval_token}\n"
        return "".join(lines)

    header = f"#!MANAGED-CONFIG {managed_url} {interval_token}\n"
    if leading_comments:
        return header + "\n" + leading_comments
    return header + "\n"


def dump_yaml(config: dict[str, Any], leading_comments: str) -> str:
    yaml_text = yaml.dump(
        config,
        Dumper=NoAliasDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=4096,
    )
    yaml_text = tweak_top_level_block_style(yaml_text)
    if leading_comments:
        if not leading_comments.endswith("\n"):
            leading_comments += "\n"
        return leading_comments + yaml_text
    return yaml_text


def render_transformed_subscription(
    loaded_text: LoadedText,
    settings: TransformSettings,
    *,
    managed_config_url: str | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    leading_comments = extract_leading_comments(loaded_text.text)
    if managed_config_url:
        leading_comments = rewrite_managed_config_header(leading_comments, managed_config_url)

    config = load_yaml(loaded_text.text)
    removed_metadata_names = strip_metadata_proxies(config)
    proxy_names = collect_proxy_names(config)
    ensure_selected_dialers_exist(proxy_names, settings.dialer_proxies)

    managed_proxies = build_managed_proxies(settings.manual_urls, settings.dialer_proxies)
    exit_names = [str(proxy["name"]) for proxy in managed_proxies]
    if settings.active_exit_name not in exit_names:
        fail(
            f"The configured active exit is not present in the managed exit list: {settings.active_exit_name}"
        )

    inject_managed_blocks(
        config=config,
        managed_proxies=managed_proxies,
        active_exit_name=settings.active_exit_name,
        listener_port=settings.listener_port,
    )
    config = reorder_top_level_keys(config)
    rendered = dump_yaml(config, leading_comments)
    return rendered, config, removed_metadata_names


def prepare_runtime(args: argparse.Namespace) -> tuple[SourceSpec, TransformSettings, LoadedText]:
    source_spec = resolve_source_spec(args)
    loaded_text = load_source_text(source_spec, args.timeout, announce=True)
    preview_config = load_yaml(loaded_text.text)
    removed_metadata_names = strip_metadata_proxies(preview_config)
    if removed_metadata_names:
        log("Removed metadata-only proxy entries: " + ", ".join(removed_metadata_names))
    proxy_names = collect_proxy_names(preview_config)
    log(f"Parsed upstream YAML. Found {len(proxy_names)} selectable proxy name(s).")
    settings = build_transform_settings(args, proxy_names)
    return source_spec, settings, loaded_text


def run_server(args: argparse.Namespace, source_spec: SourceSpec, settings: TransformSettings) -> int:
    if args.serve_port <= 0 or args.serve_port > 65535:
        fail("The serve port must be between 1 and 65535.")

    serve_path = normalize_serve_path(args.serve_path)
    bind_host = resolve_bind_host(args)
    access_urls = build_access_urls(bind_host, args.serve_port, serve_path, args.public_host)
    default_public_host = (
        args.public_host
        or ("127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host)
    )
    output_path = Path(args.output).expanduser().resolve() if args.output else None
    cache: dict[str, CachedResponse] = {}

    class SubscriptionHandler(BaseHTTPRequestHandler):
        server_version = "ClashChainLocalServer/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            log(f"HTTP {self.address_string()} {format % args}")

        def do_HEAD(self) -> None:  # noqa: N802
            self.handle_subscription_request(send_body=False)

        def do_GET(self) -> None:  # noqa: N802
            self.handle_subscription_request(send_body=True)

        def handle_subscription_request(self, *, send_body: bool) -> None:
            request_path = urlsplit(self.path).path

            if request_path == "/healthz":
                body = b"ok\n"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
                return

            if request_path not in {serve_path, "/"}:
                body = f"Use {serve_path}\n".encode("utf-8")
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
                return

            host_header = self.headers.get("Host") or f"{default_public_host}:{args.serve_port}"
            managed_url = f"http://{host_header}{request_path if request_path != '/' else serve_path}"

            try:
                loaded_text = load_source_text(source_spec, args.timeout, announce=False)
                rendered, _config, removed_names = render_transformed_subscription(
                    loaded_text,
                    settings,
                    managed_config_url=managed_url,
                )
                if removed_names:
                    log("Removed metadata-only proxy entries for this request: " + ", ".join(removed_names))
                body = rendered.encode(loaded_text.encoding)
                cache["latest"] = CachedResponse(body=body, encoding=loaded_text.encoding)
                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(body)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/yaml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Clash-Chain-Source", "fresh")
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
                return
            except UserFacingError as exc:
                if "latest" in cache:
                    cached = cache["latest"]
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/yaml; charset=utf-8")
                    self.send_header("Content-Length", str(len(cached.body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Clash-Chain-Source", "stale-cache")
                    self.end_headers()
                    if send_body:
                        self.wfile.write(cached.body)
                    log(f"Upstream fetch failed. Served cached content instead: {exc}")
                    return

                body = f"{exc}\n".encode("utf-8")
                self.send_response(HTTPStatus.BAD_GATEWAY)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
                log(f"Upstream fetch failed and no cache was available: {exc}")
                return

    httpd = ThreadingHTTPServer((bind_host, args.serve_port), SubscriptionHandler)
    log(f"Local subscription server started on {bind_host}:{args.serve_port}")
    for url in access_urls:
        log(f"Available subscription URL: {url}")
    log("Use any of the URLs above as the subscription URL in Clash Verge.")
    if output_path:
        log(f"Each successful refresh will also write to: {output_path}")
    log("Health check URL: http://127.0.0.1:" + f"{args.serve_port}/healthz")
    if args.allow_lan or bind_host in {"0.0.0.0", "::"}:
        if not args.public_host and len(access_urls) == 1:
            log("LAN access is enabled by default. If no LAN IP was auto-detected, add --public-host 192.168.x.x to print a shareable LAN URL.")
        log("If other LAN devices cannot reach this server, allow inbound Python connections through the local firewall.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Interrupt received. Shutting down the local subscription server.")
    finally:
        httpd.server_close()
    return 0


def run_cli(args: argparse.Namespace) -> int:
    source_spec, settings, loaded_text = prepare_runtime(args)
    if args.serve:
        return run_server(args, source_spec, settings)

    output_path = choose_output_path(args)
    rendered, config, removed_metadata_names = render_transformed_subscription(
        loaded_text,
        settings,
    )
    if removed_metadata_names:
        log("Removed metadata-only proxy entries for this write: " + ", ".join(removed_metadata_names))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding=loaded_text.encoding)

    log(f"Wrote output file: {output_path}")
    log(f"Output encoding: {loaded_text.encoding}")
    log(f"{MANAGED_GROUP_NAME} -> {settings.active_exit_name}")
    log(f"{MANAGED_LISTENER_NAME} port -> {settings.listener_port}")
    for index, dialer_proxy in enumerate(settings.dialer_proxies, start=1):
        log(f"{build_exit_name(index)} -> dialer-proxy: {dialer_proxy}")
    if args.verify_against:
        verify_output(config, args.verify_against)
    return 0


def main() -> int:
    args = parse_args()
    if args.input_file and args.subscription_url:
        fail("--input-file and --subscription-url cannot be used together.")
    try:
        return run_cli(args)
    except UserFacingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
