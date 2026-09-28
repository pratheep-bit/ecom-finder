import re
from typing import Optional, List, Tuple


KNOWN_BRANDS = [
    # Smartphones & Electronics
    "Samsung", "Apple", "OnePlus", "Xiaomi", "Redmi", "Realme", "Vivo", "Oppo", "iQOO", "Motorola", "Moto",
    "Google", "Nothing", "Poco", "Infinix", "Tecno", "Lava", "Nokia", "Honor",
    # Laptops & Computing
    "Asus", "Lenovo", "HP", "Dell", "Acer", "MSI", "Apple", "MacBook", "Gigabyte", "Microsoft",
    # Audio & Wearables
    "Sony", "boAt", "Boat", "Noise", "Boult", "JBL", "Sennheiser", "Bose", "Fire-Boltt", "Fastrack", "Titan", "Noise", "OnePlus",
    # Appliances
    "LG", "Whirlpool", "Bosch", "Godrej", "Haier", "IFB", "Panasonic", "Voltas", "Daikin", "Philips", "Bajaj", "Havells",
    # Peripherals
    "Logitech", "Razer", "Keychron", "Corsair", "Redragon", "Zebronics", "Portronics", "Amkette"
]


def parse_price(raw_val: any) -> Optional[float]:
    """
    Parses price representations commonly found on Amazon & Flipkart India:
    e.g. '₹18,499', 'Rs. 24,999.00', '18,499', '₹1,25,999', 18499
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val) if raw_val >= 0 else None

    text = str(raw_val).strip()
    if not text:
        return None

    # Strip currency words like Rs., INR, etc.
    text = re.sub(r"(?i)\b(rs\.?|inr|mrp)\b", "", text).strip()
    # Remove leading/trailing non-digits
    text = re.sub(r"^[^\d]+", "", text)
    text = re.sub(r"[^\d]+$", "", text)

    # Remove non-numeric characters except '.' and ','
    text = re.sub(r"[^\d.,]", "", text)
    if not text:
        return None

    # Handle Indian formatting e.g. 18,499 or 1,20,000.50
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "")
    elif text.count(".") > 1:
        # Multiple periods: strip all except last
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        val = float(text)
        return val if val >= 0 else None
    except ValueError:
        return None


def parse_rating(raw_val: any) -> Optional[float]:
    """
    Extracts a star rating float between 0.0 and 5.0.
    Handles '4.7 out of 5 stars', '4.7 ★', '4.7', 4.7
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return max(0.0, min(5.0, float(raw_val)))

    text = str(raw_val).strip()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        try:
            val = float(match.group(1))
            if 0.0 <= val <= 5.0:
                return round(val, 1)
        except ValueError:
            pass
    return None


def parse_review_count(raw_val: any) -> int:
    """
    Parses review counts, supporting raw integers, strings with commas,
    and abbreviated suffixes like '12.4K', '1.2M', '12,430 ratings'.
    """
    if raw_val is None:
        return 0
    if isinstance(raw_val, (int, float)):
        return max(0, int(raw_val))

    text = str(raw_val).strip()
    if not text:
        return 0

    # Check for 'Ratings & Reviews' format: extract highest number or review count
    if "ratings" in text.lower() and "reviews" in text.lower():
        # e.g. "10,705 Ratings & 766 Reviews" -> parse reviews or total ratings
        ratings_match = re.search(r"([\d,]+)\s*ratings", text, re.IGNORECASE)
        if ratings_match:
            text = ratings_match.group(1)

    # Check for K/M abbreviation like 12.4K or 1.2M
    k_match = re.search(r"(\d+(?:\.\d+)?)\s*k", text, re.IGNORECASE)
    if k_match:
        try:
            return int(float(k_match.group(1)) * 1000)
        except ValueError:
            pass

    m_match = re.search(r"(\d+(?:\.\d+)?)\s*m", text, re.IGNORECASE)
    if m_match:
        try:
            return int(float(m_match.group(1)) * 1000000)
        except ValueError:
            pass

    clean_digits = re.sub(r"[^\d]", "", text)
    if clean_digits:
        try:
            return int(clean_digits)
        except ValueError:
            pass
    return 0


def parse_discount_pct(current_price: Optional[float], original_price: Optional[float], raw_text: Optional[str] = None) -> Optional[float]:
    """
    Calculates or extracts discount percentage:
    e.g. 24.5%
    """
    if raw_text:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", raw_text)
        if match:
            try:
                pct = float(match.group(1))
                if 0 <= pct <= 100:
                    return round(pct, 1)
            except ValueError:
                pass

    if current_price and original_price and original_price > current_price:
        pct = ((original_price - current_price) / original_price) * 100.0
        return round(pct, 1)

    return None


def extract_brand(title: str) -> str:
    """
    Identifies the brand name from product title or returns the first capitalized token.
    """
    if not title:
        return "Generic"

    title_clean = title.strip()
    for brand in KNOWN_BRANDS:
        pattern = r"\b" + re.escape(brand) + r"\b"
        if re.search(pattern, title_clean, re.IGNORECASE):
            return brand

    # Fallback to first non-empty word
    words = title_clean.split()
    return words[0] if words else "Generic"


def normalize_title(title: str) -> str:
    """
    Cleans product title to help with fuzzy cross-platform deduplication:
    lowercased, extraneous descriptors removed, trimmed whitespace.
    """
    if not title:
        return ""

    t = title.lower()
    # Remove parenthetical packaging or colors e.g. '(Berry Red, 128 GB)'
    t = re.sub(r"\(.*?\)", " ", t)
    # Remove common promotional tags
    noise_patterns = [
        r"\b(deal of the day|limited time deal|bestseller|best seller|amazon exclusive|flipkart unique)\b",
        r"\b(with offer|lowest price|super offer|hot deal|new launch)\b",
    ]
    for p in noise_patterns:
        t = re.sub(p, " ", t, flags=re.IGNORECASE)

    # Standardize whitespace and remove unusual punctuation
    t = re.sub(r"[^\w\s\-\+]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


JUNK_SPEC_PATTERN = re.compile(
    r"(?:price|m\.r\.p|₹|\bratings?\b|\breviews?\b|%\s*off|product\s+page|delivery|sponsored|free\s+delivery|bank\s+offer|deal\s+of\s+the\s+day|save\s+extra|coupon|add\s+to\s+compare|in\s+stock|buy\s+now)",
    re.IGNORECASE,
)


def clean_specifications(specs: List[str]) -> List[str]:
    """
    Sanitizes raw scraped spec strings and removes empty, pricing, or boilerplate entries.
    """
    cleaned = []
    seen = set()
    for s in specs:
        if not s or not isinstance(s, str):
            continue
        trimmed = s.strip()
        # Skip short strings or strings with junk pricing/ratings/scraped snippet text
        if len(trimmed) < 2 or len(trimmed) > 120:
            continue
        if JUNK_SPEC_PATTERN.search(trimmed):
            continue
        if trimmed.lower() not in seen:
            seen.add(trimmed.lower())
            cleaned.append(trimmed)
    return cleaned


ACCESSORY_PATTERNS = [
    r"\b(?:back\s+)?cover\b",
    r"\bcase\b",
    r"\btempered\s+glass\b",
    r"\bscreen\s+(?:protector|guard)\b",
    r"\bcamera\s+lens\s+protector\b",
    r"\b(?:charging\s+)?cable\b",
    r"\bcharger\b",
    r"\badapter\b",
    r"\bholder\b",
    r"\bstand\b",
    r"\bpouch\b",
    r"\bskin\b",
    r"\bdummy\s+phone\b",
    r"\btoy\s+phone\b",
    r"\bcleaning\s+kit\b",
    r"\bsleeve\b",
    r"\bkeyboard\s+cover\b",
    r"\bcooling\s+pad\b",
    r"\bwall\s+mount\b",
    r"\btrolley\b",
]

CATEGORY_FLOORS = {
    "phone": 3500.0,
    "smartphone": 3500.0,
    "mobile": 3500.0,
    "iphone": 10000.0,
    "galaxy": 5000.0,
    "oneplus": 5000.0,
    "pixel": 8000.0,
    "redmi": 4000.0,
    "realme": 4000.0,
    "poco": 4000.0,
    "iqoo": 5000.0,
    "laptop": 12000.0,
    "notebook": 12000.0,
    "macbook": 25000.0,
    "television": 5000.0,
    "tv": 5000.0,
    "washing machine": 6000.0,
    "refrigerator": 7000.0,
    "fridge": 7000.0,
}


def is_accessory_or_irrelevant(title: str, query: str, price: Optional[float] = None) -> bool:
    """
    Detects if a product result is an accessory (case, cover, tempered glass, cable, toy)
    or priced unrealistically below the category floor when the user is searching for a main device.
    """
    if not title:
        return True

    title_lower = title.lower()
    q_lower = query.lower()

    # Determine if query target is a primary device category or brand
    is_device_query = any(cat in q_lower for cat in (
        "phone", "smartphone", "mobile", "laptop", "notebook", "macbook",
        "tv", "television", "washing machine", "fridge", "refrigerator",
        "iphone", "galaxy", "oneplus", "pixel", "redmi", "realme", "poco", "iqoo",
        "thinkpad", "zenbook", "vivobook", "ideapad"
    ))

    if is_device_query:
        # Check accessory patterns
        for pattern in ACCESSORY_PATTERNS:
            if re.search(pattern, title_lower):
                # Ensure the query itself wasn't specifically asking for that accessory (e.g. "phone case")
                if not any(acc in q_lower for acc in ("case", "cover", "cable", "guard", "protector", "stand", "charger", "adapter")):
                    return True

        # Check category price floors
        if price is not None and price > 0:
            for cat, floor in CATEGORY_FLOORS.items():
                if cat in q_lower and price < floor:
                    return True

    return False

