import os
import re
import discord
from discord.ui import Button, View
import requests

# Konfiguracja uprawnień bota
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# Wzór szukający adresów kontraktów Solany (32-44 znaki)
SOL_CA_REGEX = r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"


class TokenView(View):

  def __init__(self, ca: str):
    super().__init__(timeout=None)
    self.add_item(
        Button(
            label="Chart",
            url=f"https://dexscreener.com/solana/{ca}",
            style=discord.ButtonStyle.link,
        )
    )
    self.add_item(
        Button(
            label="GMGN",
            url=f"https://gmgn.ai/solana/token/{ca}",
            style=discord.ButtonStyle.link,
        )
    )
    self.add_item(
        Button(
            label="Solscan",
            url=f"https://solscan.io/token/{ca}",
            style=discord.ButtonStyle.link,
        )
    )


def pobierz_dane_tokena(ca: str):
  url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
  try:
    odpowiedz = requests.get(url, timeout=5)
    dane = odpowiedz.json()
    pary = dane.get("pairs")
    if not pary:
      return None
    pary = sorted(
        pary, key=lambda x: x.get("liquidity", {}).get("usd", 0), reverse=True
    )
    return pary[0]
  except Exception as e:
    print(f"Błąd API: {e}")
    return None


@client.event
async def on_ready():
  print(f"Zalogowano jako {client.user}! Bot jest gotowy do działania.")


@client.event
async def on_message(message):
  if message.author == client.user:
    return

  match = re.search(SOL_CA_REGEX, message.content)
  if match:
    ca = match.group(0)

    token_info = pobierz_dane_tokena(ca)
    if not token_info:
      return

    base_token = token_info.get("baseToken", {})
    nazwa = base_token.get("name", "Nieznany")
    symbol = base_token.get("symbol", "UNKNOWN")

    cena = float(token_info.get("priceUsd", 0))
    mcap = token_info.get("marketCap", token_info.get("fdv", 0))
    plynnosc = token_info.get("liquidity", {}).get("usd", 0)

    zmiana_ceny = token_info.get("priceChange", {})
    h1 = zmiana_ceny.get("h1", 0)
    h24 = zmiana_ceny.get("h24", 0)

    h1_ikona = "▲" if h1 >= 0 else "▼"
    h24_ikona = "▲" if h24 >= 0 else "▼"

    mcap_tekst = f"${mcap:,.0f}" if mcap else "0"
    if mcap and mcap > 1000:
      mcap_tekst = f"${mcap / 1000:.2f}K"

    liq_tekst = f"${plynnosc / 1000:.2f}K" if plynnosc else "$0"

    tekst_wiadomosci = (
        f"**{nazwa} ({symbol}) | SOLANA**\n"
        f"┌─ Cena: ${cena:.8f}\n"
        f"├─ MCap: {mcap_tekst}\n"
        f"├─ Płynność: {liq_tekst}\n"
        f"├─ 1h: {h1_ikona} {abs(h1)}% · 24h: {h24_ikona} {abs(h24)}%\n"
        f"└─ Kontrakt: `{ca}`"
    )

    widok = TokenView(ca)
    await message.channel.send(tekst_wiadomosci, view=widok)


# Pobieranie tokena bezpiecznie z chmury Render
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
  print("BŁĄD: Brak zmiennej środowiskowej DISCORD_TOKEN!")
else:
  client.run(TOKEN)
