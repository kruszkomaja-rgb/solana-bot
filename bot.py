import os
import re
import time
import discord
from discord.ui import View, button
import requests
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

SOL_CA_REGEX = r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"

calls = {}
user_stats = defaultdict(list)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})

def get_token_data(ca: str):
    try:
        # DexPaprika - usually faster/fresher
        url = f"https://api.dexpaprika.com/networks/solana/tokens/{ca}"
        r = session.get(url, timeout=4)
        if r.status_code != 200:
            return None
        data = r.json()

        # Fallback to DexScreener if DexPaprika fails
        if not data or "price_usd" not in data:
            url2 = f"https://api.dexscreener.com/latest/dex/tokens/{ca}?t={int(time.time())}"
            r2 = session.get(url2, timeout=4)
            pairs = r2.json().get("pairs")
            if not pairs:
                return None
            pair = sorted(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0), reverse=True)[0]
            return {
                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                "price": float(pair.get("priceUsd") or 0),
                "mcap": pair.get("marketCap") or pair.get("fdv") or 0,
                "liq": pair.get("liquidity", {}).get("usd", 0),
                "vol": pair.get("volume", {}).get("h24", 0),
                "h1": pair.get("priceChange", {}).get("h1", 0),
                "h24": pair.get("priceChange", {}).get("h24", 0),
            }

        return {
            "name": data.get("name") or data.get("symbol") or "Unknown",
            "symbol": data.get("symbol") or "???",
            "price": float(data.get("price_usd") or 0),
            "mcap": data.get("market_cap") or data.get("fdv") or 0,
            "liq": data.get("liquidity_usd") or 0,
            "vol": data.get("volume_24h") or 0,
            "h1": data.get("price_change_1h") or 0,
            "h24": data.get("price_change_24h") or 0,
        }
    except Exception as e:
        print(f"API Error: {e}")
        return None

def format_mc(num):
    if not num:
        return "$0"
    if num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    if num >= 1_000:
        return f"${num/1_000:.1f}K"
    return f"${num:,.0f}"

def build_message(ca: str, token: dict, call_data: dict):
    name = token["name"]
    symbol = token["symbol"]
    price = token["price"]
    mcap = token["mcap"]
    liq = token["liq"]
    vol = token["vol"]
    h1 = token["h1"]
    h24 = token["h24"]

    entry = call_data["entry"]
    ath = call_data["ath"]
    caller = call_data["caller_name"]

    current_x = mcap / entry if entry > 0 else 0
    ath_x = ath / entry if entry > 0 else 0

    h1_icon = "▲" if h1 >= 0 else "▼"
    h24_icon = "▲" if h24 >= 0 else "▼"

    return (
        f"**{name} ({symbol}) | SOLANA**\n"
        f"```\n"
        f"Price: ${price:.8f}\n"
        f"MCap:  {format_mc(mcap)}  →  ATH: {format_mc(ath)}\n"
        f"Liq:   {format_mc(liq)}\n"
        f"Vol24: {format_mc(vol)}\n"
        f"1h: {h1_icon} {abs(h1):.1f}%   24h: {h24_icon} {abs(h24):.1f}%\n"
        f"```\n"
        f"From call: **{current_x:.2f}x**  |  ATH: **{ath_x:.2f}x**\n"
        f"Called by **{caller}** @ {format_mc(entry)}\n"
        f"`{ca}`"
    )

class TokenView(View):
    def __init__(self, ca: str):
        super().__init__(timeout=None)
        self.ca = ca

    @button(label="Refresh", style=discord.ButtonStyle.blurple)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if self.ca not in calls:
            await interaction.followup.send("Data lost (bot restarted)", ephemeral=True)
            return

        token = get_token_data(self.ca)
        if not token:
            await interaction.followup.send("Failed to fetch", ephemeral=True)
            return

        mcap = token["mcap"]
        if mcap > calls[self.ca]["ath"]:
            calls[self.ca]["ath"] = mcap
            caller_id = calls[self.ca]["caller_id"]
            for call in user_stats[caller_id]:
                if call["ca"] == self.ca:
                    call["ath"] = mcap
                    break

        text = build_message(self.ca, token, calls[self.ca])
        await interaction.message.edit(content=text, view=self)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.lower() == ".stats":
        stats = user_stats.get(message.author.id, [])
        if not stats:
            await message.channel.send("You have no calls yet.")
            return

        total = len(stats)
        hit_2x = sum(1 for c in stats if c["ath"] / c["entry"] >= 2)
        percent = (hit_2x / total) * 100 if total else 0
        biggest = max((c["ath"] / c["entry"] for c in stats), default=0)

        text = (
            f"**Stats for {message.author.display_name}**\n"
            f"```\n"
            f"Total calls:     {total}\n"
            f"Hit 2x+:         {hit_2x} ({percent:.1f}%)\n"
            f"Biggest multi:   {biggest:.2f}x\n"
            f"```"
        )
        await message.channel.send(text)
        return

    match = re.search(SOL_CA_REGEX, message.content)
    if not match:
        return

    ca = match.group(0)
    token = get_token_data(ca)
    if not token or token["mcap"] <= 0:
        return

    mcap = token["mcap"]

    if ca not in calls:
        calls[ca] = {
            "entry": mcap,
            "ath": mcap,
            "caller_id": message.author.id,
            "caller_name": message.author.display_name
        }
        user_stats[message.author.id].append({
            "ca": ca,
            "entry": mcap,
            "ath": mcap
        })

    text = build_message(ca, token, calls[ca])
    await message.channel.send(text, view=TokenView(ca))

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
