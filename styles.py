"""Visual design system — warm rose, cream, and soft gold.
The goal: feel like a high-end personal journal. Refined, feminine, premium.
Not childish, not corporate. Elegant and warm."""

# ─────────────────────────────────────────────────────────────────────
# Palette — warm cream backdrop, rose accents, soft champagne highlights
# ─────────────────────────────────────────────────────────────────────

# Surfaces
BG_MAIN         = "#FAF6F1"     # warm cream
BG_CARD         = "#FFFFFF"     # pure white cards
BG_CARD_ALT     = "#FBF6F2"     # subtle alt for hover / archive
BG_PILL         = "#F5EBE6"     # soft blush pill background
BG_PILL_HOVER   = "#EBDDD5"
SHADOW          = "#EBDDD3"     # used as offset-frame to fake card shadow
BORDER_LIGHT    = "#F0E5DE"
BORDER_MED      = "#E2D2C8"
DIVIDER         = "#F4ECE5"

# Text — warm dark with a hint of plum
TEXT_PRIMARY    = "#3B2D33"     # cocoa-aubergine
TEXT_SECONDARY  = "#7E6970"
TEXT_MUTED      = "#B5A0A8"
TEXT_STRIKE     = "#CCB5BB"
TEXT_ON_ACCENT  = "#FFFFFF"
TEXT_ON_TINT    = "#7A2D43"

# Accent — deep rose. Mature, feminine, distinctive.
ACCENT          = "#C2607A"
ACCENT_HOVER    = "#A94E66"
ACCENT_TINT     = "#F8E4EA"      # very soft tint for hover regions / backgrounds
ACCENT_BORDER   = "#EAC8D2"

# Secondary accent — soft champagne (for highlights, "done" affordances)
GOLD            = "#D4A574"
GOLD_TINT       = "#F7EBDC"

# Category palette — three feminine but distinct hues
CATEGORY_COLORS = {
    "work":     "#C2607A",     # rose (primary)
    "personal": "#D4A574",     # champagne
    "learning": "#8E7AB5",     # soft lilac
}
CATEGORY_TINTS = {
    "work":     "#F8E4EA",
    "personal": "#F7EBDC",
    "learning": "#EFE7F5",
}
CATEGORY_LABELS = {
    "work":     "Work",
    "personal": "Personal",
    "learning": "Learning",
}
CATEGORIES = ["work", "personal", "learning"]

# Priority — clear urgency, harmonized with the rose palette
PRIORITY_COLORS = {
    "low":    "#7BAB9C",       # sage
    "medium": "#D4A574",       # champagne
    "high":   "#C25461",       # warm red-rose
}
PRIORITY_TINTS = {
    "low":    "#E4EFEC",
    "medium": "#F7EBDC",
    "high":   "#F8DEDE",
}
PRIORITY_LABELS = {
    "low":    "Low",
    "medium": "Medium",
    "high":   "High",
}
PRIORITIES = ["low", "medium", "high"]

# Overdue
OVERDUE_TEXT = "#B8403F"
OVERDUE_TINT = "#FBE3E2"

# ─────────────────────────────────────────────────────────────────────
# Typography — Segoe UI Variable + a serif accent if available
# ─────────────────────────────────────────────────────────────────────
FONT_FAMILY        = "Segoe UI Variable"
FONT_FAMILY_ALT    = "Segoe UI"
FONT_SERIF         = "Georgia"   # for the greeting — adds elegance

FONT_DISPLAY       = (FONT_SERIF, 20, "italic")
FONT_TITLE         = (FONT_FAMILY, 14, "bold")
FONT_H2            = (FONT_FAMILY, 12, "bold")
FONT_BODY          = (FONT_FAMILY, 11)
FONT_BODY_BOLD     = (FONT_FAMILY, 11, "bold")
FONT_SUBTLE        = (FONT_FAMILY, 10)
FONT_SMALL         = (FONT_FAMILY, 9)
FONT_TINY          = (FONT_FAMILY, 8)
FONT_CAPTION       = (FONT_FAMILY, 8, "bold")

# ─────────────────────────────────────────────────────────────────────
# Spacing + radii — generous, soft
# ─────────────────────────────────────────────────────────────────────
PAD_XS = 2
PAD_S  = 4
PAD_M  = 8
PAD_L  = 14
PAD_XL = 22

RADIUS_SM     = 6
RADIUS_BUTTON = 10
RADIUS_CARD   = 14
RADIUS_PILL   = 999

WINDOW_W       = 320
WINDOW_H       = 440
WINDOW_MIN_W   = 280
WINDOW_MIN_H   = 320
HEADER_H       = 32
TAB_BAR_H      = 30
GRIP_SIZE      = 14

# ─────────────────────────────────────────────────────────────────────
# App identity
# ─────────────────────────────────────────────────────────────────────
APP_NAME   = "Checkera"
APP_ID     = "checkera"
USER_NAME  = "Rashi"

GREETINGS_MORNING = [
    "Good morning, {name}",
    "Morning, {name}",
    "Hello, {name}",
]
GREETINGS_AFTERNOON = [
    "Good afternoon, {name}",
    "Hi, {name}",
]
GREETINGS_EVENING = [
    "Good evening, {name}",
    "Evening, {name}",
]
GREETING_TAGLINES_MORNING = [
    "a fresh start.",
    "let's begin.",
    "here's today.",
]
GREETING_TAGLINES_AFTERNOON = [
    "keep going.",
    "midway through.",
]
GREETING_TAGLINES_EVENING = [
    "wind down.",
    "almost there.",
]
EMPTY_STATE_MESSAGES = [
    "all done.",
    "you're clear.",
    "nothing pending.",
    "peace.",
]
