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

SOL_CA_REGEX = r"\b([1-9A-HJ-NP-Za-km-z]{32,44})\b"
MC_REGEX = r"(\d+(?:\.\d+)?)\s*[kKmM]?"

calls = {}
user_stats = defaultdict(list)

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

def parse_mc(text: str):
    """Extract MC number from text like 22.5k, 55k, 120000, 1.2m"""
    match = re.search(MC_REGEX, text, re.IGNORECASE)
    if not match:
        return None

    num = float(match.group(1))
    full = match.group(0).lower()

    if "m" in full:
        num *= 1_000_000
    elif "k" in full:
        num *= 1_000

    return num

def get_token_data(ca: str):
    try:
        # Try DexPaprika first
        r = session.get(f"https://api.dexpaprika.com/networks/solana/tokens/{ca}", timeout=4)
        if r.status_code == 200:
            data = r.json()
            if data.get("price_usd"):
                return {
                    "name": data.get("name") or data.get("symbol") or "Unknown",
                    "symbol": data.get("symbol") or "???",
                    "price": float(data.get("price_usd") or 0),
                    "mcap": float(data.get("market_cap") or data.get("fdv") or 0),
                    "liq": float(data.get("liquidity_usd") or 0),
                    "vol": float(data.get("volume_24h") or 0),
                    "h1": float(data.get("price_change_1h") or 0),
                    "h24": float(data.get("price_change_24h") or 0),
                }

        # Fallback DexScreener
        r = session.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}?t={int(time.time())}", timeout=4)
        pairs = r.json().get("pairs")
        if not pairs:
            return None
        pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        return {
            "name": pair["baseToken"].get("name", "Unknown"),
            "symbol": pair["baseToken"].get("symbol", "???"),
            "price": float(pair.get("priceUsd") or 0),
            "mcap": float(pair.get("marketCap") or pair.get("fdv") or 0),
            "liq": float(pair.get("liquidity", {}).get("usd", 0)),
            "vol": float(pair.get("volume", {}).get("h24", 0)),
            "h1": float(pair.get("priceChange", {}).get("h1", 0)),
            "h24": float(pair.get("priceChange", {}).get("h24", 0)),
        }
    except Exception as e:
        print("API Error:", e)
        return None

def format_mc(num):
    if not num:
        return "$0"
    if num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    if num >= 1_000:
        return f"${num/1_000:.1f}K"
    return f"${num:,.0f}"

def build_message(ca, token, call_data):
    current_x = token["mcap"] / call_data["entry"] if call_data["entry"] else 0
    ath_x = call_data["ath"] / call_data["entry"] if call_data["entry"] else 0

    h1_icon = "▲" if token["h1"] >= 0 else "▼"
    h24_icon = "▲" if token["h24"] >= 0 else "▼"

    return (
        f"**{token['name']} ({token['symbol']}) | SOLANA**\n"
        f"```\n"
        f"Price: ${token['price']:.8f}\n"
        f"MCap:  {format_mc(token['mcap'])}  →  ATH: {format_mc(call_data['ath'])}\n"
        f"Liq:   {format_mc(token['liq'])}\n"
        f"Vol24: {format_mc(token['vol'])}\n"
        f"1h: {h1_icon} {abs(token['h1']):.1f}%   24h: {h24_icon} {abs(token['h24']):.1f}%\n"
        f"```\n"
        f"From call: **{current_x:.2f}x**  |  ATH: **{ath_x:.2f}x**\n"
        f"Called by **{call_data['caller_name']}** @ **{format_mc(call_data['entry'])}**\n"
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
            await interaction.followup.send("Call data lost (bot restarted)", ephemeral=True)
            return

        token = get_token_data(self.ca)
        if not token:
            await interaction.followup.send("Failed to fetch data", ephemeral=True)
            return

        # Update ATH
        if token["mcap"] > calls[self.ca]["ath"]:
            calls[self.ca]["ath"] = token["mcap"]
            for call in user_stats[calls[self.ca]["caller_id"]]:
                if call["ca"] == self.ca:
                    call["ath"] = token["mcap"]
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

    # .stats command
    if message.content.lower().strip() == ".stats":
        stats = user_stats.get(message.author.id, [])
        if not stats:
            await message.reply("You have no calls yet.")
            return

        total = len(stats)
        hit_2x = sum(1 for c in stats if c["ath"] / c["entry"] >= 2)
        percent = (hit_2x / total * 100) if total else 0
        biggest = max((c["ath"] / c["entry"] for c in stats), default=0)

        text = (
            f"**Stats for {message.author.display_name}**\n"
            f"```\n"
            f"Total calls:     {total}\n"
            f"Hit 2x+:         {hit_2x} ({percent:.1f}%)\n"
            f"Biggest multi:   {biggest:.2f}x\n"
            f"```"
        )
        await message.reply(text)
        return

    # Detect CA
    ca_match = re.search(SOL_CA_REGEX, message.content)
    if not ca_match:
        return

    ca = ca_match.group(1)
    token = get_token_data(ca)
    if not token:
        return

    # Try to get MC from the message (user typed it)
    user_mc = parse_mc(message.content)

    # If user typed a MC → use it as entry, otherwise use API
    entry_mcap = user_mc if user_mc and user_mc > 0 else token["mcap"]

    if ca not in calls:
        calls[ca] = {
            "entry": entry_mcap,
            "ath": max(entry_mcap, token["mcap"]),
            "caller_id": message.author.id,
            "caller_name": message.author.display_name
        }
        user_stats[message.author.id].append({
            "ca": ca,
            "entry": entry_mcap,
            "ath": max(entry_mcap, token["mcap"])
        })

    text = build_message(ca, token, calls[ca])
    await message.channel.send(text, view=TokenView(ca))

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
