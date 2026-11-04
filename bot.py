#!/usr/bin/env python3
"""
Bot de alertas de criptomonedas (memecoins incluidas) para Telegram.

Cada vez que corre (GitHub Actions lo ejecuta cada 10 minutos):
  1. Lee los mensajes que le mandaste por Telegram (/compre, /vendi, /estado...).
  2. Revisa las señales y posiciones abiertas y te avisa si toca salir.
  3. Busca en todo el mercado (Solana, Base, BNB Chain, Monad) las monedas que
     van en tendencia alcista sostenida, descarta las que parecen estafa y te
     manda las mejores entradas, con precio de entrada, stop y objetivos.

No compra ni vende nada: tú decides y operas en FOMO.
Solo usa la biblioteca estándar de Python (nada que instalar).

Fuentes de datos (gratis, sin clave):
  - GeckoTerminal (CoinGecko): monedas en tendencia y velas de 15 minutos.
  - DEX Screener: precio, volumen, liquidez, compras y ventas.
  - GoPlus Security y RugCheck: revisión de estafas (honeypot, impuestos,
    autoridad de emisión/congelamiento, concentración de holders).
"""

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")

UA = "cripto-alertas-bot/1.0 (+github actions)"

# Redes que soporta FOMO. Cada una con su nombre en cada fuente de datos.
NETWORKS = {
    "solana": {"gecko": "solana", "dex": "solana", "goplus": "solana", "nombre": "Solana"},
    "base": {"gecko": "base", "dex": "base", "goplus": "8453", "nombre": "Base"},
    "bsc": {"gecko": "bsc", "dex": "bsc", "goplus": "56", "nombre": "BNB Chain"},
    "monad": {"gecko": "monad", "dex": "monad", "goplus": "143", "nombre": "Monad"},
}

DEFAULT_CONFIG = {
    "redes": ["solana", "base", "bsc", "monad"],
    "capital_usd": 0,
    "riesgo_por_operacion_pct": 2,
    "comision_fomo_usd": 1,
    "liquidez_minima_usd": 75000,
    "volumen_24h_minimo_usd": 150000,
    "edad_minima_horas": 24,
    "capitalizacion_minima_usd": 300000,
    "stop_minimo_pct": 4,
    "stop_maximo_pct": 15,
    "max_por_operacion_pct": 25,
    "objetivo_1_en_R": 1.5,
    "objetivo_2_en_R": 3,
    "max_alertas_por_vuelta": 3,
    "horas_sin_repetir_moneda": 6,
    "horas_validez_senal": 48,
    "exigir_revision_de_seguridad": True,
    "excluir_simbolos": ["USDC", "USDT", "DAI", "USD1", "PYUSD", "FDUSD", "USDE", "WETH", "WBTC",
                         "WSOL", "SOL", "WBNB", "BNB", "ETH", "CBBTC", "WMON", "MON"],
}

GECKO_PAUSE = 13.0  # GeckoTerminal sin clave permite ~5 llamadas por minuto


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

def log(*a):
    print(*a, file=sys.stderr, flush=True)


def now_ts():
    return time.time()


def fnum(x, default=None):
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    user = load_json(CONFIG_PATH, {})
    if isinstance(user, dict):
        for k, v in user.items():
            if k in cfg:
                cfg[k] = v
    cfg["redes"] = [r for r in cfg["redes"] if r in NETWORKS]
    cfg["excluir_simbolos"] = [s.upper() for s in cfg["excluir_simbolos"]]
    return cfg


class Http:
    """GET de JSON con reintentos. En pruebas se reemplaza por datos guardados."""

    def __init__(self):
        self.last_gecko = 0.0

    def get(self, url, headers=None, tries=3):
        if "geckoterminal.com" in url:
            wait = GECKO_PAUSE - (time.time() - self.last_gecko)
            if wait > 0:
                time.sleep(wait)
        h = {"User-Agent": UA, "Accept": "application/json"}
        h.update(headers or {})
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers=h)
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if "geckoterminal.com" in url:
                    self.last_gecko = time.time()
                return data
            except urllib.error.HTTPError as e:
                if "geckoterminal.com" in url:
                    self.last_gecko = time.time()
                if e.code == 429 or e.code >= 500:
                    time.sleep(15 * (attempt + 1))
                    continue
                log(f"HTTP {e.code} en {url[:120]}")
                return None
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
                log(f"Error de red en {url[:120]}: {e}")
                time.sleep(3)
        log(f"Sin respuesta tras {tries} intentos: {url[:120]}")
        return None

    def post(self, url, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, OSError) as e:
            log(f"Error enviando a Telegram: {e}")
            return None


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------

def ema(values, n):
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return [None] * (n - 1) + out


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(candles, n=14):
    if len(candles) <= n:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


# ----------------------------------------------------------------------------
# Fuentes de datos
# ----------------------------------------------------------------------------

def gecko_trending(http, network):
    url = (f"https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools"
           f"?duration=1h&page=1")
    data = http.get(url)
    out = []
    for p in (data or {}).get("data", []) or []:
        a = p.get("attributes") or {}
        rel = ((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}
        tid = rel.get("id") or ""
        prefix = network + "_"
        token = tid[len(prefix):] if tid.startswith(prefix) else tid.split("_", 1)[-1]
        if not token or not a.get("address"):
            continue
        out.append({"pool": a["address"], "token": token, "name": a.get("name", "")})
    return out


def gecko_candles(http, network, pool, minutes=15, limit=100, now=None):
    url = (f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/minute"
           f"?aggregate={minutes}&limit={limit}&currency=usd&token=base")
    data = http.get(url)
    rows = ((((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    now = now or now_ts()
    candles = []
    for r in rows:
        if not isinstance(r, list) or len(r) < 6:
            continue
        ts, o, h, l, c, v = (fnum(x) for x in r[:6])
        if None in (ts, o, h, l, c) or c <= 0:
            continue
        if ts + minutes * 60 > now:  # vela todavía abierta
            continue
        candles.append({"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v or 0.0})
    candles.sort(key=lambda x: x["t"])
    return candles


def dex_pairs(http, dex_chain, addresses):
    """Devuelve {token_address_lower: mejor_par} usando DEX Screener (máx. 30 por llamada)."""
    best = {}
    addresses = list(dict.fromkeys(addresses))
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        url = f"https://api.dexscreener.com/tokens/v1/{dex_chain}/{','.join(chunk)}"
        data = http.get(url)
        pairs = data if isinstance(data, list) else (data or {}).get("pairs") or []
        for p in pairs:
            base = ((p.get("baseToken") or {}).get("address") or "")
            key = base.lower()
            liq = fnum((p.get("liquidity") or {}).get("usd"), 0)
            if key and (key not in best or liq > fnum((best[key].get("liquidity") or {}).get("usd"), 0)):
                best[key] = p
    return best


def goplus_check(http, net_key, token):
    """Devuelve (ok, motivos, datos). ok=None si no se pudo revisar."""
    net = NETWORKS[net_key]
    if net_key == "solana":
        url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={token}"
    else:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{net['goplus']}?contract_addresses={token}"
    data = http.get(url)
    result = (data or {}).get("result") or {}
    info = result.get(token) or result.get(token.lower()) or (next(iter(result.values())) if result else None)
    if not info:
        return None, ["sin datos de seguridad"], {}
    motivos = []

    def flag(v):
        if isinstance(v, dict):
            v = v.get("status")
        return str(v) == "1"

    if net_key == "solana":
        if flag(info.get("mintable")):
            motivos.append("el creador puede emitir más monedas")
        if flag(info.get("freezable")):
            motivos.append("el creador puede congelar tus monedas")
        if flag(info.get("balance_mutable_authority")):
            motivos.append("el creador puede cambiar los saldos")
        if flag(info.get("closable")):
            motivos.append("el creador puede cerrar cuentas")
        if str(info.get("non_transferable")) == "1":
            motivos.append("no se puede transferir")
        tf = info.get("transfer_fee") or {}
        fee = None
        if isinstance(tf, dict):
            cur = tf.get("current_fee_rate") or {}
            fee = fnum(cur.get("fee_rate") if isinstance(cur, dict) else cur)
        if fee and fee > 0:
            motivos.append("cobra comisión en cada transferencia")
    else:
        if flag(info.get("is_honeypot")):
            motivos.append("HONEYPOT: no se puede vender")
        if flag(info.get("cannot_sell_all")):
            motivos.append("no deja vender todo")
        if flag(info.get("owner_change_balance")):
            motivos.append("el dueño puede cambiar saldos")
        if flag(info.get("hidden_owner")):
            motivos.append("dueño oculto")
        if flag(info.get("transfer_pausable")):
            motivos.append("el dueño puede pausar las ventas")
        if flag(info.get("is_blacklisted")):
            motivos.append("tiene lista negra de billeteras")
        if flag(info.get("slippage_modifiable")):
            motivos.append("el dueño puede cambiar el impuesto")
        sell_tax = fnum(info.get("sell_tax"), 0) or 0
        buy_tax = fnum(info.get("buy_tax"), 0) or 0
        if sell_tax > 1:
            sell_tax /= 100
        if buy_tax > 1:
            buy_tax /= 100
        if sell_tax > 0.10 or buy_tax > 0.10:
            motivos.append(f"impuesto alto (compra {buy_tax:.0%}, venta {sell_tax:.0%})")
        top = 0.0
        for h in (info.get("holders") or [])[:10]:
            if str(h.get("is_locked")) == "1" or str(h.get("is_contract")) == "1":
                continue
            p = fnum(h.get("percent"), 0) or 0
            top += p / 100 if p > 1 else p
        if top > 0.5:
            motivos.append(f"pocas billeteras tienen el {top:.0%} de la moneda")
    return (len(motivos) == 0), motivos, info


def rugcheck(http, token):
    """Solo Solana. Devuelve lista de riesgos graves (vacía si todo bien o sin datos)."""
    data = http.get(f"https://api.rugcheck.xyz/v1/tokens/{token}/report/summary")
    if not data:
        return []
    graves = []
    for r in data.get("risks") or []:
        if str(r.get("level", "")).lower() == "danger":
            graves.append(r.get("name") or "riesgo grave")
    return graves


# ----------------------------------------------------------------------------
# Análisis
# ----------------------------------------------------------------------------

def prefilter(pair, cfg, now=None):
    """Filtro rápido con datos de DEX Screener. Devuelve (ok, puntaje, razones)."""
    now = now or now_ts()
    sym = ((pair.get("baseToken") or {}).get("symbol") or "").upper()
    if sym in cfg["excluir_simbolos"]:
        return False, 0, ["excluida"]
    liq = fnum((pair.get("liquidity") or {}).get("usd"), 0)
    vol = pair.get("volume") or {}
    pc = pair.get("priceChange") or {}
    tx = pair.get("txns") or {}
    v24 = fnum(vol.get("h24"), 0)
    mcap = fnum(pair.get("marketCap")) or fnum(pair.get("fdv"), 0)
    created = fnum(pair.get("pairCreatedAt"))
    age_h = (now - created / 1000) / 3600 if created else 0
    if liq < cfg["liquidez_minima_usd"]:
        return False, 0, ["poca liquidez"]
    if v24 < cfg["volumen_24h_minimo_usd"]:
        return False, 0, ["poco volumen"]
    if mcap < cfg["capitalizacion_minima_usd"]:
        return False, 0, ["capitalización muy baja"]
    if age_h < cfg["edad_minima_horas"]:
        return False, 0, ["demasiado nueva"]
    m5, h1, h6, h24 = (fnum(pc.get(k), 0) for k in ("m5", "h1", "h6", "h24"))
    if not (h1 > 0 and h6 > 0 and h24 > 0):
        return False, 0, ["no va subiendo en 1h, 6h y 24h a la vez"]
    if m5 < -4:
        return False, 0, ["cayendo en los últimos 5 minutos"]
    if h1 > 60:
        return False, 0, ["subió demasiado rápido en 1h (riesgo de desplome)"]

    def ratio(k):
        t = tx.get(k) or {}
        b, s = fnum(t.get("buys"), 0), fnum(t.get("sells"), 0)
        return b / s if s else (2.0 if b else 0.0)

    r1, r24 = ratio("h1"), ratio("h24")
    if r1 < 1.05 or r24 < 1.0:
        return False, 0, ["hay más ventas que compras"]
    turnover = v24 / liq if liq else 0
    score = (min(h24, 300) / 300 * 25 + min(h6, 100) / 100 * 20 + min(h1, 30) / 30 * 10
             + min(r1, 2.5) / 2.5 * 20 + min(math.log10(max(liq, 1)) - 4, 2) / 2 * 15
             + min(turnover, 10) / 10 * 10)
    return True, score, []


def chart_setup(candles, cfg):
    """Analiza velas de 15 min. Devuelve dict con entrada/stop/objetivos o None y motivo."""
    if len(candles) < 60:
        return None, "pocas velas para analizar"
    closes = [c["c"] for c in candles]
    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    last = candles[-1]
    price = last["c"]
    if not (e9[-1] and e21[-1] and e50[-1]):
        return None, "sin medias"
    if not (e9[-1] > e21[-1] > e50[-1]):
        return None, "las medias no están en orden alcista"
    if not (e21[-1] > e21[-5] and e50[-1] > e50[-9]):
        return None, "la tendencia no está subiendo"
    if price < e21[-1]:
        return None, "el precio está por debajo de la media de 21"
    r = rsi(closes)
    if r is None or r < 50 or r > 75:
        return None, f"fuerza (RSI {r:.0f}) fuera de rango" if r is not None else "sin RSI"
    a = atr(candles)
    if not a:
        return None, "sin ATR"
    prev_high = max(c["h"] for c in candles[-25:-1])
    vols = [c["v"] for c in candles[-21:-1]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    recent_low = min(c["l"] for c in candles[-4:])
    if price > prev_high and last["v"] > 1.5 * avg_vol and price - e21[-1] <= 2.5 * a:
        tipo = "ruptura"
        detalle = "rompió el máximo de las últimas 6 horas con volumen fuerte"
    elif recent_low <= e21[-1] + 0.5 * a and last["c"] > last["o"] and price - e21[-1] <= 1.5 * a:
        tipo = "retroceso"
        detalle = "bajó a la media de 21 velas y está rebotando hacia arriba"
    else:
        return None, "no hay punto de entrada claro ahora (precio estirado o sin rebote)"
    swing_low = min(c["l"] for c in candles[-8:])
    stop = min(swing_low, e21[-1] - 0.5 * a)
    stop = min(stop, price - 1.0 * a)
    # Un stop demasiado pegado se activa con el ruido normal y la comisión se come la ganancia.
    stop = min(stop, price * (1 - cfg["stop_minimo_pct"] / 100))
    risk = price - stop
    risk_pct = risk / price * 100
    if risk <= 0:
        return None, "stop inválido"
    if risk_pct > cfg["stop_maximo_pct"]:
        return None, f"demasiado volátil (el stop quedaría a -{risk_pct:.0f}%)"
    t1 = price + cfg["objetivo_1_en_R"] * risk
    t2 = price + cfg["objetivo_2_en_R"] * risk
    return {"tipo": tipo, "detalle": detalle, "entrada": price, "stop": stop, "t1": t1, "t2": t2,
            "riesgo_pct": risk_pct, "rsi": r, "ema21": e21[-1]}, ""


def position_size(cfg, risk_pct):
    cap = fnum(cfg.get("capital_usd"), 0) or 0
    if cap <= 0:
        return None
    max_loss = cap * fnum(cfg.get("riesgo_por_operacion_pct"), 2) / 100
    fee = fnum(cfg.get("comision_fomo_usd"), 0) or 0
    budget = max_loss - 2 * fee
    if budget <= 0:
        return {"monto": 0, "perdida_max": max_loss, "aviso": True}
    tope = cap * fnum(cfg.get("max_por_operacion_pct"), 25) / 100
    amount = min(budget / (risk_pct / 100), tope)
    loss = amount * risk_pct / 100 + 2 * fee
    return {"monto": amount, "perdida_max": loss, "aviso": False}


# ----------------------------------------------------------------------------
# Mensajes
# ----------------------------------------------------------------------------

def fmt_price(p):
    if p is None:
        return "?"
    if p >= 100:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:,.4f}"
    if p >= 0.01:
        return f"${p:.5f}"
    s = f"{p:.12f}".rstrip("0")
    digits = s.split(".")[1]
    zeros = len(digits) - len(digits.lstrip("0"))
    return f"${p:.{zeros + 4}f}"


def fmt_usd(x):
    if x >= 1e9:
        return f"${x / 1e9:.1f} mil millones"
    if x >= 1e6:
        return f"${x / 1e6:.1f} M"
    if x >= 1e3:
        return f"${x / 1e3:.0f} mil"
    return f"${x:.0f}"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def entry_message(sig, pair, cfg):
    pc = pair.get("priceChange") or {}
    liq = fnum((pair.get("liquidity") or {}).get("usd"), 0)
    lines = [
        f"🟢 <b>OPORTUNIDAD DE ENTRADA: {esc(sig['simbolo'])}</b> ({NETWORKS[sig['red']]['nombre']})",
        f"Tipo: {sig['tipo']} ({esc(sig['detalle'])}).",
        "",
        f"💵 Entrada: <b>{fmt_price(sig['entrada'])}</b> (no compres si ya pasó de {fmt_price(sig['entrada_max'])})",
        f"🛑 Stop (salir si baja a): <b>{fmt_price(sig['stop'])}</b> (-{sig['riesgo_pct']:.1f}%)",
        f"🎯 Objetivo 1: {fmt_price(sig['t1'])} (+{(sig['t1'] / sig['entrada'] - 1) * 100:.1f}%): vende la mitad",
        f"🎯 Objetivo 2: {fmt_price(sig['t2'])} (+{(sig['t2'] / sig['entrada'] - 1) * 100:.1f}%): vende el resto",
        "",
        f"📈 Subida: 1h {fnum(pc.get('h1'), 0):+.0f}% · 6h {fnum(pc.get('h6'), 0):+.0f}% · 24h {fnum(pc.get('h24'), 0):+.0f}%",
        f"💧 Liquidez {fmt_usd(liq)} · Seguridad: ✅ pasó la revisión",
    ]
    size = position_size(cfg, sig["riesgo_pct"])
    if size:
        if size["aviso"]:
            lines.append(f"⚠️ Con tu capital, la comisión de FOMO se come tu pérdida máxima "
                         f"({fmt_usd(size['perdida_max'])}). Mejor no entrar.")
        else:
            lines.append(f"💼 Monto sugerido: <b>${size['monto']:.0f}</b> (si toca el stop pierdes "
                         f"~${size['perdida_max']:.0f} con comisiones)")
    lines += [
        "",
        "Para buscarla en FOMO, copia la dirección:",
        f"<code>{esc(sig['token'])}</code>",
        f"Gráfico: {esc(sig['url'])}",
        "",
    ]
    if cfg.get("_telegram", True):
        lines.append(f"Si compras, avísame por Telegram: <code>/compre {esc(sig['simbolo'])} PRECIO</code>")
    lines += [
        "<i>Es una regla, no una garantía. Las memecoins pueden caer de golpe.</i>",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Seguimiento de señales y posiciones (avisos de salida)
# ----------------------------------------------------------------------------

def check_exits(http, state, cfg, send, now=None):
    now = now or now_ts()
    tracked = [s for s in state["senales"] if s.get("abierta")]
    if not tracked:
        return
    by_chain = {}
    for s in tracked:
        by_chain.setdefault(s["red"], []).append(s["token"])
    prices = {}
    for net_key, toks in by_chain.items():
        best = dex_pairs(http, NETWORKS[net_key]["dex"], toks)
        for k, p in best.items():
            prices[(net_key, k)] = p
    for s in tracked:
        pair = prices.get((s["red"], s["token"].lower()))
        comprada = s.get("comprada", False)
        sym = esc(s["simbolo"])

        def avisar(texto, comprada=comprada):
            if not comprada:
                texto += "\n<i>(Señal que te mandé. Si no la compraste, ignora este aviso.)</i>"
            send(texto)

        if not pair:
            continue
        price = fnum(pair.get("priceUsd"))
        if not price:
            continue
        s["ultimo_precio"] = price
        ref = s.get("precio_compra") or s["entrada"]
        res = (price / ref - 1) * 100
        pc = pair.get("priceChange") or {}
        tx1 = (pair.get("txns") or {}).get("h1") or {}
        if price <= s["stop"]:
            if s.get("t1_alcanzado"):
                avisar(f"🟡 <b>SALIR DE {sym}</b>: volvió a tu precio de entrada ({fmt_price(price)}). "
                     f"Vende lo que te queda: aseguras la ganancia de la primera mitad.")
            else:
                avisar(f"🔴 <b>SALIR DE {sym}</b>: tocó el stop ({fmt_price(price)}, {res:+.1f}%). "
                     f"Vende para no perder más. Así se protege tu dinero.")
            s["abierta"] = False
            s["cierre"] = "stop"
            continue
        if price >= s["t2"]:
            avisar(f"🏁 <b>{sym} llegó al objetivo 2</b> ({fmt_price(price)}, {res:+.1f}%). "
                 f"Vende lo que te queda y cobra la ganancia.")
            s["abierta"] = False
            s["cierre"] = "objetivo 2"
            continue
        if price >= s["t1"] and not s.get("t1_alcanzado"):
            s["t1_alcanzado"] = True
            s["stop"] = max(s["stop"], ref)
            avisar(f"🎯 <b>{sym} llegó al objetivo 1</b> ({fmt_price(price)}, {res:+.1f}%). "
                 f"Vende la mitad. Sube tu stop a tu precio de entrada ({fmt_price(s['stop'])}): "
                 f"desde ahora el resto no te puede hacer perder.")
            continue
        h1 = fnum(pc.get("h1"), 0)
        buys, sells = fnum(tx1.get("buys"), 0), fnum(tx1.get("sells"), 0)
        if h1 <= -10 and sells > buys and not s.get("aviso_debilidad"):
            s["aviso_debilidad"] = True
            avisar(f"⚠️ <b>{sym} se está debilitando</b>: {h1:+.0f}% en la última hora y hay más ventas "
                 f"que compras. Precio {fmt_price(price)} ({res:+.1f}%). Considera salir antes del stop.")
        if not comprada and now - s["creada"] > cfg["horas_validez_senal"] * 3600:
            s["abierta"] = False
            s["cierre"] = "vencida"


# ----------------------------------------------------------------------------
# Comandos de Telegram
# ----------------------------------------------------------------------------

HELP = (
    "🤖 <b>Comandos</b>\n"
    "<code>/compre SIMBOLO PRECIO</code>: me dices que compraste y vigilo cuándo salir\n"
    "<code>/vendi SIMBOLO</code>: dejo de vigilarla\n"
    "<code>/estado</code>: lo que estoy vigilando\n"
    "<code>/ayuda</code>: esta lista\n\n"
    "Reviso el mercado cada ~10 minutos y te escribo solo cuando hay algo."
)


def find_signal(state, sym):
    sym = sym.upper().lstrip("$")
    cands = [s for s in state["senales"] if s["simbolo"].upper() == sym or s["token"].lower() == sym.lower()]
    cands.sort(key=lambda s: s["creada"], reverse=True)
    return cands[0] if cands else None


def handle_commands(http, state, cfg, tg, send):
    updates = tg.get_updates(state.get("telegram_offset", 0))
    for u in updates:
        state["telegram_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not text:
            continue
        if not state.get("chat_id") and not tg.fixed_chat:
            state["chat_id"] = chat
            tg.chat_id = chat
            send("✅ ¡Listo! Ya estoy conectado contigo. Te avisaré de entradas y salidas.\n\n" + HELP)
            continue
        if str(chat) != str(tg.chat_id):
            continue  # ignora a cualquier otra persona
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        if cmd in ("/start", "/ayuda", "/help"):
            send(HELP)
        elif cmd in ("/compre", "/compré", "/compra"):
            if len(parts) < 2:
                send("Escríbelo así: <code>/compre SIMBOLO PRECIO</code>")
                continue
            s = find_signal(state, parts[1])
            precio = fnum(parts[2].replace(",", "").replace("$", "")) if len(parts) > 2 else None
            if not s:
                send(f"No tengo una señal de {esc(parts[1])}. Solo puedo vigilar monedas que yo te avisé.")
                continue
            s["comprada"] = True
            s["abierta"] = True
            if precio:
                riesgo = s["entrada"] - s["stop"] if not s.get("t1_alcanzado") else None
                s["precio_compra"] = precio
                if riesgo:
                    s["stop"] = precio - riesgo
                    s["t1"] = precio + cfg["objetivo_1_en_R"] * riesgo
                    s["t2"] = precio + cfg["objetivo_2_en_R"] * riesgo
            send(f"👍 Anotado: compraste {esc(s['simbolo'])}"
                 f"{' a ' + fmt_price(precio) if precio else ''}.\n"
                 f"🛑 Stop {fmt_price(s['stop'])} · 🎯 {fmt_price(s['t1'])} y {fmt_price(s['t2'])}\n"
                 f"Te aviso cuando toque salir.")
        elif cmd in ("/vendi", "/vendí", "/venta"):
            s = find_signal(state, parts[1]) if len(parts) > 1 else None
            if not s:
                send("Escríbelo así: <code>/vendi SIMBOLO</code>")
                continue
            s["abierta"] = False
            s["cierre"] = "vendida por ti"
            send(f"👌 Listo, dejo de vigilar {esc(s['simbolo'])}.")
        elif cmd == "/estado":
            abiertas = [s for s in state["senales"] if s.get("abierta")]
            if not abiertas:
                send("No estoy vigilando nada ahora. Te aviso cuando aparezca una oportunidad.")
                continue
            lines = ["📋 <b>Vigilando</b>"]
            for s in abiertas:
                ref = s.get("precio_compra") or s["entrada"]
                p = s.get("ultimo_precio")
                res = f" ({(p / ref - 1) * 100:+.1f}%)" if p else ""
                tag = "💼 comprada" if s.get("comprada") else "señal"
                lines.append(f"• {esc(s['simbolo'])} ({tag}): ahora {fmt_price(p)}{res} · "
                             f"stop {fmt_price(s['stop'])} · 🎯 {fmt_price(s['t1'])}")
            send("\n".join(lines))


class Telegram:
    def __init__(self, http, token, chat_id):
        self.http = http
        self.token = token
        self.chat_id = chat_id
        self.fixed_chat = bool(chat_id)
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        if not self.token or not self.chat_id:
            log("[telegram sin configurar]\n" + text)
            return
        self.http.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                       {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": True})

    def get_updates(self, offset):
        if not self.token:
            return []
        data = self.http.get(f"https://api.telegram.org/bot{self.token}/getUpdates?offset={offset}&timeout=0")
        return (data or {}).get("result") or []


# ----------------------------------------------------------------------------
# Escaneo del mercado
# ----------------------------------------------------------------------------

def scan(http, state, cfg, send, now=None):
    now = now or now_ts()
    recientes = {(s["red"], s["token"].lower()): s["creada"] for s in state["senales"]}
    candidatos = []
    for net_key in cfg["redes"]:
        net = NETWORKS[net_key]
        pools = gecko_trending(http, net["gecko"])
        log(f"{net['nombre']}: {len(pools)} monedas en tendencia")
        if not pools:
            continue
        pairs = dex_pairs(http, net["dex"], [p["token"] for p in pools])
        for p in pools:
            pair = pairs.get(p["token"].lower())
            if not pair:
                continue
            last = recientes.get((net_key, p["token"].lower()))
            if last and now - last < cfg["horas_sin_repetir_moneda"] * 3600:
                continue
            ok, score, why = prefilter(pair, cfg, now)
            if ok:
                candidatos.append({"red": net_key, "pool": p["pool"], "token": p["token"],
                                   "pair": pair, "score": score})
    candidatos.sort(key=lambda c: c["score"], reverse=True)
    log(f"{len(candidatos)} monedas pasaron el primer filtro")
    enviadas = 0
    revisadas = 0
    for c in candidatos:
        if enviadas >= cfg["max_alertas_por_vuelta"] or revisadas >= 6:
            break
        sym = (c["pair"].get("baseToken") or {}).get("symbol") or "?"
        ok, motivos, _ = goplus_check(http, c["red"], c["token"])
        if ok is not True:
            if ok is None and not cfg["exigir_revision_de_seguridad"]:
                pass
            else:
                log(f"  {sym}: descartada por seguridad: {', '.join(motivos)}")
                continue
        if c["red"] == "solana":
            graves = rugcheck(http, c["token"])
            if graves:
                log(f"  {sym}: descartada por RugCheck: {', '.join(graves)}")
                continue
        revisadas += 1
        pool = c["pair"].get("pairAddress") or c["pool"]
        candles = gecko_candles(http, NETWORKS[c["red"]]["gecko"], pool, now=now)
        setup, why = chart_setup(candles, cfg)
        if not setup:
            log(f"  {sym}: sin entrada: {why}")
            continue
        live = fnum(c["pair"].get("priceUsd")) or setup["entrada"]
        # Usa el precio de ahora si se movió poco desde el cierre de la vela.
        entrada = live if abs(live / setup["entrada"] - 1) < 0.03 else setup["entrada"]
        if entrada <= setup["stop"]:
            continue
        riesgo = entrada - setup["stop"]
        sig = {
            "red": c["red"], "token": c["token"], "pool": pool, "simbolo": sym,
            "url": c["pair"].get("url") or f"https://dexscreener.com/{NETWORKS[c['red']]['dex']}/{pool}",
            "tipo": setup["tipo"], "detalle": setup["detalle"],
            "entrada": entrada, "entrada_max": entrada + 0.25 * riesgo,
            "stop": setup["stop"], "riesgo_pct": riesgo / entrada * 100,
            "t1": entrada + cfg["objetivo_1_en_R"] * riesgo,
            "t2": entrada + cfg["objetivo_2_en_R"] * riesgo,
            "creada": now, "abierta": True, "comprada": False,
        }
        if sig["riesgo_pct"] > cfg["stop_maximo_pct"]:
            continue
        send(entry_message(sig, c["pair"], cfg))
        state["senales"].append(sig)
        enviadas += 1
    return enviadas


def prune(state, now=None):
    now = now or now_ts()
    keep = []
    for s in state["senales"]:
        if s.get("abierta") or now - s["creada"] < 7 * 86400:
            keep.append(s)
    state["senales"] = keep[-200:]


class WhatsApp:
    """Envía mensajes a tu propio WhatsApp con CallMeBot (gratis, uso personal).
    Solo envía: los comandos (/compre, /estado...) siguen siendo por Telegram."""

    def __init__(self, http, phone, apikey):
        self.http = http
        self.phone = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
        self.apikey = (apikey or "").strip()
        self.sent = []
        self.last = 0.0

    @property
    def ready(self):
        return bool(self.phone and self.apikey)

    @staticmethod
    def to_whatsapp(text):
        import re
        t = re.sub(r"</?b>", "*", text)
        t = re.sub(r"</?i>", "_", t)
        t = re.sub(r"</?code>", "", t)
        return t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    def send(self, text):
        if not self.ready:
            return
        msg = self.to_whatsapp(text)
        self.sent.append(msg)
        wait = 3 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        url = ("https://api.callmebot.com/whatsapp.php?phone=" + urllib.parse.quote(self.phone)
               + "&apikey=" + urllib.parse.quote(self.apikey) + "&text=" + urllib.parse.quote(msg))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
        except (urllib.error.URLError, OSError) as e:
            log(f"Error enviando a WhatsApp: {e}")
        self.last = time.time()


def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = load_config()
    state = load_json(STATE_PATH, {})
    state.setdefault("senales", [])
    http = Http()
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_env = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    tg = Telegram(http, token, chat_env or state.get("chat_id"))
    if chat_env:
        tg.fixed_chat = True

    wa = WhatsApp(http, os.environ.get("WHATSAPP_PHONE", ""), os.environ.get("CALLMEBOT_APIKEY", ""))
    cfg["_telegram"] = bool(token)

    def send(text):
        if tg.chat_id:
            tg.send(text)
        wa.send(text)

    handle_commands(http, state, cfg, tg, send)
    if "--prueba" in argv:
        send("🧪 Mensaje de prueba: el bot funciona y puede escribirte.")
    if not tg.chat_id and not wa.ready:
        log("Todavía no sé a quién escribir: abre tu bot en Telegram y mándale /start, "
            "o configura WhatsApp (WHATSAPP_PHONE y CALLMEBOT_APIKEY).")
        save_json(STATE_PATH, state)
        return 0
    check_exits(http, state, cfg, send)
    n = scan(http, state, cfg, send)
    prune(state)
    state["ultima_vuelta"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(STATE_PATH, state)
    log(f"Listo: {n} alerta(s) de entrada enviadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
