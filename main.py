import requests
import os
import json
import time
import threading
from datetime import datetime, timedelta

import nest_asyncio
nest_asyncio.apply()

from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Konfigurasi ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DATA_FILE = "indodax_chat_realtime.jsonl"
POLLING_INTERVAL = 1  # detik

# --- Polling Chatroom Indodax ---
def polling_chatroom():
    url = "https://indodax.com/api/v2/chatroom/history"
    shown_ids = set()
    limit = 50
    print("Polling chatroom Indodax dimulai...")
    while True:
        try:
            params = {"limit": limit, "offset": 0}
            response = requests.get(url, params=params)
            data = response.json()
            if not (data.get("success") and "data" in data and "content" in data["data"] and data["data"]["content"]):
                print("Tidak ada data atau gagal:", data)
                time.sleep(POLLING_INTERVAL)
                continue
            new_chats = []
            for chat in reversed(data["data"]["content"]):
                if chat["id"] not in shown_ids:
                    shown_ids.add(chat["id"])
                    new_chats.append(chat)
            if new_chats:
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    for chat in new_chats:
                        f.write(json.dumps(chat, ensure_ascii=False) + "\n")
                print(f"Tambah {len(new_chats)} chat baru.")
            time.sleep(POLLING_INTERVAL)
        except Exception as e:
            print("Error polling:", e)
            time.sleep(POLLING_INTERVAL)

# --- Fungsi konversi waktu WIB <-> UTC ---
def wib_to_utc(dt_wib):
    return dt_wib - timedelta(hours=7)

def utc_to_wib(dt_utc):
    return dt_utc + timedelta(hours=7)

# --- Bot Telegram (async/await) ---
def search_by_time_range(start_str, end_str, username=None):
    results = []
    try:
        start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
        start_time_utc = wib_to_utc(start_time)
        end_time_utc = wib_to_utc(end_time)
        with open(DATA_FILE, encoding="utf-8") as f:
            for line in f:
                chat = json.loads(line)
                ts = chat.get("timestamp")
                if ts:
                    chat_time_utc = datetime.utcfromtimestamp(int(ts))
                    if start_time_utc <= chat_time_utc <= end_time_utc:
                        if username:
                            if chat.get("username", "").lower() == username.lower():
                                results.append(chat)
                        else:
                            results.append(chat)
    except Exception as e:
        print("Error:", e)
    return results

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Gunakan perintah:\n"
        "1. cari data berdasarkan waktu\n/data waktu_awal,waktu_akhir\n"
        "Contoh:\n/data 2025-08-15 10:00:00,2025-08-15 11:00:00\n"
        "2. jika cari berdasarkan username\n/data waktu_awal,waktu_akhir,username\n"
        "Contoh:\n/data 2025-08-15 10:00:00,2025-08-15 11:00:00,ahmadkholiln75"
        "\n\n 📌data terbatas❗️❗️❗️ tidak bisa cek riwayat terlalu jauh"
    )

async def data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.replace('/data', '', 1).strip()
    if not args:
        await update.message.reply_text(
            "Format: \n 1. /data waktu_awal,waktu_akhir\n 2. /data waktu_awal,waktu_akhir,username\n"
            "Contoh:\n/data 2025-08-15 10:00:00,2025-08-15 11:00:00\n"
            "atau\n/data 2025-08-15 10:00:00,2025-08-15 11:00:00,ahmadkholiln75"
            "\n\n 📌data terbatas❗️❗️❗️ tidak bisa cek riwayat terlalu jauh"
        )
        return
    parts = [s.strip() for s in args.split(',')]
    if len(parts) < 2:
        await update.message.reply_text("Format salah! Minimal: /data waktu_awal,waktu_akhir")
        return
    start_str, end_str = parts[0], parts[1]
    username = parts[2] if len(parts) > 2 else None
    hasil = search_by_time_range(start_str, end_str, username)
    if not hasil:
        await update.message.reply_text("Tidak ada chat pada rentang waktu tersebut.")
        return

    # Penamaan file hasil
    if username:
        safe_username = "".join(c for c in username if c.isalnum() or c in ('_', '-')).strip()
        filename = f"hasil_{safe_username}.txt"
    else:
        filename = f"hasil_{update.message.from_user.id}.txt"

    # Simpan ke file TXT: [tanggal] username: content
    with open(filename, "w", encoding="utf-8") as f:
        for chat in hasil:
            try:
                chat_time_utc = datetime.utcfromtimestamp(int(chat["timestamp"]))
                waktu_wib = utc_to_wib(chat_time_utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                waktu_wib = ""
            f.write(f"[{waktu_wib}] {chat.get('username')}: {chat.get('content')}\n")
        f.write(f"\nTotal chat: {len(hasil)}\n")
    with open(filename, "rb") as f:
        await update.message.reply_document(document=InputFile(f), filename=filename)
    # Hapus file setelah dikirim
    try:
        os.remove(filename)
    except Exception as e:
        print(f"Gagal menghapus file {filename}: {e}")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            await update.message.reply_text("File chatroom berhasil di-reset (dihapus).")
        else:
            await update.message.reply_text("File chatroom sudah kosong atau belum ada.")
    except Exception as e:
        await update.message.reply_text(f"Gagal menghapus file: {e}")

async def export_jsonl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not os.path.exists(DATA_FILE):
            await update.message.reply_text("File data chatroom belum ada.")
            return
        with open(DATA_FILE, "rb") as f:
            await update.message.reply_document(document=InputFile(f), filename=DATA_FILE)
    except Exception as e:
        await update.message.reply_text(f"Gagal mengirim file: {e}")

async def export_jsonl_waktu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.replace('/export_jsonl_waktu', '', 1).strip()
    if not args or ',' not in args:
        await update.message.reply_text(
            "Format: /export_jsonl_waktu waktu_awal,waktu_akhir\n"
            "Contoh:\n/export_jsonl_waktu 2025-08-15 10:00:00,2025-08-15 11:00:00"
        )
        return
    start_str, end_str = [s.strip() for s in args.split(',', 1)]
    hasil = search_by_time_range(start_str, end_str)
    if not hasil:
        await update.message.reply_text("Tidak ada chat pada rentang waktu tersebut.")
        return

    filename = f"export_{update.message.from_user.id}.jsonl"
    with open(filename, "w", encoding="utf-8") as f:
        for chat in hasil:
            f.write(json.dumps(chat, ensure_ascii=False) + "\n")
    with open(filename, "rb") as f:
        await update.message.reply_document(document=InputFile(f), filename=filename)
    # Hapus file setelah dikirim
    try:
        os.remove(filename)
    except Exception as e:
        print(f"Gagal menghapus file {filename}: {e}")

async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("data", data_command))
    app.add_handler(CommandHandler("reset_2025", reset_command)) 
    app.add_handler(CommandHandler("export_jsonl", export_jsonl_command))
    app.add_handler(CommandHandler("export_jsonl_waktu", export_jsonl_waktu_command))
    print("Bot Telegram siap.")
    await app.run_polling()

# --- Main ---
if __name__ == "__main__":
    # Jalankan polling di thread terpisah
    t_poll = threading.Thread(target=polling_chatroom, daemon=True)
    t_poll.start()
    # Bot Telegram di thread utama (dengan nest_asyncio)
    import asyncio
    asyncio.get_event_loop().run_until_complete(run_bot())
