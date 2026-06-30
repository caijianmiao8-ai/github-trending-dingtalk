# GitHub 每日热门 → 钉钉推送

每天定时抓取 [GitHub Trending](https://github.com/trending)（全部语言 · 每日榜）的 Top 10 项目，
拼成 Markdown 卡片，通过钉钉自定义机器人（加签模式）推送到群里。

- **零第三方依赖**：纯 Python 标准库（`urllib` + `re`），无需 `pip install`。
- **云端定时**：GitHub Actions 每天 09:00（北京时间）自动跑，不依赖本机开机。
- **可配置**：条数、榜单周期（日/周/月）、是否只看某语言，都能改。

推送效果（示例）：

> #### 🔥 GitHub 热门项目 · 2026-06-30
> 🥇 **[simplex-chat/simplex-chat]()** `Haskell`　⭐ 16,893 · 📈 今日 +1,607
> 🥈 **[…]()** `Shell`　⭐ 119,363 · 📈 今日 +1,425
> …

---

## 一、本地先跑一遍（可选，验证效果）

```bash
# 只预览、不推送
DRY_RUN=1 python3 daily_trending.py

# 真正推送到钉钉（先填好 Webhook 和 Secret）
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx"
export DINGTALK_SECRET="SECxxxx"
python3 daily_trending.py
```

或复制 `.env.example` 为 `.env` 填好后：`set -a; source .env; set +a && python3 daily_trending.py`

## 二、钉钉机器人怎么建（加签模式）

1. 进入目标钉钉群 → 右上角 **设置** → **机器人** → **添加机器人** → **自定义**。
2. 安全设置勾选 **加签**，会得到一串以 `SEC` 开头的密钥 → 这就是 `DINGTALK_SECRET`。
3. 完成后复制 **Webhook 地址**（形如 `https://oapi.dingtalk.com/robot/send?access_token=xxx`）→ 这就是 `DINGTALK_WEBHOOK`。

## 三、部署到 GitHub Actions（云端每日自动跑）

1. 把本目录推到一个 GitHub 仓库（建议 **private**）。
2. 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加两个：
   - `DINGTALK_WEBHOOK`
   - `DINGTALK_SECRET`

   或用 `gh` 命令行：
   ```bash
   gh secret set DINGTALK_WEBHOOK   # 回车后粘贴 webhook 地址
   gh secret set DINGTALK_SECRET    # 回车后粘贴 SEC 开头的密钥
   ```
3. 完成。Actions 会按 `.github/workflows/daily-trending.yml` 里的定时（每天北京时间 09:00）自动推送。
   想立刻测一次：仓库 → **Actions → GitHub Daily Trending → Run workflow**（可选 `dry_run=true` 先看日志不发消息）。

## 四、自定义

改 `.github/workflows/daily-trending.yml` 里的环境变量与定时：

| 变量 | 含义 | 默认 |
|------|------|------|
| `TOP_N` | 推送条数 | `10` |
| `SINCE` | 榜单周期 `daily`/`weekly`/`monthly` | `daily` |
| `LANGUAGE` | 只看某语言（如 `python`），留空=全部 | 全部 |
| `TRANSLATE` | 把英文简介翻成中文（`0` 关闭） | `1` |
| `TARGET_LANG` | 翻译目标语言 | `zh-CN` |

> 翻译走免密钥接口（Google 优先，失败回退 MyMemory，再失败保留英文原文）；已是中文的简介自动跳过。

**改推送时间**：修改 `cron`，注意用 **UTC**。例如北京时间 08:00 = `0 0 * * *`，每周一 09:00 = `0 1 * * 1`。

## 注意事项

- GitHub Actions 的定时任务在高峰期**可能延迟几分钟到一小时**，对每日推送无影响。
- 仓库连续 **60 天无活动**后，定时任务会被 GitHub 自动暂停，到时手动在 Actions 页面重新启用即可。
- 钉钉单个机器人限频 **20 条/分钟**，每天一条远不会触发。
- 解析依赖 GitHub Trending 页面结构，若某天 GitHub 大改页面导致解析不到，脚本会以非零退出并报错（Actions 里能看到）。
