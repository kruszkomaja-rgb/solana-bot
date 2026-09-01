import os
import re
import discord
from discord.ui import Button, View, button
import requests
from datetime import datetime

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

SOL_CA_REGEX = r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"

# Stores entry Market Cap for each CA  →  { "contract": entry_mcap }
entry_mcs = {}

def get_token_data(ca: str):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", timeout=6)
        data = r.json()
        pairs = data.get("pairs")
        if not pairs:
            return None
        pairs = sorted(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0), reverse=True)
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

class TokenView(View):
    def __init__(self, ca: str, entry_mcap: float):
        super().__init__(timeout=None)
        self.ca = ca
        self.entry_mcap = entry_mcap

        # Link buttons
        self.add_item(Button(label="Chart", url=f"https://dexscreener.com/solana/{ca}", style=discord.ButtonStyle.link))
        self.add_item(Button(label="GMGN", url=f"https://gmgn.ai/solana/token/{ca}", style=discord.ButtonStyle.link))
        self.add_item(Button(label="Solscan", url=f"https://solscan.io/token/{ca}", style=discord.ButtonStyle.link))

    @button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()

        token = get_token_data(self.ca)
        if not token:
            await interaction.followup.send("Could not fetch data.", ephemeral=True)
            return

        base = token.get("baseToken", {})
        name = base.get("name", "Unknown")
        symbol = base.get("symbol", "???")
        price = float(token.get("priceUsd") or 0)
        mcap = token.get("marketCap") or token.get("fdv") or 0
        liq = token.get("liquidity", {}).get("usd", 0)
        change = token.get("priceChange", {})
        h1 = change.get("h1", 0)
        h24 = change.get("h24", 0)

        # Calculate x multiplier
        if self.entry_mcap and self.entry_mcap > 0:
            multiplier = mcap / self.entry_mcap
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
            f"└─ CA: `{self.ca}`"
        )

        await interaction.message.edit(content=text, view=self)

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

    base = token.get("baseToken", {})
    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "???")
    price = float(token.get("priceUsd") or 0)
    mcap = token.get("marketCap") or token.get("fdv") or 0
    liq = token.get("liquidity", {}).get("usd", 0)
    change = token.get("priceChange", {})
    h1 = change.get("h1", 0)
    h24 = change.get("h24", 0)

    # Save entry MC the first time we see this CA
    if ca not in entry_mcs:
        entry_mcs[ca] = mcap

    entry_mcap = entry_mcs[ca]

    # Calculate current x
    if entry_mcap > 0:
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

    view = TokenView(ca, entry_mcap)
    await message.channel.send(text, view=view)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found!")
else:
    client.run(TOKEN)
