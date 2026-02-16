#(©) @Hybrid_Vamp - https://github.com/hybridvamp
# Premium custom emoji IDs for Telegram messages and buttons
# Use HTML format in messages: <tg-emoji emoji-id="ID">fallback</tg-emoji>

E = {
    "success": (5323628709469495421, "✅"),
    "error": (5767151002666929821, "❌"),
    "warning": (5242628160297641831, "⚠️"),
    "phone": (5467539229468793355, "📞"),
    "money": (5375296873982604963, "💰"),
    "renew": (5264727218734524899, "🔄"),
    "get_code": (5433811242135331842, "📨"),
    "back": (5190458330719461749, "⬅️"),
    "admin": (5472308992514464048, "🛠️"),
    "user": (5422683699130933153, "👤"),
    "my_rentals": (5767374504175078683, "🛒"),
    "number_ctrl": (5190458330719461749, "🔢"),
    "export_csv": (5400090058030075645, "📑"),
    "available": (5323307196807653127, "🟢"),
    "rented": (5323535839391653590, "🔴"),
    "loading": (5451732530048802485, "⌛"),
    "pay": (5445353829304387411, "💳"),
    "prices": (5197434882321567830, "💵"),
    "language": (5399898266265475100, "🌍"),
    "english": (5202021044105257611, "🇺🇸"),
    "russian": (5449408995691341691, "🇷🇺"),
    "korean": (5456531898304047227, "🇰🇷"),
    "chinese": (5449408995691341691, "🇨🇳"),
    "next": (5190458330719461749, "➡️"),
    "down": (5190458330719461749, "⬇️"),
    "phone_welcome": (5407025283456835913, "📱"),
    "security": (5472308992514464048, "🔐"),
    "messages": (5253742260054409879, "📩"),
    "renewal": (5264727218734524899, "♻️"),
    "welcome": (5940434198413184876, "🚀"),
    "date": (5274055917766202507, "📅"),
    "user_id": (5190458330719461749, "🆔"),
    "tonkeeper": (5206583755367538087, "💸"),
    "invoice": (5440410042773824003, "📌"),
    "lang": (6037516707164064818, "🌐"),
    "timeout": (5242628160297641831, "⏰"),
    "get_code_lang": (5406809207947142040, "📲"),
    "page": (5400090058030075645, "📄"),
    "add_balance": (5375296873982604963, "➕"),
    "delete": (5190458330719461749, "🗑️"),
    "help": (5449428597922079323, "❓"),
    "back_home": (5465226866321268133, "🏠"),
    "rules": (5334882760735598374, "📜"),
    "time": (5413704112220949842, "🕒"),
    "username": (5318757666800031348, "🔗"),
    "admin_bullet": (5472308992514464048, "▎"),
    "welcome_features": (5472164874886846699, "✨"),
    "available_status": (5323307196807653127, "📦"),
    "copyright": (5229177516727478228, "©"),
    "transfer": (5915851493533028206, "↗️"),
}

def e(key: str, use_custom: bool = None) -> str:
    """
    Return emoji for message text.
    use_custom=True: Premium custom emoji (requires bot owner to have Telegram Premium).
    use_custom=False: Plain Unicode emoji - works for everyone (default).
    """
    if key not in E:
        return ""
    emoji_id, fallback = E[key]
    if use_custom is None:
        try:
            from config import USE_CUSTOM_EMOJI
            use_custom = USE_CUSTOM_EMOJI
        except Exception:
            use_custom = False
    if use_custom:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def eid(key: str) -> str | None:
    """Return custom emoji ID string for InlineKeyboardButton icon_custom_emoji_id."""
    if key not in E:
        return None
    return str(E[key][0])
