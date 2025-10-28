import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import json
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from flask import Flask, request, jsonify, send_from_directory
import threading

# ============= CONFIG =============
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
WEB_SECRET = os.environ.get("WEB_SECRET", "MySecret123")
BACKGROUND_PATH = "background.gif"
FONT_FOLDER = "fonts"
DEFAULT_FONT = "BebasNeue-Regular.ttf"
CONFIG_FILE = "config.json"
PORT = int(os.environ.get("PORT", 10000))
# =================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)

# ---- Load & Save Config ----
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)

config = load_config()

# ---- GFX Generator ----
def load_font(path, size):
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()

def measure_text(draw, text, font):
    try:
        return draw.textsize(text, font=font)
    except AttributeError:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2]-bbox[0], bbox[3]-bbox[1]

def draw_text_with_outline(draw, pos, text, font, fill, outline, width=2):
    x, y = pos
    for ox in range(-width, width+1):
        for oy in range(-width, width+1):
            if ox == 0 and oy == 0:
                continue
            draw.text((x+ox, y+oy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)

def render_gif_with_text(settings, slot, text):
    base = Image.open(BACKGROUND_PATH)
    frames, durations = [], []
    for frame in ImageSequence.Iterator(base):
        f = frame.convert("RGBA")
        frames.append(f.copy())
        durations.append(frame.info.get("duration", 100))

    font_slot = load_font(os.path.join(FONT_FOLDER, settings["font"]), settings["font_size_slot"])
    font_text = load_font(os.path.join(FONT_FOLDER, settings["font"]), settings["font_size_text"])

    out_frames = []
    for frame in frames:
        img = frame.copy()
        draw = ImageDraw.Draw(img)
        w, h = img.size

        slot_w, slot_h = measure_text(draw, str(slot), font_slot)
        slot_x = int(w * 0.03)
        slot_y = int((h - slot_h) / 2)
        draw_text_with_outline(draw, (slot_x, slot_y), str(slot), font_slot,
                               tuple(settings["color_text"]), tuple(settings["color_outline"]))

        text_w, text_h = measure_text(draw, text, font_text)
        text_x = slot_x + slot_w + int(w * 0.03)
        text_y = int((h - text_h) / 2)
        draw_text_with_outline(draw, (text_x, text_y), text, font_text,
                               tuple(settings["color_text"]), tuple(settings["color_outline"]))
        out_frames.append(img.convert("P", palette=Image.ADAPTIVE))

    output = BytesIO()
    out_frames[0].save(output, format="GIF", save_all=True, append_images=out_frames[1:],
                       duration=durations, loop=0, disposal=2)
    output.seek(0)
    return output

def get_guild_settings(guild_id):
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {
            "font": DEFAULT_FONT,
            "font_size_slot": 90,
            "font_size_text": 48,
            "color_text": [255, 255, 255, 255],
            "color_outline": [0, 0, 0, 255]
        }
        save_config(config)
    return config[gid]

# ---- Slash Commands ----
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print(f"✅ Logged in as {bot.user}")
    except Exception as e:
        print(f"Sync error: {e}")

@bot.tree.command(name="setfontsize", description="Change font size (admin only)")
@app_commands.describe(target="slot or text", size="new font size")
async def setfontsize(interaction: discord.Interaction, target: str, size: int):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permissions!", ephemeral=True)
        return
    s = get_guild_settings(interaction.guild_id)
    if target.lower() == "slot":
        s["font_size_slot"] = size
    else:
        s["font_size_text"] = size
    save_config(config)
    await interaction.response.send_message(f"✅ {target} font size set to {size}")

@bot.tree.command(name="setcolor", description="Change text color (admin only)")
@app_commands.describe(target="slot or text", color="Hex color like #FF0000")
async def setcolor(interaction: discord.Interaction, target: str, color: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permissions!", ephemeral=True)
        return
    s = get_guild_settings(interaction.guild_id)
    rgb = tuple(int(color[i:i+2], 16) for i in (1,3,5))
    if target.lower() in ["slot", "text"]:
        s["color_text"] = list(rgb) + [255]
    save_config(config)
    await interaction.response.send_message(f"✅ {target} color set to {color}",
                                            embed=discord.Embed(description=" ", color=int(color[1:], 16)))

@bot.tree.command(name="setoutlinecolor", description="Change outline color (admin only)")
@app_commands.describe(color="Hex color like #000000")
async def setoutlinecolor(interaction: discord.Interaction, color: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permissions!", ephemeral=True)
        return
    s = get_guild_settings(interaction.guild_id)
    rgb = tuple(int(color[i:i+2], 16) for i in (1,3,5))
    s["color_outline"] = list(rgb) + [255]
    save_config(config)
    await interaction.response.send_message(f"✅ Outline color set to {color}",
                                            embed=discord.Embed(description=" ", color=int(color[1:], 16)))

@bot.tree.command(name="gfx", description="Generate one banner manually")
@app_commands.describe(slot="Slot number 2–25", text="Banner text")
async def gfx(interaction: discord.Interaction, slot: int, text: str):
    await interaction.response.defer()
    s = get_guild_settings(interaction.guild_id)
    gif = await asyncio.to_thread(render_gif_with_text, s, slot, text)
    await interaction.followup.send(file=discord.File(gif, filename=f"slot{slot}.gif"))

# ---- Web Panel API ----
@app.route("/sendgfx", methods=["POST"])
def sendgfx():
    data = request.get_json()
    if data.get("secret") != WEB_SECRET:
        return jsonify({"error": "invalid secret"}), 403

    guild_id = int(data["guild_id"])
    channel_id = int(data["channel_id"])
    slots = data["slots"]

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify({"error": "guild not found"}), 404
    channel = guild.get_channel(channel_id)
    if not channel:
        return jsonify({"error": "channel not found"}), 404

    settings = get_guild_settings(guild_id)

    async def send_all():
        for slot, text in sorted(slots.items(), key=lambda x: int(x[0])):
            if text.strip():
                gif = await asyncio.to_thread(render_gif_with_text, settings, int(slot), text.strip())
                await channel.send(file=discord.File(gif, filename=f"slot{slot}.gif"))
                await asyncio.sleep(1)

    asyncio.run_coroutine_threadsafe(send_all(), bot.loop)
    return jsonify({"status": "ok"})

@app.route("/")
def panel():
    return send_from_directory("web", "form.html")

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

if __name__ == "__main__":
    from threading import Thread
    import webbrowser

    def run_flask():
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

    Thread(target=run_flask).start()
    bot.run(DISCORD_TOKEN)

