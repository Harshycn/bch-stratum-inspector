#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BCH Stratum Inspector
=====================
A transparency tool for Bitcoin Cash miners.

Connects to any BCH pool's Stratum endpoint, fetches the block template,
and decodes the coinbase transaction so you can inspect:

  • Output addresses — who actually receives the block reward (CashAddr + Legacy)
  • Pool tag         — the identity string embedded in the coinbase (full UTF-8)
  • Block metadata   — height, reward, prev-hash, difficulty

No external dependencies — pure Python 3 standard library.

Usage:
    python bch_stratum_inspector.py                              # all pools
    python bch_stratum_inspector.py harshy                       # single pool
    python bch_stratum_inspector.py --host example.com --port 3333  # custom
    python bch_stratum_inspector.py --worker bitcoincash:q... harshy
    python bch_stratum_inspector.py --list                       # show pools
    python bch_stratum_inspector.py --debug harshy               # verbose

Author : Harshy  (https://harshy.site/)
License: MIT
"""

import socket
import json
import struct
import hashlib
import sys
import datetime
import argparse

# ══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Pool registry — add / remove entries as needed
# Format: 'name': ('hostname', port)
POOLS = {
    # ── Legitimate pools ──
    'harshy':       ('bch.harshy.site',        3333),
    'molepool':     ('eu.molepool.com',         5566),
    'solopool':     ('eu2.solopool.org',         8002),
    '2miners':      ('solo-bch.2miners.com',     9090),
    'solohash':     ('solo.solohash.co.uk',      3337),
    'solomining':   ('stratum.solomining.io',    5566),
    'solo-pool':    ('bch-eu.solo-pool.org',     3333),
    'xppool':       ('in.xppool.in',             5566),
    # ── Highly suspicious pools (see https://redd.it/1p6z0g0) ──
    'zsolo':        ('bch.zsolo.bid',            5057),
    'luckymonster': ('bch.luckymonster.pro',     6112),
    'millpools':    ('bch.millpools.cc',         6567),
}

# Default worker credentials (can be overridden via --worker / --password)
DEFAULT_WORKER   = 'bitcoincash:qp3wjpa3tjlj042z2wv7hahsldgwhwy0rq9sywjpyy'
DEFAULT_PASSWORD = 'x'

# Runtime config — populated by main()
WORKER   = DEFAULT_WORKER
PASSWORD = DEFAULT_PASSWORD
DEBUG    = False


# ══════════════════════════════════════════════════════════════════════════════
#  Address Encoding — CashAddr (bitcoincash:q…)
# ══════════════════════════════════════════════════════════════════════════════

_CASHADDR_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'


def _cashaddr_polymod(values):
    """BCH-style polymod for CashAddr checksum computation."""
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ d
        if c0 & 0x01: c ^= 0x98f2bc8e61
        if c0 & 0x02: c ^= 0x79b76d99e2
        if c0 & 0x04: c ^= 0xf33e5fb3c4
        if c0 & 0x08: c ^= 0xae2eabe2a8
        if c0 & 0x10: c ^= 0x1e4f43e470
    return c ^ 1


def _cashaddr_hrp_expand(prefix):
    return [ord(c) & 0x1f for c in prefix] + [0]


def _convert_bits(data, from_bits, to_bits, pad=True):
    """General power-of-2 base conversion."""
    acc, bits, ret = 0, 0, []
    maxv = (1 << to_bits) - 1
    for value in data:
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to_bits - bits)) & maxv)
    return ret


def hash160_to_cashaddr(hash160: bytes, script_type: str = 'P2PKH') -> str:
    """Convert a HASH-160 digest to a CashAddr string."""
    prefix = 'bitcoincash'
    version_byte = 0x00 if script_type == 'P2PKH' else 0x08
    payload = _convert_bits([version_byte] + list(hash160), 8, 5)
    values = _cashaddr_hrp_expand(prefix) + payload + [0] * 8
    checksum = [(_cashaddr_polymod(values) >> 5 * (7 - i)) & 0x1f for i in range(8)]
    return f"{prefix}:{''.join(_CASHADDR_CHARSET[d] for d in payload + checksum)}"


# ══════════════════════════════════════════════════════════════════════════════
#  Address Encoding — Legacy (Base58Check, 1…/3…)
# ══════════════════════════════════════════════════════════════════════════════

_BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _base58check_encode(payload: bytes) -> str:
    """Encode raw bytes to a Base58Check string."""
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    data = payload + checksum
    n = int.from_bytes(data, 'big')
    result = ''
    while n > 0:
        n, r = divmod(n, 58)
        result = _BASE58_ALPHABET[r] + result
    # Preserve leading zero-bytes as '1' characters
    for byte in data:
        if byte == 0:
            result = '1' + result
        else:
            break
    return result


def hash160_to_legacy(hash160: bytes, script_type: str = 'P2PKH') -> str:
    """Convert a HASH-160 digest to a legacy Base58Check address."""
    version = b'\x00' if script_type == 'P2PKH' else b'\x05'
    return _base58check_encode(version + hash160)


# ══════════════════════════════════════════════════════════════════════════════
#  Raw Coinbase Transaction Parser
# ══════════════════════════════════════════════════════════════════════════════

class CoinbaseTxParser:
    """Minimal Bitcoin/BCH raw transaction deserializer."""

    def __init__(self, hex_str: str):
        self._data = bytes.fromhex(hex_str)
        self._pos = 0

    # ── low-level readers ────────────────────────────────────────────────────

    def _read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def _u32(self):  return struct.unpack('<I', self._read(4))[0]
    def _i32(self):  return struct.unpack('<i', self._read(4))[0]
    def _u64(self):  return struct.unpack('<Q', self._read(8))[0]

    def _varint(self):
        n = self._data[self._pos]; self._pos += 1
        if   n < 0xfd: return n
        elif n == 0xfd: return struct.unpack('<H', self._read(2))[0]
        elif n == 0xfe: return struct.unpack('<I', self._read(4))[0]
        else:           return struct.unpack('<Q', self._read(8))[0]

    # ── main entry point ─────────────────────────────────────────────────────

    def parse(self) -> dict:
        """Return {'version', 'inputs': [...], 'outputs': [...], 'locktime'}."""
        tx = {'version': self._i32()}

        in_count = self._varint()
        tx['inputs'] = []
        for _ in range(in_count):
            prev_hash = self._read(32).hex()
            prev_index = self._u32()
            script_len = self._varint()
            script_sig = self._read(script_len)
            sequence = self._u32()
            tx['inputs'].append({
                'prev_hash': prev_hash,
                'prev_index': prev_index,
                'scriptSig': script_sig,
                'sequence': sequence,
            })

        out_count = self._varint()
        tx['outputs'] = []
        for _ in range(out_count):
            value = self._u64()
            script_len = self._varint()
            script_pubkey = self._read(script_len)
            tx['outputs'].append({
                'value': value,
                'scriptPubKey': script_pubkey,
            })

        tx['locktime'] = self._u32()
        return tx


# ══════════════════════════════════════════════════════════════════════════════
#  Coinbase Field Decoders
# ══════════════════════════════════════════════════════════════════════════════

def parse_block_height(script_sig: bytes):
    """Extract block height from a BIP-34 coinbase scriptSig."""
    if len(script_sig) < 2:
        return None
    h_len = script_sig[0]
    if 1 <= h_len <= 8 and len(script_sig) > h_len:
        return int.from_bytes(script_sig[1:1 + h_len], 'little')
    return None


def parse_coinbase_tag(script_sig: bytes):
    """
    Return (readable_tag, raw_bytes) from the coinbase scriptSig.

    The first push (BIP-34 block height) is skipped; everything after it is
    decoded as UTF-8 (with fallback to latin-1).  Non-printable control chars
    are stripped while all visible Unicode characters (CJK, emoji, …) are kept.
    """
    if len(script_sig) < 2:
        return '', b''
    h_len = script_sig[0]
    raw = script_sig[1 + h_len:]
    if not raw:
        return '', b''
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    text = ''.join(c for c in text if c.isprintable() or c == ' ').strip()
    return text, raw


def parse_script_pubkey(script: bytes):
    """
    Identify the script type and extract addresses.

    Returns (script_type, address_dict_or_None, extra_hex).
    address_dict has keys 'cashaddr' and 'legacy' when applicable.
    """
    if not script:
        return 'EMPTY', None, ''

    # P2PKH — OP_DUP OP_HASH160 PUSH20 <20B> OP_EQUALVERIFY OP_CHECKSIG
    if (len(script) == 25
            and script[:3] == b'\x76\xa9\x14'
            and script[23:] == b'\x88\xac'):
        h160 = script[3:23]
        return 'P2PKH', {
            'cashaddr': hash160_to_cashaddr(h160, 'P2PKH'),
            'legacy':   hash160_to_legacy(h160, 'P2PKH'),
        }, h160.hex()

    # P2SH — OP_HASH160 PUSH20 <20B> OP_EQUAL
    if (len(script) == 23
            and script[:2] == b'\xa9\x14'
            and script[22] == 0x87):
        h160 = script[2:22]
        return 'P2SH', {
            'cashaddr': hash160_to_cashaddr(h160, 'P2SH'),
            'legacy':   hash160_to_legacy(h160, 'P2SH'),
        }, h160.hex()

    # OP_RETURN — data carrier output
    if script[0] == 0x6a:
        return 'OP_RETURN', None, script[1:].hex()

    # P2PK — <compressed/uncompressed pubkey> OP_CHECKSIG
    if script[-1] == 0xac and len(script) in (35, 67):
        pk_len = script[0]
        if pk_len == len(script) - 2:
            pubkey = script[1:-1]
            h160 = hashlib.new('ripemd160', hashlib.sha256(pubkey).digest()).digest()
            return 'P2PK', {
                'cashaddr': hash160_to_cashaddr(h160, 'P2PKH'),
                'legacy':   hash160_to_legacy(h160, 'P2PKH'),
            }, pubkey.hex()

    return 'UNKNOWN', None, script.hex()


# ══════════════════════════════════════════════════════════════════════════════
#  Stratum Protocol Helpers
# ══════════════════════════════════════════════════════════════════════════════

def stratum_prevhash_to_blockchain(prevhash_hex: str) -> str:
    """
    Convert a Stratum-encoded prevhash to blockchain-explorer byte order.

    Stratum transmits the 32-byte hash as eight 4-byte groups, each internally
    byte-swapped.  We reverse within each group, then reverse the whole hash.
    """
    if len(prevhash_hex) != 64:
        return prevhash_hex
    # Step 1 — undo per-group byte swap
    internal = ''.join(
        ''.join(prevhash_hex[i + j:i + j + 2] for j in range(6, -1, -2))
        for i in range(0, 64, 8)
    )
    # Step 2 — reverse entire 32 bytes → big-endian display order
    return ''.join(internal[j:j + 2] for j in range(62, -1, -2))


def _tcp_connect(host: str, port: int) -> socket.socket:
    """Open a plain TCP connection with a 30-second timeout."""
    print(f'[*] Connecting to {host}:{port} …')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect((host, port))
    print('[+] Connected')
    return s


def _stratum_send(sock, method, params, msg_id):
    msg = json.dumps({'id': msg_id, 'method': method, 'params': params}) + '\n'
    sock.sendall(msg.encode())


def _stratum_recv(sock, timeout=15):
    """Receive one or more newline-delimited JSON messages."""
    buf = b''
    sock.settimeout(timeout)
    results = []
    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Non-JSON response — could be an error banner (e.g. "IP Banned")
                        text = line.decode('utf-8', errors='replace').strip()
                        if text:
                            print(f'[!] Non-JSON from pool: {text}')
            if results:
                sock.settimeout(3)
        except socket.timeout:
            break
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
            if DEBUG:
                print(f'    [DEBUG] _stratum_recv network error: {type(e).__name__}: {e}')
            break
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Difficulty & Unit Helpers
# ══════════════════════════════════════════════════════════════════════════════

_DIFF1_TARGET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
_UNITS = [(1e18, 'E'), (1e15, 'P'), (1e12, 'T'), (1e9, 'G'), (1e6, 'M'), (1e3, 'K')]


def nbits_to_difficulty(nbits_hex: str):
    """Return (human_str, raw_float) from a compact nBits value."""
    nbits = int(nbits_hex, 16)
    exp = nbits >> 24
    coeff = nbits & 0x007fffff
    if nbits & 0x00800000:
        coeff = -coeff
    target = coeff * (1 << (8 * (exp - 3)))
    if target <= 0:
        return 'N/A', 0.0
    diff = _DIFF1_TARGET / target
    for threshold, unit in _UNITS:
        if diff >= threshold:
            return f'{diff / threshold:.2f} {unit}', diff
    return f'{diff:.2f}', diff


def _sat_to_bch(sat: int) -> float:
    return sat / 1e8


# ══════════════════════════════════════════════════════════════════════════════
#  Pool Query & Result Display
# ══════════════════════════════════════════════════════════════════════════════

def query_pool(pool_name: str, host: str, port: int) -> bool:
    """Connect to *one* pool, fetch its template, parse & print.  Return True on success."""
    print(f'\n[*] Pool: {pool_name.upper()} ({host}:{port})\n')

    try:
        sock = _tcp_connect(host, port)

        # ── subscribe ────────────────────────────────────────────────────────
        print('[*] mining.subscribe …')
        _stratum_send(sock, 'mining.subscribe', ['cgminer/4.9.2'], 1)
        responses = _stratum_recv(sock)

        extranonce1 = extranonce2_size = None
        for r in responses:
            if r.get('id') == 1:
                if r.get('result'):
                    extranonce1 = r['result'][1]
                    extranonce2_size = r['result'][2]
                    print(f'[+] Subscribed  ExtraNonce1={extranonce1}  ExtraNonce2Size={extranonce2_size}')
                elif r.get('error'):
                    print(f'[-] Subscribe failed: {r["error"]}'); sock.close(); return False

        if extranonce1 is None:
            print('[-] No valid subscribe response'); sock.close(); return False

        # ── authorize ────────────────────────────────────────────────────────
        print(f'[*] mining.authorize ({WORKER}) …')
        _stratum_send(sock, 'mining.authorize', [WORKER, PASSWORD], 2)

        # ── wait for mining.notify ───────────────────────────────────────────
        print('[*] Waiting for mining.notify …')
        notify = None
        pool_diff = None
        auth_rejected = False
        for attempt in range(15):
            responses = _stratum_recv(sock, timeout=5)
            if DEBUG:
                if responses:
                    for r in responses:
                        print(f'    [DEBUG] recv #{attempt}: {json.dumps(r, ensure_ascii=False)}')
                else:
                    print(f'    [DEBUG] recv #{attempt}: (empty — timed out)')
            for r in responses:
                m = r.get('method', '')
                if m == 'mining.notify':
                    notify = r
                elif m == 'mining.set_difficulty':
                    pool_diff = r.get('params', [None])[0]
                    print(f'[+] Pool difficulty: {pool_diff}')
                elif r.get('id') == 2:
                    if r.get('result') is True:
                        print('[+] Authorized')
                    else:
                        err = r.get('error') or 'result=false (no error detail)'
                        print(f'[-] Authorization rejected: {err}')
                        auth_rejected = True
            if notify or auth_rejected:
                break
        sock.close()

        if auth_rejected and not notify:
            print('[-] Pool rejected the worker — check your address/credentials')
            return False

        if not notify:
            print('[-] Timeout — no mining.notify received'); return False

        # ── decode template ──────────────────────────────────────────────────
        print('\n[+] Mining job received — decoding …\n')
        p = notify['params']
        job_id, prev_raw, cb1, cb2 = p[0], p[1], p[2], p[3]
        merkle_branch = p[4]
        ver_hex, nbits_hex, ntime_hex = p[5], p[6], p[7]
        clean = p[8] if len(p) > 8 else False

        coinbase_hex = cb1 + extranonce1 + ('00' * extranonce2_size) + cb2
        prev_hash = stratum_prevhash_to_blockchain(prev_raw)

        tx = CoinbaseTxParser(coinbase_hex).parse()
        sig = tx['inputs'][0]['scriptSig']
        height = parse_block_height(sig)
        tag, tag_raw = parse_coinbase_tag(sig)
        total_reward = sum(o['value'] for o in tx['outputs'])

        ver_int = int(ver_hex, 16)
        diff_str, _ = nbits_to_difficulty(nbits_hex)
        try:
            ts = datetime.datetime.fromtimestamp(int(ntime_hex, 16), datetime.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
        except Exception:
            ts = 'N/A'

        # ── pretty-print ─────────────────────────────────────────────────────
        W = 68
        def hdr(title):
            print('┌' + '─' * W + '┐')
            print('│' + title.center(W) + '│')
            print('├' + '─' * W + '┤')
        def ftr():
            print('└' + '─' * W + '┘'); print()

        hdr('Basic Info')
        print(f'│  Pool:         {pool_name.upper()} ({host})')
        print(f'│  Job ID:       {job_id}')
        print(f'│  Version:      0x{ver_hex} ({ver_int})')
        print(f'│  Difficulty:   0x{nbits_hex} → {diff_str}')
        print(f'│  Timestamp:    0x{ntime_hex} → {ts}')
        print(f'│  Clean Jobs:   {clean}')
        if pool_diff is not None:
            print(f'│  Pool Diff:    {pool_diff}')
        ftr()

        hdr('Block Data')
        print(f'│  Height:       {height}')
        print(f'│  Reward:       {_sat_to_bch(total_reward):.8f} BCH ({total_reward:,} sat)')
        print(f'│  Prev Hash:    {prev_hash}')
        ftr()

        hdr('Coinbase Tag')
        print(f'│  Tag:          {tag}')
        print(f'│  ScriptSig:    {sig.hex()}')
        print(f'│  Tag Raw:      {tag_raw.hex()}')
        print(f'│  ExtraNonce1:  {extranonce1}')
        print(f'│  EN2 Size:     {extranonce2_size} bytes')
        ftr()

        hdr(f'Coinbase Outputs ({len(tx["outputs"])})')
        for i, out in enumerate(tx['outputs']):
            bch = _sat_to_bch(out['value'])
            stype, addr, extra = parse_script_pubkey(out['scriptPubKey'])
            print('│')
            print(f'│  ── Output #{i} ──')
            print(f'│    Value:      {bch:.8f} BCH ({out["value"]:,} sat)')
            print(f'│    Type:       {stype}')
            if addr and isinstance(addr, dict):
                print(f'│    CashAddr:   {addr["cashaddr"]}')
                print(f'│    Legacy:     {addr["legacy"]}')
            if stype == 'OP_RETURN':
                print(f'│    Data (hex): {extra}')
                try:
                    raw = bytes.fromhex(extra)
                    readable = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in raw)
                    if any(32 <= b <= 126 for b in raw):
                        print(f'│    Readable:   {readable}')
                except Exception:
                    pass
            elif stype == 'P2PK':
                print(f'│    Pubkey:     {extra}')
            else:
                print(f'│    Script:     {out["scriptPubKey"].hex()}')
        print('│')
        ftr()

        if merkle_branch:
            hdr(f'Merkle Branch ({len(merkle_branch)} levels ≈ {2**len(merkle_branch)} txs)')
            for i, h in enumerate(merkle_branch):
                print(f'│  [{i:2d}] {h}')
            ftr()

        hdr('Raw Coinbase Tx (hex)')
        for i in range(0, len(coinbase_hex), 64):
            print(f'│  {coinbase_hex[i:i+64]}')
        ftr()

        print('═' * (W + 2))
        print(f'  ✓ {pool_name.upper()} — done')
        print('═' * (W + 2))
        return True

    except socket.timeout:          print(f'\n[-] {pool_name.upper()}: connection timed out')
    except ConnectionRefusedError:  print(f'\n[-] {pool_name.upper()}: connection refused')
    except ConnectionResetError:    print(f'\n[-] {pool_name.upper()}: connection reset')
    except Exception as e:          print(f'\n[-] {pool_name.upper()}: {type(e).__name__}: {e}')
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════════════════════

def _build_parser():
    """Build the argparse CLI parser."""
    p = argparse.ArgumentParser(
        prog='bch_stratum_inspector',
        description='BCH Stratum Inspector — mining pool transparency tool',
        epilog='Examples:\n'
               '  %(prog)s                              # query all preconfigured pools\n'
               '  %(prog)s harshy                       # query a single preconfigured pool\n'
               '  %(prog)s --host stratum.example.com --port 3333   # query a custom pool\n'
               '  %(prog)s --worker bitcoincash:qxyz... harshy      # override worker address\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('pool', nargs='?', default=None,
                   help='preconfigured pool name (e.g. harshy, zsolo, 2miners)')
    p.add_argument('--host', default=None,
                   help='custom pool hostname (use with --port)')
    p.add_argument('--port', type=int, default=None,
                   help='custom pool port (use with --host)')
    p.add_argument('-w', '--worker', default=None,
                   help=f'worker address (default: {DEFAULT_WORKER[:30]}…)')
    p.add_argument('-p', '--password', default=None,
                   help='stratum password (default: x)')
    p.add_argument('--debug', action='store_true',
                   help='print raw Stratum messages for troubleshooting')
    p.add_argument('--list', action='store_true',
                   help='list all preconfigured pools and exit')
    return p


def main():
    global WORKER, PASSWORD, DEBUG

    parser = _build_parser()
    args = parser.parse_args()

    # Apply overrides
    if args.worker:
        WORKER = args.worker
    if args.password:
        PASSWORD = args.password
    if args.debug:
        DEBUG = True

    W = 68
    print()
    print('╔' + '═' * W + '╗')
    print('║' + '  BCH Stratum Inspector'.center(W) + '║')
    print('╚' + '═' * W + '╝')

    # --list: show preconfigured pools
    if args.list:
        print(f'\n  Preconfigured pools ({len(POOLS)}):\n')
        for name, (h, p) in POOLS.items():
            print(f'    {name:<15s}  {h}:{p}')
        print()
        return

    # --host/--port: custom pool
    if args.host:
        port = args.port or 3333
        label = args.pool or 'custom'
        query_pool(label, args.host, port)
        return

    # Positional: single preconfigured pool
    if args.pool:
        name = args.pool.lower()
        if name in POOLS:
            h, p = POOLS[name]
            query_pool(name, h, p)
        else:
            print(f"\n[!] Unknown pool '{name}'.")
            print(f'    Available: {", ".join(POOLS)}')
            print(f'    Or use --host and --port to test a custom endpoint.')
        return

    # No arguments: query all preconfigured pools
    print(f'\n[*] Querying all {len(POOLS)} pools: {", ".join(POOLS)} …')
    ok = fail = 0
    for name, (h, p) in POOLS.items():
        print('\n' + '▓' * (W + 2))
        print(f'  ▶ {name.upper()} ({h}:{p})')
        print('▓' * (W + 2))
        if query_pool(name, h, p):
            ok += 1
        else:
            fail += 1

    print()
    print('╔' + '═' * W + '╗')
    print('║' + '  Summary'.center(W) + '║')
    print('╠' + '═' * W + '╣')
    print(f'║  Total: {len(POOLS)}  |  Success: {ok}  |  Failed: {fail}'.ljust(W) + '║')
    print('╚' + '═' * W + '╝')


if __name__ == '__main__':
    main()
