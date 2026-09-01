import os
import re
import discord
from discord.ui import Modal, TextInput, View, button
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Storage
user_calls = defaultdict(list)  # {user_id: [call_dict, ...]}

def parse_number(text: str):
    """Convert 25k / 1.5m / 25000 → float"""
    if not text:
        return None
    text = text.lower().replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([km])?", text)
    if not match:
        return None
    num = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        num *= 1_000
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

class CallModal(Modal, title="New Call"):
    ca = TextInput(label="Contract Address (CA)", placeholder="Paste the CA here", required=True, max_length=50)
    call_mc = TextInput(label="Call MC", placeholder="Example: 25k or 25000", required=True, max_length=20)
    target = TextInput(label="Target (MC or x)", placeholder="Example: 100k or 4x", required=True, max_length=20)
    ath = TextInput(label="ATH (optional)", placeholder="Leave empty if not yet", required=False, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        call_mc = parse_number(self.call_mc.value)
        target_raw = self.target.value.strip().lower()
        ath = parse_number(self.ath.value) if self.ath.value else call_mc

        if not call_mc:
            await interaction.response.send_message("Invalid Call MC", ephemeral=True)
            return

        # Parse target
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

        call = {
            "ca": ca,
            "call_mc": call_mc,
            "target_mc": target_mc,
            "target_x": target_x,
            "ath": ath or call_mc,
            "hit_target": (ath or call_mc) >= target_mc
        }

        user_calls[interaction.user.id].append(call)

        text = (
            f"**New Call Saved**\n"
            f"```\n"
            f"CA:     {ca}\n"
            f"Called: {format_mc(call_mc)}\n"
            f"Target: {format_mc(target_mc)} ({target_x:.2f}x)\n"
            f"ATH:    {format_mc(call['ath'])}\n"
            f"```"
        )
        await interaction.response.send_message(text)

class CallView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="New Call", style=discord.ButtonStyle.green)
    async def new_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CallModal())

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower().strip()

    # .call → open form
    if content == ".call":
        await message.channel.send("Click the button to make a new call:", view=CallView())
        return

    # .stats
    if content == ".stats":
        calls = user_calls.get(message.author.id, [])
        if not calls:
            await message.reply("You have no calls yet.\nType `.call` to add one.")
            return

        total = len(calls)
        hit = sum(1 for c in calls if c["hit_target"])
        percent = (hit / total * 100) if total else 0
        biggest = max((c["ath"] / c["call_mc"] for c in calls), default=0)

        text = (
            f"**Stats for {message.author.display_name}**\n"
            f"```\n"
            f"Total calls:     {total}\n"
            f"Hit target:      {hit} ({percent:.1f}%)\n"
            f"Biggest multi:   {biggest:.2f}x\n"
            f"```\n"
            f"**Recent calls:**\n"
        )

        # Show last 5 calls
        for i, c in enumerate(reversed(calls[-5:]), 1):
            status = "✅" if c["hit_target"] else "❌"
            text += f"`{i}.` {c['ca'][:6]}... | Call {format_mc(c['call_mc'])} → ATH {format_mc(c['ath'])} | {status}\n"

        await message.reply(text)
        return

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
