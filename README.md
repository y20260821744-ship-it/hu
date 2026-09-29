# 日本二手平台上新监控与推送系统

常驻运行的「日本二手平台商品上新监控与推送系统」。目前实现两个平台：

- **煤炉 Mercari**（jp.mercari.com）— 流量最大的个人二手平台
- **骏河屋 Suruga-ya**（suruga-ya.jp）— 中古游戏 / 玩具 / 周边 / 卡牌

按自定义关键词 / 价格区间 / 指定卖家规则匹配，发现**从未见过的新商品**后立即通过
Telegram / 钉钉 / Bark / 企业微信 / 微信公众号（第三方）等多渠道推送，并提供 Web 管理面板。

> 技术栈：Python 3.11 · FastAPI · APScheduler · SQLAlchemy · httpx · SQLite（可切 MySQL）· Docker Compose

---

## 功能一览

| 模块 | 说明 |
|---|---|
| 关键词监控 | 多关键词并行；支持日/中/英文；中文自动映射日文同义词（`app/matcher.py` 可扩展）；关键词内空格 = AND 逻辑 |
| 抓取频率 | 每平台独立设置（默认 300 秒，下限 30 秒）；内置日本 IP 代理池轮换、随机 UA、指数退避、连续失败自动降频 |
| 代理池管理 | Web 面板「代理池」直接增删 / 启停 / 测试代理，改完**无需重启**立即生效，自动轮换；.env 的 PROXY_LIST 作兜底 |
| 实时上新 | 命中且从未入库的商品立即推送；`platform+item_id` 唯一索引保证**绝不重复推送** |
| 高级规则 | 价格区间、指定卖家、指定品牌（任一规则满足即放行） |
| 通知渠道 | Telegram / 钉钉 / Bark / 企业微信 / PushPlus / WxPusher / Server酱 / 邮件 SMTP / 通用 Webhook；失败自动重试 3 次并记录日志 |
| Web 面板 | 仪表盘（监控状态 / 统计）、关键词管理、规则管理、命中记录、平台设置、推送日志、手动触发抓取 |

## 系统流程

```
平台适配器(煤炉/骏河屋)
   ↓
调度抓取（每平台独立频率 + 代理池/UA/退避/降频）
   ↓
解析归一（统一字段: 平台/商品ID/标题/价格/卖家/图片/链接/上架时间/状态）
   ↓
规则匹配（关键词 AND/OR、价格区间、指定卖家、品牌）
   ↓
去重入库（platform+item_id 唯一，仅新商品放行）
   ↓
推送队列（失败重试 3 次）
   ↓
多渠道通知（Telegram/钉钉/Bark/企微/公众号/邮件/Webhook）
```

## 快速开始（本地）

```bash
# 1. 准备环境
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置（复制模板并按需填写）
cp .env.example .env
#    重点配置:
#    - PROXY_LIST       日本 IP 代理池（国内 IP 大概率被限流，强烈建议填写）
#    - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  等通知渠道

# 3. 添加监控关键词（中文也会自动匹配日文同义词）
python run.py addkw "ポケモン カード"
python run.py addkw "海贼王手办" zh
python run.py addkw "PS5" en

# 4a. 先手动跑一次验证（打印统计，不启动常驻服务）
python run.py once

# 4b. 启动面板 + 后台调度（浏览器打开 http://localhost:8000）
python run.py serve
```

## Docker 部署（兼容宝塔 / 腾讯云 VPS）

```bash
cp .env.example .env
# 编辑 .env（代理、渠道密钥、频率）

docker compose up -d --build
# 面板地址: http://服务器IP:8000
# 数据持久化在 ./data/monitor.db
```

宝塔面板方式：新建站点反向代理 `服务器IP:8000`，或直接用 `docker compose` 映射端口即可。

## 通知渠道接入步骤

| 渠道 | 步骤 |
|---|---|
| **Telegram（推荐）** | ① 私聊 @BotFather → `/newbot` 创建机器人，得到 token 填入 `TELEGRAM_BOT_TOKEN`；② 私聊 @userinfobot 获取你的 chat_id 填入 `TELEGRAM_CHAT_ID` |
| 钉钉 | 群设置 → 智能群助手 → 添加机器人 → 自定义机器人，复制 webhook 填入 `DINGTALK_WEBHOOK`（开启加签则填 `DINGTALK_SECRET`） |
| Bark (iOS) | App Store 安装 Bark → 获取推送 key 填入 `BARK_KEY` |
| 企业微信 | 群 → 添加群机器人 → 复制 webhook 填入 `WECOM_WEBHOOK`（微信里可直接收到） |
| 微信公众号 | 认证服务号个人办不了，推荐第三方：**PushPlus**（pushplus.plus 扫码注册拿 token）/ **WxPusher** / **Server酱 Turbo**，任选其一填入对应项 |
| 邮件 | 配置 `SMTP_HOST/PORT/USER/PASSWORD/FROM/TO` |
| 通用 Webhook | 填入任意 HTTP POST 接口地址 `WEBHOOK_URL`，收到 JSON 负载 |

> 说明：个人微信自动化（wxauto/wechaty 类）存在**封号风险**，本项目默认不实现，仅保留 Notifier 接口便于以后扩展。

## 代理配置（重要）

- 各平台服务条款**禁止高频爬取**；请保持最低可用频率，优先使用官方/非官方 API 而非纯 HTML 解析。
- **日本 IP 代理是硬需求**：国内 IP 大概率被限制或验证码拦截。两种配置方式（二选一或组合）：
  ```
  PROXY_LIST=http://user:pass@jp-proxy1:port,http://user:pass@jp-proxy2:port
  ```
  或登录 Web 面板 → **代理池** 页直接添加（推荐：可增删/启停/测试，改完无需重启）。
  面板启用代理优先于 `PROXY_LIST`；多个代理自动轮换，单 IP 限频。
- 雅虎系平台风控更严，遇验证码**自动跳过本轮并告警**，不做暴力重试（本工具当前未含雅虎平台，后续扩展时遵循此原则）。
- 连续失败达到 `FAILURE_DOWNGRADE_THRESHOLD`（默认 3 次）自动降频，面板会显示「已降频」告警。

## Web 面板

- 仪表盘 `/`：统计、各平台监控状态（频率/渠道/风控）、最近命中、手动触发抓取
- 关键词 `/keywords`：增删 / 启停
- 规则 `/rules`：价格区间 / 指定卖家 / 品牌
- 命中记录 `/items`：按平台筛选、分页
- 平台设置 `/settings`：每平台抓取频率、代理模式、启用渠道（保存后调度自动同步，无需重启）
- 代理池 `/proxies`：增删 / 启停 / 测试代理，抓取自动轮换，改完立即生效
- 推送日志 `/logs`：各渠道推送结果与错误

## 合规与风控说明

1. 各平台服务条款禁止高频爬取，频率控制在最低可用档位；本工具数据仅用于**个人监控提醒**，不用于转售。
2. 控制抓取频率、支持代理轮换、遇验证码自动跳过并告警。
3. 推送内容不含违反平台规则的信息；请勿对同一接口高频请求。

## 项目结构

```
hu/
├── run.py                  # 命令行入口（once/scan/serve/addkw）
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .env.example            # 配置模板
├── app/
│   ├── config.py           # 环境变量配置
│   ├── database.py         # SQLAlchemy 引擎/会话
│   ├── models.py           # 数据表（keywords/rules/items/push_logs/price_history/settings/sellers/proxies）
│   ├── matcher.py          # 关键词+同义词映射、规则匹配
│   ├── service.py          # 核心流程：抓取→匹配→去重→推送
│   ├── scheduler.py        # APScheduler 每平台独立频率调度
│   ├── main.py             # FastAPI Web 面板
│   ├── crawler/
│   │   └── fetcher.py      # httpx + 代理池(面板/DB) + 随机UA + 指数退避 + 降频
│   ├── adapters/
│   │   ├── base.py         # 适配器基类 + 统一商品字段
│   │   ├── mercari.py      # 煤炉
│   │   ├── suruga.py       # 骏河屋
│   │   └── registry.py     # 适配器注册表
│   ├── notifier/
│   │   ├── base.py         # Notifier 抽象
│   │   ├── manager.py      # 多渠道发送 + 重试 + 日志
│   │   └── telegram/dingtalk/bark/wecom/pushplus/wxpusher/serverchan/email/webhook.py
│   └── templates/          # Jinja2 面板页面
```

## 后续扩展（按需求书预留）

- 补齐其余平台（乐天二手 Rakuma、雅虎闲置、雅虎日拍）：只需在 `app/adapters/` 新增 Adapter 并在 `registry.py` 注册。
- Phase 3：自动收藏 / 下单预留接口、统计面板增强、多账号/多用户。

## 免责声明

本工具仅用于个人合规使用的上新监控提醒。请遵守各平台服务条款，控制抓取频率，配置合规代理；因使用本工具产生的账号风险由使用者自行承担。
