"""Turn an allowed private update into a small command, discarding unrelated content."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from jarvis.assistant.commands import SLASH_COMMANDS

if TYPE_CHECKING:
    from jarvis.interfaces.telegram.config import TelegramConfig

REPLIES = {
    "unpaired": "Jarvis belum dipasangkan. Buat kode pairing di komputer, lalu kirim /pair KODE.",
    "paired": (
        "Pairing berhasil. Kirim pesan biasa untuk berbicara dengan KURO. /help untuk bantuan."
    ),
    "pair_failed": "Pairing tidak berhasil. Periksa kode dan masa berlakunya di komputer.",
    "already_paired": "Akun ini sudah dipasangkan. Gunakan /status atau /help.",
    "help": (
        "KURO\nKirim pesan biasa untuk bertanya ke AI cloud. /ask TEKS tetap tersedia.\n"
        "/docs — daftar dokumen\n/doc UUID — status dokumen\n"
        "/askdoc UUID PERTANYAAN — jawaban bersumber\n/deldoc UUID — hapus dokumen lokal\n"
        "/remember kunci nilai — simpan fakta profil untuk AI\n/memory — lihat profil\n"
        "/forget kunci — hapus fakta\n/new — percakapan baru\n/clear — hapus isi percakapan lokal\n"
        "/approve KODE — setujui satu panggilan premium\n/cancel — batalkan permintaan\n"
        "/toolapprove ID FINGERPRINT — setujui proposal Calendar\n"
        "/toolstatus ID — lihat status tindakan Calendar\n"
        "Calendar: coba 'apa jadwalku besok?' setelah diaktifkan pemilik.\n"
        "/ai — status AI\n/status — koneksi Telegram\n/privacy — batas privasi"
    ),
    "status": (
        "KURO terhubung dan akunmu sudah dipasangkan.\n"
        "Kirim pesan biasa. Cek /ai untuk worker AI dan /docs untuk dokumen.\n"
        "Premium selalu meminta konfirmasi per panggilan."
    ),
    "privacy": (
        "Hanya akun yang dipasangkan di chat pribadi dilayani. Chat bot melalui Telegram, "
        "bukan Secret Chat E2EE.\nPesan biasa dan /ask yang dilayani AI mengirim pertanyaan, "
        "profil tersimpan "
        "dan riwayat terpilih "
        "ke OpenRouter/provider dengan syarat no-training dan ZDR. Cloud tetap memproses data.\n"
        "/askdoc mengirim pertanyaan dan maksimal 4 kutipan dokumen private yang dipilih. "
        "Ekstraksi, OCR dan embedding lokal. Dokumen restricted diblokir dari cloud.\n"
        "Perintah Calendar yang dikenali diproses langsung; argumen dan hasil disimpan "
        "sebagai catatan tindakan dan diproses Google Calendar. Catatan ini terpisah dari /clear.\n"
        "Riwayat lokal disimpan 30 hari; /clear menghapus isi lokal, "
        "bukan salinan Telegram/backup. "
        "Profil sampai /forget; audit biaya dipertahankan. Receipt 48 jam.\n"
        "Jangan kirim kredensial/data restricted. Lampiran belum diproses."
    ),
    "unsupported": "Kirim pesan teks biasa untuk berbicara dengan KURO, atau /help. "
    "Perintah ini/lampiran belum didukung.",
    "assistant": "Jawaban tidak tersedia.",
    "knowledge": "Informasi dokumen tidak tersedia.",
}


@dataclass(frozen=True)
class IncomingCommand:
    update_id: int
    chat_id: int
    command: str
    pair_code: str | None = field(default=None, repr=False)
    argument: str | None = field(default=None, repr=False)


def parse_update(
    update: dict, config: "TelegramConfig", bot_username: str, now: datetime
) -> IncomingCommand | None:
    if type(update.get("update_id")) is not int or not 0 <= update["update_id"] < 2**63 - 1:
        raise ValueError("Invalid update identifier")
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    if (
        type(sender.get("id")) is not int
        or sender["id"] != config.sender_id
        or sender.get("is_bot") is not False
        or type(chat.get("id")) is not int
        or chat["id"] != config.sender_id
        or chat.get("type") != "private"
        or type(message.get("date")) is not int
        or not -60 <= now.timestamp() - message["date"] <= 86400
    ):
        return None
    forbidden = (
        "forward_origin",
        "forward_from",
        "forward_from_chat",
        "forward_date",
        "via_bot",
        "sender_chat",
        "business_connection_id",
        "sender_business_bot",
        "guest_query_id",
        "guest_bot_caller_user",
        "guest_bot_caller_chat",
    )
    if any(key in message for key in forbidden) or message.get("is_automatic_forward"):
        return None
    raw = message.get("text")
    command, pair_code, argument = "unsupported", None, None
    if isinstance(raw, str) and 0 < len(raw) <= 4096:
        pieces = raw.strip().split(maxsplit=1)
        first = pieces[0] if pieces else ""
        # Telegram's @bot suffix belongs to slash commands only. Ordinary text
        # starting with an email address or @handle must not disappear silently.
        name = first
        if first.startswith("/"):
            name, separator, mention = first.partition("@")
            if separator and mention.lower() != bot_username.lower():
                return None
        if name == "/jarvis_setup":
            return None
        if name in ("/start", "/help", "/status", "/privacy", "/pair"):
            command = name[1:]
        if name.removeprefix("/") in SLASH_COMMANDS and name.startswith("/"):
            command = name[1:]
            if len(pieces) == 2 and command not in {
                "restricted",
                "memory",
                "ai",
                "new",
                "clear",
                "cancel",
            }:
                argument = pieces[1].strip()
        if command == "pair" and len(pieces) == 2 and len(pieces[1]) <= 200:
            pair_code = pieces[1].strip()

        # Plain private text is an internal KURO chat ingress.
        # Unknown slash commands remain unsupported.
        if command == "unsupported" and first and not first.startswith("/"):
            command = "chat"
            argument = raw.strip()

    return IncomingCommand(
        update["update_id"],
        config.sender_id,
        command,
        pair_code,
        argument,
    )
