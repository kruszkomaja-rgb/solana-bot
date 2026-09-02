import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ui import Modal, TextInput, View, button
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

RESULTS_CHANNEL_ID = 1544498477701005332
TRADE_CHANNEL_ID = 1544519128369471508

BANNER_URL = "https://i.imgur.com/bt1F4J8.png"
ICON_URL = "https://i.imgur.com/YvPJYPP.png"

user_calls = defaultdict(dict)
user_trades = defaultdict(dict)

call_counter = 0
trade_counter = 0

def parse_number(text: str):
    if not text:
        return None
    text = text.lower().replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([km])?", text)
    if not match:
        return None
    num = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        num *= 1000
    elif suffix == "m":
        num *= 1_000_000
    return num

def format_mc(num):
    if num is None:
        return "—"
    if num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    if num >= 1_000:
        return f"${num/1_000:.1f}K"
    return f"${num:,.0f}"

def get_stats_embed(user_name: str, user_id: int, data_dict: dict, title_prefix: str, footer_text: str):
    records = data_dict.get(user_id, {})
    closed = [c for c in records.values() if c["ath"] is not None]

    if not closed:
        return None

    total = len(closed)
    hits = sum(1 for c in closed if c["hit"])
    misses = total - hits
    accuracy = (hits / total * 100) if total else 0
    biggest = max((c["target_x"] for c in closed), default=0)
    avg_multi = sum(c["target_x"] for c in closed) / total

    embed = discord.Embed(
        title=f"{title_prefix} — {user_name}",
        color=0xFFFFFF
    )
    embed.add_field(name="Closed", value=str(total), inline=True)
    embed.add_field(name="Hits", value=str(hits), inline=True)
    embed.add_field(name="Misses", value=str(misses), inline=True)
    embed.add_field(name="Accuracy", value=f"**{accuracy:.1f}%**", inline=True)
    embed.add_field(name="Best Multi", value=f"**{biggest:.2f}x**", inline=True)
    embed.add_field(name="Avg Multi", value=f"{avg_multi:.2f}x", inline=True)
    embed.set_footer(text=footer_text)
    return embed

def get_aggregate_stats_embed(data_dict: dict, title: str, footer_text: str):
    total_closed = 0
    total_hits = 0
    total_misses = 0

    for user_id, records in data_dict.items():
        closed = [c for c in records.values() if c["ath"] is not None]
        total_closed += len(closed)
        total_hits += sum(1 for c in closed if c["hit"])
        total_misses += sum(1 for c in closed if not c["hit"])

    accuracy = (total_hits / total_closed * 100) if total_closed > 0 else 0

    embed = discord.Embed(
        title=title,
        color=0xFFFFFF,
        description="Daily performance summary across all users."
    )
    embed.add_field(name="Total Closed", value=str(total_closed), inline=True)
    embed.add_field(name="Good Calls (Hits)", value=str(total_hits), inline=True)
    embed.add_field(name="Bad Calls (Misses)", value=str(total_misses), inline=True)
    embed.add_field(name="Accuracy", value=f"**{accuracy:.1f}%**", inline=True)
    embed.set_footer(text=footer_text)
    return embed

class NewCallModal(Modal, title="New Call"):
    ca = TextInput(label="Contract Address (CA)", placeholder="Paste CA here...", required=True, max_length=50)
    call_mc = TextInput(label="Call MC", placeholder="e.g. 25k", required=True, max_length=20)
    target = TextInput(label="Target (MC or x)", placeholder="e.g. 100k or 4x", required=True, max_length=20)

    def __init__(self, target_user_id: int):
        super().__init__()
        self.target_user_id = target_user_id

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        call_mc = parse_number(self.call_mc.value)
        target_raw = self.target.value.strip().lower()

        if not call_mc:
            await interaction.response.send_message("Invalid Call MC", ephemeral=True)
            return

        if "x" in target_raw:
            try:
                target_x = float(re.search(r"([\d.]+)", target_raw).group(1))
                target_mc = call_mc * target_x
            except:
                await interaction.response.send_message("Invalid Target", ephemeral=True)
                return
        else:
            target_mc = parse_number(target_raw)
            if not target_mc:
                await interaction.response.send_message("Invalid Target", ephemeral=True)
                return
            target_x = target_mc / call_mc

        user_calls[self.target_user_id][ca] = {
            "call_mc": call_mc,
            "target_mc": target_mc,
            "target_x": target_x,
            "ath": None,
            "hit": False,
            "caller": interaction.user.display_name
        }

        embed = discord.Embed(
            title="Call Opened",
            description=f"**CA:** `{ca}`\n**Entry:** {format_mc(call_mc)}\n**Target:** {format_mc(target_mc)} ({target_x:.2f}x)",
            color=0xFFFFFF
        )
        embed.set_footer(text="Click the button below when ready")

        view = ATHView(ca, self.target_user_id, is_trade=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class NewTradeModal(Modal, title="New Trade"):
    ca = TextInput(label="Contract Address (CA)", placeholder="Paste CA here...", required=True, max_length=50)
    call_mc = TextInput(label="Trade MC", placeholder="e.g. 25k", required=True, max_length=20)
    target = TextInput(label="Target (MC or x)", placeholder="e.g. 100k or 4x", required=True, max_length=20)
    sol_amount = TextInput(label="SOL Invested", placeholder="e.g. 0.1", required=True, max_length=20)

    def __init__(self, target_user_id: int):
        super().__init__()
        self.target_user_id = target_user_id

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        call_mc = parse_number(self.call_mc.value)
        target_raw = self.target.value.strip().lower()
        sol_raw = self.sol_amount.value.strip().replace(",", "")

        if not call_mc:
            await interaction.response.send_message("Invalid Trade MC", ephemeral=True)
            return

        try:
            sol_invested = float(sol_raw)
        except ValueError:
            await interaction.response.send_message("Invalid SOL Amount", ephemeral=True)
            return

        if "x" in target_raw:
            try:
                target_x = float(re.search(r"([\d.]+)", target_raw).group(1))
                target_mc = call_mc * target_x
            except:
                await interaction.response.send_message("Invalid Target", ephemeral=True)
                return
        else:
            target_mc = parse_number(target_raw)
            if not target_mc:
                await interaction.response.send_message("Invalid Target", ephemeral=True)
                return
            target_x = target_mc / call_mc

        user_trades[self.target_user_id][ca] = {
            "call_mc": call_mc,
            "target_mc": target_mc,
            "target_x": target_x,
            "sol_invested": sol_invested,
            "ath": None,
            "hit": False,
            "caller": interaction.user.display_name
        }

        embed = discord.Embed(
            title="Trade Opened",
            description=f"**CA:** `{ca}`\n**Entry:** {format_mc(call_mc)}\n**Target:** {format_mc(target_mc)} ({target_x:.2f}x)\n**Invested:** {sol_invested} SOL",
            color=0xFFFFFF
        )
        embed.set_footer(text="Click the button below when ready")

        view = ATHView(ca, self.target_user_id, is_trade=True)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ATHModal(Modal, title="Add ATH"):
    def __init__(self, ca: str, user_id: int, is_trade: bool):
        super().__init__()
        self.ca = ca
        self.user_id = user_id
        self.is_trade = is_trade
        self.ath_input = TextInput(label="ATH Market Cap", placeholder="e.g. 87k", required=True, max_length=20)
        self.add_item(self.ath_input)

    async def on_submit(self, interaction: discord.Interaction):
        global call_counter, trade_counter
        ath = parse_number(self.ath_input.value)
        if not ath:
            await interaction.response.send_message("Invalid ATH", ephemeral=True)
            return

        data_dict = user_trades if self.is_trade else user_calls
        calls = data_dict[self.user_id]
        if self.ca not in calls or calls[self.ca]["ath"] is not None:
            await interaction.response.send_message("This record is already closed.", ephemeral=True)
            return

        data = calls[self.ca]
        data["ath"] = ath
        data["hit"] = ath >= data["target_mc"]
        multi = data["target_x"]

        color = 0x00C853 if data["hit"] else 0xD32F2F
        result = "TARGET HIT" if data["hit"] else "MISSED"

        if self.is_trade:
            trade_counter += 1
            num_str = f"trade #{trade_counter:03d}"
            channel_id = TRADE_CHANNEL_ID
            title_text = "TRADE RESULT"
            
            sol_inv = data["sol_invested"]
            sol_return = sol_inv * multi if data["hit"] else 0.0
            profit_loss = sol_return - sol_inv
        else:
            call_counter += 1
            num_str = f"call #{call_counter:03d}"
            channel_id = RESULTS_CHANNEL_ID
            title_text = "CALL RESULT"

        embed = discord.Embed(title=title_text, color=color)
        embed.add_field(name="Contract", value=f"`{self.ca}`", inline=False)
        embed.add_field(name="Entry", value=format_mc(data["call_mc"]), inline=True)
        embed.add_field(name="ATH", value=format_mc(ath), inline=True)
        embed.add_field(name="Multiple", value=f"**{multi:.2f}x**", inline=True)
        embed.add_field(name="Target", value=format_mc(data["target_mc"]), inline=True)
        
        if self.is_trade:
            embed.add_field(name="Invested", value=f"{sol_inv:.4f} SOL", inline=True)
            embed.add_field(name="Return", value=f"{sol_return:.4f} SOL", inline=True)
            embed.add_field(name="P/L", value=f"{'+' if profit_loss >= 0 else ''}{profit_loss:.4f} SOL", inline=True)

        embed.add_field(name="Result", value=f"**{result}**", inline=True)
        embed.set_footer(text=f"{num_str} • Called by {data['caller']}")

        target_channel = client.get_channel(channel_id)
        if target_channel:
            await target_channel.send(embed=embed)

        await interaction.response.edit_message(
            content="Result sent to the channel.",
            embed=None,
            view=None
        )

class ATHView(View):
    def __init__(self, ca: str, user_id: int, is_trade: bool):
        super().__init__(timeout=None)
        self.ca = ca
        self.user_id = user_id
        self.is_trade = is_trade

    @button(label="Add ATH", style=discord.ButtonStyle.blurple)
    async def add_ath(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the owner can add ATH.", ephemeral=True)
            return
        await interaction.response.send_modal(ATHModal(self.ca, self.user_id, self.is_trade))

class CallView(View):
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @button(label="Call", style=discord.ButtonStyle.secondary, emoji="💸")
    async def make_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can make calls here.", ephemeral=True)
            return
        await interaction.response.send_modal(NewCallModal(self.target_user_id))

    @button(label="Stats", style=discord.ButtonStyle.primary, emoji="📊")
    async def view_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can check stats here.", ephemeral=True)
            return

        embed = get_stats_embed(interaction.user.display_name, self.target_user_id, user_calls, "STATS", "Mego Calls")
        if not embed:
            await interaction.response.send_message("You have no closed calls yet.", ephemeral=True)
            return

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("Sent your stats to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Could not send DM. Please enable direct messages from server members.", ephemeral=True)

    @button(label="Trade", style=discord.ButtonStyle.success, emoji="📈")
    async def make_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can make trades here.", ephemeral=True)
            return
        await interaction.response.send_modal(NewTradeModal(self.target_user_id))

    @button(label="TrdStats", style=discord.ButtonStyle.primary, emoji="📉")
    async def view_trdstats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can check trade stats here.", ephemeral=True)
            return

        embed = get_stats_embed(interaction.user.display_name, self.target_user_id, user_trades, "TRADE STATS", "Mego Trades")
        if not embed:
            await interaction.response.send_message("You have no closed trades yet.", ephemeral=True)
            return

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("Sent your trade stats to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Could not send DM. Please enable direct messages from server members.", ephemeral=True)

    @button(label="PNL", style=discord.ButtonStyle.green, emoji="📊")
    async def pnl_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can check PNL here.", ephemeral=True)
            return
        
        user_c = user_calls.get(self.target_user_id, {})
        user_t = user_trades.get(self.target_user_id, {})
        
        closed_calls = [c for c in user_c.values() if c["ath"] is not None]
        closed_trades = [t for t in user_t.values() if t["ath"] is not None]

        if not closed_calls and not closed_trades:
            await interaction.response.send_message("You have no closed calls or trades of all time to generate PNL from.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"All-Time PNL Report — {interaction.user.display_name}",
            color=0xFFFFFF,
            description="Here is your complete all-time PNL summary from all closed calls and trades."
        )

        if closed_calls:
            total_calls = len(closed_calls)
            hits_calls = sum(1 for c in closed_calls if c["hit"])
            misses_calls = total_calls - hits_calls
            accuracy_calls = (hits_calls / total_calls * 100) if total_calls else 0
            best_call_multi = max((c["target_x"] for c in closed_calls), default=0)

            embed.add_field(
                name="📈 All-Time Calls",
                value=(
                    f"• Total Closed: **{total_calls}**\n"
                    f"• Hits: **{hits_calls}** | Misses: **{misses_calls}**\n"
                    f"• Accuracy: **{accuracy_calls:.1f}%**\n"
                    f"• Best Multiplier: **{best_call_multi:.2f}x**"
                ),
                inline=False
            )

        if closed_trades:
            total_trades = len(closed_trades)
            hits_trades = sum(1 for t in closed_trades if t["hit"])
            misses_trades = total_trades - hits_trades
            accuracy_trades = (hits_trades / total_trades * 100) if total_trades else 0
            
            total_invested = sum(t["sol_invested"] for t in closed_trades)
            total_returned = sum(t["sol_invested"] * t["target_x"] if t["hit"] else 0.0 for t in closed_trades)
            net_pnl = total_returned - total_invested

            embed.add_field(
                name="📉 All-Time Trades",
                value=(
                    f"• Total Closed: **{total_trades}**\n"
                    f"• Hits: **{hits_trades}** | Misses: **{misses_trades}**\n"
                    f"• Accuracy: **{accuracy_trades:.1f}%**\n"
                    f"• Total Invested: **{total_invested:.4f} SOL**\n"
                    f"• Total Returned: **{total_returned:.4f} SOL**\n"
                    f"• Net P/L: **{'+' if net_pnl >= 0 else ''}{net_pnl:.4f} SOL**"
                ),
                inline=False
            )

        embed.set_footer(text="Mego PNL • All-Time Report")

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("Sent your all-time PNL report to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Could not send DM. Please enable direct messages from server members.", ephemeral=True)

async def daily_stats_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(timezone.utc)
        target = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        results_channel = client.get_channel(RESULTS_CHANNEL_ID)
        if results_channel:
            embed = get_aggregate_stats_embed(user_calls, "DAILY CALLS STATS (24H)", "Mego Calls • Daily Update")
            await results_channel.send(embed=embed)

        trade_channel = client.get_channel(TRADE_CHANNEL_ID)
        if trade_channel:
            embed = get_aggregate_stats_embed(user_trades, "DAILY TRADES STATS (24H)", "Mego Trades • Daily Update")
            await trade_channel.send(embed=embed)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    client.loop.create_task(daily_stats_loop())

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower().strip()

    if content.startswith(".call"):
        parts = message.content.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.reply("Usage: `.call USER_ID`")
            return

        target_id = int(parts[1])

        embed = discord.Embed(
            color=0xFFFFFF,
            description="**Only the owner of this call panel can make calls here.**"
        )
        embed.set_image(url=BANNER_URL)
        embed.set_thumbnail(url=ICON_URL)
        embed.set_footer(text="Mego Calls • Restricted Access")

        await message.channel.send(embed=embed, view=CallView(target_id))

        try:
            await message.delete()
        except:
            pass
        return

    if content == ".stats":
        embed = get_stats_embed(message.author.display_name, message.author.id, user_calls, "STATS", "Mego Calls")
        if not embed:
            await message.reply("You have no closed calls yet.")
            return
        await message.reply(embed=embed)
        return

    if content == ".trdstats":
        embed = get_stats_embed(message.author.display_name, message.author.id, user_trades, "TRADE STATS", "Mego Trades")
        if not embed:
            await message.reply("You have no closed trades yet.")
            return
        await message.reply(embed=embed)
        return

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
