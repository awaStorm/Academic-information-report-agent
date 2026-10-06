# -*- coding: utf-8 -*-
"""
LLM 客户端统一工厂 + 宽容重试（全项目唯一入口）

为什么必须有这个模块（2026-10-06 实测踩坑，用户报障 HTTP 500）：
    `OpenAI()` 默认的 httpx 客户端是 `trust_env=True`。在 Windows 上，
    httpx 的 trust_env 会经由 `urllib.request.getproxies()` 读取
    【注册表里的系统代理】——实测本机 `ProxyEnable=1` /
    `ProxyServer=127.0.0.1:7897`（Clash Verge）。于是每一句 LLM 请求
    都被塞进代理隧道；代理节点抖动的那一瞬间，TLS 握手直接以

        httpcore.ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING]
        EOF occurred in violation of protocol (_ssl.c:1020)

    失败，冒泡成 `openai.APIConnectionError`，最终把整轮 Agent 对话
    打成 HTTP 500，前端只看到一句「发送失败」。

    而 `api.deepseek.com` 这类国内端点**直连 0.76s 就返回 200**（实测）。
    把 LLM 的可用性绑在一个会抖动的本地代理上没有任何收益，只多一个故障点。
    因此这里统一：**默认绕开系统代理**，并对连接类错误做指数退避重试。
    确实需要走代理时，设置环境变量 `LLM_USE_SYSTEM_PROXY=1` 即可恢复原行为。

    （同一教训此前已单独用在 `weread_scraper.build_session()`
     的 `s.trust_env = False` 上，这里是把它提升为全项目统一口径。）
"""
import logging
import os
import time

import httpx
from openai import OpenAI

logger = logging.getLogger("src.utils.llm_client")

# 超时一律给宽：LLM 单次响应可达数十秒（本项目 max_tokens 配置到 30000），
# 宁可等，也不要因为读超时把一轮正常分析打断。
DEFAULT_TIMEOUT = httpx.Timeout(connect=20.0, read=600.0, write=120.0, pool=60.0)

# 连接类错误默认重试次数（每次失败之间的退避由 base_delay 指数放大）
DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 2.0

_TRUTHY = ("1", "true", "yes", "on")


def use_system_proxy() -> bool:
    """LLM 请求是否走系统代理。默认 False（直连）。"""
    return str(os.getenv("LLM_USE_SYSTEM_PROXY", "")).strip().lower() in _TRUTHY


def build_llm_client(api_key, base_url, timeout=None, max_retries=2):
    """
    构造 OpenAI 兼容客户端（统一口径）。

    - 默认 `trust_env=False`：不读系统代理，避免本地代理抖动打断业务；
    - 超时给定宽裕的默认值（600s 读超时），并把 SDK 自身重试保留为 2 次
      （用于 429 / 5xx 这类服务端瞬时错误）；
    - 连接类错误再由本模块的 `call_with_retry` 做更长退避的外层重试。
    """
    timeout = timeout or DEFAULT_TIMEOUT
    kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if not use_system_proxy():
        # 关键：绕开 Windows 注册表里的系统代理（Clash / V2Ray 等）
        kwargs["http_client"] = httpx.Client(trust_env=False, timeout=timeout)
    return OpenAI(**kwargs)


def is_connection_error(exc: BaseException) -> bool:
    """
    判断是否为「网络层连不上」类错误（而非业务错误）。

    只有这一类值得重试、也只有这一类该给用户「稍后重试」的提示；
    参数错误、模型不存在、额度不足等重试多少次都没用。
    """
    try:
        import openai
    except Exception:  # pragma: no cover
        openai = None

    if openai is not None:
        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
            return True
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    # SDK 内部异常名兜底（版本差异时不至于漏判）
    name = type(exc).__name__
    return name in ("APIConnectionError", "APITimeoutError", "ConnectError",
                    "ConnectTimeout", "ReadTimeout", "WriteTimeout",
                    "RemoteProtocolError", "PoolTimeout")


def call_with_retry(fn, *, attempts=DEFAULT_ATTEMPTS, base_delay=DEFAULT_BASE_DELAY,
                    on_retry=None, **kwargs):
    """
    对同步 LLM 调用做宽容重试（仅对连接类错误重试）。

    为什么需要外层重试：SDK 自带的退避是 0.4s / 0.8s 量级，用来扛代理或
    网络节点的切换太短——实测 10-06 10:09 那次就是 SDK 两次重试全部撞在
    同一个失效节点上。这里改用 2s → 4s 的指数退避，给链路恢复留出时间；
    LLM 调用本身是幂等的读取型请求，重试不会造成业务副作用（最多多花
    tokens，远优于整轮对话失败）。

    返回 fn 的原始返回值；非连接类错误或重试耗尽时原样抛出。
    """
    last_err = None
    for i in range(1, attempts + 1):
        try:
            return fn(**kwargs)
        except Exception as e:
            last_err = e
            if not is_connection_error(e) or i >= attempts:
                raise
            delay = base_delay * (2 ** (i - 1))
            logger.warning("LLM 请求失败（第 %d/%d 次），%.1fs 后重试：%s",
                           i, attempts, delay, str(e)[:160])
            if on_retry:
                try:
                    on_retry(i, attempts, delay, e)
                except Exception:
                    pass
            time.sleep(delay)
    raise last_err  # pragma: no cover（循环内必然 return 或 raise）


def describe_llm_error(exc: BaseException) -> str:
    """把 LLM 异常翻译成用户能看懂、且能据以行动的一句话。"""
    detail = str(exc).strip()
    if is_connection_error(exc):
        return (
            "LLM 服务连接失败（已自动重试 %d 次仍未成功）。"
            "常见原因：网络中断、代理/加速器节点抖动、或 LLM 服务端临时不可用。"
            "直接重试通常即可恢复；若持续失败，请检查网络连接，"
            "或临时关闭系统代理（Clash 等）后重试。原始错误：%s"
            % (DEFAULT_ATTEMPTS, (detail[:180] or type(exc).__name__))
        )
    return "LLM 调用失败：%s" % (detail[:300] or type(exc).__name__)
