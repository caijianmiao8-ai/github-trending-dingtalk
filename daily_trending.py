#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 每日热门项目 -> 钉钉推送

抓取 https://github.com/trending（全部语言 / 每日榜）的 Top N 项目，
拼成 Markdown 消息，通过钉钉自定义机器人（加签模式）推送到群里。

零第三方依赖：仅用 Python 标准库（urllib + re）。

环境变量：
  DINGTALK_WEBHOOK   钉钉机器人 Webhook（必填，形如 https://oapi.dingtalk.com/robot/send?access_token=xxx）
  DINGTALK_SECRET    加签密钥，以 SEC 开头（加签模式必填；关键词模式可留空）
  TOP_N              推送条数，默认 10
  SINCE              榜单周期：daily / weekly / monthly，默认 daily
  LANGUAGE           只看某语言（如 python）；留空 = 全部语言
  TRANSLATE          是否把英文简介翻成中文，默认 1（开启）；设 0 关闭
  TARGET_LANG        翻译目标语言，默认 zh-CN
  DRY_RUN            设为 1/true 时只打印消息、不真正推送（本地调试用）
"""

import os
import re
import sys
import time
import json
import hmac
import base64
import hashlib
import datetime
import urllib.parse
import urllib.request

TRENDING_BASE = "https://github.com/trending"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BEIJING = datetime.timezone(datetime.timedelta(hours=8))

# ---------- 工具函数 ----------

def env(name, default=""):
    return os.environ.get(name, default).strip()

def strip_tags(s):
    """去掉 HTML 标签 + 反转义实体 + 合并空白。"""
    import html as _html
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

# ---------- 翻译（英文简介 -> 中文，免密钥） ----------

def _has_cjk(s):
    return any("一" <= ch <= "鿿" for ch in s)


def _google_translate(text, target):
    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&tl=" + urllib.parse.quote(target) + "&dt=t&q="
        + urllib.parse.quote(text)
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def _mymemory_translate(text, target):
    url = (
        "https://api.mymemory.translated.net/get?langpair="
        + urllib.parse.quote("en|" + target) + "&q=" + urllib.parse.quote(text)
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = data.get("responseData", {}).get("translatedText", "")
    if out and "MYMEMORY WARNING" not in out.upper():
        return out
    return ""


def translate(text, target="zh-CN"):
    """英文简介翻译成中文；已是中文或为空则原样返回；接口全失败时回退英文原文。"""
    if not text or _has_cjk(text):
        return text
    for fn in (_google_translate, _mymemory_translate):
        try:
            out = fn(text, target).strip()
            if out:
                return out
        except Exception:
            continue
    return text

# ---------- 抓取 & 解析 ----------

def fetch_html():
    lang = env("LANGUAGE")
    since = env("SINCE", "daily") or "daily"
    url = TRENDING_BASE + (f"/{urllib.parse.quote(lang)}" if lang else "")
    url += f"?since={since}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace"), url


def parse_trending(html):
    """从 trending 页面 HTML 中解析项目列表。锚点均已对真实页面验证。"""
    repos = []
    for art in re.findall(r'<article class="Box-row".*?</article>', html, re.S):
        # 仓库名：必须从 <h2> 里取 a 的 href，避免误取顶部 sponsor 链接
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", art, re.S)
        if not h2:
            continue
        href = re.search(r'href="(/[^"]+)"', h2.group(1))
        if not href:
            continue
        full_name = href.group(1).strip("/")
        if "/" not in full_name:
            continue

        # 描述（可能没有）
        desc_m = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', art, re.S)
        desc = strip_tags(desc_m.group(1)) if desc_m else ""

        # 语言（可能没有）
        lang_m = re.search(
            r'<span itemprop="programmingLanguage">([^<]+)</span>', art
        )
        language = lang_m.group(1).strip() if lang_m else ""

        # 总 star 数（stargazers 链接里的文本）
        star_m = re.search(r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>', art, re.S)
        total_stars = strip_tags(star_m.group(1)) if star_m else ""

        # 周期内新增（如 "1,607 stars today"）
        period_m = re.search(
            r'class="[^"]*float-sm-right[^"]*"[^>]*>(.*?)</span>', art, re.S
        )
        period_raw = strip_tags(period_m.group(1)) if period_m else ""
        delta_m = re.search(r"([\d,]+)\s*stars", period_raw)
        delta = delta_m.group(1) if delta_m else ""

        repos.append({
            "name": full_name,
            "url": f"https://github.com/{full_name}",
            "desc": desc,
            "lang": language,
            "stars": total_stars,
            "delta": delta,
            "period_raw": period_raw,
        })
    return repos

# ---------- 组装钉钉消息 ----------

def build_markdown(repos, source_url):
    now = datetime.datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    since = env("SINCE", "daily") or "daily"
    period_cn = {"daily": "每日榜", "weekly": "每周榜", "monthly": "每月榜"}.get(since, since)
    scope_cn = env("LANGUAGE") or "全部语言"

    title = f"GitHub 今日热门 Top {len(repos)}"
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    parts = [f"#### 🔥 GitHub 热门项目 · {date_str}"]
    parts.append(f"> 数据来源：GitHub Trending（{scope_cn} · {period_cn}）")

    for i, r in enumerate(repos):
        rank = medals.get(i, f"`{i + 1:>2}`")
        lang = f" `{r['lang']}`" if r["lang"] else ""
        parts.append(f"{rank} **[{r['name']}]({r['url']})**{lang}")

        meta = []
        if r["stars"]:
            meta.append(f"⭐ {r['stars']}")
        if r["delta"]:
            meta.append(f"📈 今日 +{r['delta']}")
        elif r["period_raw"]:
            meta.append(f"📈 {r['period_raw']}")
        if meta:
            parts.append("　　" + " · ".join(meta))

        if r["desc"]:
            parts.append(f"> {r['desc']}")

    parts.append("---")
    parts.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')}（北京时间） · [查看完整榜单]({source_url})")

    # 钉钉 Markdown 用空行分隔，换行才生效
    text = "\n\n".join(parts)
    return title, text

# ---------- 钉钉推送 ----------

def signed_url(webhook, secret):
    """加签模式：拼接 timestamp 和 sign。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def push_dingtalk(webhook, secret, title, text):
    url = signed_url(webhook, secret) if secret else webhook
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("errcode") != 0:
        raise RuntimeError(f"钉钉推送失败：{result}")
    return result

# ---------- 主流程 ----------

def main():
    top_n = int(env("TOP_N", "10") or "10")
    dry_run = env("DRY_RUN").lower() in ("1", "true", "yes")

    html, source_url = fetch_html()
    repos = parse_trending(html)[:top_n]
    if not repos:
        sys.exit("ERROR: 没有解析到任何项目，GitHub Trending 页面结构可能已变化。")

    # 把英文简介翻成中文（默认开启，可用 TRANSLATE=0 关闭）
    if env("TRANSLATE", "1").lower() not in ("0", "false", "no"):
        target = env("TARGET_LANG", "zh-CN") or "zh-CN"
        for r in repos:
            r["desc"] = translate(r["desc"], target)

    title, text = build_markdown(repos, source_url)

    if dry_run:
        print(f"[DRY_RUN] 解析到 {len(repos)} 个项目；标题：{title}\n")
        print(text)
        return

    webhook = env("DINGTALK_WEBHOOK")
    secret = env("DINGTALK_SECRET")
    if not webhook:
        sys.exit("ERROR: 未设置 DINGTALK_WEBHOOK 环境变量。")

    result = push_dingtalk(webhook, secret, title, text)
    print(f"OK: 已推送 {len(repos)} 个项目 -> {result}")


if __name__ == "__main__":
    main()
