import os
import re
import time
import discord
from discord.ui import View, button
import requests

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

SOL_CA_REGEX = r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"
entry_mcs = {}

def get_token_data(ca: str):
    try:
        # Cache buster so we get fresher data
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}?t={int(time.time())}"
        
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
        
        r = requests.get(url, headers=headers, timeout=6)
        data = r.json()
        pairs = data.get("pairs")
        
        if not pairs:
            return None
            
        # Sort by highest liquidity
        pairs = sorted(
            pairs,
            key=lambda x: x.get("liquidity", {}).get("usd", 0),
            reverse=True
        )
        return pairs[0]
    except Exception as e:
        print(f"API Error: {e}")
        return None

def format_number(num):
    if not num:
        return "$0"
    if num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    if num >= 1_000:
        return f"${num/1_000:.1f}K"
    return f"${num:,.0f}"

def build_message(ca: str, token: dict, entry_mcap: float):
    base = token.get("baseToken", {})
    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "???")
    price = float(token.get("priceUsd") or 0)
    mcap = token.get("marketCap") or token.get("fdv") or 0
    liq = token.get("liquidity", {}).get("usd", 0)
    change = token.get("priceChange", {})
    h1 = change.get("h1", 0)
    h24 = change.get("h24", 0)

    if entry_mcap and entry_mcap > 0:
        multiplier = mcap / entry_mcap
        x_text = f"**{multiplier:.2f}x**"
    else:
        x_text = "—"

    h1_icon = "▲" if h1 >= 0 else "▼"
    h24_icon = "▲" if h24 >= 0 else "▼"

    text = (
        f"**{name} ({symbol}) | SOLANA**\n"
        f"┌─ Price: `${price:.8f}`\n"
        f"├─ MCap: **{format_number(mcap)}**\n"
        f"├─ Liquidity: {format_number(liq)}\n"
        f"├─ 1h: {h1_icon} {abs(h1)}% · 24h: {h24_icon} {abs(h24)}%\n"
        f"├─ From call: {x_text}\n"
        f"└─ CA: `{ca}`"
    )
    return text

class TokenView(View):
    def __init__(self, ca: str, entry_mcap: float):
        super().__init__(timeout=None)
        self.ca = ca
        self.entry_mcap = entry_mcap

    @button(label="🔄 Refresh", style=discord.ButtonStyle.blurple)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        token = get_token_data(self.ca)
        if not token:
            await interaction.followup.send("❌ Failed to fetch data", ephemeral=True)
            return

        new_text = build_message(self.ca, token, self.entry_mcap)
        await interaction.message.edit(content=new_text, view=self)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    match = re.search(SOL_CA_REGEX, message.content)
    if not match:
        return

    ca = match.group(0)
    token = get_token_data(ca)
    if not token:
        return

    mcap = token.get("marketCap") or token.get("fdv") or 0

    if ca not in entry_mcs:
        entry_mcs[ca] = mcap

    entry_mcap = entry_mcs[ca]
    text = build_message(ca, token, entry_mcap)
    view = TokenView(ca, entry_mcap)

    await message.channel.send(text, view=view)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found!")
else:
    client.run(TOKEN)
