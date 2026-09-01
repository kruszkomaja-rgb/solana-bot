import os
import re
import discord
from discord.ui import Modal, TextInput, View, button
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Storage
# {user_id: {ca: call_data}}
user_calls = defaultdict(dict)

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
    ca = TextInput(label="Contract Address (CA)", placeholder="Paste CA here", required=True, max_length=50)
    call_mc = TextInput(label="Call MC", placeholder="Example: 25k", required=True, max_length=20)
    target = TextInput(label="Target (MC or x)", placeholder="Example: 100k or 4x", required=True, max_length=20)

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
            "ath": None,          # not closed yet
            "hit_target": False
        }

        text = (
            f"**Call Opened**\n"
            f"```\n"
            f"CA:     {ca}\n"
            f"Called: {format_mc(call_mc)}\n"
            f"Target: {format_mc(target_mc)} ({target_x:.2f}x)\n"
            f"```\n"
            f"When finished, click **Add ATH** and enter the ATH."
        )
        await interaction.response.send_message(text)

class AddATHModal(Modal, title="Add ATH"):
    ca = TextInput(label="Contract Address (CA)", placeholder="Paste the same CA", required=True, max_length=50)
    ath = TextInput(label="ATH Market Cap", placeholder="Example: 87k", required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        ca = self.ca.value.strip()
        ath = parse_number(self.ath.value)

        if not ath:
            await interaction.response.send_message("Invalid ATH", ephemeral=True)
            return

        calls = user_calls[interaction.user.id]

        if ca not in calls:
            await interaction.response.send_message("You don't have an open call with this CA.", ephemeral=True)
            return

        if calls[ca]["ath"] is not None:
            await interaction.response.send_message("This call is already closed.", ephemeral=True)
            return

        calls[ca]["ath"] = ath
        calls[ca]["hit_target"] = ath >= calls[ca]["target_mc"]
        multi = ath / calls[ca]["call_mc"]

        status = "HIT TARGET" if calls[ca]["hit_target"] else "Missed"

        text = (
            f"**Call Closed**\n"
            f"```\n"
            f"CA:     {ca}\n"
            f"Called: {format_mc(calls[ca]['call_mc'])}\n"
            f"ATH:    {format_mc(ath)} ({multi:.2f}x)\n"
            f"Target: {format_mc(calls[ca]['target_mc'])}\n"
            f"Result: {status}\n"
            f"```"
        )
        await interaction.response.send_message(text)

class MainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="New Call", style=discord.ButtonStyle.green)
    async def new_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NewCallModal())

    @button(label="Add ATH", style=discord.ButtonStyle.blurple)
    async def add_ath(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddATHModal())

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower().strip()

    if content == ".call":
        await message.channel.send("**Call Tracker**", view=MainView())
        return

    if content == ".stats":
        calls = user_calls.get(message.author.id, {})
        closed = [c for c in calls.values() if c["ath"] is not None]

        if not closed:
            await message.reply("You have no closed calls yet.")
            return

        total = len(closed)
        hits = sum(1 for c in closed if c["hit_target"])
        percent = (hits / total * 100) if total else 0
        biggest = max((c["ath"] / c["call_mc"] for c in closed), default=0)

        text = (
            f"**Stats for {message.author.display_name}**\n"
            f"```\n"
            f"Closed calls:    {total}\n"
            f"Hit target:      {hits} ({percent:.1f}%)\n"
            f"Biggest multi:   {biggest:.2f}x\n"
            f"```"
        )
        await message.reply(text)
        return

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
