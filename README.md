**English** | [中文](README_zh-CN.md)

# BCH Stratum Inspector

A transparency tool for Bitcoin Cash miners.  Connects to mining pools via the **Stratum protocol**, fetches the block template, and **decodes the coinbase transaction** — letting you see exactly who gets paid and how the block reward is distributed.

## Motivation

In solo mining, miners expect the block reward to go directly to their own address, or to a trusted pool address with transparent payout records.  But how can you verify this without reading the raw block template?

This tool connects to any BCH pool's Stratum endpoint and reveals exactly what's inside the coinbase transaction — the outputs, addresses, pool tags, and more.  Whether you're auditing a pool you use or researching how different pools structure their templates, this gives you the data to decide for yourself.

## Features

| Feature | Detail |
|---|---|
| **Dual Address Format** | Every output shows both **CashAddr** (`bitcoincash:q…`) and **Legacy** (`1…` / `3…`) |
| **Pool Tag Decoding** | Full UTF-8 support — CJK characters, emoji, and ASCII |
| **Block Metadata** | Height (BIP-34), reward, previous hash (explorer format) |
| **Difficulty** | Compact nBits → human-readable with auto-scaling (K/M/G/T/P/E) |
| **Multi-Pool** | Query all configured pools in one run, or pick one via CLI |
| **Zero Dependencies** | Pure Python standard library — no `pip install` needed |

## Quick Start

```bash
# Query all configured pools
python bch_stratum_inspector.py

# Query a specific pool
python bch_stratum_inspector.py harshy
```

## Preconfigured Pools

| Name | Endpoint | Status |
|---|---|---|
| `harshy` | `bch.harshy.site:3333` | ✅ [Harshy's Pool](https://harshy.site/) |
| `molepool` | `eu.molepool.com:5566` | ✅ Legitimate |
| `solopool` | `eu2.solopool.org:8002` | ✅ Legitimate |
| `2miners` | `solo-bch.2miners.com:9090` | ✅ Legitimate |
| `solohash` | `solo.solohash.co.uk:3337` | ✅ Legitimate |
| `solomining` | `stratum.solomining.io:5566` | ✅ Legitimate |
| `solo-pool` | `bch-eu.solo-pool.org:3333` | ✅ Legitimate |
| `xppool` | `in.xppool.in:5566` | ✅ Legitimate |
| `zsolo` | `bch.zsolo.bid:5057` | ⚠️ Highly suspicious |
| `luckymonster` | `bch.luckymonster.pro:6112` | ⚠️ Highly suspicious |
| `millpools` | `bch.millpools.cc:6567` | ⚠️ Highly suspicious |

> ⚠️ These pools display high hashrate on their dashboards, yet no blocks with matching coinbase tags can be found on blockchain explorers.  There are also reports of BTC-labeled endpoints secretly serving BCH templates, effectively mining BCH with hashrate the miner intended for BTC.  See the [community investigation on Reddit](https://www.reddit.com/r/BitAxe/comments/1p6z0g0/beware_zsolobid_and_luckymonsterpro_are_scam_pools/) for detailed evidence.

Edit the `POOLS` dict in the script to add or remove pools.  You can also point the tool at any BTC-labeled Stratum endpoint — if it returns a BCH block template, that's a red flag.

## What to Look For

When you run the tool, pay attention to the **Coinbase Outputs** section.

### Understanding coinbase outputs

> **Important:** Seeing the pool's address (instead of yours) in the coinbase output does **not** automatically mean a scam.  Some solo pools legitimately mine to a pool-controlled wallet and distribute rewards afterward.  The key difference is **transparency**.

A trustworthy solo pool should provide:
- A public dashboard showing blocks found and payout history
- Verifiable on-chain records linking mined blocks to your payouts
- Clear documentation of the fee structure

A fraudulent pool typically offers **none of this** — no block history, no proof of payouts, and no way to verify that your hashrate is being used honestly.

### 🔍 SHA256d hashrate redirection

Some pools go further: they accept SHA256d hashrate from miners who selected **BTC**, but secretly redirect it to mine **BCH** for the pool's own profit.  This tool exposes this because:

- The **coinbase tag** reveals which pool actually assembled the block template
- The **output addresses** show who receives the reward
- Cross-referencing with your pool dashboard reveals discrepancies

If you're pointed at a "BTC solo pool" but this tool shows its Stratum endpoint serving **BCH block templates**, the pool is mining BCH with your hashrate without your consent.

## Sample Output

```
┌────────────────────────────────────────────────────────────────────┐
│                         Coinbase Tag                              │
├────────────────────────────────────────────────────────────────────┤
│  Tag:          /Harshy's Pool🎶想欲予阮出外的人🏍️飞向一个繁华世界🚆🌏/
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    Coinbase Outputs (2)                            │
├────────────────────────────────────────────────────────────────────┤
│  ── Output #0 ──
│    Value:      3.12500000 BCH (312,500,000 sat)
│    Type:       P2PKH
│    CashAddr:   bitcoincash:qzue7uw652l7knjsfrpma788rse7sqcn7u...
│    Legacy:     1HvV1uQXTZMEMqxCTcjLkSpR335YRRMLwP
└────────────────────────────────────────────────────────────────────┘
```

## How It Works

```
┌─────────┐   Stratum    ┌───────────┐
│  Script │◄────────────►│ BCH Pool  │
└────┬────┘  TCP/JSON     └───────────┘
     │
     ▼
 1. mining.subscribe  → get ExtraNonce
 2. mining.authorize  → authenticate worker
 3. mining.notify     → receive block template
     │
     ▼
 Reconstruct coinbase tx → Decode outputs → Show who gets paid
```

The coinbase transaction is the first transaction in every block.  It has no real inputs — instead, the `scriptSig` encodes the block height (BIP-34) and a pool identification tag.  The **outputs** determine who receives the block reward.

### Address Formats

| Format | Example | Notes |
|---|---|---|
| **CashAddr** | `bitcoincash:qzue7uw…` | Modern BCH format |
| **Legacy** | `1HvV1uQXTZ…` | Compatible with BTC-style explorers |

Both formats point to the same HASH-160 on the blockchain.

## Requirements

- Python 3.6+
- No external packages

## License

MIT — built by [Harshy's Pool](https://harshy.site/), a BCH solo mining pool.
