import discord
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # 重要！需要開這個

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Bot 已上線為 {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.lower() == "ping":
        await message.channel.send("pong！")
    elif "你好" in message.content:
        await message.channel.send("你好～")

client.run(TOKEN)
