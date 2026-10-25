from echoscope.normalize import extract_urls, normalize_text, normalize_url


def test_arabic_variants_collapse():
    # Hamza variants, tashkeel and tatweel should not hide a copy.
    assert normalize_text("أخبار عاجلة") == normalize_text("اخبار عاجلة")
    assert normalize_text("عَاجِل") == normalize_text("عاجل")
    assert normalize_text("عـــاجل") == normalize_text("عاجل")


def test_hebrew_niqqud_removed():
    assert normalize_text("שָׁלוֹם") == normalize_text("שלום")


def test_emoji_hashtags_mentions_urls_removed():
    noisy = "🚨 BREAKING!! Something happened #breaking @somechannel https://t.me/x"
    assert normalize_text(noisy) == "breaking something happened"


def test_eastern_arabic_digits():
    assert normalize_text("٢٠٢٦") == "2026"


def test_url_canonicalisation():
    a = normalize_url("https://WWW.Example.com/path/?utm_source=tg&id=5#frag")
    b = normalize_url("example.com/path?id=5")
    assert a == b == "https://example.com/path?id=5"


def test_extract_urls_strips_trailing_punctuation():
    assert extract_urls("see (https://a.example/x).") == ["https://a.example/x"]
