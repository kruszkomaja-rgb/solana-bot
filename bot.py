import os
import re
import discord
from discord.ui import Modal, TextInput, View, button
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

RESULTS_CHANNEL_ID = 1544498477701005332

# ←←← WSTAW LINKI DO OBRAZKÓW
BANNER_URL = "https://imgur.com/a/kB1mpGD.png"      # Mego Call Bot banner
ICON_URL = "https://imgur.com/a/v8Rcvr2.png"          # małe zdjęcie

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
        embed.set_footer(text="Click the button below when you have the ATH")

        view = ATHView(ca, self.target_user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
            await interaction.response.send_message("This call is already closed.", ephemeral=True)
            return

        data = calls[self.ca]
        data["ath"] = ath
        data["hit"] = ath >= data["target_mc"]
        multi = ath / data["call_mc"]

        color = 0x00C853 if data["hit"] else 0xD32F2F
        result = "TARGET HIT" if data["hit"] else "MISSED"

        embed = discord.Embed(title="CALL RESULT", color=color)
        embed.add_field(name="Contract", value=f"`{self.ca}`", inline=False)
        embed.add_field(name="Entry", value=format_mc(data["call_mc"]), inline=True)
        embed.add_field(name="ATH", value=format_mc(ath), inline=True)
        embed.add_field(name="Multiple", value=f"**{multi:.2f}x**", inline=True)
        embed.add_field(name="Target", value=format_mc(data["target_mc"]), inline=True)
        embed.add_field(name="Result", value=f"**{result}**", inline=True)
        embed.set_footer(text=f"Called by {data['caller']}")

        results_channel = client.get_channel(RESULTS_CHANNEL_ID)
        if results_channel:
            await results_channel.send(embed=embed)

        await interaction.response.edit_message(
            content="Result sent to the channel.",
            embed=None,
            view=None
        )

class ATHView(View):
    def __init__(self, ca: str, user_id: int):
        super().__init__(timeout=None)
        self.ca = ca
        self.user_id = user_id

    @button(label="Add ATH", style=discord.ButtonStyle.blurple)
    async def add_ath(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the owner of this call can add ATH.", ephemeral=True)
            return
        await interaction.response.send_modal(ATHModal(self.ca, self.user_id))

class CallView(View):
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @button(label="Call", style=discord.ButtonStyle.secondary)  # ciemny / szary przycisk
    async def make_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("Only the owner can make calls here.", ephemeral=True)
            return
        await interaction.response.send_modal(NewCallModal(self.target_user_id))

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.lower().startswith(".call"):
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

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
else:
    client.run(TOKEN)
