[English](README.md) | **中文**

# BCH Stratum Inspector

面向 Bitcoin Cash 矿工的**透明度工具**。通过 Stratum 协议连接矿池，获取区块模板，解码 Coinbase 交易 — 让你清楚看到区块奖励的分配情况。

## 动机

Solo 挖矿中，矿工期望区块奖励直接进入自己的地址，或进入有透明支付记录的可信矿池地址。但如果不读取原始区块模板，你怎么验证？

本工具连接任意 BCH 矿池的 Stratum 端点，揭示 Coinbase 交易的实际内容 — 输出地址、矿池标签等。无论你是在审计自己使用的矿池，还是研究不同矿池的模板结构，它都能提供数据让你自行判断。

## 功能

| 功能 | 说明 |
|---|---|
| **双格式地址** | 每个输出同时显示 **CashAddr** (`bitcoincash:q…`) 和 **Legacy** (`1…` / `3…`) |
| **矿池标签解码** | 完整 UTF-8 支持 — 中文、emoji、ASCII |
| **区块元数据** | 高度 (BIP-34)、奖励、前一区块哈希（浏览器格式） |
| **难度显示** | nBits → 人类可读值 (K/M/G/T/P/E) |
| **多矿池** | 一次查询所有配置矿池，或命令行指定单个 |
| **零依赖** | 纯 Python 标准库，无需安装 |

## 快速开始

```bash
# 查询所有配置矿池
python bch_stratum_inspector.py

# 查询指定矿池
python bch_stratum_inspector.py harshy
```

## 预配置矿池

| 名称 | 端点 | 状态 |
|---|---|---|
| `harshy` | `bch.harshy.site:3333` | ✅ [Harshy's Pool](https://harshy.site/) |
| `molepool` | `eu.molepool.com:5566` | ✅ 正规 |
| `solopool` | `eu2.solopool.org:8002` | ✅ 正规 |
| `2miners` | `solo-bch.2miners.com:9090` | ✅ 正规 |
| `solohash` | `solo.solohash.co.uk:3337` | ✅ 正规 |
| `solomining` | `stratum.solomining.io:5566` | ✅ 正规 |
| `solo-pool` | `bch-eu.solo-pool.org:3333` | ✅ 正规 |
| `xppool` | `in.xppool.in:5566` | ✅ 正规 |
| `zsolo` | `bch.zsolo.bid:5057` | ⚠️ 高度可疑 |
| `luckymonster` | `bch.luckymonster.pro:6112` | ⚠️ 高度可疑 |
| `millpools` | `bch.millpools.cc:6567` | ⚠️ 高度可疑 |

> ⚠️ 这些矿池在面板上显示较高算力，但区块链浏览器中找不到任何匹配其 Coinbase 标签的出块记录。此外还有报告指出，其标注为 BTC 的端点实际下发的是 BCH 区块模板，等于用矿工本应挖 BTC 的算力偷偷挖 BCH。详细证据见 [Reddit 社区调查](https://www.reddit.com/r/BitAxe/comments/1p6z0g0/beware_zsolobid_and_luckymonsterpro_are_scam_pools/)。

编辑脚本顶部的 `POOLS` 字典即可增删矿池。你也可以把工具指向任何标注为 BTC 的 Stratum 端点 — 如果返回的是 BCH 区块模板，那就是个危险信号。

## 如何辨别

运行工具后，重点关注 **Coinbase 输出** 部分。

### 理解 Coinbase 输出

> **注意：** 看到矿池地址（而非你的地址）出现在 Coinbase 输出中，**并不自动等于骗局**。部分 Solo 矿池确实会先出块到矿池钱包，事后再分配奖励。关键区别在于**透明度**。

一个值得信赖的 Solo 矿池应当提供：
- 公开的仪表板，展示已出块记录和支付历史
- 可链上验证的记录，证明出块与支付的对应关系
- 清晰的费率说明

而虚假矿池通常**什么都不提供** — 没有出块记录、没有支付证明、无法验证你的算力是否被诚实使用。

### 🔍 SHA256d 算力劫持

更恶劣的手段是：矿池接受矿工指定挖 **BTC** 的 SHA256d 算力，却暗中将其转去挖 **BCH**，中饱私囊。本工具可以揭露这一行为，因为：

- **Coinbase 标签** 显示了实际组装区块模板的矿池身份
- **输出地址** 显示了谁拿到了奖励
- 与你的矿池面板交叉对比即可发现差异

如果你连接的是一个"BTC Solo 矿池"，但本工具显示其 Stratum 端点在下发 **BCH 区块模板**，说明该矿池正在未经你同意的情况下用你的算力挖 BCH。

## 工作原理

```
┌─────────┐   Stratum    ┌───────────┐
│  脚本   │◄────────────►│ BCH 矿池  │
└────┬────┘  TCP/JSON     └───────────┘
     │
     ▼
 1. mining.subscribe  → 获取 ExtraNonce
 2. mining.authorize  → 认证矿工
 3. mining.notify     → 接收区块模板
     │
     ▼
 重建 Coinbase 交易 → 解码输出 → 显示谁拿了钱
```

Coinbase 交易是每个区块的第一笔交易。它没有真正的输入 — `scriptSig` 里编码了区块高度 (BIP-34) 和矿池标识标签。**输出**决定了谁获得区块奖励。

### 地址格式

| 格式 | 示例 | 说明 |
|---|---|---|
| **CashAddr** | `bitcoincash:qzue7uw…` | BCH 现代格式 |
| **Legacy** | `1HvV1uQXTZ…` | 兼容 BTC 风格浏览器 |

两者指向区块链上相同的 HASH-160。

## 环境要求

- Python 3.6+
- 无需外部包

## 许可证

MIT — 由 [Harshy's Pool](https://harshy.site/)（BCH Solo 矿池）开发。
