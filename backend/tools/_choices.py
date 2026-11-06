"""Option lists shared by several tools' dropdowns (see ToolSpec.selects)."""

WIKIPEDIA_LANGUAGES = (
    ("en", "English"), ("fr", "French — Français"), ("de", "German — Deutsch"), ("es", "Spanish — Español"),
    ("it", "Italian — Italiano"), ("pt", "Portuguese — Português"), ("nl", "Dutch — Nederlands"), ("pl", "Polish — Polski"),
    ("sv", "Swedish — Svenska"), ("ru", "Russian — Русский"), ("uk", "Ukrainian — Українська"), ("tr", "Turkish — Türkçe"),
    ("ar", "Arabic — العربية"), ("fa", "Persian — فارسی"), ("he", "Hebrew — עברית"), ("hi", "Hindi — हिन्दी"),
    ("bn", "Bengali — বাংলা"), ("ur", "Urdu — اردو"), ("id", "Indonesian — Bahasa Indonesia"), ("vi", "Vietnamese — Tiếng Việt"),
    ("th", "Thai — ไทย"), ("zh", "Chinese — 中文"), ("ja", "Japanese — 日本語"), ("ko", "Korean — 한국어"),
)

CURRENCIES = (
    ("usd", "USD"), ("eur", "EUR"), ("gbp", "GBP"), ("jpy", "JPY"), ("inr", "INR"), ("cad", "CAD"), ("aud", "AUD"),
    ("chf", "CHF"), ("cny", "CNY"), ("btc", "BTC"), ("eth", "ETH"),
)

COUNTRIES = (
    ("us", "United States"), ("gb", "United Kingdom"), ("ca", "Canada"), ("au", "Australia"), ("in", "India"),
    ("de", "Germany"), ("fr", "France"), ("es", "Spain"), ("it", "Italy"), ("nl", "Netherlands"), ("br", "Brazil"),
    ("mx", "Mexico"), ("jp", "Japan"), ("kr", "South Korea"), ("sg", "Singapore"), ("ae", "United Arab Emirates"),
)

# Google News editions use upper-case country codes
COUNTRIES_UPPER = tuple((code.upper(), name) for code, name in COUNTRIES)

LANGUAGES = (
    ("auto", "Auto-detect"), ("en", "English"), ("es", "Spanish — Español"), ("fr", "French — Français"),
    ("de", "German — Deutsch"), ("it", "Italian — Italiano"), ("pt", "Portuguese — Português"),
    ("nl", "Dutch — Nederlands"), ("pl", "Polish — Polski"), ("ru", "Russian — Русский"),
    ("uk", "Ukrainian — Українська"), ("zh", "Chinese — 中文"), ("ja", "Japanese — 日本語"),
    ("ko", "Korean — 한국어"), ("ar", "Arabic — العربية"), ("hi", "Hindi — हिन्दी"),
    ("sv", "Swedish — Svenska"), ("no", "Norwegian — Norsk"), ("fi", "Finnish — Suomi"),
    ("da", "Danish — Dansk"), ("tr", "Turkish — Türkçe"), ("vi", "Vietnamese — Tiếng Việt"),
    ("id", "Indonesian — Bahasa Indonesia"), ("th", "Thai — ไทย"), ("el", "Greek — Ελληνικά"),
    ("he", "Hebrew — עברית"), ("hu", "Hungarian — Magyar"), ("cs", "Czech — Čeština"),
    ("ro", "Romanian — Română"), ("bg", "Bulgarian — Български"),
)
