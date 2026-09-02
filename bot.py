import os
import re
import discord
from discord.ui import Modal, TextInput, View, button
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

user_calls = defaultdict(dict)  # {user_id: {ca: data}}

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

class NewCallModal(Modal, title="New Call"):
    ca = TextInput(label="Contract Address", placeholder="Paste CA here...", required=True, max_length=50)
    call_mc = TextInput(label="Call Market Cap", placeholder="e.g. 25k or 25000", required=True, max_length=20)
    target = TextInput(label="Target (MC or x)", placeholder="e.g. 100k or 4x", required=True, max_length=20)

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

        user_calls[interaction.user.id][ca] = {
            "call_mc": call_mc,
            "target_mc": target_mc,
            "target_x": target_x,
            "ath": None,
            "hit": False
        }

        embed = discord.Embed(
            title="Call Opened",
            color=0x57F287,
            description=f"**CA**\n`{ca}`"
        )
        embed.add_field(name="Called at", value=format_mc(call_mc), inline=True)
        embed.add_field(name="Target", value=f"{format_mc(target_mc)} ({target_x:.2f}x)", inline=True)
        embed.add_field(name="Status", value="Open", inline=True)
        embed.set_footer(text=f"Called by {interaction.user.display_name}")

        view = ATHView(ca, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

class ATHModal(Modal, title="Add ATH"):
    def __init__(self, ca: str, user_id: int):
        super().__init__()
        self.ca = ca
        self.user_id = user_id
        self.ath_input = TextInput(label="ATH Market Cap", placeholder="e.g. 87k", required=True, max_length=20)
        self.add_item(self.ath_input)

    async def on_submit(self, interaction: discord.Interaction):
        ath = parse_number(self.ath_input.value)
        if not ath:
            await interaction.response.send_message("Invalid ATH", ephemeral=True)
            return

        calls = user_calls[self.user_id]
        if self.ca not in calls or calls[self.ca]["ath"] is not None:
            await interaction.response.send_message("This call is already closed or doesn't exist.", ephemeral=True)
            return

        data = calls[self.ca]
        data["ath"] = ath
        data["hit"] = ath >= data["target_mc"]
        multi = ath / data["call_mc"]

        color = 0x57F287 if data["hit"] else 0xED4245
        result = "TARGET HIT" if data["hit"] else "MISSED"

        embed = discord.Embed(
            title="Call Closed",
            color=color,
            description=f"**CA**\n`{self.ca}`"
        )
        embed.add_field(name="Called at", value=format_mc(data["call_mc"]), inline=True)
        embed.add_field(name="ATH", value=f"{format_mc(ath)} ({multi:.2f}x)", inline=True)
        embed.add_field(name="Target", value=format_mc(data["target_mc"]), inline=True)
        embed.add_field(name="Result", value=f"**{result}**", inline=False)
        embed.set_footer(text=f"Called by {interaction.user.display_name}")

        await interaction.response.edit_message(embed=embed, view=None)

class ATHView(View):
    def __init__(self, ca: str, user_id: int):
        super().__init__(timeout=None)
        self.ca = ca
        self.user_id = user_id

    @button(label="Add ATH", style=discord.ButtonStyle.blurple)
    async def add_ath(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your call.", ephemeral=True)
            return
        await interaction.response.send_modal(ATHModal(self.ca, self.user_id))

class MainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="New Call", style=discord.ButtonStyle.green, emoji="📞")
    async def new_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NewCallModal())

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower().strip()

    if content == ".call":
        embed = discord.Embed(
            title="Call Tracker",
            description="Click the button below to open a new call.",
            color=0x5865F2
        )
        await message.channel.send(embed=embed, view=MainView())
        return

    if content == ".stats":
        calls = user_calls.get(message.author.id, {})
        closed = [c for c in calls.values() if c["ath"] is not None]

        if not closed:
            await message.reply("You have no closed calls yet.")
            return

        total = len(closed)
        hits = sum(1 for c in closed if c["hit"])
        misses = total - hits
        accuracy = (hits / total * 100) if total else 0
        biggest = max((c["ath"] / c["call_mc"] for c in closed), default=0)
        avg_multi = sum(c["ath"] / c["call_mc"] for c in closed) / total

        embed = discord.Embed(
            title=f"Stats — {message.author.display_name}",
            color=0x5865F2
        )
        embed.add_field(name="Total Closed", value=str(total), inline=True)
        embed.add_field(name="Good Calls", value=f"{hits}", inline=True)
        embed.add_field(name="Bad Calls", value=f"{misses}", inline=True)
        embed.add_field(name="Accuracy", value=f"**{accuracy:.1f}%**", inline=True)
        embed.add_field(name="Biggest Multi", value=f"**{biggest:.2f}x**", inline=True)
        embed.add_field(name="Average Multi", value=f"{avg_multi:.2f}x", inline=True)

        await message.reply(embed=embed)
        return

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
