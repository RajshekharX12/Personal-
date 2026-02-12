import json

# Load the current lang.json
with open('lang.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# TON Emoji IDs (from TON Emoji pack)
EMOJIS = {
    'rocket': '5377471691916978617',
    'phone': '5370869711888194012',
    'sparkles': '5359785904535774578',
    'lock': '5377399456693011056',
    'mail': '5370869711888194012',
    'money': '5377457244938489129',
    'recycle': '5359967122611353050',
    'diamond': '5377399456693011056',
    'check': '5314250708508464081',
    'star': '5359785904535774578',
    'fire': '5368324170671202286',
}

# Update English messages with premium emojis
data['en']['welcome'] = f'<tg-emoji emoji-id="{EMOJIS["rocket"]}">🚀</tg-emoji> {{name}} Welcome to Rental Bot!\n\n<tg-emoji emoji-id="{EMOJIS["phone"]}">📱</tg-emoji> +888 Numbers — Instant, Private & Secure\n\n<tg-emoji emoji-id="{EMOJIS["sparkles"]}">✨</tg-emoji> What you get:\n  • <tg-emoji emoji-id="{EMOJIS["lock"]}">🔐</tg-emoji> Anonymous & Secure rentals\n  • <tg-emoji emoji-id="{EMOJIS["mail"]}">📩</tg-emoji> Get codes anytime – fast & reliable\n  • <tg-emoji emoji-id="{EMOJIS["money"]}">💵</tg-emoji> Instant Payment in TON @send\n  • <tg-emoji emoji-id="{EMOJIS["recycle"]}">♻️</tg-emoji> Instant Renewal – never lose your number\n\n<tg-emoji emoji-id="{EMOJIS["rocket"]}">🚀</tg-emoji> Your digital number, always online, always yours.\n<tg-emoji emoji-id="{EMOJIS["diamond"]}">⬇️</tg-emoji> Pick a rent option & start now!'

data['en']['payment_confirmed'] = f'<tg-emoji emoji-id="{EMOJIS["check"]}">✅</tg-emoji> **Payment confirmed! Your balance has been updated.**'

data['en']['rental_success'] = f'<tg-emoji emoji-id="{EMOJIS["diamond"]}">💎</tg-emoji> **You have successfully rented the number**\n\nNumber: `{{number}}`\nDuration: **{{duration}}**\nPrice: **{{price}} TON**\n\n<tg-emoji emoji-id="{EMOJIS["money"]}">💰</tg-emoji> Your new balance is **{{balance}} TON**.'

data['en']['here_is_code'] = f'<tg-emoji emoji-id="{EMOJIS["star"]}">⭐</tg-emoji> **Your code:** `{{code}}`\n\n__👉 Click on Code It will be copied.__'

data['en']['profile_text'] = f'<tg-emoji emoji-id="{EMOJIS["money"]}">💰</tg-emoji> **Your Profile**\n\n🆔 User ID: `{{id}}`\n👤 First Name: {{fname}}\n🔗 Username: {{uname}}\n<tg-emoji emoji-id="{EMOJIS["money"]}">💰</tg-emoji> Balance: **{{bal}} TON**\n💳 Payment Method: {{payment_method}}'

data['en']['pay_amount_tonkeeper'] = f'<tg-emoji emoji-id="{EMOJIS["diamond"]}">💎</tg-emoji> **Pay with Tonkeeper**\n\n<tg-emoji emoji-id="{EMOJIS["money"]}">💰</tg-emoji> Amount: **{{amount}} TON**\n📍 Address: `{{address}}`\n\n<tg-emoji emoji-id="{EMOJIS["rocket"]}">🚀</tg-emoji> **Quick Payment:**\n1️⃣ Click \'<tg-emoji emoji-id="{EMOJIS["diamond"]}">💎</tg-emoji> Open Tonkeeper\' button below\n2️⃣ Tonkeeper will open with pre-filled details\n3️⃣ Confirm the payment in Tonkeeper\n4️⃣ Copy the transaction hash\n5️⃣ Return here and click \'<tg-emoji emoji-id="{EMOJIS["check"]}">✅</tg-emoji> I\'ve Paid\'\n6️⃣ Paste the transaction hash\n\n⚠️ Send exactly **{{amount}} TON** to avoid issues!'

data['en']['insufficient_balance'] = f'<tg-emoji emoji-id="{EMOJIS["fire"]}">❌</tg-emoji> Insufficient balance. Please add funds to your account.'

data['en']['error_occurred'] = f'<tg-emoji emoji-id="{EMOJIS["fire"]}">❌</tg-emoji> An error occurred. Please try again later.'

# Save updated lang.json
with open('lang.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("✅ Updated lang.json with premium TON emojis!")
