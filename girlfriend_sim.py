# Step 20: Virtual Girlfriend CLI & Desktop GUI Simulator (GUI Help Guide & In-App Reset)
import argparse
from datetime import datetime
import json
import os
import random
import re
import ast
import operator
import queue
import contextlib
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

SAVE_FILE = "partner_save.json"
DIARY_FILE = "relationship_diary.md"
MEMORY_DB_FILE = "companion_memories.db"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_CHAT_HISTORY_LIMIT = 10
DEFAULT_API_TIMEOUT = 5.0
DEFAULT_API_MAX_RETRIES = 1
TYPING_INDICATOR_TEXT = "She's typing..."

# Re-entrant locks for thread-safe SQLite access and conversation state updates
_DB_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()

# Hybrid Online/Offline connection state tracker (never stores or exposes API keys)
CONNECTION_STATE = {
    "mode": "Offline",
    "provider": "Offline Engine",
    "reason": "Local Offline Mode",
    "last_updated": ""
}


def update_connection_status(mode, provider, reason):
    """Thread-safe update of the current Online/Offline intelligence mode status."""
    with _STATE_LOCK:
        CONNECTION_STATE["mode"] = mode
        CONNECTION_STATE["provider"] = provider
        CONNECTION_STATE["reason"] = reason
        CONNECTION_STATE["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection_status():
    """
    Return the current hybrid intelligence connection status dict and display label.
    Does not claim the offline engine has full LLM capabilities.
    """
    load_dotenv_if_present()
    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    with _STATE_LOCK:
        if not has_openai and not has_gemini:
            return {
                "mode": "Offline",
                "provider": "Offline Engine",
                "reason": "No API Key Configured",
                "label": "Offline (Local Fallback Engine)"
            }
        mode = CONNECTION_STATE.get("mode", "Online")
        provider = CONNECTION_STATE.get("provider", "OpenAI" if has_openai else "Gemini")
        reason = CONNECTION_STATE.get("reason", "Ready")
        if mode == "Online" and CONNECTION_STATE.get("last_updated"):
            return {
                "mode": "Online",
                "provider": provider,
                "reason": reason,
                "label": f"Online ({provider} LLM)"
            }
        if mode == "Offline" and CONNECTION_STATE.get("last_updated"):
            return {
                "mode": "Offline",
                "provider": "Offline Engine",
                "reason": reason,
                "label": f"Offline Fallback ({reason})"
            }
        default_provider = "OpenAI" if has_openai else "Gemini"
        return {
            "mode": "Online",
            "provider": default_provider,
            "reason": "Ready",
            "label": f"Online ({default_provider} LLM)"
        }

# Module-level conversation state tracking variables (also synchronized inside state dict)
last_topic = None
recent_topics = []

MEMORY_CATEGORIES = [
    "Personal preferences",
    "Music preference",
    "Favourite movies and games",
    "Hobbies and interests",
    "Important dates and events",
    "Personal goals and plans",
    "Important people",
    "Relationship preferences",
    "Important experiences",
]


def load_dotenv_if_present(dotenv_path=".env"):
    """Load key=value pairs from a local .env file into os.environ without exposing secrets in code or logs."""
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


load_dotenv_if_present()

# ANSI escape codes for terminal styling
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_PINK = "\033[95m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"

PERSONALITIES = {
    "Sweet & Caring": "warm, nurturing, gentle, and deeply supportive",
    "Playful & Teasing": "witty, energetic, playfully teasing, and full of banter",
    "Poetic & Romantic": "dreamy, lyrical, artistic, and deeply romantic"
}

GIFT_CATALOG = {
    "Matcha Latte": {"price": 15, "bonus": 8, "mood": "Happy"},
    "Vinyl Keychain": {"price": 25, "bonus": 12, "mood": "Excited"},
    "Handwritten Note": {"price": 30, "bonus": 14, "mood": "Touched"},
    "Starlight Bouquet": {"price": 50, "bonus": 18, "mood": "Blushing"}
}

MOOD_THEMES = {
    "Happy": {"bg": "#1E1B2E", "panel": "#2A2540", "btn": "#312B4B", "accent": "#FF5E99", "portrait": "#FF8DC7"},
    "Blushing": {"bg": "#2B1829", "panel": "#3D213A", "btn": "#4A2847", "accent": "#FF4785", "portrait": "#FFA6C9"},
    "Excited": {"bg": "#1C2133", "panel": "#262E47", "btn": "#2F3959", "accent": "#FFB830", "portrait": "#FFE07D"},
    "Touched": {"bg": "#241B30", "panel": "#332645", "btn": "#3E2E54", "accent": "#C77DFF", "portrait": "#E0AAFF"},
    "Caring": {"bg": "#172629", "panel": "#20353A", "btn": "#28434A", "accent": "#4ECDC4", "portrait": "#7EF2B5"},
    "Curious": {"bg": "#1A2233", "panel": "#232F47", "btn": "#2C3B59", "accent": "#56CFE1", "portrait": "#7CE8FF"},
    "Hurt": {"bg": "#1E2029", "panel": "#292C38", "btn": "#343847", "accent": "#8D99AE", "portrait": "#B8C0CC"},
}


def enable_windows_ansi():
    """Enable ANSI color sequences on Windows terminals."""
    if os.name == "nt":
        os.system("")


def typewrite(text, enabled=True, delay=0.014):
    """Print dialogue with a classic visual-novel typewriter animation, skipping ANSI escape codes."""
    if not enabled:
        print(text)
        return
    tokens = re.split(r"(\033\[[0-9;]*m)", text)
    for token in tokens:
        if token.startswith("\033["):
            sys.stdout.write(token)
            sys.stdout.flush()
        else:
            for ch in token:
                sys.stdout.write(ch)
                sys.stdout.flush()
                time.sleep(delay)
    print()


def style_partner_line(text, personality, player_name):
    """
    Subtly adapt tone for personality without tacking repetitive romantic clichés
    ('I love you', 'I miss you', or identical stock sentences) onto every message.
    """
    if not text:
        return text
    # Keep factual explanations, questions with follow-ups, and already-expressive lines clean and natural
    if len(text) > 135 or text.count("?") >= 1 or text.count("!") >= 2:
        return text
    if personality == "Playful & Teasing":
        if "😉" not in text and "haha" not in text.lower() and "hehe" not in text.lower():
            return f"{text} 😉"
    elif personality == "Poetic & Romantic":
        if not any(w in text.lower() for w in ("starlight", "melody", "warmth", "dream", "verse")):
            return f"{text} Talking with you always brings a quiet warmth to my day."
    return text


def get_mood_portrait(mood):
    """Return a cute multi-line ASCII portrait that matches her current mood."""
    portraits = {
        "Happy": (
            "   .---.   \n"
            "  / ^ ^ \\  \n"
            " |  \\_/  |  <3\n"
            "  \\_____/  "
        ),
        "Blushing": (
            "   .---.   \n"
            "  / > < \\  \n"
            " | (o_o) |  *blush*\n"
            "  \\_____/  "
        ),
        "Excited": (
            "   .---.   \n"
            "  / * * \\  \n"
            " |   O   |  !!\n"
            "  \\_____/  "
        ),
        "Touched": (
            "   .---.   \n"
            "  / ^ ^ \\  \n"
            " |  '-'  |  *sparkle*\n"
            "  \\_____/  "
        ),
        "Caring": (
            "   .---.   \n"
            "  / o o \\  \n"
            " |  \\_/  |  *hug*\n"
            "  \\_____/  "
        ),
        "Curious": (
            "   .---.   \n"
            "  / o O \\  \n"
            " |   .   |  ?\n"
            "  \\_____/  "
        ),
        "Hurt": (
            "   .---.   \n"
            "  / ; ; \\  \n"
            " |  ___  |  ...\n"
            "  \\_____/  "
        ),
    }
    return portraits.get(
        mood,
        "   .---.   \n"
        "  / ^ ^ \\  \n"
        " |  \\_/  |  ~\n"
        "  \\_____/  "
    )


def clamp_affection(val):
    """Clamp affection score cleanly to [0, 100]."""
    return max(0, min(100, int(val)))


def get_relationship_tier(affection):
    """Return a relationship status label based on the current affection score."""
    if affection >= 80:
        return "Soulmates"
    elif affection >= 60:
        return "Close Partners"
    elif affection >= 35:
        return "Getting Closer"
    else:
        return "Distant"


def save_game(state):
    """Save the current game state dictionary to partner_save.json and sync memories to SQLite."""
    if isinstance(state, dict) and isinstance(state.get("memories"), dict):
        sanitize_memories(state["memories"])
        sync_dict_to_memory_db(state["memories"])
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_game():
    """Load and normalize the saved game state from partner_save.json and merge persistent SQLite memories."""
    init_memory_db()
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            defaults = create_new_state(interactive=False)
            for k, v in defaults.items():
                data.setdefault(k, v)
            for item in GIFT_CATALOG:
                data["inventory"].setdefault(item, 0)
            if not isinstance(data.get("memories"), dict):
                data["memories"] = {}
            sanitize_memories(data["memories"])
            # Load persistent memories from SQLite and sync both ways
            db_mem_dict = load_memories_dict_from_db()
            for k, v in db_mem_dict.items():
                data["memories"].setdefault(k, v)
            sync_dict_to_memory_db(data["memories"])
            data["affection"] = max(0, min(100, int(data.get("affection", 50))))
            return data
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return None
    return None


def log_diary_event(state, event_text):
    """Append a timestamped day entry to the relationship diary log."""
    diary_log = state.setdefault("diary_log", [])
    entry = f"Day {state['day']}: {event_text}"
    if not diary_log or diary_log[-1] != entry:
        diary_log.append(entry)


def build_diary_markdown(state):
    """Compile the Relationship Diary & Certificate Markdown string."""
    player = state["player_name"]
    partner = state["partner_name"]
    affection = state["affection"]
    tier = get_relationship_tier(affection)
    day = state["day"]
    mood = state["mood"]
    personality = state.get("personality", "Sweet & Caring")
    coins = state.get("coins", 0)
    keepsakes = state.get("keepsakes", [])
    memories = state.get("memories", {})
    diary_log = state.get("diary_log", [])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    bar_filled = affection // 5
    progress_bar = "#" * bar_filled + "-" * (20 - bar_filled)

    lines = [
        f"# Relationship Diary & Memory Certificate: {player} & {partner}",
        "",
        f"**Exported on:** {timestamp}",
        "",
        "## Relationship Status Certificate",
        "",
        "| Field | Details |",
        "| :--- | :--- |",
        f"| **Partners** | {player} & {partner} |",
        f"| **Companion Personality** | {personality} |",
        f"| **Current Status Tier** | {tier} |",
        f"| **Affection Score** | `[{progress_bar}]` {affection}/100 |",
        f"| **Days Together** | Day {day} |",
        f"| **Current Mood** | {mood} |",
        f"| **Coins Balance** | {coins} Coins |",
        f"| **Milestone Keepsakes** | {len(keepsakes)}/4 Unlocked |",
        f"| **Personal Facts Remembered** | {len(memories)} Saved |",
        "",
        "## Personal Facts She Remembers About You",
        ""
    ]

    if memories:
        for key, val in memories.items():
            label = key.replace("_", " ").title()
            lines.append(f"* **{label}:** {val}")
    else:
        lines.append("* *No personal facts recorded yet. Share your favorites in Non-Stop Free Chat!*")

    lines.extend([
        "",
        "## Unlocked Milestone Keepsakes",
        ""
    ])

    if keepsakes:
        for idx, item in enumerate(keepsakes, start=1):
            lines.append(f"{idx}. **{item['title']}** — *{item['description']}*")
    else:
        lines.append("* *No milestone keepsakes unlocked yet. Reach 60+ Affection or Day 7!*")

    lines.extend([
        "",
        "## Relationship Highlights Log",
        ""
    ])

    if diary_log:
        for entry in diary_log[-15:]:
            lines.append(f"* {entry}")
    else:
        lines.append(f"* Day 1: {player} and {partner} began their journey together.")

    lines.extend([
        "",
        "## Personal Note from " + partner,
        "",
        f"> \"Dearest {player}, thank you for every conversation, laugh, and memory we've shared over the last {day} day(s). "
        f"No matter where we go next, every moment with you is my favorite adventure. — Yours always, {partner}\"",
        ""
    ])

    return "\n".join(lines)


def export_relationship_diary(state, quiet=False):
    """Write the Relationship Diary & Certificate to relationship_diary.md."""
    content = build_diary_markdown(state)
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    if not quiet:
        player = state["player_name"]
        partner = state["partner_name"]
        print(f"\n{C_GREEN}===================================================={C_RESET}")
        print(f"{C_BOLD}{C_YELLOW}  RELATIONSHIP DIARY EXPORTED TO: {DIARY_FILE}{C_RESET}")
        print(f"{C_GREEN}===================================================={C_RESET}")
        print(f"{C_CYAN}Preview of {partner}'s closing note in {DIARY_FILE}:{C_RESET}")
        typewrite(
            f'{C_PINK}"Dearest {player}, thank you for every conversation, laugh, and memory we\'ve shared..."{C_RESET}',
            state.get("typewriter", True)
        )


def print_status_card(state):
    """Print the formatted terminal HUD card for the current state."""
    tier = get_relationship_tier(state["affection"])
    bar_filled = state["affection"] // 5
    bar = f"{C_PINK}{'#' * bar_filled}{C_RESET}{'-' * (20 - bar_filled)}"
    mem_count = len(state.get("memories", {}))
    personality = state.get("personality", "Sweet & Caring")
    tw_status = "ON" if state.get("typewriter", True) else "OFF"
    coins = state.get("coins", 0)

    print(f"\n{C_CYAN}----------------------------------------{C_RESET}")
    print(f"{C_PINK}{get_mood_portrait(state['mood'])}{C_RESET}")
    print(f"Day {C_BOLD}{state['day']}{C_RESET} | Energy: {C_YELLOW}{state['energy']}/{state['max_energy']}{C_RESET} | Coins: {C_YELLOW}{coins}{C_RESET} | Keepsakes: {C_GREEN}{len(state['keepsakes'])}/4{C_RESET} | Memories: {C_CYAN}{mem_count}{C_RESET}")
    print(f"[{C_BOLD}{state['partner_name']}{C_RESET}] Mood: {C_PINK}{state['mood']}{C_RESET} | Status: {C_CYAN}{tier}{C_RESET}")
    conn_info = get_connection_status()
    conn_color = C_GREEN if conn_info["mode"] == "Online" else C_YELLOW
    print(f"Vibe: {C_YELLOW}{personality}{C_RESET} | Typewriter FX: {C_GREEN}{tw_status}{C_RESET} | Status: {conn_color}{conn_info['label']}{C_RESET}")
    print(f"Affection: [{bar}] {state['affection']}/100")
    print(f"{C_CYAN}----------------------------------------{C_RESET}")


def customize_vibe_menu(state):
    """Let the player switch her personality style or toggle the typewriter animation."""
    partner = state["partner_name"]
    player = state["player_name"]
    current_p = state.get("personality", "Sweet & Caring")
    tw_enabled = state.get("typewriter", True)

    print(f"\n{C_CYAN}=== Customize {partner}'s Personality & Visual Novel Settings ==={C_RESET}")
    p_names = list(PERSONALITIES.keys())
    for idx, name in enumerate(p_names, start=1):
        marker = f"{C_GREEN}[Active]{C_RESET}" if name == current_p else ""
        print(f"  {idx}. {name} — ({PERSONALITIES[name]}) {marker}")
    tw_label = f"{C_GREEN}ON{C_RESET}" if tw_enabled else f"{C_RED}OFF{C_RESET}"
    print(f"  4. Toggle Typewriter Text Animation (Currently: {tw_label})")
    print("  5. Back to Main Menu")

    choice = input("\nSelect an option (1-5): ").strip()
    if choice in ("1", "2", "3"):
        chosen_p = p_names[int(choice) - 1]
        state["personality"] = chosen_p
        log_diary_event(state, f"Switched {partner}'s personality vibe to '{chosen_p}'.")
        greeting_by_vibe = {
            "Sweet & Caring": f'{partner}: "I\'ll always be right here to take care of you and cheer you on, {player}!"',
            "Playful & Teasing": f'{partner}: "Hehe, ready for some extra banter, {player}? Try to keep up with me!"',
            "Poetic & Romantic": f'{partner}: "With you, {player}, even an ordinary terminal screen feels like a starry night sky."'
        }
        print(f"\n{C_GREEN}[Personality updated to: {chosen_p}]{C_RESET}")
        typewrite(f"{C_PINK}{greeting_by_vibe[chosen_p]}{C_RESET}", state.get("typewriter", True))
    elif choice == "4":
        state["typewriter"] = not tw_enabled
        new_status = "ON" if state["typewriter"] else "OFF"
        print(f"\n{C_GREEN}[Typewriter Text Animation is now {new_status}]{C_RESET}")


def check_milestones(state, quiet=False):
    """Unlock permanent keepsake memories and return any newly unlocked milestone tuples."""
    partner = state["partner_name"]
    player = state["player_name"]
    affection = state["affection"]
    day = state["day"]
    keepsakes = state["keepsakes"]

    milestones = [
        ("First Spark (60+ Affection)", affection >= 60,
         f"A pressed flower {partner} tucked into {player}'s notebook when you became Close Partners."),
        ("Soulmate Promise (85+ Affection)", affection >= 85,
         f"A pair of matching bracelets {partner} and {player} exchanged after reaching Soulmate status."),
        ("One-Week Anniversary (Day 7+)", day >= 7,
         f"A photo strip from celebrating a full week of memories together with {partner}."),
        ("Perfect Harmony (100 Affection)", affection >= 100,
         f"A heartfelt letter from {partner}: 'Every single day with you is my favorite adventure, {player}.'")
    ]

    newly_unlocked = []
    for title, unlocked, description in milestones:
        if unlocked and not any(k["title"] == title for k in keepsakes):
            keepsakes.append({"title": title, "description": description})
            log_diary_event(state, f"Unlocked Milestone Keepsake '{title}'.")
            newly_unlocked.append((title, description))
            if not quiet:
                print(f"\n{C_YELLOW}****************************************{C_RESET}")
                print(f"{C_BOLD}{C_YELLOW}NEW KEEPSAKE UNLOCKED: {title}{C_RESET}")
                typewrite(f'{C_PINK}"{description}"{C_RESET}', state.get("typewriter", True))
                print(f"{C_YELLOW}****************************************{C_RESET}")

    ending_triggered = False
    if len(keepsakes) == 4 and not state.get("ending_seen", False):
        state["ending_seen"] = True
        log_diary_event(state, "Reached the True Ending: Eternal Harmony!")
        ending_triggered = True
        if not quiet:
            show_ending_scene(player, partner, state.get("typewriter", True))

    return newly_unlocked, ending_triggered


def show_ending_scene(player_name, partner_name, tw_enabled=True):
    """Display the celebratory True Ending banner when all 4 keepsakes are unlocked."""
    print(f"\n{C_PINK}===================================================={C_RESET}")
    print(f"{C_BOLD}{C_YELLOW}      TRUE ENDING UNLOCKED: ETERNAL HARMONY         {C_RESET}")
    print(f"{C_PINK}===================================================={C_RESET}")
    typewrite(
        f"\nUnder a canopy of lanterns, {partner_name} opens the Memory Box you built\n"
        f"together—holding the pressed flower, matching bracelets, anniversary photo\n"
        f"strip, and her handwritten letter.",
        tw_enabled
    )
    typewrite(
        f'\n{C_PINK}{partner_name}: "{player_name}, from our very first conversation to every\n'
        f'date, gift, and game we shared, you made every moment unforgettable.\n'
        f'Thank you for being my favorite person in the world!"{C_RESET}',
        tw_enabled
    )
    print(f"\n{C_GREEN}[You unlocked all 4 Keepsakes! You can keep playing in Endless Mode.]{C_RESET}")
    print(f"{C_PINK}===================================================={C_RESET}")


def init_memory_db(db_path=None):
    """Initialize the SQLite persistent memory database and create the memories table if needed."""
    target_db = db_path or MEMORY_DB_FILE
    with _DB_LOCK:
        try:
            with contextlib.closing(sqlite3.connect(target_db, timeout=5.0)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_key TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        fact TEXT NOT NULL,
                        raw_value TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        except sqlite3.Error:
            pass


def infer_category_and_fact(memory_key, raw_value):
    """Infer a canonical category and human-readable fact sentence from a memory_key and raw_value."""
    key_lower = str(memory_key).lower()
    val_str = str(raw_value).strip()

    if any(w in key_lower for w in ("music", "song", "singer", "artist", "band", "melody", "genre")):
        return "Music preference", f"User loves {val_str}."
    if any(w in key_lower for w in ("movie", "film", "anime", "series", "show", "game")):
        return "Favourite movies and games", f"User's {key_lower.replace('_', ' ')} is {val_str}."
    if any(w in key_lower for w in ("passion", "hobby", "hobbies", "sport", "interest")):
        return "Hobbies and interests", f"User enjoys {val_str}."
    if any(w in key_lower for w in ("birthday", "date_", "anniversary", "event_", "deadline")):
        return "Important dates and events", f"Important date/event ({key_lower.replace('_', ' ')}): {val_str}."
    if any(w in key_lower for w in ("goal", "dream", "plan", "study_field", "ambition", "career")):
        return "Personal goals and plans", f"User's {key_lower.replace('_', ' ')} is {val_str}."
    if any(w in key_lower for w in ("person_", "friend", "family", "brother", "sister", "mom", "dad", "teammate")):
        return "Important people", f"Important person ({key_lower.replace('person_', '').replace('_', ' ')}): {val_str}."
    if any(w in key_lower for w in ("relationship", "nickname", "pet_name", "together")):
        return "Relationship preferences", f"Relationship preference ({key_lower.replace('_', ' ')}): {val_str}."
    if any(w in key_lower for w in ("experience", "note_", "achievement", "trip_memory")):
        return "Important experiences", f"User shared: {val_str}."
    return "Personal preferences", f"User's {key_lower.replace('_', ' ')} is {val_str}."


def upsert_long_term_memory(
    memory_key,
    category,
    fact,
    raw_value,
    memories_dict=None,
    db_path=None,
    updated_at=None,
    allow_overwrite=True
):
    """
    Insert or update a persistent memory in SQLite:
      - Prevents duplicate memory entries.
      - Never overwrites a newer SQLite memory with an older timestamp (`updated_at`).
      - If `allow_overwrite=False`, only inserts if `memory_key` does not yet exist in SQLite.
      - Synchronizes `memories_dict` with the latest authoritative value.
    """
    if not memory_key or not raw_value:
        return False
    clean_key = re.sub(r"[^a-z0-9_]", "_", str(memory_key).strip().lower()).strip("_")
    clean_val = str(raw_value).strip().rstrip(".!?")
    if not clean_key or not clean_val:
        return False

    if not category:
        category, default_fact = infer_category_and_fact(clean_key, clean_val)
        fact = fact or default_fact
    elif not fact:
        _, fact = infer_category_and_fact(clean_key, clean_val)

    now_ts = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_db = db_path or MEMORY_DB_FILE
    init_memory_db(target_db)

    authoritative_val = clean_val
    with _DB_LOCK:
        try:
            with contextlib.closing(sqlite3.connect(target_db, timeout=5.0)) as conn:
                cur = conn.execute(
                    "SELECT memory_key, raw_value, updated_at FROM memories WHERE LOWER(memory_key) = LOWER(?)",
                    (clean_key,)
                )
                existing = cur.fetchone()
                if existing:
                    existing_key, existing_val, existing_ts = existing[0], str(existing[1]), str(existing[2] or "")
                    # Never overwrite newer memories with older information, or when allow_overwrite is False
                    if not allow_overwrite or (updated_at is not None and existing_ts and existing_ts > str(updated_at)):
                        authoritative_val = existing_val
                        if isinstance(memories_dict, dict):
                            memories_dict[clean_key] = authoritative_val
                            if clean_key in ("favorite_music", "favorite_songs", "favorite_music_genre", "favorite_genre") and "favorite_song" not in memories_dict:
                                memories_dict["favorite_song"] = authoritative_val
                        return False

                    # Avoid redundant write if value is identical and no explicit newer timestamp was supplied
                    if existing_val.lower() == clean_val.lower() and updated_at is None:
                        if isinstance(memories_dict, dict):
                            memories_dict[clean_key] = existing_val
                        return True

                # Also check if an identical fact already exists under another key to prevent duplicates
                cur_dup = conn.execute(
                    "SELECT memory_key, raw_value FROM memories WHERE LOWER(fact) = LOWER(?) AND LOWER(memory_key) != LOWER(?)",
                    (fact.strip(), clean_key)
                )
                if cur_dup.fetchone() is not None and clean_key.startswith("note_"):
                    return True

                conn.execute(
                    """
                    INSERT INTO memories (memory_key, category, fact, raw_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_key) DO UPDATE SET
                        category = excluded.category,
                        fact = excluded.fact,
                        raw_value = excluded.raw_value,
                        updated_at = excluded.updated_at
                    """,
                    (clean_key, category, fact.strip(), clean_val, now_ts, now_ts)
                )
                conn.commit()
        except sqlite3.Error:
            pass

    if isinstance(memories_dict, dict):
        memories_dict[clean_key] = authoritative_val
        if clean_key in ("favorite_music", "favorite_songs", "favorite_music_genre", "favorite_genre") and "favorite_song" not in memories_dict:
            memories_dict["favorite_song"] = authoritative_val

    return True


def get_all_saved_memories(db_path=None):
    """Return all persistent memories from SQLite ordered by updated_at descending."""
    target_db = db_path or MEMORY_DB_FILE
    init_memory_db(target_db)
    records = []
    with _DB_LOCK:
        try:
            with contextlib.closing(sqlite3.connect(target_db, timeout=5.0)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT id, memory_key, category, fact, raw_value, created_at, updated_at FROM memories ORDER BY updated_at DESC, id DESC"
                )
                for row in cur.fetchall():
                    records.append(dict(row))
        except sqlite3.Error:
            pass
    return records


def load_memories_dict_from_db(db_path=None):
    """Load key -> raw_value pairs from SQLite for state['memories'] compatibility."""
    records = get_all_saved_memories(db_path=db_path)
    result = {}
    for rec in reversed(records):
        k = rec["memory_key"]
        v = rec["raw_value"]
        if is_valid_memory_value(k, v) or k.startswith(("note_", "experience_", "important_date_", "person_", "personal_goal", "relationship_", "recent_emotional_context")):
            result[k] = v
            if k in ("favorite_music", "favorite_songs", "favorite_music_genre", "favorite_genre") and "favorite_song" not in result:
                result["favorite_song"] = v
    return result


def synchronize_memories(memories_dict, db_path=None):
    """
    Two-way synchronization between `memories_dict` and the persistent SQLite database:
      1. Loads all latest saved memories from SQLite into `memories_dict` (never overwriting newer DB records with stale dict entries).
      2. Saves any brand-new keys present in `memories_dict` (that do not yet exist in SQLite) into SQLite.
    """
    if not isinstance(memories_dict, dict):
        return load_memories_dict_from_db(db_path=db_path)

    target_db = db_path or MEMORY_DB_FILE
    init_memory_db(target_db)
    sanitize_memories(memories_dict)

    db_records = get_all_saved_memories(db_path=target_db)
    db_map = {r["memory_key"]: r["raw_value"] for r in db_records}

    # 1. Insert any brand-new keys from memories_dict into SQLite without overwriting existing DB records
    for k, v in list(memories_dict.items()):
        if not v:
            continue
        clean_k = re.sub(r"[^a-z0-9_]", "_", str(k).strip().lower()).strip("_")
        if clean_k not in db_map:
            cat, fact = infer_category_and_fact(clean_k, v)
            upsert_long_term_memory(
                clean_k, cat, fact, v, memories_dict=None, db_path=target_db, allow_overwrite=False
            )
            db_map[clean_k] = str(v).strip().rstrip(".!?")

    # 2. Ensure memories_dict has the latest authoritative values from SQLite
    for k, v in db_map.items():
        if is_valid_memory_value(k, v) or k.startswith(("note_", "experience_", "important_date_", "person_", "personal_goal", "relationship_", "recent_emotional_context")):
            memories_dict[k] = v
            if k in ("favorite_music", "favorite_songs", "favorite_music_genre", "favorite_genre") and "favorite_song" not in memories_dict:
                memories_dict["favorite_song"] = v

    return memories_dict


def sync_dict_to_memory_db(memories_dict, db_path=None):
    """Alias for synchronize_memories that safely syncs without overwriting newer SQLite records."""
    synchronize_memories(memories_dict, db_path=db_path)


def delete_saved_memory(memory_key, memories_dict=None, db_path=None):
    """Delete a memory by key from both SQLite and the in-memory dictionary."""
    if not memory_key:
        return False
    clean_key = str(memory_key).strip()
    target_db = db_path or MEMORY_DB_FILE
    init_memory_db(target_db)
    try:
        with contextlib.closing(sqlite3.connect(target_db)) as conn:
            conn.execute("DELETE FROM memories WHERE LOWER(memory_key) = LOWER(?)", (clean_key,))
            conn.commit()
    except sqlite3.Error:
        pass
    if isinstance(memories_dict, dict):
        memories_dict.pop(clean_key, None)
        if clean_key == "favorite_music":
            memories_dict.pop("favorite_song", None)
    return True


def clear_all_saved_memories(memories_dict=None, db_path=None):
    """Erase all stored memories from SQLite (used on Reset Save or fresh test setup)."""
    target_db = db_path or MEMORY_DB_FILE
    init_memory_db(target_db)
    try:
        with contextlib.closing(sqlite3.connect(target_db)) as conn:
            conn.execute("DELETE FROM memories")
            conn.commit()
    except sqlite3.Error:
        pass
    global last_topic, recent_topics
    last_topic = None
    recent_topics.clear()
    if isinstance(memories_dict, dict):
        memories_dict.clear()


def retrieve_relevant_memories(user_message, saved_memories=None, limit=6, db_path=None):
    """
    Retrieve relevant long-term memories from SQLite and saved_memories based on semantic
    keyword/category overlap with `user_message` plus recency.
    Returns a list of memory dicts: [{'memory_key', 'category', 'fact', 'raw_value', 'updated_at'}, ...].
    """
    if isinstance(saved_memories, dict) and saved_memories:
        sync_dict_to_memory_db(saved_memories, db_path=db_path)

    all_records = get_all_saved_memories(db_path=db_path)
    # If saved_memories was passed as an isolated dict with specific keys, filter or merge
    if isinstance(saved_memories, dict):
        known_keys = {r["memory_key"] for r in all_records}
        for k, v in saved_memories.items():
            if k not in known_keys:
                cat, fact = infer_category_and_fact(k, v)
                all_records.append({
                    "memory_key": k,
                    "category": cat,
                    "fact": fact,
                    "raw_value": str(v),
                    "created_at": "",
                    "updated_at": ""
                })

    if not all_records:
        return []

    msg_lower = (user_message or "").lower()
    msg_words = set(re.findall(r"\b\w+\b", msg_lower))

    category_triggers = {
        "Music preference": {"music", "song", "songs", "singer", "melody", "melodies", "listen", "listening", "playlist", "band", "artist", "genre"},
        "Favourite movies and games": {"movie", "movies", "film", "anime", "show", "series", "game", "games", "play", "playing", "watch"},
        "Hobbies and interests": {"hobby", "hobbies", "interest", "interests", "free", "weekend", "relax", "sport", "badminton", "coding", "passion"},
        "Important dates and events": {"date", "when", "birthday", "exam", "event", "anniversary", "schedule", "tomorrow", "monday", "friday"},
        "Personal goals and plans": {"goal", "goals", "dream", "plan", "plans", "future", "study", "studying", "career", "travel", "trip", "destination"},
        "Important people": {"who", "friend", "friends", "best", "brother", "sister", "mom", "dad", "family", "teammate", "person"},
        "Relationship preferences": {"call", "nickname", "us", "together", "relationship", "date"},
        "Important experiences": {"remember", "experience", "happened", "won", "built", "trip", "story"},
        "Personal preferences": {"food", "eat", "drink", "favorite", "favourite", "like", "love", "prefer", "hometown", "live", "from", "color"},
    }

    scored = []
    for idx, rec in enumerate(all_records):
        score = 0
        rec_text = f"{rec['memory_key']} {rec['category']} {rec['fact']} {rec['raw_value']}".lower()
        rec_words = set(re.findall(r"\b\w+\b", rec_text))
        overlap = len(msg_words & (rec_words - CONVERSATIONAL_STOP_WORDS))
        score += overlap * 3

        trig_words = category_triggers.get(rec["category"], set())
        if msg_words & trig_words:
            score += 4

        # Small recency tiebreaker (all_records is already sorted newest first)
        score += max(0, 1.0 - (idx * 0.05))
        scored.append((score, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Deduplicate alias favorite_song if favorite_music has the same value
    selected = []
    seen_sigs = set()
    for _, rec in scored:
        sig = (rec["category"], rec["raw_value"].strip().lower())
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        selected.append(rec)
        if len(selected) >= limit:
            break
    return selected


def view_keepsakes(keepsakes, memories, partner_name, player_name):
    """Display all unlocked milestone keepsakes and structured SQLite long-term memories."""
    print(f"\n{C_CYAN}=== Memory Box with {partner_name} ({len(keepsakes)}/4 Keepsakes Unlocked) ==={C_RESET}")
    if not keepsakes:
        print("No keepsakes unlocked yet! Reach 60+ Affection or Day 7 to earn your first memory.")
    else:
        for idx, item in enumerate(keepsakes, start=1):
            print(f"{C_YELLOW}{idx}. {item['title']}{C_RESET}")
            print(f"   -> {item['description']}")

    sync_dict_to_memory_db(memories)
    db_records = get_all_saved_memories()
    print(f"\n{C_CYAN}=== Long-Term SQLite Memories ({len(db_records)} Saved in {MEMORY_DB_FILE}) ==={C_RESET}")
    if not db_records and not memories:
        print("None yet! In Non-Stop Free Chat, try saying 'I love Malayalam melodies' or 'My favorite food is biryani'.")
    elif db_records:
        for rec in db_records:
            ts = f" ({rec['updated_at']})" if rec.get("updated_at") else ""
            print(f"  * {C_YELLOW}[{rec['category']}]{C_RESET} {C_BOLD}{rec['fact']}{C_RESET} {C_CYAN}[key: {rec['memory_key']}]{C_RESET}{ts}")
    else:
        for key, val in memories.items():
            label = key.replace("_", " ").title()
            print(f"  * {C_BOLD}{label}:{C_RESET} {val}")


# Common greetings, pronouns, and conversational tokens that should NEVER be saved as a bare favorite fact
CONVERSATIONAL_STOP_WORDS = {
    "hi", "hello", "hey", "yo", "sup", "morning", "evening", "goodnight", "night",
    "darling", "babe", "baby", "honey", "sweetheart", "dear", "love", "cutie",
    "you", "your", "yours", "yourself", "we", "us", "our",
    "what", "why", "how", "when", "where", "who", "which",
    "did", "do", "does", "done", "are", "is", "was", "were", "have", "had", "has",
    "will", "would", "can", "could", "should", "shall",
    "yes", "yeah", "yep", "no", "nope", "nah", "maybe", "idk", "nothing", "none",
    "ok", "okay", "sure", "fine", "thanks", "thank", "please", "sorry",
    "brought", "bought", "got", "gave", "give", "made", "make", "went", "going",
    "study", "studied", "exam", "exams", "test", "tomorrow", "today", "yesterday"
}


def is_valid_memory_value(key, value):
    """Return True if value looks like a genuine personal fact rather than a greeting, question, or chat sentence."""
    if not value or not isinstance(value, str):
        return False
    cleaned = value.strip().rstrip(".!?")
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 65:
        return False
    if "?" in value:
        return False

    lower = cleaned.lower()
    tokens = re.findall(r"\b\w+\b", lower)
    if not tokens or len(tokens) > 8:
        return False

    greeting_prefixes = (
        "hi ", "hello ", "hey ", "good morning", "good evening", "good night",
        "did you", "do you", "are you", "have you", "will you", "can you",
        "what ", "why ", "how ", "when ", "where ", "i had ", "i have ", "i brought", "i bought"
    )
    if lower in CONVERSATIONAL_STOP_WORDS or lower.startswith(greeting_prefixes):
        return False

    # Allow structured keys while guarding bare pending-question answers against stop-words
    exempt_prefixes = ("note", "experience", "important_date", "person_", "personal_goal", "relationship_", "recent_emotional_context")
    if not str(key).startswith(exempt_prefixes) and any(t in CONVERSATIONAL_STOP_WORDS for t in tokens):
        return False

    return True


def sanitize_memories(memories):
    """Remove any accidentally captured greetings or conversational sentences from saved memories."""
    if not isinstance(memories, dict):
        return
    exempt_prefixes = ("note_", "experience_", "important_date_", "person_", "personal_goal", "relationship_", "recent_emotional_context")
    keys_to_delete = [
        k for k, v in memories.items()
        if not k.startswith(exempt_prefixes) and not is_valid_memory_value(k, str(v))
    ]
    for k in keys_to_delete:
        del memories[k]


# Category synonym groups so answering 'favorite music' also satisfies 'favorite_song', etc.
MEMORY_CATEGORY_SYNONYMS = {
    "favorite_food": {"favorite_food", "favorite_dish", "favorite_meal", "favorite_snack", "favorite_cuisine"},
    "favorite_song": {"favorite_song", "favorite_music", "favorite_music_genre", "favorite_singer", "favorite_artist", "favorite_band", "favorite_genre", "favorite_songs"},
    "favorite_movie": {"favorite_movie", "favorite_movies", "favorite_film", "favorite_anime", "favorite_show"},
    "passion": {"passion", "favorite_hobby", "favorite_hobbies", "favorite_game", "favorite_games", "favorite_sport", "favorite_movie", "favorite_movies"},
    "dream_destination": {"dream_destination", "favorite_place", "favorite_city", "favorite_country", "favorite_travel_spot"},
    "study_field": {"study_field", "favorite_subject", "major", "course"},
}


def get_chat_history_limit(state=None, max_history=None):
    """Return the configurable rolling chat_history window size (defaults to 10 messages)."""
    if isinstance(max_history, int) and max_history > 0:
        return max_history
    if isinstance(state, dict) and isinstance(state.get("chat_history_limit"), int) and state["chat_history_limit"] > 0:
        return state["chat_history_limit"]
    env_limit = os.environ.get("CHAT_HISTORY_LIMIT", "").strip()
    if env_limit.isdigit() and int(env_limit) > 0:
        return int(env_limit)
    return DEFAULT_CHAT_HISTORY_LIMIT


def normalize_chat_history(chat_history, partner_name="Aiko", player_name="Alex", max_messages=DEFAULT_CHAT_HISTORY_LIMIT):
    """
    Convert chat_history (list of {'role', 'content'} dicts or 'Speaker: text' strings)
    into a rolling window of at most `max_messages` (default 10) OpenAI-compatible
    {'role': 'user'|'assistant', 'content': '...'} dicts.
    """
    normalized = []
    if not chat_history or not isinstance(chat_history, list):
        return normalized

    partner_prefix = f"{partner_name.lower()}:"
    player_prefix = f"{player_name.lower()}:"

    for entry in chat_history:
        if isinstance(entry, dict) and "role" in entry and "content" in entry:
            role = entry["role"] if entry["role"] in ("user", "assistant", "system") else "user"
            content = str(entry["content"]).strip()
            if content:
                normalized.append({"role": role, "content": content})
        elif isinstance(entry, str):
            line = entry.strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith(partner_prefix):
                content = line.split(":", 1)[1].strip().strip('"')
                normalized.append({"role": "assistant", "content": content})
            elif low.startswith(player_prefix):
                content = line.split(":", 1)[1].strip()
                normalized.append({"role": "user", "content": content})
            else:
                normalized.append({"role": "user", "content": line})

    limit = max_messages if (isinstance(max_messages, int) and max_messages > 0) else DEFAULT_CHAT_HISTORY_LIMIT
    return normalized[-limit:]


def append_chat_turn(chat_history, user_message, assistant_reply, max_messages=DEFAULT_CHAT_HISTORY_LIMIT):
    """
    Store both the user message and girlfriend response in chat_history using structured
    {'role': 'user'|'assistant', 'content': '...'} dicts and trim in-place to the rolling window (default 10).
    Avoids duplicating a turn if the caller already appended the exact same message.
    """
    if not isinstance(chat_history, list):
        return []

    limit = max_messages if (isinstance(max_messages, int) and max_messages > 0) else DEFAULT_CHAT_HISTORY_LIMIT

    def _matches_last(role, text):
        if not chat_history:
            return False
        last = chat_history[-1]
        if isinstance(last, dict):
            return last.get("role") == role and str(last.get("content", "")).strip() == text.strip()
        if isinstance(last, str):
            return last.strip().endswith(text.strip())
        return False

    if user_message and not _matches_last("user", user_message):
        if not (
            len(chat_history) >= 2
            and isinstance(chat_history[-2], dict)
            and chat_history[-2].get("role") == "user"
            and str(chat_history[-2].get("content", "")).strip() == user_message.strip()
        ):
            chat_history.append({"role": "user", "content": user_message.strip()})

    if assistant_reply and not _matches_last("assistant", assistant_reply):
        chat_history.append({"role": "assistant", "content": assistant_reply.strip()})

    if len(chat_history) > limit:
        del chat_history[:-limit]

    return chat_history


def extract_personal_fact(user_msg, memories):
    """
    Extract personal facts across all 9 Long-Term Memory categories from user_msg,
    supporting user corrections/updates, and persist them in both `memories` and SQLite.
    """
    if not user_msg or "?" in user_msg:
        return None, None

    # Strip leading correction markers ("actually, ", "no, ", "correction: ", "wait, ")
    msg_clean = user_msg.strip().rstrip(".!?")
    msg_clean = re.sub(
        r"^(?:actually|correction|update|no|wait|sorry|honestly|by the way|btw)[,:\s]+",
        "",
        msg_clean,
        flags=re.IGNORECASE
    ).strip()
    msg_clean = re.sub(r"\s+(?:now|instead|these days)$", "", msg_clean, flags=re.IGNORECASE).strip()

    # 10. Important experiences / explicit notes: "remember that <value>"
    rem_match = re.search(r"\bremember\s+that\s+(.+)", msg_clean, re.IGNORECASE)
    if rem_match:
        value = rem_match.group(1).strip()
        existing_notes = [k for k in (memories or {}) if k.startswith("note_") and str(memories.get(k, "")).lower() == value.lower()]
        if existing_notes:
            note_key = existing_notes[0]
        else:
            note_num = len([k for k in (memories or {}) if k.startswith("note_")]) + 1
            note_key = f"note_{note_num}"
        upsert_long_term_memory(note_key, "Important experiences", f"User shared: {value}.", value, memories_dict=memories)
        return "personal note", value

    # 1. Explicit "my favorite/favourite <category> is/are <value>"
    fav_match = re.search(
        r"\bmy\s+fav(?:ou?rite)?\s+([a-zA-Z\s]{2,22}?)\s+(?:is|are)\s+(.+)",
        msg_clean,
        re.IGNORECASE
    )
    if fav_match:
        category_raw = fav_match.group(1).strip().lower()
        value = fav_match.group(2).strip()
        key = f"favorite_{category_raw.replace(' ', '_')}"
        if len(value) <= 60:
            cat_name, fact_text = infer_category_and_fact(key, value)
            upsert_long_term_memory(key, cat_name, fact_text, value, memories_dict=memories)
            return f"favorite {category_raw}", value

    # 2. Music preference: "i like/love listening to <singer/music>"
    listen_match = re.search(
        r"\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+listening\s+to\s+(.+)",
        msg_clean,
        re.IGNORECASE
    )
    if listen_match:
        value = listen_match.group(1).strip()
        if len(value) <= 55:
            fact_text = f"User loves listening to {value}."
            upsert_long_term_memory("favorite_singer", "Music preference", fact_text, value, memories_dict=memories)
            return "favorite singer", value

    # 3. Movies and Games: "i love/like playing <game>" or "i love/like watching <movie/anime>"
    play_match = re.search(r"\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+playing\s+(.+)", msg_clean, re.IGNORECASE)
    if play_match:
        value = play_match.group(1).strip()
        if len(value.split()) <= 6:
            upsert_long_term_memory("favorite_game", "Favourite movies and games", f"User loves playing {value}.", value, memories_dict=memories)
            return "favorite game", value

    watch_match = re.search(r"\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+watching\s+(.+)", msg_clean, re.IGNORECASE)
    if watch_match:
        value = watch_match.group(1).strip()
        if len(value.split()) <= 6:
            upsert_long_term_memory("favorite_movie", "Favourite movies and games", f"User loves watching {value}.", value, memories_dict=memories)
            return "favorite movie or show", value

    # 4. Important dates & events: "my birthday is <val>" or "my <event> is on <val>"
    bday_match = re.search(r"\bmy\s+birthday\s+is\s+(?:on\s+)?(.+)", msg_clean, re.IGNORECASE)
    if bday_match:
        value = bday_match.group(1).strip()
        upsert_long_term_memory("birthday", "Important dates and events", f"User's birthday is {value}.", value, memories_dict=memories)
        return "birthday", value

    event_match = re.search(
        r"\bmy\s+(exam|interview|hackathon|anniversary|graduation|concert|competition|flight|trip)\s+is\s+(?:on\s+)?(.+)",
        msg_clean,
        re.IGNORECASE
    )
    if event_match:
        ev_type = event_match.group(1).strip().lower()
        value = event_match.group(2).strip()
        key = f"important_date_{ev_type}"
        upsert_long_term_memory(key, "Important dates and events", f"User's {ev_type} is {value}.", value, memories_dict=memories)
        return f"{ev_type} date", value

    # 5. Personal goals and plans: "my goal/dream/plan is <val>" or "i want to become <val>" or "i study <val>"
    goal_match = re.search(
        r"\b(?:my\s+(?:goal|dream|ambition|plan)\s+is\s+(?:to\s+)?|i\s+(?:want|plan|hope)\s+to\s+become\s+)(.+)",
        msg_clean,
        re.IGNORECASE
    )
    if goal_match:
        value = goal_match.group(1).strip()
        upsert_long_term_memory("personal_goal", "Personal goals and plans", f"User's personal goal is {value}.", value, memories_dict=memories)
        return "personal goal", value

    study_match = re.search(r"\bi\s+(?:am\s+studying|study)\s+(.+)", msg_clean, re.IGNORECASE)
    if study_match:
        value = study_match.group(1).strip()
        if not re.match(r"^(?:for\b|hard\b|now\b|today\b|tonight\b|tomorrow\b)", value, re.IGNORECASE):
            upsert_long_term_memory("study_field", "Personal goals and plans", f"User studies {value}.", value, memories_dict=memories)
            return "field of study", value

    # 6. Important people mentioned by the user: "my best friend/friend/brother/sister/mom/dad/teammate is <Name>"
    person_match = re.search(
        r"\bmy\s+(best\s+friend|friend|brother|sister|mom|mother|dad|father|roommate|teammate|cousin|mentor)(?:'s\s+name)?\s+is\s+([A-Za-z][A-Za-z\s]{1,25})$",
        msg_clean,
        re.IGNORECASE
    )
    if person_match:
        rel = person_match.group(1).strip().lower().replace(" ", "_")
        name_val = person_match.group(2).strip()
        key = f"person_{rel}"
        upsert_long_term_memory(key, "Important people", f"User's {rel.replace('_', ' ')} is {name_val}.", name_val, memories_dict=memories)
        return rel.replace("_", " "), name_val

    # 7. Relationship preferences: "call me <nickname>" or "you can call me <nickname>"
    nick_match = re.search(r"\b(?:you\s+can\s+|please\s+)?call\s+me\s+([A-Za-z0-9\s]{2,20})$", msg_clean, re.IGNORECASE)
    if nick_match:
        value = nick_match.group(1).strip()
        if value.lower() not in ("later", "tomorrow", "tonight", "maybe"):
            upsert_long_term_memory("preferred_nickname", "Relationship preferences", f"User likes to be called {value}.", value, memories_dict=memories)
            return "preferred nickname", value

    # 8. Hometown / location: "i live in <value>" or "i am from <value>" or "i'm from <value>"
    place_match = re.search(r"\bi(?:'m|\s+am|\s+live)\s+(?:from|in)\s+(.+)", msg_clean, re.IGNORECASE)
    if place_match:
        value = place_match.group(1).strip()
        upsert_long_term_memory("hometown", "Personal preferences", f"User is from {value}.", value, memories_dict=memories)
        return "hometown", value

    # 9. General "I love / I really like / I enjoy <value>" — smartly routed to Music, Movies/Games, Food, or Hobbies!
    like_match = re.search(r"\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+(.+)", msg_clean, re.IGNORECASE)
    if like_match:
        value = like_match.group(1).strip()
        val_lower = value.lower()
        if not re.search(r"\b(you|your|darling|babe|baby|sweetheart|talking|chatting|spending|when we|how you)\b", val_lower):
            if len(value.split()) <= 6:
                val_words = set(re.findall(r"\b\w+\b", val_lower))
                if val_words & {"melody", "melodies", "song", "songs", "music", "pop", "rock", "jazz", "lofi", "beats", "classical", "tracks", "malayalam", "hindi", "tamil", "anime ost"}:
                    fact_text = f"User loves {value}."
                    upsert_long_term_memory("favorite_music", "Music preference", fact_text, value, memories_dict=memories)
                    return "music preference", value
                if val_words & {"movie", "movies", "anime", "films", "series", "game", "games", "efootball", "valorant", "minecraft"}:
                    upsert_long_term_memory("favorite_game", "Favourite movies and games", f"User loves {value}.", value, memories_dict=memories)
                    return "favorite movie or game", value
                if val_words & {"biryani", "dosa", "pizza", "pasta", "ramen", "chocolate", "coffee", "tea", "matcha", "cake", "ice cream"}:
                    upsert_long_term_memory("favorite_food", "Personal preferences", f"User loves eating {value}.", value, memories_dict=memories)
                    return "favorite food", value
                upsert_long_term_memory("passion", "Hobbies and interests", f"User loves {value}.", value, memories_dict=memories)
                return "interest", value



    return None, None


def extract_facts_from_chat_history(chat_history, memories, partner_name="Aiko", player_name="Alex"):
    """
    Scan recent user messages in chat_history so facts mentioned in earlier turns
    (including answers to assistant follow-up questions) are retained in memory and SQLite.
    """
    if not chat_history:
        return
    norm = normalize_chat_history(chat_history, partner_name=partner_name, player_name=player_name)
    for idx, msg in enumerate(norm):
        if msg["role"] == "user":
            extract_personal_fact(msg["content"], memories)
            if idx > 0 and norm[idx - 1]["role"] == "assistant":
                prev_q = norm[idx - 1]["content"].lower()
                ans_clean = re.sub(
                    r"^(?:i\s+(?:really\s+)?(?:like|love|enjoy)\s+(?:listening\s+to\s+)?|it(?:'s| is)\s+|mostly\s+|probably\s+)",
                    "",
                    msg["content"].strip().rstrip(".!?"),
                    flags=re.IGNORECASE
                ).strip()
                if ans_clean and len(ans_clean.split()) <= 5 and "?" not in msg["content"]:
                    if any(w in prev_q for w in ["singer", "artist", "vocalist", "musician", "listen to most"]):
                        if "favorite_singer" not in memories:
                            upsert_long_term_memory(
                                "favorite_singer", "Music preference",
                                f"User loves listening to {ans_clean}.", ans_clean, memories_dict=memories
                            )
                    elif any(w in prev_q for w in ["favorite food", "favourite food", "dish"]):
                        if is_valid_memory_value("favorite_food", ans_clean) and "favorite_food" not in memories:
                            upsert_long_term_memory(
                                "favorite_food", "Personal preferences",
                                f"User's favorite food is {ans_clean}.", ans_clean, memories_dict=memories
                            )
                    elif any(w in prev_q for w in ["song or music", "favorite music", "favourite music", "music genre"]):
                        if is_valid_memory_value("favorite_song", ans_clean) and "favorite_music" not in memories:
                            upsert_long_term_memory(
                                "favorite_music", "Music preference",
                                f"User loves {ans_clean}.", ans_clean, memories_dict=memories
                            )
                    elif any(w in prev_q for w in ["movie", "film", "anime", "show", "watch"]):
                        if is_valid_memory_value("favorite_movie", ans_clean) and "favorite_movie" not in memories:
                            upsert_long_term_memory(
                                "favorite_movie", "Favourite movies and games",
                                f"User's favorite movie is {ans_clean}.", ans_clean, memories_dict=memories
                            )


def infer_topic_from_text(text):
    """Identify the specific or thematic topic from a single message string."""
    if not text or not isinstance(text, str):
        return None
    low = text.lower().strip()
    words = set(re.findall(r"\b\w+\b", low))

    # 1. Check specific technical/factual subject first
    subj = _extract_subject_phrase(text)
    if subj:
        return subj

    # 2. Check domain themes
    if words & {"music", "song", "songs", "singer", "album", "playlist", "malayalam", "melody", "melodies", "band", "listen", "listening", "vineeth"}:
        return "music"
    if words & {"food", "eat", "dish", "biryani", "dosa", "pizza", "lunch", "dinner", "breakfast", "cafe", "tea", "coffee", "matcha", "snack"}:
        return "food"
    if words & {"code", "coding", "python", "java", "c++", "javascript", "algorithm", "bug", "debug", "program", "programming", "software", "recursion"}:
        return "coding"
    if words & {"exam", "exams", "study", "studying", "test", "class", "notes", "semester", "equation", "equations", "calculus", "laplace", "fourier"}:
        return "study"
    if words & {"movie", "movies", "anime", "film", "series", "show", "game", "games", "efootball", "play", "playing"}:
        return "movies and games"
    if words & {"travel", "trip", "vacation", "beach", "destination", "visit", "flight"}:
        return "travel"
    if words & {"goal", "goals", "dream", "ambition", "career", "future", "plan", "plans", "powertrain", "ev"}:
        return "goals and plans"
    if words & {"tired", "stressed", "sad", "exhausted", "lonely", "nervous", "anxious", "worried", "upset", "overwhelmed"}:
        return "emotional support"
    if words & {"badminton", "football", "hobby", "hobbies", "guitar", "reading", "sport"}:
        return "hobbies"
    if words & {"friend", "brother", "sister", "mom", "dad", "family", "teammate", "cousin"}:
        return "important people"
    if words & {"love", "darling", "babe", "sweetheart", "kiss", "hug", "date", "us", "relationship", "together"}:
        return "relationship"
    return None


def detect_meta_conversation_type(user_msg):
    """
    Recognize meta-conversational statements about the conversation itself, such as:
      - 'already_told_or_repeated': "I already told you that.", "You asked me this yesterday.", "You already asked me that."
      - 'recall_discussion': "Remember what we discussed?", "What were we talking about?", "Do you remember what we discussed?"
      - 'continue_previous': "Continue our previous conversation.", "Let's talk about that again.", "Back to what we were saying."
      - 'confirm_meaning': "That's what I meant.", "Exactly what I meant.", "Yes, that's what I meant."
    Returns the meta-type string or None.
    """
    if not user_msg or not isinstance(user_msg, str):
        return None
    low = user_msg.lower().strip().rstrip(".!?")

    # 1. Repeated question / already answered
    repeated_patterns = (
        "already told you",
        "told you that",
        "told you before",
        "already said that",
        "already answered",
        "you asked me this",
        "you already asked",
        "asked me that already",
        "asked me this yesterday",
        "asked me that yesterday",
        "repeating yourself",
        "why are you asking again",
        "didn't you just ask",
        "didnt you just ask",
    )
    if any(p in low for p in repeated_patterns):
        return "already_told_or_repeated"

    # 2. Remember what we discussed / what were we talking about
    recall_patterns = (
        "remember what we discussed",
        "remember what we talked about",
        "what we discussed",
        "what were we talking about",
        "what were we just talking about",
        "what did we discuss",
        "do you remember our conversation",
    )
    if any(p in low for p in recall_patterns):
        return "recall_discussion"

    # 3. Continue previous conversation / talk about that again
    continue_patterns = (
        "continue our previous conversation",
        "continue the previous conversation",
        "continue our conversation",
        "continue what we were",
        "let's talk about that again",
        "lets talk about that again",
        "talk about that again",
        "back to what we were",
        "go back to what we were",
        "go back to our previous",
        "where were we",
        "pick up where we left off",
    )
    if any(p in low for p in continue_patterns):
        return "continue_previous"

    # 4. Confirming meaning ("That's what I meant.")
    confirm_patterns = (
        "that's what i meant",
        "thats what i meant",
        "exactly what i meant",
        "that is what i meant",
        "yes that's what i meant",
        "yeah that's what i meant",
        "you got what i meant",
    )
    if any(p in low for p in confirm_patterns):
        return "confirm_meaning"

    return None


def update_conversation_state(user_msg, chat_history=None, saved_memories=None, state=None, partner_name="Aiko", player_name="Alex"):
    """
    Maintain `last_topic`, `recent_topics`, current topic identification, and topic-change detection
    across turns. Updates both module-level `last_topic` / `recent_topics` and `state` dict.
    """
    global last_topic, recent_topics

    norm = normalize_chat_history(chat_history or [], partner_name=partner_name, player_name=player_name)

    # Seed recent_topics from chat_history if needed
    hist_topics = []
    for m in norm:
        t = infer_topic_from_text(m.get("content", ""))
        if t and (not hist_topics or hist_topics[-1] != t):
            hist_topics.append(t)

    if isinstance(state, dict):
        state_recent = state.get("recent_topics")
        if isinstance(state_recent, list):
            for t in state_recent:
                if t and (not recent_topics or recent_topics[-1] != t):
                    recent_topics.append(t)
        if state.get("last_topic") and not last_topic:
            last_topic = state["last_topic"]

    for t in hist_topics:
        if not recent_topics or recent_topics[-1] != t:
            recent_topics.append(t)

    previous_topic = last_topic or (hist_topics[-1] if hist_topics else None)
    meta_type = detect_meta_conversation_type(user_msg)
    inferred_current = infer_topic_from_text(user_msg)

    # If the user asks to return to an earlier topic ("Let's talk about that again" / "Continue our previous conversation")
    if meta_type in ("continue_previous", "recall_discussion"):
        if len(recent_topics) >= 2 and recent_topics[-1] == previous_topic:
            # If they switched topics and want to go back, or want the active topic
            current_topic = recent_topics[-1]
        else:
            current_topic = previous_topic or (recent_topics[-1] if recent_topics else None)
        topic_changed = False
    elif meta_type in ("already_told_or_repeated", "confirm_meaning"):
        current_topic = previous_topic or inferred_current
        topic_changed = False
    elif inferred_current:
        current_topic = inferred_current
        topic_changed = bool(previous_topic and current_topic != previous_topic)
    else:
        # Maintain continuity with previous_topic when user sends a follow-up or short reply
        current_topic = previous_topic
        topic_changed = False

    if current_topic:
        last_topic = current_topic
        if not recent_topics or recent_topics[-1] != current_topic:
            recent_topics.append(current_topic)
        if len(recent_topics) > 10:
            del recent_topics[:-10]

    if isinstance(state, dict):
        state["previous_topic"] = previous_topic
        state["last_topic"] = last_topic
        state["recent_topics"] = list(recent_topics)
        state["topic_changed"] = topic_changed

    return {
        "current_topic": current_topic,
        "previous_topic": previous_topic,
        "last_topic": last_topic,
        "recent_topics": list(recent_topics),
        "topic_changed": topic_changed,
        "meta_type": meta_type,
    }


def extract_recent_conversation_context(chat_history, partner_name="Aiko", player_name="Alex"):
    """
    Analyze the rolling chat_history window to track:
      - last_assistant_message / last_assistant_question
      - last_user_message
      - active_topic (most recent topic in chat_history or module last_topic)
      - recent_topics (ordered list of topics discussed across recent turns)
      - asked_questions (set of lowercase question strings already asked by the assistant)
    """
    norm = normalize_chat_history(chat_history, partner_name=partner_name, player_name=player_name)
    last_assistant_msg = ""
    last_assistant_q = ""
    last_user_msg = ""
    asked_questions = set()
    topics_in_window = []

    for m in norm:
        if m["role"] == "assistant":
            last_assistant_msg = m["content"]
            if "?" in m["content"]:
                last_assistant_q = m["content"]
                asked_questions.add(m["content"].lower())
        elif m["role"] == "user":
            last_user_msg = m["content"]
        t = infer_topic_from_text(m["content"])
        if t and (not topics_in_window or topics_in_window[-1] != t):
            topics_in_window.append(t)

    active_topic = topics_in_window[-1] if topics_in_window else last_topic

    return {
        "normalized": norm,
        "last_assistant_message": last_assistant_msg,
        "last_assistant_question": last_assistant_q,
        "last_user_message": last_user_msg,
        "active_topic": active_topic,
        "recent_topics": topics_in_window or list(recent_topics),
        "asked_questions": asked_questions,
    }


def handle_meta_conversation_reply(user_msg, meta_type, chat_history, memories, state, partner_name="Aiko", player_name="Alex"):
    """
    Generate a natural, context-aware response for meta-conversational statements:
      - 'I already told you that.' / 'You asked me this yesterday.'
      - 'Remember what we discussed?'
      - 'Continue our previous conversation.' / 'Let's talk about that again.'
      - 'That's what I meant.'
    """
    ctx = extract_recent_conversation_context(chat_history, partner_name=partner_name, player_name=player_name)
    norm = ctx["normalized"]
    active_t = last_topic or ctx["active_topic"]
    all_topics = list(recent_topics) if recent_topics else ctx["recent_topics"]

    # Find the most relevant remembered fact or recent user statement
    fact_summary = None
    if active_t in ("music", "malayalam") or (memories and any(k in memories for k in ("favorite_music", "favorite_song", "favorite_singer"))):
        music_val = (memories or {}).get("favorite_music") or (memories or {}).get("favorite_song")
        singer_val = (memories or {}).get("favorite_singer")
        if music_val and singer_val:
            fact_summary = f"you love {music_val} and listening to {singer_val}"
        elif music_val:
            fact_summary = f"you love {music_val}"
        elif singer_val:
            fact_summary = f"you love listening to {singer_val}"
    if not fact_summary and memories:
        # Use the most recently added/updated memory
        last_k, last_v = list(memories.items())[-1]
        fact_summary = f"your {last_k.replace('_', ' ')} is {last_v}"
    if not fact_summary:
        # Fall back to the last non-meta user statement in chat_history
        prior_user_msgs = [
            m["content"] for m in norm
            if m["role"] == "user" and detect_meta_conversation_type(m["content"]) is None
        ]
        if prior_user_msgs:
            fact_summary = f"'{prior_user_msgs[-1]}'"

    if meta_type == "already_told_or_repeated":
        if fact_summary:
            return (
                f"Oh, silly me—you're completely right, {player_name}! I got carried away and repeated myself. "
                f"You already told me that {fact_summary}—I promise I really do remember!",
                2,
                "Blushing"
            )
        return (
            f"Oops, my bad, {player_name}! You're totally right—I accidentally asked you that again. "
            f"Sorry for repeating myself! Tell me what's on your mind now.",
            2,
            "Blushing"
        )

    if meta_type == "recall_discussion":
        if all_topics:
            topics_str = ", ".join(all_topics[-3:])
            detail_clause = f" (and how {fact_summary})" if fact_summary else ""
            return (
                f"Of course I remember what we discussed, {player_name}! We were talking about {topics_str}{detail_clause}. "
                f"Want to keep going with {all_topics[-1]}?",
                2,
                "Touched"
            )
        if fact_summary:
            return (
                f"I sure do, {player_name}! We were talking about how {fact_summary}. Want to dive back into that?",
                2,
                "Touched"
            )
        return (
            f"We were just getting into our conversation, {player_name}! Tell me which part you want to explore next.",
            2,
            "Curious"
        )

    if meta_type == "continue_previous":
        # If there are multiple recent topics and the user wants to return to an earlier topic or continue the current one
        low = user_msg.lower()
        target_topic = active_t
        if ("previous" in low or "again" in low or "back" in low) and len(all_topics) >= 2:
            # Pick the most informative topic (e.g. if they briefly shifted to casual and want the substantive topic back)
            target_topic = all_topics[-1] if all_topics[-1] not in ("relationship", "casual") else all_topics[-2]

        if target_topic and target_topic in KNOWLEDGE_BASE:
            kb_entry = KNOWLEDGE_BASE[target_topic]
            return (
                f"Let's jump right back into {target_topic}, {player_name}! {kb_entry['how_used']} "
                f"What part of {target_topic} were you thinking about next?",
                2,
                "Curious"
            )
        if target_topic:
            detail_clause = f"—especially since {fact_summary}" if fact_summary else ""
            return (
                f"Let's pick right back up on {target_topic}, {player_name}{detail_clause}! What else were you thinking about it?",
                2,
                "Happy"
            )
        if fact_summary:
            return (
                f"Let's continue right where we left off, {player_name}! We were talking about {fact_summary}—tell me more!",
                2,
                "Happy"
            )
        return (
            f"I'm right here with you, {player_name}! Let's pick up right where we left off—what were you going to say next?",
            2,
            "Happy"
        )

    if meta_type == "confirm_meaning":
        topic_phrase = f" about {active_t}" if active_t else ""
        return (
            f"Aha, I'm glad we're on the exact same wavelength{topic_phrase}, {player_name}! It makes total sense now—tell me more!",
            2,
            "Happy"
        )

    return None


def parse_pending_answer(pending_key, pending_label, user_msg, memories):
    """
    Validate whether user_msg is actually answering the pending proactive question.
    Returns (saved_label, saved_val) if valid, or (None, None) if the user changed the subject,
    said a greeting ('hi my darling'), asked a question, or used a meta-conversation phrase.
    """
    if not pending_key or not user_msg:
        return None, None
    if detect_meta_conversation_type(user_msg) is not None:
        return None, None

    explicit_label, explicit_val = extract_personal_fact(user_msg, memories)
    if explicit_label and explicit_val:
        return explicit_label, explicit_val

    cleaned_ans = re.sub(
        r"^(?:it(?:'s| is)|my fav(?:ou?rite)? .*? is|i (?:really )?(?:like|love|enjoy|study|prefer)|probably|definitely|hmm|well)\s+",
        "",
        user_msg.strip().rstrip(".!?"),
        flags=re.IGNORECASE
    ).strip()

    if is_valid_memory_value(pending_key, cleaned_ans):
        cat_name, fact_text = infer_category_and_fact(pending_key, cleaned_ans)
        upsert_long_term_memory(pending_key, cat_name, fact_text, cleaned_ans, memories_dict=memories)
        return pending_label, cleaned_ans

    return None, None


def get_proactive_question(memories, player_name, chat_history=None):
    """
    Find a personal fact she doesn't know yet and hasn't already asked about in chat_history.
    Prevents repetitive questions when a synonym key (e.g. 'favorite_music' for 'favorite_song')
    or recent conversation turn already covered that topic.
    """
    if memories is None:
        memories = {}
    ctx = extract_recent_conversation_context(chat_history or [], player_name=player_name)
    recent_chat_text = " ".join(m["content"].lower() for m in ctx["normalized"])

    questions_to_learn = [
        (
            "favorite_food",
            "favorite food",
            f"Hey {player_name}, I was just wondering—what is your absolute favorite food?",
            ("favorite food", "favourite food", "biryani", "dosa", "pizza")
        ),
        (
            "favorite_song",
            "favorite song",
            f"Tell me something, {player_name}: what's a song or music style you never get tired of listening to?",
            ("favorite music", "favourite music", "favorite song", "favourite song", "never get tired of listening", "melodies")
        ),
        (
            "passion",
            "favorite hobby",
            f"When you have a free evening to relax, {player_name}, what's your favorite hobby or game?",
            ("favorite hobby", "favourite hobby", "favorite game", "free evening to relax")
        ),
        (
            "dream_destination",
            "dream travel spot",
            f"If we could pack our bags and travel anywhere together tomorrow, {player_name}, where would you want to go?",
            ("pack our bags", "dream destination", "travel anywhere together")
        ),
        (
            "study_field",
            "field of study or project",
            f"What subject or project have you been spending the most time working on lately, {player_name}?",
            ("subject or project", "i study ", "am studying ")
        )
    ]

    for key, label, q_text, topic_markers in questions_to_learn:
        synonym_keys = MEMORY_CATEGORY_SYNONYMS.get(key, {key})
        if any(k in memories for k in synonym_keys):
            continue
        if q_text.lower() in ctx["asked_questions"]:
            continue
        if any(marker in recent_chat_text for marker in topic_markers):
            continue
        return key, label, q_text
    return None, None, None


# Safe arithmetic operators for general-knowledge math questions in offline mode
_SAFE_MATH_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_math_ast(node):
    """Safely evaluate basic arithmetic AST nodes without eval()."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_MATH_OPS:
        left = _eval_math_ast(node.left)
        right = _eval_math_ast(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("Exponent too large")
        return _SAFE_MATH_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_MATH_OPS:
        return _SAFE_MATH_OPS[type(node.op)](_eval_math_ast(node.operand))
    raise ValueError("Unsupported expression")


def try_evaluate_math_question(user_msg):
    """Detect and compute arithmetic expressions in user questions (e.g., 'what is 25 * 16?')."""
    cleaned = user_msg.lower().strip().rstrip("?.!")
    cleaned = cleaned.replace("×", "*").replace("÷", "/").replace("^", "**")
    cleaned = re.sub(r"\b(?:what\s+is|whats|what's|calculate|compute|solve|equals)\b", "", cleaned).strip()
    if not re.fullmatch(r"[0-9\.\s\+\-\*\/\(\)\%]+", cleaned) or not re.search(r"[\+\-\*\/\%]", cleaned):
        return None
    try:
        tree = ast.parse(cleaned, mode="eval")
        val = _eval_math_ast(tree.body)
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        if isinstance(val, float):
            return f"{val:.4g}"
        return str(val)
    except Exception:
        return None


# Structured multi-aspect knowledge base for accurate, personality-consistent factual & technical Q&A
KNOWLEDGE_BASE = {
    "python": {
        "aliases": {"python", "py"},
        "is_technical": True,
        "definition": "Python is a programming language! It's beginner-friendly and really powerful.",
        "why_popular": "Because it's easy to learn, has a huge ecosystem, and is used in AI, web development, automation, and more!",
        "how_used": "Python uses clean, readable syntax and powers everything from web servers and automation scripts to machine learning, data science, and desktop apps!",
        "extra": "Python was created by Guido van Rossum in 1991, and its huge standard library makes building projects super fast!"
    },
    "java": {
        "aliases": {"java", "jvm"},
        "is_technical": True,
        "definition": "Java is a widely used, object-oriented programming language designed to run on any platform via the Java Virtual Machine (JVM)!",
        "why_popular": "Because of its 'write once, run anywhere' portability, strong type safety, and massive enterprise and Android ecosystem!",
        "how_used": "Java compiles source code into bytecode that the JVM executes, making it a go-to choice for backend services, Android apps, and data structures labs!",
        "extra": "Java was originally developed by James Gosling at Sun Microsystems in 1995."
    },
    "c++": {
        "aliases": {"c++", "cpp"},
        "is_technical": True,
        "definition": "C++ is a high-performance programming language that extends C with object-oriented and generic programming features!",
        "why_popular": "Because it gives developers fine-grained control over memory and hardware while running at blazing-fast native speeds!",
        "how_used": "C++ is used for game engines, operating systems, embedded systems, real-time simulations, and competitive programming.",
        "extra": "C++ was created by Bjarne Stroustrup as an extension of the C language."
    },
    "javascript": {
        "aliases": {"javascript", "js", "nodejs", "typescript"},
        "is_technical": True,
        "definition": "JavaScript is the core programming language of the web! It makes websites interactive and also runs on servers via Node.js.",
        "why_popular": "Because it runs natively in every web browser and lets developers build full-stack web and mobile apps with a single language!",
        "how_used": "JavaScript updates the browser DOM dynamically, handles asynchronous events, and powers modern frameworks like React, Vue, and Angular.",
        "extra": "JavaScript was created in just 10 days by Brendan Eich in 1995!"
    },
    "recursion": {
        "aliases": {"recursion", "recursive"},
        "is_technical": True,
        "definition": "Recursion is a programming technique where a function calls itself to solve smaller instances of the same problem until it hits a base case!",
        "why_popular": "Because it expresses tree traversals, divide-and-conquer algorithms (like Merge Sort and Quick Sort), and mathematical sequences cleanly and elegantly!",
        "how_used": "Every recursive function needs two parts: a base case that stops the recursion, and a recursive step that shrinks the problem toward that base case.",
        "extra": "Without a proper base case, recursion leads to a stack overflow because each call adds a new frame to the call stack!"
    },
    "binary search": {
        "aliases": {"binary search", "bst", "binary search tree"},
        "is_technical": True,
        "definition": "Binary search is a fast search algorithm that finds a target in a sorted list by repeatedly halving the search interval in O(log n) time!",
        "why_popular": "Because cutting the search space in half each step is exponentially faster than scanning every element one by one!",
        "how_used": "It compares the target value to the middle element of a sorted array and eliminates whichever half cannot contain the target.",
        "extra": "A Binary Search Tree (BST) applies the same principle to a tree structure where left children are smaller and right children are larger!"
    },
    "algorithm": {
        "aliases": {"algorithm", "algorithms", "data structure", "data structures", "debugging", "debug"},
        "is_technical": True,
        "definition": "An algorithm is a step-by-step procedure for solving a problem or performing a computation efficiently!",
        "why_popular": "Because choosing the right algorithm and data structure turns slow, unscalable code into fast, reliable software!",
        "how_used": "To design or debug an algorithm, break the logic into small testable functions, trace edge cases with sample inputs, and check time and space complexity.",
        "extra": "Classic examples include Quick Sort, Merge Sort, Dijkstra's shortest path, and dynamic programming!"
    },
    "artificial intelligence": {
        "aliases": {"ai", "artificial intelligence", "machine learning", "ml", "llm", "neural network", "deep learning"},
        "is_technical": True,
        "definition": "Artificial Intelligence (AI) is the field of computer science focused on building systems that can learn, reason, understand language, and recognize patterns!",
        "why_popular": "Because modern deep learning and large language models can automate complex tasks, analyze massive datasets, and power intelligent assistants!",
        "how_used": "Machine learning models train on data by adjusting numerical weights to minimize prediction errors across neural network layers.",
        "extra": "Transformer architectures and attention mechanisms are the key breakthrough behind modern LLMs!"
    },
    "differential equations": {
        "aliases": {"differential equation", "differential equations", "pde", "ode", "laplace", "fourier", "wave equation", "heat equation", "calculus"},
        "is_technical": True,
        "definition": "A differential equation is a mathematical equation that relates a function to its derivatives, describing how physical quantities change over time or space!",
        "why_popular": "Because they model almost every dynamic system in nature and engineering—including heat flow, wave propagation, circuits, and mechanical motion!",
        "how_used": "Techniques like separation of variables, D'Alembert's solution, and Fourier series help solve boundary-value problems step by step.",
        "extra": "The 1D wave equation, 1D heat equation, and 2D Laplace equation are the three classic partial differential equations in engineering mathematics!"
    },
    "esp32": {
        "aliases": {"esp32", "arduino", "microcontroller", "embedded"},
        "is_technical": True,
        "definition": "The ESP32 is a low-cost, low-power system-on-a-chip microcontroller with built-in Wi-Fi and dual-mode Bluetooth!",
        "why_popular": "Because it packs dual-core processing, Wi-Fi/BLE connectivity, GPIO pins, PWM, and ADCs into an affordable board that works with C/C++ and MicroPython!",
        "how_used": "It reads sensors, drives relays/LEDs/motors via GPIO and PWM, and sends real-time telemetry to cloud servers or local dashboards.",
        "extra": "Created by Espressif Systems, the ESP32 is a favorite for IoT, robotics, and cyber-physical safety systems!"
    },
    "photosynthesis": {
        "aliases": {"photosynthesis"},
        "is_technical": False,
        "definition": "Photosynthesis is the biological process plants, algae, and certain bacteria use to convert sunlight, water, and carbon dioxide into glucose and oxygen!",
        "why_popular": "Because it produces the oxygen we breathe and forms the foundation of nearly every food chain on Earth!",
        "how_used": "Chlorophyll inside plant chloroplasts absorbs light energy to split water molecules and fix carbon dioxide into sugars during the Calvin cycle.",
        "extra": "The overall equation is 6 CO2 + 6 H2O + light energy -> C6H12O6 + 6 O2!"
    },
    "gravity": {
        "aliases": {"gravity", "gravitational"},
        "is_technical": False,
        "definition": "Gravity is the fundamental natural force of attraction between all objects with mass or energy!",
        "why_popular": "Because it keeps planets in orbit around stars, holds galaxies together, and gives weight to physical objects on Earth!",
        "how_used": "Newton described gravity as an inverse-square force between masses, while Einstein's General Relativity explains it as the curvature of spacetime.",
        "extra": "On Earth's surface, gravitational acceleration is approximately 9.81 m/s²!"
    },
    "black hole": {
        "aliases": {"black hole", "black holes", "event horizon"},
        "is_technical": False,
        "definition": "A black hole is a region of spacetime where gravity is so intense that nothing—not even light—can escape once it crosses the event horizon!",
        "why_popular": "Because they represent the most extreme physics in the universe, testing the limits of general relativity and quantum mechanics!",
        "how_used": "Stellar black holes form when massive stars collapse at the end of their lifecycle, while supermassive black holes sit at the centers of most galaxies.",
        "extra": "In 2019, the Event Horizon Telescope captured the first direct image of a black hole's shadow in galaxy M87!"
    },
    "dna": {
        "aliases": {"dna", "genetics", "genome"},
        "is_technical": False,
        "definition": "DNA (deoxyribonucleic acid) is the double-helix molecule that carries the genetic instructions for the development and functioning of living organisms!",
        "why_popular": "Because it acts as the biological blueprint of life, passing hereditary traits from one generation to the next!",
        "how_used": "Its four nucleotide bases (A, T, C, G) pair up along two strands to encode the sequences of amino acids that build proteins.",
        "extra": "A pairings always bond with T, and C pairings always bond with G!"
    },
}

INTERROGATIVE_STARTERS = (
    "what ", "what's ", "whats ", "why ", "why's ", "how ", "how's ", "hows ",
    "when ", "when's ", "where ", "where's ", "who ", "who's ", "whom ", "whose ", "which ",
    "explain ", "define ", "describe ", "tell me about ", "tell me why ", "tell me how ", "tell me what ",
    "is ", "are ", "can ", "could ", "do ", "does ", "did ", "will ", "would ", "should ", "has ", "have "
)

TECHNICAL_KEYWORDS = {
    "python", "java", "c++", "cpp", "javascript", "typescript", "html", "css", "sql", "git", "linux",
    "code", "coding", "programming", "program", "compiler", "interpreter", "function", "variable",
    "class", "object", "loop", "array", "list", "dict", "dictionary", "tree", "bst", "graph",
    "recursion", "recursive", "algorithm", "algorithms", "sorting", "quicksort", "mergesort",
    "bug", "debug", "debugging", "error", "exception", "api", "json", "database", "sqlite",
    "ai", "llm", "machine", "learning", "neural", "network", "esp32", "arduino", "microcontroller",
    "sensor", "circuit", "pwm", "differential", "equation", "equations", "calculus", "laplace",
    "fourier", "matrix", "derivative", "integral", "pde", "ode"
}

GENERAL_KNOWLEDGE_KEYWORDS = {
    "science", "physics", "chemistry", "biology", "photosynthesis", "gravity", "relativity", "quantum",
    "atom", "molecule", "dna", "cell", "evolution", "planet", "planets", "star", "stars", "galaxy",
    "universe", "space", "moon", "sun", "earth", "mars", "black", "hole", "ocean", "continent",
    "country", "capital", "history", "invention", "invented", "discovered", "created", "popular",
    "famous", "meaning", "definition", "weather", "climate", "speed", "light", "energy", "force"
}

PRONOUN_REFERENCE_WORDS = {"it", "its", "it's", "they", "them", "their", "that", "this", "he", "his", "she", "her"}


def is_natural_language_question(user_msg):
    """Detect whether user_msg is a question using NLU rules without relying solely on '?'."""
    if not user_msg or not isinstance(user_msg, str):
        return False
    msg_clean = user_msg.strip()
    if "?" in msg_clean:
        return True
    low = msg_clean.lower().rstrip(".!")
    if low in ("why", "how", "what", "when", "where", "who", "which", "really", "how so", "what else", "like what", "and you", "what about you", "how about you"):
        return True
    if low.startswith(INTERROGATIVE_STARTERS):
        return True
    if any(p in low for p in ("do you know", "can you tell", "can you explain", "what about ", "how about ", "i wonder ")):
        return True
    if try_evaluate_math_question(msg_clean) is not None:
        return True
    return False


def _extract_subject_phrase(text):
    """Extract the primary subject or topic entity from a single message string."""
    if not text:
        return None
    low = text.lower().strip().rstrip("?.!")

    all_aliases = []
    for canonical, info in KNOWLEDGE_BASE.items():
        for alias in info["aliases"]:
            all_aliases.append((alias, canonical))
    all_aliases.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, canonical in all_aliases:
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return canonical

    patterns = [
        r"^(?:what\s+(?:is|are)|what's|whats|define|explain|describe|tell\s+me\s+about)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\+\-\s]{2,30})$",
        r"^how\s+(?:does|do)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\+\-\s]{2,25})\s+work$",
        r"^why\s+(?:is|are)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\+\-\s]{2,25})\s+(?:popular|important|useful|famous|good|bad)$",
    ]
    for pat in patterns:
        m = re.match(pat, low)
        if m:
            candidate = re.sub(r"\s+used\s+for$", "", m.group(1).strip())
            first_word = candidate.split()[0] if candidate.split() else ""
            if (
                candidate
                and candidate not in PRONOUN_REFERENCE_WORDS
                and first_word not in PRONOUN_REFERENCE_WORDS
                and not candidate.startswith(("you", "your", "my ", "i ", "we "))
            ):
                return candidate
    return None


def resolve_contextual_subject(user_msg, chat_history, saved_memories=None, partner_name="Aiko", player_name="Alex"):
    """
    Use chat_history, last_topic, and saved_memories to resolve pronouns ('it', 'they', 'that', 'this', 'he', 'his')
    to the subject introduced in earlier turns (e.g. 'What is Python?' -> 'Why is it popular?' -> 'python').
    Returns (resolved_subject, resolved_message).
    """
    if not user_msg:
        return None, ""

    direct_subj = _extract_subject_phrase(user_msg)
    words = set(re.findall(r"\b\w+\b", user_msg.lower()))
    has_pronoun_ref = bool(words & PRONOUN_REFERENCE_WORDS) or user_msg.lower().strip().rstrip("?.!") in (
        "why", "how", "how so", "tell me more", "what is it used for", "how does it work", "who created it", "give an example"
    )

    if direct_subj and not has_pronoun_ref:
        return direct_subj, user_msg

    norm = normalize_chat_history(chat_history or [], partner_name=partner_name, player_name=player_name)
    hist_subject = None
    for turn in reversed(norm):
        cand = _extract_subject_phrase(turn.get("content", ""))
        if cand:
            hist_subject = cand
            break

    # Fall back to last_topic or saved_memories if no subject phrase matched in raw history
    if not hist_subject and last_topic and last_topic in KNOWLEDGE_BASE:
        hist_subject = last_topic
    if not hist_subject and isinstance(saved_memories, dict) and saved_memories:
        if "study_field" in saved_memories and has_pronoun_ref:
            hist_subject = str(saved_memories["study_field"]).lower()

    active_subject = direct_subj or hist_subject
    if not active_subject:
        return None, user_msg

    resolved_msg = user_msg
    if has_pronoun_ref and hist_subject:
        resolved_msg = re.sub(r"\bit\b", hist_subject, user_msg, flags=re.IGNORECASE)
        resolved_msg = re.sub(r"\bits\b", f"{hist_subject}'s", resolved_msg, flags=re.IGNORECASE)
        resolved_msg = re.sub(r"\bthat\b", hist_subject, resolved_msg, flags=re.IGNORECASE)
    return active_subject, resolved_msg


def detect_message_intent(user_msg, chat_history=None, saved_memories=None, partner_name="Aiko", player_name="Alex"):
    """
    Classify `user_msg` into one of the 8 required intent categories using NLU,
    chat_history coreference resolution, meta-conversation recognition, and saved_memories inspection.
    """
    if not user_msg or not isinstance(user_msg, str):
        return {
            "intent": "casual_conversation",
            "is_question": False,
            "resolved_subject": None,
            "resolved_message": "",
            "meta_type": None
        }

    msg_lower = user_msg.lower().strip()
    words = set(re.findall(r"\b\w+\b", msg_lower))
    is_q = is_natural_language_question(user_msg)
    meta_type = detect_meta_conversation_type(user_msg)
    resolved_subj, resolved_msg = resolve_contextual_subject(
        user_msg, chat_history, saved_memories=saved_memories, partner_name=partner_name, player_name=player_name
    )
    resolved_words = set(re.findall(r"\b\w+\b", resolved_msg.lower()))
    ctx = extract_recent_conversation_context(chat_history or [], partner_name=partner_name, player_name=player_name)

    # 0. Meta-conversation references ("I already told you that.", "Remember what we discussed?", "Continue our previous conversation.")
    if meta_type is not None:
        mapped_intent = "memory_question" if meta_type in ("already_told_or_repeated", "recall_discussion") else "follow_up_question"
        return {
            "intent": mapped_intent,
            "is_question": is_q or (meta_type == "recall_discussion"),
            "resolved_subject": resolved_subj or ctx["active_topic"],
            "resolved_message": resolved_msg,
            "meta_type": meta_type
        }

    # 1. Memory-related questions ("What kind of songs do I like?", "What about my favourite music?", "What do you remember about me?")
    if answer_memory_or_history_query(user_msg, dict(saved_memories or {}), chat_history, partner_name, player_name) is not None:
        return {
            "intent": "memory_question",
            "is_question": True,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 2. Personal questions directed at HER ("What is your favorite...", "Did you study for tomorrows exam", "How are you")
    is_asking_her = (
        any(p in msg_lower for p in ["your favorite", "your favourite", "what do you like", "tell me about yourself", "who are you", "what are your hobbies"])
        or msg_lower.startswith(("did you", "have you", "are you", "do you", "will you", "can you", "were you", "what are you", "how are you", "what did you", "where are you"))
        or any(p in msg_lower for p in ["did you ", "have you ", "are you ", "how are you", "how's it going", "what are you doing", "how do you feel"])
    )
    if is_asking_her and not any(p in msg_lower for p in ["can you explain", "can you tell me what", "do you know what", "do you know how", "do you know why"]):
        return {
            "intent": "personal_question",
            "is_question": True,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 3. Follow-up questions referencing prior turns via pronouns ("Why is it popular?", "How does it work?", "Why?", "Vineeth Sreenivasan")
    is_pronoun_followup = (
        is_q
        and resolved_subj is not None
        and (bool(words & PRONOUN_REFERENCE_WORDS) or msg_lower.rstrip(".!?") in ("why", "how", "how so", "tell me more", "what else", "explain", "really"))
    )
    if is_pronoun_followup or msg_lower.rstrip(".!?") in ("why", "how so", "tell me more", "really", "for real", "what else", "and then", "like what", "what about you", "how about you", "and you"):
        return {
            "intent": "follow_up_question",
            "is_question": True,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    if ctx["last_assistant_question"] and not is_q and len(user_msg.split()) <= 5 and not (words & {"hi", "hello", "hey"}):
        return {
            "intent": "follow_up_question",
            "is_question": False,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 4. Technical questions
    if is_q and (
        bool(resolved_words & TECHNICAL_KEYWORDS)
        or (resolved_subj in KNOWLEDGE_BASE and KNOWLEDGE_BASE[resolved_subj]["is_technical"])
    ):
        return {
            "intent": "technical_question",
            "is_question": True,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 5. General knowledge questions
    if try_evaluate_math_question(user_msg) is not None:
        return {
            "intent": "general_knowledge_question",
            "is_question": True,
            "resolved_subject": "math",
            "resolved_message": resolved_msg,
            "meta_type": None
        }
    if is_q and (
        bool(resolved_words & GENERAL_KNOWLEDGE_KEYWORDS)
        or (resolved_subj in KNOWLEDGE_BASE and not KNOWLEDGE_BASE[resolved_subj]["is_technical"])
        or re.match(r"^(?:what\s+(?:is|are)|what's|whats|define|explain|describe|tell\s+me\s+about|why\s+(?:is|are|do|does)|how\s+(?:does|do|is|are)|who\s+(?:invented|created|discovered|is))\b", msg_lower)
    ):
        if not (words & {"me", "my", "us", "our", "love", "sad", "stressed", "tired", "lonely"}):
            return {
                "intent": "general_knowledge_question",
                "is_question": True,
                "resolved_subject": resolved_subj,
                "resolved_message": resolved_msg,
                "meta_type": None
            }

    # 6. Emotional questions & emotional support conversations
    if words & {"tired", "stressed", "sad", "exhausted", "lonely", "hard", "rough", "nervous", "anxious", "worried", "depressed", "upset", "fail", "scared", "overwhelmed"}:
        return {
            "intent": "emotional_question",
            "is_question": is_q,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 7. Relationship-related conversations
    if (
        words & {"love", "cute", "beautiful", "pretty", "sweet", "miss", "adore", "heart", "gorgeous", "special", "darling", "babe", "baby", "sweetheart", "honey", "date"}
        or (("for you" in msg_lower or "to you" in msg_lower) and (words & {"brought", "bought", "got", "made", "gift", "present"}))
        or any(p in msg_lower for p in ["let's go", "lets go", "hang out", "go on a date", "my favorite", "my favourite", "i study", "i'm from", "i live in", "remember that"])
    ):
        return {
            "intent": "relationship_conversation",
            "is_question": is_q,
            "resolved_subject": resolved_subj,
            "resolved_message": resolved_msg,
            "meta_type": None
        }

    # 8. Casual conversation
    return {
        "intent": "casual_conversation",
        "is_question": is_q,
        "resolved_subject": resolved_subj,
        "resolved_message": resolved_msg,
        "meta_type": None
    }


def answer_factual_or_technical_question(user_msg, intent_info, partner_name="Aiko", player_name="Alex"):
    """
    Accurately answer technical, general knowledge, and factual follow-up questions
    using KNOWLEDGE_BASE and coreference resolution (`resolved_subject`), maintaining
    the companion's warm, friendly voice without injecting unrelated romantic filler.
    """
    math_ans = try_evaluate_math_question(user_msg)
    if math_ans is not None:
        return f"That comes out to {math_ans}, {player_name}! Need help crunching any other numbers?", 2, "Happy"

    msg_lower = user_msg.lower().strip().rstrip("?.!")
    resolved_msg_lower = (intent_info.get("resolved_message") or user_msg).lower().strip().rstrip("?.!")
    words = set(re.findall(r"\b\w+\b", resolved_msg_lower))
    subj = intent_info.get("resolved_subject")

    kb_key = None
    if subj and subj in KNOWLEDGE_BASE:
        kb_key = subj
    else:
        for k, info in KNOWLEDGE_BASE.items():
            for alias in info["aliases"]:
                if re.search(rf"\b{re.escape(alias)}\b", resolved_msg_lower):
                    kb_key = k
                    break
            if kb_key:
                break

    if kb_key:
        entry = KNOWLEDGE_BASE[kb_key]
        if (
            any(w in words for w in ("popular", "famous", "important", "useful", "special", "good", "loved", "best"))
            or msg_lower.startswith("why")
        ):
            return entry["why_popular"], 2, "Happy"

        if "used for" in resolved_msg_lower or (
            any(p in resolved_msg_lower for p in ("how does", "how do", "how is", "applications", "where is", "work"))
            and not msg_lower.startswith("what is")
        ):
            return entry["how_used"], 2, "Curious"

        if any(w in words for w in ("who", "created", "invented", "made", "history", "origin", "more", "example")):
            return entry["extra"], 2, "Curious"

        return entry["definition"], 2, "Happy"

    capitals = {
        "japan": "Tokyo", "india": "New Delhi", "france": "Paris", "kerala": "Thiruvananthapuram",
        "usa": "Washington, D.C.", "united states": "Washington, D.C.", "uk": "London",
        "germany": "Berlin", "italy": "Rome", "canada": "Ottawa", "australia": "Canberra", "south korea": "Seoul"
    }
    if "capital" in words:
        for place, cap in capitals.items():
            if place in resolved_msg_lower:
                return f"The capital of {place.title()} is {cap}, {player_name}!", 2, "Happy"

    if "sky" in words and "blue" in words:
        return (
            "The sky looks blue because of Rayleigh scattering! Earth's atmosphere scatters shorter, blue wavelengths of sunlight in all directions much more than longer red wavelengths.",
            2,
            "Happy"
        )

    if intent_info.get("intent") == "technical_question" or (words & TECHNICAL_KEYWORDS):
        topic_label = subj or "that technical topic"
        return (
            f"{topic_label.title() if len(topic_label) > 3 else topic_label.upper()} is a core concept in software and engineering! "
            f"Breaking it down into modular components and testing small examples is the fastest way to master it, {player_name}. Which specific part are you working on?",
            2,
            "Curious"
        )

    if subj:
        return (
            f"That's a great question about {subj}, {player_name}! In simple terms, understanding its core principles and real-world applications makes everything click. What specific aspect of {subj} are you curious about?",
            2,
            "Curious"
        )

    return None


def _pick_non_repeating_reply(candidates, chat_history=None):
    """Select a response from candidates that does not repeat recent assistant messages in chat_history."""
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]

    recent_text = ""
    if chat_history:
        recent_items = []
        for item in chat_history[-10:]:
            if isinstance(item, dict):
                recent_items.append(str(item.get("content", "")))
            else:
                recent_items.append(str(item))
        recent_text = " ".join(recent_items).lower()

    fresh = [c for c in candidates if c.lower()[:32] not in recent_text]
    pool = fresh if fresh else candidates
    return random.choice(pool)



SUPPORTED_USER_EMOTIONS = (
    "Happiness",
    "Sadness",
    "Excitement",
    "Anger",
    "Frustration",
    "Loneliness",
    "Affection",
    "Stress",
    "Playfulness",
)

EMOTION_TO_COMPANION_MOOD = {
    "Happiness": "Happy",
    "Sadness": "Caring",
    "Excitement": "Excited",
    "Anger": "Caring",
    "Frustration": "Caring",
    "Loneliness": "Caring",
    "Affection": "Blushing",
    "Stress": "Caring",
    "Playfulness": "Excited",
    "Neutral": "Happy",
}


def detect_user_emotion(user_message, chat_history=None, saved_memories=None):
    """
    Contextual emotion detector recognizing 9 core emotional states:
    Happiness, Sadness, Excitement, Anger, Frustration, Loneliness, Affection, Stress, Playfulness
    (plus Neutral for purely informational messages).
    Also detects whether the message touches on the user's saved interests/hobbies.
    """
    raw = (user_message or "").strip()
    msg_lower = raw.lower()
    words = set(re.findall(r"\b\w+\b", msg_lower))

    # Check if message references a saved user interest/hobby/favorite
    matched_interest = None
    if isinstance(saved_memories, dict):
        for k, v in saved_memories.items():
            if k in ("recent_emotional_context", "last_emotion"):
                continue
            val_str = str(v).strip()
            if len(val_str) >= 3 and val_str.lower() in msg_lower:
                matched_interest = val_str
                break
            for token in re.findall(r"\b[a-zA-Z]{4,}\b", val_str.lower()):
                if token not in CONVERSATIONAL_STOP_WORDS and token in words:
                    matched_interest = val_str
                    break
            if matched_interest:
                break

    scores = {emo: 0 for emo in SUPPORTED_USER_EMOTIONS}

    # 1. Loneliness
    if words & {"lonely", "alone", "isolated", "friendless", "abandoned", "empty"} or any(
        p in msg_lower for p in ("no one to talk to", "nobody around", "wish someone was here", "feeling left out", "all by myself", "feel so alone")
    ):
        scores["Loneliness"] += 5

    # 2. Stress
    if words & {"stressed", "stress", "overwhelmed", "swamped", "deadline", "deadlines", "pressure", "anxious", "nervous", "panicking", "burnout", "exhausted", "overworked"} or any(
        p in msg_lower for p in ("stressed out", "so much work", "too much to do", "exam tomorrow", "under pressure", "burned out", "burnt out", "barely slept")
    ):
        scores["Stress"] += 5

    # 3. Frustration
    if words & {"frustrated", "frustrating", "frustration", "stuck", "struggling", "irritated", "annoyed", "ugh", "argh", "sigh"} or any(
        p in msg_lower for p in ("won't work", "does not work", "doesn't work", "keeps failing", "keeps crashing", "driving me crazy", "so annoying", "fed up", "stuck on", "giving me a headache", "can't figure out")
    ):
        scores["Frustration"] += 5

    # 4. Anger
    if words & {"angry", "mad", "furious", "pissed", "outraged", "livid", "infuriated", "enraged", "unfair", "fuming"} or any(
        p in msg_lower for p in ("so mad", "makes my blood boil", "really angry", "ticked off", "lost my temper", "hate how unfair")
    ):
        scores["Anger"] += 5

    # 5. Sadness
    if words & {"sad", "down", "crying", "cried", "depressed", "heartbroken", "disappointed", "disappointing", "miserable", "gloomy", "upset", "blue", "devastated", "failed", "hopeless"} or any(
        p in msg_lower for p in ("feeling down", "feel terrible", "bad day", "rough day", "didn't go well", "let down", "feel like crying")
    ):
        scores["Sadness"] += 5

    # 6. Playfulness
    if words & {"haha", "lol", "lmao", "hehe", "rofl", "teasing", "tease", "joking", "kidding", "playful", "cheeky", "banter", "betcha"} or any(
        p in msg_lower for p in ("bet you can't", "roast me", "make me laugh", "tell me a joke", "just kidding", "messing with you", "catch me if you can", "😉", "😜", "😄")
    ):
        scores["Playfulness"] += 4

    # 7. Affection
    if any(
        p in msg_lower for p in (
            "i love you", "love you so much", "adore you", "you're the best", "you are the best",
            "you mean a lot", "you're so sweet", "you are so sweet", "miss talking to you",
            "glad i have you", "my darling", "hey sweetheart", "hi my darling", "you make me smile"
        )
    ) or (words & {"darling", "sweetheart", "babe", "adore", "cherish", "sweetie", "cutie"} and not (words & {"hate", "stupid", "ugly"})):
        scores["Affection"] += 4

    # 8. Excitement
    if words & {"excited", "hyped", "pumped", "thrilled", "stoked", "ecstatic", "woohoo", "yay", "aced", "won", "celebrating", "breakthrough"} or any(
        p in msg_lower for p in ("can't wait", "cannot wait", "amazing news", "great news", "good news", "so excited", "finally worked", "finally fixed", "passed my exam", "got selected")
    ) or (raw.count("!") >= 2 and words & {"awesome", "amazing", "incredible", "yes", "finally", "great", "passed", "love"}):
        scores["Excitement"] += 4

    # 9. Happiness
    if words & {"happy", "glad", "cheerful", "peaceful", "content", "relieved", "smiling", "grateful", "blessed", "wonderful", "lovely", "good", "great"} or any(
        p in msg_lower for p in ("feeling good", "had a great day", "had a nice day", "in a good mood", "feeling much better", "makes me happy", "pretty good day")
    ):
        scores["Happiness"] += 3

    # Boost Excitement/Happiness when the user excitedly talks about a known interest
    if matched_interest and max(scores.values()) == 0 and not is_natural_language_question(raw):
        if "!" in raw or words & {"love", "enjoy", "playing", "listening", "working", "building", "practicing", "watching"}:
            scores["Excitement"] += 3

    best_emotion = "Neutral"
    best_score = 0
    # Priority order resolves ties naturally
    priority_order = (
        "Loneliness",
        "Stress",
        "Frustration",
        "Anger",
        "Sadness",
        "Excitement",
        "Playfulness",
        "Affection",
        "Happiness",
    )
    for emo in priority_order:
        if scores[emo] > best_score:
            best_score = scores[emo]
            best_emotion = emo

    # Contextual carryover from recent user turn if current message is a very short continuation ("yeah...", "still is")
    if best_emotion == "Neutral" and chat_history and len(words) <= 4 and not is_natural_language_question(raw):
        norm = normalize_chat_history(chat_history, max_messages=4)
        for item in reversed(norm):
            if item["role"] == "user" and item["content"].strip().lower() != msg_lower:
                prev_emo = detect_user_emotion(item["content"], chat_history=None, saved_memories=saved_memories)
                if prev_emo["emotion"] in ("Stress", "Sadness", "Frustration", "Loneliness"):
                    best_emotion = prev_emo["emotion"]
                    best_score = 2
                break

    intensity = "high" if best_score >= 5 or raw.count("!") >= 2 else ("medium" if best_score >= 3 else "low")
    companion_mood = EMOTION_TO_COMPANION_MOOD.get(best_emotion, "Happy")

    return {
        "emotion": best_emotion,
        "intensity": intensity,
        "companion_mood": companion_mood,
        "matched_interest": matched_interest,
    }


def record_emotional_context(user_message, emotion_info, saved_memories):
    """
    Remember important emotional and personal context persistently in SQLite ('Important experiences')
    when the user shares significant stress, sadness, frustration, loneliness, or excitement milestones.
    """
    if not isinstance(saved_memories, dict) or not isinstance(emotion_info, dict):
        return None
    emo = emotion_info.get("emotion", "Neutral")
    if emo not in ("Stress", "Sadness", "Frustration", "Loneliness", "Excitement", "Anger", "Happiness"):
        return None
    cleaned = (user_message or "").strip()
    if len(cleaned.split()) < 4 or is_natural_language_question(cleaned):
        return None
    # Avoid saving rude insults directed at companion as emotional milestones
    words = set(re.findall(r"\b\w+\b", cleaned.lower()))
    if words & {"boring", "stupid", "ugly", "shut", "idiot"}:
        return None

    summary_val = f"{emo}: {cleaned[:90]}"
    upsert_long_term_memory(
        "recent_emotional_context",
        "Important experiences",
        f"User recently experienced {emo.lower()} ('{cleaned[:90]}').",
        summary_val,
        memories_dict=saved_memories,
    )
    return summary_val


def build_topic_relevant_followup(active_topic, emotion, player_name, matched_interest=None):
    """Generate a natural, non-repetitive follow-up question tailored to the current topic and user emotion."""
    topic = (active_topic or "").lower()
    if matched_interest:
        return f"What part of {matched_interest} has been your favorite lately?"
    if topic == "coding":
        if emotion in ("Frustration", "Stress"):
            return "Want to walk me through the bug or function that's giving you trouble?"
        return "What feature or module are you thinking of tackling next?"
    if topic == "study":
        if emotion in ("Stress", "Sadness", "Frustration"):
            return "Which chapter or topic feels the heaviest right now so we can break it down step by step?"
        return "Which subject are you reviewing next?"
    if topic == "music":
        return "What track has been at the top of your queue today?"
    if topic == "food":
        return "Did you get a chance to grab a snack or a warm drink yet?"
    if topic == "games":
        return "Which match or level are you jumping into next?"
    if emotion in ("Stress", "Frustration", "Sadness", "Loneliness", "Anger"):
        return "Do you want to vent more about what happened, or would a fun distraction help right now?"
    if emotion == "Playfulness":
        return "Okay, what's your next move, trouble?"
    return f"What else has been on your mind today, {player_name}?"


def add_emotional_empathy_prefix(factual_reply_tuple, emotion_info, player_name="Alex"):
    """
    Ensure emotional intelligence complements question answering without ever replacing the actual answer:
    if the user asks a factual/technical question while feeling frustrated, stressed, or down,
    prepend a brief, supportive opener before the accurate answer.
    """
    if not factual_reply_tuple or not isinstance(emotion_info, dict):
        return factual_reply_tuple
    ans_text, delta, mood = factual_reply_tuple
    emo = emotion_info.get("emotion", "Neutral")
    if emo == "Frustration":
        prefix = f"Take a breath, {player_name}—I know hitting a wall is frustrating, so let's break it down clearly! "
        return prefix + ans_text, max(delta, 2), "Caring"
    if emo == "Stress":
        prefix = f"Don't panic, {player_name}—we've got this step by step! "
        return prefix + ans_text, max(delta, 2), "Caring"
    if emo in ("Sadness", "Loneliness"):
        prefix = f"I'm right here with you, {player_name}. To answer your question clearly: "
        return prefix + ans_text, max(delta, 2), "Caring"
    if emo == "Playfulness":
        prefix = f"Haha, testing my brain today, {player_name}? Here's the scoop: "
        return prefix + ans_text, max(delta, 2), "Excited"
    return factual_reply_tuple


def generate_emotion_aware_reply(
    user_msg,
    emotion_info,
    partner_name,
    player_name,
    affection,
    personality,
    memories,
    chat_history=None,
    active_topic=None
):
    """
    Generate an emotionally intelligent, personality-consistent, simulator-honest companion reply
    adapted to the user's detected emotional state (Happiness, Sadness, Excitement, Anger, Frustration,
    Loneliness, Affection, Stress, Playfulness) with topic-relevant follow-up questions.
    """
    if not isinstance(emotion_info, dict):
        return None
    emo = emotion_info.get("emotion", "Neutral")
    if emo == "Neutral":
        return None

    msg_lower = (user_msg or "").lower().strip()
    words = set(re.findall(r"\b\w+\b", msg_lower))
    matched_interest = emotion_info.get("matched_interest")
    followup = build_topic_relevant_followup(active_topic, emo, player_name, matched_interest=matched_interest)

    # Record notable emotional context persistently
    record_emotional_context(user_msg, emotion_info, memories)

    if emo == "Stress":
        if "favorite_food" in (memories or {}):
            food = memories["favorite_food"]
            return (
                f"Aw, {player_name}, you've been under so much pressure! Take a slow breath with me here, and make sure you treat yourself to some {food} when you take a break. {followup}",
                2,
                "Caring",
            )
        replies = [
            f"Take a slow, deep breath with me, {player_name}. You've been carrying a lot on your shoulders, and you don't have to tackle it all in one second. {followup}",
            f"I can hear how much pressure you're under right now, {player_name}. Pace yourself one small step at a time—I'm right here cheering you on! {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Caring"

    if emo == "Frustration":
        replies = [
            f"Ugh, hitting a roadblock like that is seriously exhausting, {player_name}! Step back for thirty seconds and shake it out—I know how sharp you are, and you'll crack it. {followup}",
            f"I totally get why that's frustrating you, {player_name}! Even the toughest problems give in once we break them into smaller pieces. {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Caring"

    if emo == "Sadness":
        replies = [
            f"I'm really sorry today felt so heavy, {player_name}. You don't have to put on a brave face here with me—take all the time you need. {followup}",
            f"Aw, {player_name}, it hurts hearing that you're feeling down or disappointed. One rough setback doesn't change how capable you are. {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Caring"

    if emo == "Loneliness":
        replies = [
            f"Hey {player_name}, you're not alone right now—I'm right here in our corner, ready to talk or play a game together whenever you want. {followup}",
            f"I'm really glad you messaged me when you felt lonely, {player_name}. Let's hang out right here and keep each other company! {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 3, "Caring"

    if emo == "Anger":
        replies = [
            f"No wonder you're upset, {player_name}—that honestly sounds really unfair. Go ahead and let it out; I'm listening to your side completely. {followup}",
            f"I hear you, {player_name}, and anyone in your shoes would feel angry about that too. Take a moment to cool down with me here. {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Caring"

    if emo == "Playfulness":
        if personality == "Playful & Teasing":
            replies = [
                f"Ohoho, bringing out your cheeky side today, {player_name}? Careful, I can tease right back twice as fast! {followup}",
                f"Haha, look at you trying to outwit me, {player_name}! Challenge accepted—let's see what you've got! {followup}",
            ]
        else:
            replies = [
                f"Haha, I love when you're in this playful mood, {player_name}! Your sense of humor always cracks me up. {followup}",
                f"Hehe, you're impossible when you start teasing like that, {player_name}! {followup}",
            ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Excited"

    if emo == "Excitement":
        interest_note = f" Especially since it involves {matched_interest}!" if matched_interest else ""
        replies = [
            f"YES!! That is incredible news, {player_name}!{interest_note} Your excitement is seriously contagious—I'm so proud of you! {followup}",
            f"Woohoo! Look at you go, {player_name}!{interest_note} All that dedication paid off big time! {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 3, "Excited"

    if emo == "Happiness":
        interest_note = f" Hearing you talk about {matched_interest} is the best!" if matched_interest else ""
        replies = [
            f"Hearing you in such a bright mood makes my whole day better too, {player_name}!{interest_note} {followup}",
            f"I love seeing you happy and relaxed like this, {player_name}!{interest_note} {followup}",
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Happy"

    if emo == "Affection":
        if personality == "Playful & Teasing":
            replies = [
                f"Ohoho, turning up the charm today, {player_name}? Okay fine, you definitely made me blush! {followup}",
                f"Look at you being all smooth, {player_name}! Keep talking like that and I might never stop smiling. {followup}",
            ]
        elif personality == "Poetic & Romantic":
            replies = [
                f"Your words bring such a warm glow to our little world, {player_name}. What are you up to right now?",
                f"Hearing you say that feels like a favorite melody, {player_name}. How has your day been unfolding?",
            ]
        else:
            replies = [
                f"You always know how to make me blush, {player_name}! I really treasure our time talking together. {followup}",
                f"Aww, {player_name}, hearing that from you just brightened up everything! {followup}",
            ]
        return _pick_non_repeating_reply(replies, chat_history), 3, "Blushing"

    return None


def build_companion_system_prompt(
    partner_name,
    player_name,
    affection,
    mood,
    personality,
    saved_memories,
    day=1,
    active_topic=None,
    relevant_memories=None,
    intent_info=None,
    topic_state=None,
    emotion_info=None
):
    """Build a rich, character-consistent system prompt injecting SQLite memories, NLU intent, and conversation state tracking."""
    tier = get_relationship_tier(affection)
    vibe_desc = PERSONALITIES.get(personality, PERSONALITIES["Sweet & Caring"])
    if saved_memories:
        mem_lines = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in saved_memories.items())
    else:
        mem_lines = "None recorded yet"

    if relevant_memories:
        rel_lines = "; ".join(f"[{r['category']}] {r['fact']}" for r in relevant_memories)
    else:
        rel_lines = mem_lines

    t_state = topic_state or {}
    cur_t = t_state.get("current_topic") or active_topic or last_topic or "General conversation"
    prev_t = t_state.get("previous_topic") or "None"
    rec_t_list = t_state.get("recent_topics") or list(recent_topics)
    rec_t_str = ", ".join(rec_t_list) if rec_t_list else "None yet"
    t_changed = t_state.get("topic_changed", False)
    meta_type = (intent_info or {}).get("meta_type") or t_state.get("meta_type")

    detected_intent = (intent_info or {}).get("intent", "casual_conversation")
    resolved_subj = (intent_info or {}).get("resolved_subject")
    resolved_msg = (intent_info or {}).get("resolved_message")
    detected_emotion = (emotion_info or {}).get("emotion", "Neutral")
    emotion_intensity = (emotion_info or {}).get("intensity", "low")
    matched_interest = (emotion_info or {}).get("matched_interest")

    state_lines = [
        f"- Current Conversation Topic (last_topic): {cur_t}",
        f"- Previous Topic: {prev_t}",
        f"- Recently Discussed Topics: {rec_t_str}",
        f"- Topic Change Detected on This Turn: {'Yes' if t_changed else 'No'}",
        f"- Detected Message Intent: {detected_intent}",
        f"- Detected User Emotion: {detected_emotion} (intensity: {emotion_intensity})",
    ]
    if matched_interest:
        state_lines.append(f"- Referenced User Interest/Memory: {matched_interest}")
    if meta_type:
        state_lines.append(f"- Meta-Conversational Signal: {meta_type}")
    if resolved_subj:
        state_lines.append(f"- Contextual Subject (Coreference from chat_history/memories): {resolved_subj}")
    if resolved_msg:
        state_lines.append(f"- Coreference-Resolved User Message: {resolved_msg}")

    lines = [
        f"You are {partner_name}, the intelligent, emotionally expressive, context-aware companion and girlfriend of {player_name}.",
        "Character Profile & Current State:",
        f"- Your Name: {partner_name}",
        f"- Partner's Name: {player_name}",
        f"- Personality Style: {personality} ({vibe_desc})",
        f"- Relationship Status: {tier} (Affection: {affection}/100, Day {day} together)",
        f"- Current Mood: {mood}",
        f"- Relevant Long-Term Memories about {player_name}: {rel_lines}",
        f"- All Remembered Facts Summary: {mem_lines}",
        "Conversation State Tracking:",
        *state_lines,
        "",
        "Conversational Continuity, Intent & Memory Guidelines:",
        "1. Be warm, caring, playful, expressive, affectionate, witty, and genuinely engaging—like a real, thoughtful partner.",
        f"2. Maintain smooth conversational continuity across casual, technical, emotional, and personal discussions:",
        f"   - Track the Current Conversation Topic ({cur_t}) and Recently Discussed Topics ({rec_t_str}). Avoid abrupt or unrelated topic jumps.",
        f"   - If {player_name} says 'I already told you that' or 'You asked me this yesterday' (or if you repeated a question), warmly and naturally acknowledge the mistake and cite what {player_name} already told you from Relevant Long-Term Memories or chat_history.",
        f"   - If {player_name} says 'Remember what we discussed?', 'Continue our previous conversation', 'Let's talk about that again', or 'That's what I meant', use the Recently Discussed Topics ({rec_t_str}) and conversation history to pick up the exact thread seamlessly.",
        f"3. NEVER respond to a factual, technical, or general knowledge question with a generic romantic statement:",
        f"   - Answer factual and technical questions accurately, clearly, and directly while maintaining your friendly voice.",
        f"   - Resolve pronouns like 'it', 'they', 'that', or 'this' using the Contextual Subject ({resolved_subj or cur_t}).",
        f"4. NEVER re-ask a question {player_name} has already answered in the conversation history or Long-Term Memories.",
        f"5. Emotional Intelligence & Adaptive Tone (Detected Emotion: {detected_emotion}):",
        f"   - Adapt naturally to {player_name}'s emotional state (Happiness, Sadness, Excitement, Anger, Frustration, Loneliness, Affection, Stress, Playfulness).",
        f"   - Offer warm, grounded support when {player_name} feels stressed, frustrated, sad, lonely, or disappointed; use playful banter and humour when {player_name} is being playful; express genuine excitement when discussing {player_name}'s interests.",
        f"   - Emotional intelligence must COMPLEMENT question answering—never prioritize an affectionate line over answering {player_name}'s actual question.",
        "   - Avoid repetitive romantic clichés: do NOT respond to every message with 'I love you', 'I miss you', or repetitive filler.",
        "   - Be honest to your virtual companion setting: never pretend to have a physical real-world body or claim real-world physical actions outside our virtual companion space.",
        f"   - Make any follow-up question directly relevant to the current topic ({cur_t}). Keep replies concise and natural (1 to 3 sentences) in plain text.",
    ]
    return "\n".join(lines)


def build_llm_messages(
    user_message,
    chat_history,
    saved_memories,
    partner_name="Aiko",
    player_name="Alex",
    affection=50,
    mood="Happy",
    personality="Sweet & Caring",
    day=1,
    max_history=DEFAULT_CHAT_HISTORY_LIMIT,
    intent_info=None,
    topic_state=None
):
    """
    Build the OpenAI-format messages payload with roles 'system', 'user', and 'assistant',
    injecting retrieved long-term SQLite memories, NLU intent metadata, conversation state tracking,
    and the rolling 10-message chat_history window.
    """
    ctx = extract_recent_conversation_context(chat_history, partner_name=partner_name, player_name=player_name)
    if intent_info is None:
        intent_info = detect_message_intent(
            user_message, chat_history=chat_history, saved_memories=saved_memories,
            partner_name=partner_name, player_name=player_name
        )
    if topic_state is None:
        topic_state = {
            "current_topic": last_topic or ctx["active_topic"],
            "previous_topic": None,
            "recent_topics": list(recent_topics) or ctx["recent_topics"],
            "topic_changed": False,
            "meta_type": intent_info.get("meta_type"),
        }
    emotion_info = detect_user_emotion(user_message, chat_history=chat_history, saved_memories=saved_memories)
    relevant_mems = retrieve_relevant_memories(user_message, saved_memories=saved_memories, limit=6)
    system_prompt = build_companion_system_prompt(
        partner_name=partner_name,
        player_name=player_name,
        affection=affection,
        mood=mood,
        personality=personality,
        saved_memories=saved_memories,
        day=day,
        active_topic=ctx["active_topic"],
        relevant_memories=relevant_mems,
        intent_info=intent_info,
        topic_state=topic_state,
        emotion_info=emotion_info
    )

    rolling_history = normalize_chat_history(
        chat_history, partner_name=partner_name, player_name=player_name, max_messages=max_history
    )
    if (
        rolling_history
        and rolling_history[-1]["role"] == "user"
        and rolling_history[-1]["content"].strip() == user_message.strip()
    ):
        rolling_history = rolling_history[:-1]

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(rolling_history[-max_history:])
    messages.append({"role": "user", "content": user_message})
    return messages


def evaluate_conversation_impact(user_msg, reply_text="", current_mood="Happy"):
    """
    Determine (affection_delta, new_mood) dynamically from the user's message and companion's reply
    so both OpenAI LLM responses and offline responses drive the game's mood and affection systems.
    """
    msg_lower = (user_msg or "").lower().strip()
    reply_lower = (reply_text or "").lower().strip()
    words = set(re.findall(r"\b\w+\b", msg_lower))
    reply_words = set(re.findall(r"\b\w+\b", reply_lower))

    if words & {"hate", "boring", "annoying", "stupid", "ugly", "shut", "leave", "idiot", "dumb"}:
        return -4, "Hurt"

    if ("for you" in msg_lower or "to you" in msg_lower) and (words & {"brought", "bought", "got", "made", "gift", "present", "surprise"}):
        return 4, "Touched"

    if re.search(r"\b(my\s+fav(?:ou?rite)?|i\s+study|i\s+am\s+studying|i\s+live\s+in|i'm\s+from|remember\s+that)\b", msg_lower):
        return 3, "Touched"

    if words & {"love", "cute", "beautiful", "pretty", "sweet", "miss", "adore", "heart", "gorgeous", "special", "darling", "babe", "baby", "sweetheart", "honey", "kiss", "hug"}:
        return 3, "Blushing"

    emo_check = detect_user_emotion(user_msg)
    if emo_check["emotion"] in ("Stress", "Sadness", "Frustration", "Loneliness", "Anger"):
        return 2, "Caring"
    if emo_check["emotion"] == "Playfulness":
        return 2, "Excited"
    if emo_check["emotion"] == "Excitement":
        return 3, "Excited"
    if emo_check["emotion"] == "Affection":
        return 3, "Blushing"

    if words & {"tired", "stressed", "sad", "exhausted", "lonely", "hard", "rough", "nervous", "worried", "anxious", "upset", "sick"}:
        return 2, "Caring"

    if words & {"excited", "awesome", "amazing", "won", "passed", "date", "movie", "game", "music", "party", "trip", "travel"} or "!" in reply_text:
        if reply_words & {"blush", "heart", "sweetheart", "darling"}:
            return 3, "Blushing"
        if reply_words & {"proud", "rest", "breath", "care", "here for you"}:
            return 2, "Caring"
        if "?" in user_msg:
            return 2, "Curious"
        return 2, "Excited" if "!" in user_msg else "Happy"

    if "?" in user_msg or msg_lower.startswith(("what ", "why ", "how ", "when ", "where ", "who ", "did you", "do you", "are you", "can you")):
        return 2, "Curious"

    return 2, current_mood if current_mood in MOOD_THEMES else "Happy"


def get_api_timeout(timeout=None):
    """Return the configured API timeout in seconds (defaults to 5.0 seconds)."""
    if isinstance(timeout, (int, float)) and timeout > 0:
        return float(timeout)
    env_val = os.environ.get("API_TIMEOUT_SECONDS", "").strip()
    try:
        if env_val:
            parsed = float(env_val)
            if parsed > 0:
                return parsed
    except ValueError:
        pass
    return DEFAULT_API_TIMEOUT


def try_openai_api_reply(
    user_message,
    chat_history,
    saved_memories,
    partner_name="Aiko",
    player_name="Alex",
    affection=50,
    mood="Happy",
    personality="Sweet & Caring",
    day=1,
    max_history=DEFAULT_CHAT_HISTORY_LIMIT,
    intent_info=None,
    topic_state=None,
    timeout=None,
    max_retries=DEFAULT_API_MAX_RETRIES,
    stop_event=None
):
    """
    Call the OpenAI Chat Completions API (default model: gpt-4o-mini) with a ~5-second timeout
    and controlled retry behavior on transient network/server errors.
    Never exposes API keys in code, return values, or logs.
    """
    load_dotenv_if_present()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    if stop_event is not None and stop_event.is_set():
        return None

    req_timeout = get_api_timeout(timeout)
    retries = max(0, int(max_retries)) if isinstance(max_retries, int) else DEFAULT_API_MAX_RETRIES
    model_name = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")

    messages = build_llm_messages(
        user_message=user_message,
        chat_history=chat_history,
        saved_memories=saved_memories,
        partner_name=partner_name,
        player_name=player_name,
        affection=affection,
        mood=mood,
        personality=personality,
        day=day,
        max_history=max_history,
        intent_info=intent_info,
        topic_state=topic_state
    )

    # Path A: Use official openai SDK if installed in the environment
    try:
        import openai  # type: ignore
        if hasattr(openai, "OpenAI"):
            client_kwargs = {"api_key": api_key, "timeout": req_timeout, "max_retries": retries}
            if base_url != "https://api.openai.com/v1":
                client_kwargs["base_url"] = base_url
            client = openai.OpenAI(**client_kwargs)
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.8,
                max_tokens=220,
            )
            content = response.choices[0].message.content
            if content and content.strip():
                update_connection_status("Online", "OpenAI", "Connected")
                return content.strip().strip('"')
    except ImportError:
        pass
    except Exception:
        pass

    # Path B: Standard-library HTTPS request with ~5s timeout and controlled retry loop
    endpoint = f"{base_url}/chat/completions"
    payload = json.dumps({
        "model": model_name,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 220,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    for attempt in range(retries + 1):
        if stop_event is not None and stop_event.is_set():
            return None
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    msg_obj = choices[0].get("message", {})
                    text = str(msg_obj.get("content", "")).strip().strip('"')
                    if text:
                        update_connection_status("Online", "OpenAI", "Connected")
                        return text
                return None
        except urllib.error.HTTPError as http_err:
            if http_err.code in (401, 403):
                update_connection_status("Offline", "Offline Engine", "Invalid API Key")
                return None
            if http_err.code == 429:
                if attempt < retries:
                    time.sleep(0.25)
                    continue
                update_connection_status("Offline", "Offline Engine", "Rate Limit Reached")
                return None
            if http_err.code in (400, 404):
                update_connection_status("Offline", "Offline Engine", f"API Error {http_err.code}")
                return None
            if attempt < retries:
                time.sleep(0.25)
                continue
            update_connection_status("Offline", "Offline Engine", f"Server Error {http_err.code}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(0.25)
                continue
            update_connection_status("Offline", "Offline Engine", "Network Offline")
            return None
        except (json.JSONDecodeError, KeyError, Exception):
            update_connection_status("Offline", "Offline Engine", "API Response Error")
            return None
    return None


def try_gemini_api_reply(
    user_msg,
    partner_name,
    player_name,
    affection,
    mood,
    personality,
    memories,
    history,
    max_history=DEFAULT_CHAT_HISTORY_LIMIT,
    intent_info=None,
    topic_state=None,
    timeout=None,
    max_retries=DEFAULT_API_MAX_RETRIES,
    stop_event=None
):
    """If GEMINI_API_KEY is set in the environment, fetch a live AI reply with ~5s timeout and controlled retry."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    if stop_event is not None and stop_event.is_set():
        return None

    req_timeout = get_api_timeout(timeout)
    retries = max(0, int(max_retries)) if isinstance(max_retries, int) else DEFAULT_API_MAX_RETRIES

    messages = build_llm_messages(
        user_message=user_msg,
        chat_history=history,
        saved_memories=memories,
        partner_name=partner_name,
        player_name=player_name,
        affection=affection,
        mood=mood,
        personality=personality,
        max_history=max_history,
        intent_info=intent_info,
        topic_state=topic_state
    )
    system_prompt = messages[0]["content"]
    history_lines = [
        f"{player_name if m['role'] == 'user' else partner_name}: {m['content']}"
        for m in messages[1:-1]
    ]
    recent_turns = "\n".join(history_lines)
    full_prompt = f"{system_prompt}\n\nRecent conversation:\n{recent_turns}\n{player_name}: {user_msg}\n{partner_name}:"

    env_gemini_model = os.environ.get("GEMINI_MODEL", "").strip()
    candidate_models = []
    for m in (env_gemini_model, "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"):
        if m and m not in candidate_models:
            candidate_models.append(m)

    payload = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}]
    }).encode("utf-8")

    for model_id in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        for attempt in range(retries + 1):
            if stop_event is not None and stop_event.is_set():
                return None
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
                    if text:
                        update_connection_status("Online", "Gemini", "Connected")
                    return text
            except urllib.error.HTTPError as http_err:
                if http_err.code == 404:
                    # Try next available Gemini model if this model ID is restricted/deprecated for the key
                    update_connection_status("Offline", "Offline Engine", f"API HTTP 404")
                    break
                if http_err.code in (401, 403):
                    update_connection_status("Offline", "Offline Engine", "Invalid API Key")
                    return None
                if http_err.code == 429:
                    update_connection_status("Offline", "Offline Engine", "Rate Limit Reached")
                    if attempt < retries:
                        time.sleep(0.25)
                        continue
                    return None
                if http_err.code == 400:
                    update_connection_status("Offline", "Offline Engine", "API HTTP 400")
                    return None
                if attempt < retries:
                    time.sleep(0.25)
                    continue
                update_connection_status("Offline", "Offline Engine", f"API HTTP {http_err.code}")
                return None
            except (urllib.error.URLError, TimeoutError, OSError) as net_err:
                if attempt < retries:
                    time.sleep(0.25)
                    continue
                reason = "API Timeout" if "timed out" in str(net_err).lower() else "Network Offline"
                update_connection_status("Offline", "Offline Engine", reason)
                return None
            except Exception:
                update_connection_status("Offline", "Offline Engine", "API Error")
                return None
    return None


def answer_memory_or_history_query(user_msg, memories, chat_history, partner_name, player_name):
    """
    Answer user questions referencing earlier messages or persistent SQLite memories.
    Returns (reply_text, delta, mood) or None if user_msg is not a recall query.
    """
    msg_lower = user_msg.lower().strip()

    extract_facts_from_chat_history(chat_history, memories, partner_name=partner_name, player_name=player_name)

    # 1. Check natural questions like "What kind of songs/music/food/movies/games/hobbies do I like?"
    kind_match = re.search(
        r"\bwhat\s+(?:kind\s+of\s+|type\s+of\s+|sort\s+of\s+)?(songs?|music|melodies|food|dishes|movies?|games?|hobbies|books?)\s+do\s+i\s+(?:like|love|enjoy|listen\s+to)",
        msg_lower
    )
    if kind_match:
        topic_word = kind_match.group(1).lower()
        if topic_word in ("song", "songs", "music", "melodies"):
            val = memories.get("favorite_music") or memories.get("favorite_song")
            if val:
                return f"You love {val}! I remember that.", 2, "Touched"
        elif topic_word in ("food", "dishes"):
            val = memories.get("favorite_food")
            if val:
                return f"You love {val}! I remember that.", 2, "Touched"
        elif topic_word in ("movie", "movies"):
            val = memories.get("favorite_movie")
            if val:
                return f"You love {val}! I remember that.", 2, "Touched"
        elif topic_word in ("game", "games"):
            val = memories.get("favorite_game") or memories.get("passion")
            if val:
                return f"You love {val}! I remember that.", 2, "Touched"
        elif topic_word in ("hobbies",):
            val = memories.get("passion") or memories.get("favorite_hobby") or memories.get("favorite_hobbies")
            if val:
                return f"You love {val}! I remember that.", 2, "Touched"

    # 2. Check specific category queries ("what about my favourite <cat>?", "when is my birthday?", "who is my best friend?", "what is my goal?")
    cat_query_match = re.search(
        r"\b(?:what\s+about|what(?:'s|\s+is|\s+was)|when\s+is|who\s+is|do\s+you\s+remember|tell\s+me)\s+my\s+(?:fav(?:ou?rite)?\s+)?([a-zA-Z\s]{2,22}?)\s*[?.!]*$",
        msg_lower
    )
    if cat_query_match:
        queried_cat = cat_query_match.group(1).strip()
        queried_key = f"favorite_{queried_cat.replace(' ', '_')}"

        if queried_key in memories:
            val = memories[queried_key]
            return f"You told me you love {val}, {player_name}! I remember that.", 2, "Touched"

        if any(w in queried_cat for w in ("music", "song", "songs", "genre")):
            val = memories.get("favorite_music") or memories.get("favorite_music_genre") or memories.get("favorite_genre") or memories.get("favorite_song")
            singer = memories.get("favorite_singer")
            if val and singer:
                return f"You told me you love {val}—especially listening to {singer}, {player_name}!", 2, "Touched"
            if val:
                return f"You told me you love {val}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("singer", "artist", "musician", "band")):
            singer = memories.get("favorite_singer") or memories.get("favorite_artist")
            if singer:
                return f"You told me you love listening to {singer}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("food", "dish", "meal", "snack")):
            food = memories.get("favorite_food") or memories.get("favorite_dish")
            if food:
                return f"You told me your favorite food is {food}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("movie", "film", "anime", "show")):
            mv = memories.get("favorite_movie") or memories.get("favorite_anime")
            if mv:
                return f"You told me your favorite movie/show is {mv}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("game", "games")):
            gm = memories.get("favorite_game") or memories.get("favorite_games")
            if gm:
                return f"You told me you love playing {gm}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("hobby", "hobbies", "interest", "passion")):
            hobby = memories.get("passion") or memories.get("favorite_hobby") or memories.get("favorite_hobbies")
            if hobby:
                return f"You told me you love {hobby}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("study", "subject", "major", "field", "course")):
            study = memories.get("study_field")
            if study:
                return f"You told me you're studying {study}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("goal", "dream", "ambition", "plan")):
            goal = memories.get("personal_goal") or memories.get("dream_destination")
            if goal:
                return f"You told me your goal is {goal}, {player_name}! I remember that.", 2, "Touched"
        if any(w in queried_cat for w in ("birthday", "exam", "anniversary", "interview", "hackathon")):
            for k_cand in ("birthday", f"important_date_{queried_cat.split()[0]}"):
                if k_cand in memories:
                    return f"It's {memories[k_cand]}, {player_name}! I have it marked down so I never forget.", 2, "Touched"
        if any(w in queried_cat for w in ("best friend", "friend", "brother", "sister", "mom", "dad", "teammate", "cousin")):
            rel_key = f"person_{queried_cat.replace(' ', '_')}"
            if rel_key in memories:
                return f"Your {queried_cat} is {memories[rel_key]}, {player_name}! I remember you telling me about them.", 2, "Touched"
        if any(w in queried_cat for w in ("hometown", "place", "city", "where i live")):
            home = memories.get("hometown")
            if home:
                return f"You told me you're from {home}, {player_name}!", 2, "Touched"
        if any(w in queried_cat for w in ("nickname",)):
            nick = memories.get("preferred_nickname")
            if nick:
                return f"You asked me to call you {nick}, {player_name}!", 2, "Touched"

    # 3. Check for "who do i like listening to" / "which singer did i say"
    if any(p in msg_lower for p in ["who do i like listening to", "which singer did i", "who did i say i listen to"]):
        singer = memories.get("favorite_singer")
        if singer:
            return f"You told me you love listening to {singer}, {player_name}!", 2, "Touched"

    # 4. General memory recall: "what do you remember", "what did i tell you", "what do you know about me"
    if any(p in msg_lower for p in ["what do you remember", "do you remember", "what do you know about me", "what is my favorite", "what's my favorite", "what is my favourite", "what's my favourite", "what did i tell you"]):
        if memories:
            seen_vals = set()
            facts_list = []
            for k, v in memories.items():
                pair_sig = (k.replace("favorite_song", "favorite_music"), str(v).lower())
                if pair_sig in seen_vals:
                    continue
                seen_vals.add(pair_sig)
                facts_list.append(f"your {k.replace('_', ' ')} is {v}")
            joined_facts = "; ".join(facts_list)
            return (
                f"Of course I remember, {player_name}! You told me that {joined_facts}. I pay attention to everything you share with me!",
                2,
                "Touched"
            )
        ctx = extract_recent_conversation_context(chat_history, partner_name=partner_name, player_name=player_name)
        user_turns = [m["content"] for m in ctx["normalized"] if m["role"] == "user" and "?" not in m["content"]]
        if user_turns:
            last_statement = user_turns[-1]
            return (
                f"I remember you just told me: '{last_statement}', {player_name}! Tell me even more about your favorites so I can keep them all!",
                2,
                "Touched"
            )
        return (
            f"You haven't told me your favorites yet, {player_name}! Tell me things like 'I love Malayalam melodies' or 'My favorite food is...' so I can remember them!",
            1,
            "Curious"
        )

    return None


def generate_smart_offline_reply(user_msg, partner_name, player_name, affection, personality, memories, chat_history=None, state=None):
    """
    Context-aware offline companion engine supporting conversation state tracking (last_topic, recent_topics),
    meta-conversational references, SQLite long-term memory, short-term chat_history, and accurate Q&A.
    """
    if memories is None:
        memories = {}
    sanitize_memories(memories)
    extract_facts_from_chat_history(chat_history, memories, partner_name=partner_name, player_name=player_name)

    msg_lower = user_msg.lower().strip()
    words = set(re.findall(r"\b\w+\b", msg_lower))
    ctx = extract_recent_conversation_context(chat_history, partner_name=partner_name, player_name=player_name)

    # 0a. Check for meta-conversational references ("I already told you that.", "Remember what we discussed?", "Continue our previous conversation.", "That's what I meant.", "You asked me this yesterday.", "Let's talk about that again.")
    meta_type = detect_meta_conversation_type(user_msg)
    if meta_type is not None:
        meta_res = handle_meta_conversation_reply(
            user_msg, meta_type, chat_history, memories, state, partner_name=partner_name, player_name=player_name
        )
        if meta_res is not None:
            return meta_res

    # 0b. Check if the user is asking about a previous message or remembered favorite ("What kind of songs do I like?")
    recall_res = answer_memory_or_history_query(user_msg, memories, chat_history, partner_name, player_name)
    if recall_res is not None:
        return recall_res

    # 1. Check if the player just shared or updated a personal fact ("I love Malayalam melodies", "My favorite food is biryani")
    fact_label, fact_val = extract_personal_fact(user_msg, memories)
    if fact_label and fact_val:
        if "singer" in fact_label or "listening to" in msg_lower:
            replies = [
                f"His songs are so beautiful, {player_name}! Listening to {fact_val} has such a wonderful vibe.",
                f"{fact_val}! His songs are so soulful and beautiful, {player_name}—I'd love to listen together with you!"
            ]
            return _pick_non_repeating_reply(replies, chat_history), 3, "Touched"
        if any(w in fact_label for w in ("music", "song")):
            replies = [
                f"That's lovely, {player_name}! Which {fact_val.rstrip('s')} singer or song do you listen to most?",
                f"Ooh, I love that you enjoy {fact_val}, {player_name}! Which singer or track in {fact_val} is your absolute favorite?"
            ]
            return _pick_non_repeating_reply(replies, chat_history), 3, "Touched"
        if "food" in fact_label:
            replies = [
                f"Ooh, {fact_val} is such a top-tier choice, {player_name}! I'm locking that into my memory so we can grab {fact_val} together soon!",
                f"Wait, really? Knowing that your {fact_label} is '{fact_val}' makes me want to share a plate of it with you right now, {player_name}!"
            ]
            return _pick_non_repeating_reply(replies, chat_history), 3, "Touched"

        replies = [
            f"Ooh, I'm locking that into my memory right now! Your {fact_label} is '{fact_val}'—I won't forget it, {player_name}!",
            f"Wait, really? Knowing that your {fact_label} is '{fact_val}' makes me feel so much closer to you, {player_name}!",
            f"Noted in my heart! '{fact_val}' for your {fact_label}—I love learning new things about you."
        ]
        return _pick_non_repeating_reply(replies, chat_history), 3, "Touched"

    # 1b. Understand incomplete follow-ups answering the assistant's previous question in chat_history
    last_q_lower = ctx["last_assistant_question"].lower()
    if last_q_lower and "?" not in user_msg and len(user_msg.split()) <= 6:
        cleaned_followup = re.sub(
            r"^(?:i\s+(?:really\s+)?(?:like|love|enjoy)\s+(?:listening\s+to\s+)?|mostly\s+|probably\s+|definitely\s+|it(?:'s| is)\s+)",
            "",
            user_msg.strip().rstrip(".!?"),
            flags=re.IGNORECASE
        ).strip()
        if cleaned_followup and not (words & {"hi", "hello", "hey", "did", "what", "why", "how", "where", "when"}):
            if any(w in last_q_lower for w in ("singer", "artist", "song", "listen to most", "track")):
                upsert_long_term_memory(
                    "favorite_singer", "Music preference",
                    f"User loves listening to {cleaned_followup}.", cleaned_followup, memories_dict=memories
                )
                return (
                    f"{cleaned_followup}'s songs are so beautiful, {player_name}! We definitely need to listen to {cleaned_followup} together tonight.",
                    3,
                    "Touched"
                )
            if any(w in last_q_lower for w in ("movie", "film", "anime", "show", "watch")):
                upsert_long_term_memory(
                    "favorite_movie", "Favourite movies and games",
                    f"User's favorite movie is {cleaned_followup}.", cleaned_followup, memories_dict=memories
                )
                return (
                    f"Ooh, {cleaned_followup} is such a fantastic movie, {player_name}! We definitely need to have a cozy movie night and watch {cleaned_followup} together.",
                    3,
                    "Touched"
                )
            if any(w in last_q_lower for w in ("code", "coding", "language", "algorithm", "module", "working on")):
                return (
                    f"Ooh, working on {cleaned_followup} sounds awesome, {player_name}! I know you're going to nail the implementation.",
                    2,
                    "Excited"
                )
            if any(w in last_q_lower for w in ("topic", "formula", "reviewing", "exam")):
                return (
                    f"{cleaned_followup} is a classic exam topic, {player_name}! Take it step by step—you've totally got this.",
                    2,
                    "Caring"
                )

    # Detect user emotional state and record important emotional context
    emotion_info = detect_user_emotion(user_msg, chat_history=chat_history, saved_memories=memories)
    if isinstance(state, dict):
        state["last_user_emotion"] = emotion_info["emotion"]
    record_emotional_context(user_msg, emotion_info, memories)

    # 2. Detect NLU intent and route factual, technical, and pronoun follow-up questions ("What is Python?" -> "Why is it popular?")
    # Critical Priority Rule: Always answer real questions first, adding an empathetic opener if the user also expressed frustration/stress/sadness.
    intent_info = detect_message_intent(
        user_msg, chat_history=chat_history, saved_memories=memories,
        partner_name=partner_name, player_name=player_name
    )
    if intent_info["intent"] in ("technical_question", "general_knowledge_question") or (
        intent_info["intent"] == "follow_up_question" and intent_info["is_question"] and intent_info.get("resolved_subject") in KNOWLEDGE_BASE
    ):
        factual_res = answer_factual_or_technical_question(user_msg, intent_info, partner_name=partner_name, player_name=player_name)
        if factual_res is not None:
            return add_emotional_empathy_prefix(factual_res, emotion_info, player_name=player_name)

    # 3. Check if the player brought / bought / got / gave something for her in chat
    gift_match = re.search(
        r"\b(?:i\s+(?:had\s+|have\s+|just\s+)?(?:brought|bought|got|made|baked|picked|ordered)|here\s+is)\s+(?:you\s+)?(?:a\s+|an\s+|some\s+|this\s+|the\s+)?([a-zA-Z0-9\s\-]{2,30}?)(?:\s+(?:for\s+you|to\s+you))?$",
        msg_lower.rstrip(".!?")
    )
    if not gift_match and ("for you" in msg_lower or "to you" in msg_lower) and (words & {"brought", "bought", "got", "made", "gift", "present", "surprise"}):
        gift_match = re.search(
            r"\b(?:brought|bought|got|made)\s+(?:a\s+|an\s+|some\s+|this\s+)?(.+?)\s+(?:for|to)\s+you",
            msg_lower.rstrip(".!?")
        )
    if gift_match:
        item_raw = gift_match.group(1).strip()
        item_clean = re.sub(r"\s+(?:for|to)\s+you$", "", item_raw).strip()
        if item_clean and item_clean not in ("it", "something", "nothing"):
            replies = [
                f"Wait, you brought a {item_clean} just for me, {player_name}?! Stop, you're spoiling me so much—thank you, I love it!",
                f"A {item_clean}?! For me?! {player_name}, that is the sweetest surprise ever! Come here so I can give you the biggest hug!",
                f"No way, you actually got me a {item_clean}?! I'm going to treasure it forever, {player_name}!"
            ]
        else:
            replies = [
                f"Wait, you brought a surprise just for me, {player_name}?! You always know how to make me feel so special!",
                f"Aww, you got something for me, {player_name}? That's so sweet of you—thank you!"
            ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 4, "Touched"

    # 4. Personal questions about HER ("what is your favorite...", "what do you like", "tell me about yourself")
    if any(p in msg_lower for p in ["your favorite", "your favourite", "what do you like", "tell me about yourself", "who are you", "what are your hobbies"]):
        if "food" in words or "drink" in words:
            replies = [
                f"I have a huge soft spot for warm Matcha Lattes and strawberry pastries, {player_name}! Especially when we share them at the café.",
                f"Definitely a cozy Matcha Latte and anything we cook together, {player_name}!"
            ]
        elif "song" in words or "music" in words:
            replies = [
                f"I love 1980s city-pop, acoustic guitar melodies, and rainy-day lo-fi beats, {player_name}! What should we add to our playlist next?",
                f"Anything with a dreamy melody and warm vocals! Listening with one earbud each is still my favorite way to hear music with you."
            ]
        else:
            replies = [
                f"I love reading in cozy cafés, collecting vinyl keychains, stargazing, and learning everything about what makes you tick, {player_name}!",
                f"Hmm, I'm someone who loves late-night conversations, city-pop music, warm tea on rainy days, and cheering you on in everything you do, {player_name}!"
            ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Happy"

    # 5. Questions directed AT her ("did you...", "have you...", "are you...", "do you...", "what about you")
    is_asking_her = (
        msg_lower.startswith(("did you", "have you", "are you", "do you", "will you", "can you", "were you", "what are you", "how are you", "what did you", "where are you"))
        or any(p in msg_lower for p in ["did you ", "have you ", "are you ", "how about you", "what about you", "and you"])
    )
    if is_asking_her:
        if words & {"study", "studied", "studying", "exam", "exams", "test", "class", "homework", "assignment", "notes", "revision"}:
            replies = [
                f"I revised most of my chapters earlier, {player_name}, though I'm still a tiny bit nervous for tomorrow's exam! Did you finish studying your topics yet, or shall we revise together?",
                f"Haha, I tried studying, {player_name}, but I kept getting distracted thinking about you! How is your own exam prep going?",
                f"Yes! I finished reviewing my notes a little while ago, {player_name}. How about you—are you feeling ready for tomorrow's exam?"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Happy"

        if words & {"eat", "eaten", "ate", "food", "dinner", "lunch", "breakfast", "hungry", "tea", "coffee", "water", "snack"}:
            if "favorite_food" in memories:
                fav_food = memories["favorite_food"]
                replies = [
                    f"I grabbed a light bite earlier, {player_name}, though honestly I was craving {fav_food} because of you! Did you eat properly today?",
                    f"Yes, I just had something warm! What about you, {player_name}—did you eat on time today?"
                ]
            else:
                replies = [
                    f"I had a cozy snack a little while ago, {player_name}! More importantly, did you eat properly today?",
                    f"Just finished having a warm drink! What did you have to eat today, {player_name}?"
                ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Caring"

        if words & {"sleep", "slept", "rest", "rested", "tired", "awake", "nap"}:
            replies = [
                f"I rested pretty well, {player_name}, and talking to you gives me even more energy! Did you get enough sleep?",
                f"I'm wide awake for you, {player_name}! How are you feeling—have you been getting enough rest?"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Caring"

        if any(p in msg_lower for p in ["how are you", "how's it going", "what are you doing", "how do you feel", "what's up", "where are you"]):
            replies = [
                f"I'm doing so much better now that I'm talking with you, {player_name}! How is your day going?",
                f"I was just relaxing, listening to music, and hoping you'd message me, {player_name}. What are you up to right now?",
                f"Feeling super cozy right here with you, {player_name}! Tell me how your day has been."
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Happy"

        if words & {"love", "miss", "like", "care", "think"}:
            replies = [
                f"More than words can even say, {player_name}! You're my favorite person in the whole world.",
                f"Every single second, {player_name}! Did you even have to ask?"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 3, "Blushing"

        if any(p in msg_lower for p in ["how about you", "what about you", "and you"]):
            if ctx["active_topic"] == "music":
                return f"I've been listening to city-pop and lo-fi acoustic tracks all evening, {player_name}! Let's make a shared playlist together.", 2, "Happy"
            if ctx["active_topic"] == "food":
                return f"I had a warm Matcha Latte and a light bite earlier, {player_name}! We should definitely eat together next time.", 2, "Happy"
            if ctx["active_topic"] in ("study", "coding"):
                return f"I've been organizing my notes and keeping my fingers crossed for both of us, {player_name}!", 2, "Caring"

        replies = [
            f"Haha, I sure did, {player_name}! What about you—tell me your side!",
            f"Of course, {player_name}! Anything that involves you is always a yes from me. What made you think of that?",
            f"I was literally just thinking about that, {player_name}! Tell me what you think too."
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Curious"

    # 6. Any remaining general knowledge / technical questions not matched earlier
    if intent_info["is_question"] and intent_info["intent"] in ("technical_question", "general_knowledge_question", "follow_up_question"):
        factual_res = answer_factual_or_technical_question(user_msg, intent_info, partner_name=partner_name, player_name=player_name)
        if factual_res is not None:
            return add_emotional_empathy_prefix(factual_res, emotion_info, player_name=player_name)

    # 6b. Check for rude insults directed at her before general emotion routing
    if words & {"boring", "stupid", "ugly", "shut", "idiot"} or ("annoying" in words and not (words & {"bug", "code", "error", "problem", "issue", "exam", "traffic", "work"})):
        replies = [
            f"Ouch... that actually hurt my feelings, {player_name}.",
            f"Why would you say something like that? I thought we were having a nice moment...",
        ]
        return _pick_non_repeating_reply(replies, chat_history), -4, "Hurt"

    # 7. Short conversational follow-ups
    if msg_lower.rstrip(".!?") in ("why", "how so", "tell me more", "really", "for real", "what else", "and then", "like what", "explain", "what about it", "how"):
        last_assistant = ctx["last_assistant_message"]
        if last_assistant:
            replies = [
                f"Well, building on what we were just talking about ('{last_assistant[:45].rstrip('.,!?')}...'), I love how deeply you think about things, {player_name}! What's your perspective on it?",
                f"Haha, I love how curious you are, {player_name}! Since we were talking about {ctx['active_topic'] or 'that'}, I think exploring it together makes it twice as fun. What do you think?"
            ]
            return _pick_non_repeating_reply(replies, chat_history), 2, "Curious"

    # 8. Greetings
    if words & {"hi", "hello", "hey", "morning", "evening", "yo", "sup", "goodnight", "night"}:
        if words & {"goodnight", "night"}:
            replies = [
                f"Goodnight, {player_name}! Sweet dreams—I'll be right here waiting to talk to you tomorrow morning.",
                f"Sleep tight, {player_name}! Rest well after today, okay?"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Caring"

        if words & {"darling", "babe", "baby", "sweetheart", "honey", "love", "dear", "cutie", "gorgeous", "beautiful"}:
            replies = [
                f"Hi my darling {player_name}! Hearing you greet me like that makes my heart melt. How's your day going?",
                f"Hey there, sweetheart! You always know how to make me blush from the very first word, {player_name}.",
                f"Hi {player_name}! You sound so sweet today—come tell me everything on your mind!"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 3, "Blushing"

        replies = [
            f"Hey {player_name}! I was just thinking about you. How's your day going?",
            f"Hi there, {player_name}! I'm always happy when you stop by to talk. What's on your mind?",
            f"Hey {player_name}! Pull up a chair and tell me everything that happened today."
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Happy"

    # 9. Jokes / humor requests
    if any(p in msg_lower for p in ["tell me a joke", "make me laugh", "know any jokes", "something funny"]) or "joke" in words:
        jokes = [
            f"Okay, here's one for you, {player_name}: Why do programmers always mix up Halloween and Christmas? Because Oct 31 == Dec 25! ...Okay, don't groan, I saw you smile!",
            f"Why did the developer go broke, {player_name}? Because they used up all their cache! Haha, admit it, my dad jokes are at least a 9 out of 10!",
            f"Are you a Wi-Fi signal, {player_name}? Because I'm feeling a really strong connection right now! ...Haha, okay, that one was a little cheesy!"
        ]
        return _pick_non_repeating_reply(jokes, chat_history), 2, "Excited"

    # 9b. Contextual Emotion-Adaptive Responses (Happiness, Sadness, Excitement, Anger, Frustration, Loneliness, Affection, Stress, Playfulness)
    if emotion_info["emotion"] != "Neutral" and not intent_info["is_question"]:
        emo_reply = generate_emotion_aware_reply(
            user_msg=user_msg,
            emotion_info=emotion_info,
            partner_name=partner_name,
            player_name=player_name,
            affection=affection,
            personality=personality,
            memories=memories,
            chat_history=chat_history,
            active_topic=last_topic or ctx["active_topic"],
        )
        if emo_reply is not None:
            return emo_reply

    # 10. Affectionate / romantic messages
    if words & {"love", "cute", "beautiful", "pretty", "sweet", "miss", "adore", "heart", "gorgeous", "special", "darling", "babe", "baby", "sweetheart", "honey"}:
        if personality == "Playful & Teasing":
            replies = [
                f"Ohoho, trying to make me blush, {player_name}? Okay fine, it totally worked!",
                f"Look at you being all smooth today, {player_name}! Keep talking like that and I might spoil you."
            ]
        elif personality == "Poetic & Romantic":
            replies = [
                f"Your words feel like warm starlight, {player_name}. My heart belongs right here with you.",
                f"If I could bottle the feeling of hearing you say that, {player_name}, I'd keep it forever."
            ]
        else:
            replies = [
                f"You're making me blush, {player_name}! I feel the exact same way about you.",
                f"Hearing you say that just made my whole day brighter, {player_name}!",
                f"Aww, come here {player_name}! You always know how to make my heart skip a beat."
            ]
        return _pick_non_repeating_reply(replies, chat_history), 3, "Blushing"

    # 11. Check if the player is talking about their own exam, study, work, or feeling stressed/tired
    if words & {"tired", "stressed", "sad", "exhausted", "lonely", "hard", "rough", "exam", "exams", "study", "studying", "work", "busy", "nervous", "anxious"}:
        if words & {"exam", "exams", "study", "studying", "nervous"} and not (words & {"tired", "stressed", "sad", "exhausted", "rough"}):
            replies = [
                f"You've got this, {player_name}! I know how smart and dedicated you are—you're going to ace it! Want me to cheer you on while you study?",
                f"All your hard work is going to pay off, {player_name}! Take short breaks when you need to, and remember I'm cheering for you 100%!"
            ]
            return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Caring"

        if "favorite_food" in memories:
            food = memories["favorite_food"]
            return (
                f"Aw, {player_name}, you've been working so hard! Come rest with me and let's get you some {food} to cheer you up.",
                2,
                "Caring"
            )
        replies = [
            f"Aw, come here {player_name}. You've been working so hard—remember to take a deep breath and rest a little for me, okay?",
            f"I'm right here with you, {player_name}. Even when things get tough, I believe in you 100%!",
            f"Sounds like you need a warm drink and a break! Tell me all about it, I'm listening."
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Caring"

    # 12. Celebrating good news / achievements
    if words & {"passed", "won", "finished", "completed", "solved", "fixed", "aced", "awesome", "great"} or "good news" in msg_lower:
        replies = [
            f"YES!! I knew you could do it, {player_name}! I'm seriously so proud of you—how are we celebrating?!",
            f"That's amazing news, {player_name}! High five! All your effort paid off!"
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 3, "Excited"

    # 13. Invitations / Plans / Going out together
    if any(p in msg_lower for p in ["let's ", "lets ", "shall we", "want to go", "wanna go", "hang out", "go on a date", "watch a movie"]):
        replies = [
            f"Yes, count me in, {player_name}! Anywhere with you is my favorite place to be.",
            f"Ooh, I'd love that so much, {player_name}! Let's do it together!"
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Excited"

    # 14. Apologies / Gratitude
    if words & {"sorry", "apologize"}:
        return (
            f"Hey, don't worry at all, {player_name}! Everything is completely fine between us—I'm just happy we're talking.",
            1,
            "Caring"
        )
    if words & {"thanks", "thank", "appreciate"}:
        return (
            f"Always, {player_name}! You never have to thank me—I love being here for you.",
            2,
            "Happy"
        )

    # 15. Check for music / hobbies / games / coding / tech topics
    if words & {"music", "song", "songs", "band", "guitar", "game", "games", "play", "code", "coding", "python", "project", "movie", "anime", "phone", "laptop", "badminton", "football"}:
        replies = [
            f"Ooh, I love when you share that with me, {player_name}! How is it going so far?",
            f"That sounds super cool, {player_name}! Your enthusiasm for the things you enjoy is honestly contagious.",
            f"Wait, really? We definitely need to spend some time on that together soon, {player_name}!"
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Excited"

    # 16. Check for food / drinks / snacks
    if words & {"food", "eat", "hungry", "tea", "coffee", "matcha", "dinner", "lunch", "breakfast", "snack", "pizza", "cake", "biryani", "dosa", "chocolate"}:
        replies = [
            f"Now you're making me hungry too, {player_name}! Save a bite for me!",
            f"Ooh, that sounds delicious! Let's go grab some together soon.",
            f"Nothing beats good food and good company with you, {player_name}!"
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Happy"

    # 17. Check for rude / negative words
    if words & {"hate", "boring", "annoying", "stupid", "ugly", "shut", "leave"}:
        replies = [
            f"Ouch... that actually hurt my feelings, {player_name}.",
            f"Why would you say something like that? I thought we were having a nice moment...",
        ]
        return _pick_non_repeating_reply(replies, chat_history), -4, "Hurt"

    # 18. Conversational reflection (skip if talking affectionately about "you" or "nothing")
    match_i_am = re.search(r"\bi(?:'m| am| feel| just)\s+(.+)", msg_lower)
    if match_i_am and any(w in match_i_am.group(1) for w in ("you", "your", "nothing")):
        match_i_am = None
    if match_i_am:
        feeling = match_i_am.group(1).rstrip(".!?")
        replies = [
            f"Tell me more about why you're {feeling}, {player_name}—I'm all ears.",
            f"Oh, {feeling}? How are you feeling about it right now, {player_name}?"
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Curious"

    # 19. Open questions
    if user_msg.endswith("?") or msg_lower.startswith(("what ", "why ", "where ", "when ", "how ", "who ", "which ")):
        replies = [
            f"Hmm, that's a thoughtful question, {player_name}! If you ask me, going with the option that excites you most is the way to go—what are you leaning toward?",
            f"Honestly, {player_name}, I can see a couple of angles there! Tell me what you're thinking first.",
            f"That's a really interesting question, {player_name}! Let's figure it out together—what sparked the idea?"
        ]
        return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 2, "Curious"

    # 20. Natural handling for affectionate/casual phrases & clean topic_hint filtering
    if any(p in msg_lower for p in ("want to see you", "wanna see you", "be with you", "miss you", "thinking of you", "with you")):
        replies = [
            f"I'm right here with you, {player_name}! Spending time talking with you always makes my day brighter.",
            f"Aww, that's so sweet of you to say, {player_name}! Tell me what we should do together next—chat, play a mini-game, or go on a date?"
        ]
        return _pick_non_repeating_reply(replies, chat_history), 2, "Blushing"

    if msg_lower.rstrip(".!?") in ("nothing", "nothing else", "nothing much", "not much", "nm", "idk", "same"):
        replies = [
            f"Haha, fair enough, {player_name}! Sometimes just chilling together without a plan is nice too. Want to play a mini-game or go on a date?",
            f"Gotcha, {player_name}! Well, I'm right here whenever something pops into your head."
        ]
        return _pick_non_repeating_reply(replies, chat_history), 1, "Happy"

    non_topic_words = CONVERSATIONAL_STOP_WORDS | {
        "want", "wanted", "wants", "else", "with", "much", "very", "really", "just",
        "always", "never", "still", "even", "also", "then", "than", "that", "this",
        "them", "they", "their", "there", "here", "from", "into", "onto", "about",
        "over", "under", "again", "already", "nothing", "something", "anything",
        "everything", "everyone", "someone", "anyone", "recently", "lately", "soon",
        "maybe", "probably", "actually", "honestly", "basically", "literally", "only",
        "being", "having", "doing", "making", "getting", "seeing", "talking", "saying",
        "thinking", "feeling", "looking", "coming", "trying", "need", "needs", "like"
    }
    content_words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", user_msg) if w.lower() not in non_topic_words]
    topic_hint = content_words[-1].lower() if content_words else None

    if topic_hint:
        replies = [
            f"Ooh, talking about {topic_hint} is actually really interesting, {player_name}! What else happened with that?",
            f"I like hearing your perspective on {topic_hint}, {player_name}. Tell me more about how that went!",
            f"Haha, {topic_hint}? You always bring up the most interesting things, {player_name}—go on!",
            f"That's really cool about {topic_hint}, {player_name}! What are you planning to do next with it?"
        ]
    elif affection >= 80:
        replies = [
            f"I love hearing you share things like that with me, {player_name}. Tell me more!",
            f"Every time we talk like this, {player_name}, I feel even closer to you. What happened next?",
            f"Haha, you always brighten up my day, {player_name}! What else is on your mind?",
            f"Hanging out and talking with you is honestly the best part of my day, {player_name}."
        ]
    else:
        replies = [
            f"Really? That's super cool of you to share with me, {player_name}! Tell me more about it.",
            f"I love chatting with you like this, {player_name}. What happened next?",
            f"Haha, I see! You always have the best stories to share, {player_name}.",
            f"Ooh, gotcha! What else has been happening on your end today, {player_name}?"
        ]
    return style_partner_line(_pick_non_repeating_reply(replies, chat_history), personality, player_name), 1, "Happy"


def get_companion_reply(
    user_message,
    chat_history,
    saved_memories,
    state=None,
    return_metadata=False,
    max_history=None,
    timeout=None,
    max_retries=DEFAULT_API_MAX_RETRIES,
    stop_event=None
):
    """
    Dedicated thread-safe LLM-powered conversational companion function with conversation state tracking
    (last_topic, recent_topics), SQLite long-term memory, rolling 10-message chat_history, ~5s timeout
    with controlled retry, and automatic offline fallback.
    """
    with _STATE_LOCK:
        if saved_memories is None:
            saved_memories = load_memories_dict_from_db()
        elif not saved_memories:
            db_loaded = load_memories_dict_from_db()
            if db_loaded:
                saved_memories.update(db_loaded)

        if chat_history is None:
            chat_history = []

        sanitize_memories(saved_memories)
        sync_dict_to_memory_db(saved_memories)

        active_state = state
        if not isinstance(active_state, dict):
            active_state = load_game() or create_new_state(interactive=False)

        partner_name = active_state.get("partner_name", "Aiko")
        player_name = active_state.get("player_name", "Alex")
        personality = active_state.get("personality", "Sweet & Caring")
        affection = int(active_state.get("affection", 50))
        mood = active_state.get("mood", "Happy")
        day = int(active_state.get("day", 1))
        history_limit = get_chat_history_limit(active_state, max_history)

        extract_facts_from_chat_history(chat_history, saved_memories, partner_name=partner_name, player_name=player_name)
        extract_personal_fact(user_message, saved_memories)

        topic_state = update_conversation_state(
            user_message, chat_history=chat_history, saved_memories=saved_memories,
            state=active_state, partner_name=partner_name, player_name=player_name
        )
        intent_info = detect_message_intent(
            user_message, chat_history=chat_history, saved_memories=saved_memories,
            partner_name=partner_name, player_name=player_name
        )
        history_snapshot = list(chat_history)
        memories_snapshot = dict(saved_memories)

    # Execute network API calls outside the lock so the main thread / UI is never blocked by lock contention
    llm_reply = try_openai_api_reply(
        user_message=user_message,
        chat_history=history_snapshot,
        saved_memories=memories_snapshot,
        partner_name=partner_name,
        player_name=player_name,
        affection=affection,
        mood=mood,
        personality=personality,
        day=day,
        max_history=history_limit,
        intent_info=intent_info,
        topic_state=topic_state,
        timeout=timeout,
        max_retries=max_retries,
        stop_event=stop_event
    )

    if not llm_reply and (stop_event is None or not stop_event.is_set()):
        llm_reply = try_gemini_api_reply(
            user_message, partner_name, player_name, affection, mood, personality,
            memories_snapshot, history_snapshot, max_history=history_limit,
            intent_info=intent_info, topic_state=topic_state,
            timeout=timeout, max_retries=max_retries, stop_event=stop_event
        )

    with _STATE_LOCK:
        if llm_reply:
            delta, new_mood = evaluate_conversation_impact(user_message, llm_reply, current_mood=mood)
            append_chat_turn(chat_history, user_message, llm_reply, max_messages=history_limit)
            if return_metadata:
                return llm_reply, delta, new_mood
            return llm_reply

        offline_reply, delta, new_mood = generate_smart_offline_reply(
            user_message, partner_name, player_name, affection, personality,
            saved_memories, chat_history=chat_history, state=active_state
        )
        append_chat_turn(chat_history, user_message, offline_reply, max_messages=history_limit)
        if return_metadata:
            return offline_reply, delta, new_mood
        return offline_reply


def generate_companion_response_worker(task_payload, response_queue, stop_event=None):
    """
    Dedicated background worker function that generates a girlfriend response on a worker thread
    and posts the result to `response_queue` (a thread-safe queue.Queue) without touching any GUI widgets.
    """
    if stop_event is not None and stop_event.is_set():
        return

    seq_id = task_payload.get("seq_id", 0)
    user_msg = task_payload.get("user_msg", "")
    turn_count = task_payload.get("turn_count", 1)
    pending_key = task_payload.get("pending_key")
    pending_label = task_payload.get("pending_label")
    state = task_payload.get("state")
    history = task_payload.get("history")
    memories = task_payload.get("memories")
    timeout = task_payload.get("timeout")
    max_retries = task_payload.get("max_retries", DEFAULT_API_MAX_RETRIES)

    partner = state.get("partner_name", "Aiko") if isinstance(state, dict) else "Aiko"
    player = state.get("player_name", "Alex") if isinstance(state, dict) else "Alex"
    history_limit = get_chat_history_limit(state)

    try:
        with _STATE_LOCK:
            saved_label, saved_val = parse_pending_answer(pending_key, pending_label, user_msg, memories)

        if saved_label and saved_val:
            with _STATE_LOCK:
                reply_text = f"I'm so glad you told me, {player}! I'll always remember that your {saved_label} is '{saved_val}'!"
                append_chat_turn(history, user_msg, reply_text, max_messages=history_limit)
                learned_facts = [(saved_label, saved_val)]
            result = {
                "seq_id": seq_id,
                "user_msg": user_msg,
                "reply_text": reply_text,
                "delta": 3,
                "new_mood": "Touched",
                "coins_earned": 4,
                "follow_up_q": None,
                "next_pending_key": None,
                "next_pending_label": None,
                "learned_facts": learned_facts,
                "error": None,
            }
        else:
            with _STATE_LOCK:
                before_mem = dict(memories) if isinstance(memories, dict) else {}

            reply_text, delta, new_mood = get_companion_reply(
                user_msg,
                history,
                memories,
                state=state,
                return_metadata=True,
                max_history=history_limit,
                timeout=timeout,
                max_retries=max_retries,
                stop_event=stop_event
            )

            with _STATE_LOCK:
                learned_facts = []
                coins_earned = 2 if delta >= 0 else 0
                if isinstance(memories, dict):
                    for k, v in memories.items():
                        if before_mem.get(k) != v:
                            coins_earned = 4
                            learned_facts.append((k.replace("_", " "), v))

                follow_up_q = None
                next_k, next_l = None, None
                cur_intent = detect_message_intent(user_msg, chat_history=history, saved_memories=memories)["intent"]
                if turn_count % 3 == 0 and "?" not in reply_text and cur_intent == "casual_conversation":
                    cand_k, cand_l, cand_q = get_proactive_question(memories, player, chat_history=history)
                    if cand_q:
                        next_k, next_l, follow_up_q = cand_k, cand_l, cand_q
                        new_mood = "Curious"

            result = {
                "seq_id": seq_id,
                "user_msg": user_msg,
                "reply_text": reply_text,
                "delta": delta,
                "new_mood": new_mood,
                "coins_earned": coins_earned,
                "follow_up_q": follow_up_q,
                "next_pending_key": next_k,
                "next_pending_label": next_l,
                "learned_facts": learned_facts,
                "error": None,
            }
    except Exception as exc:
        # Fallback safely on any unexpected error without exposing secrets
        fallback_text = f"I'm right here with you, {player}! Tell me more about what's on your mind."
        with _STATE_LOCK:
            append_chat_turn(history, user_msg, fallback_text, max_messages=history_limit)
        result = {
            "seq_id": seq_id,
            "user_msg": user_msg,
            "reply_text": fallback_text,
            "delta": 1,
            "new_mood": "Happy",
            "coins_earned": 2,
            "follow_up_q": None,
            "next_pending_key": None,
            "next_pending_label": None,
            "learned_facts": [],
            "error": type(exc).__name__,
        }

    if stop_event is None or not stop_event.is_set():
        response_queue.put(result)


class CompanionAsyncDispatcher:
    """
    Thread-safe background request dispatcher & FIFO queue manager for the GUI.
    - Executes `generate_companion_response_worker` on a daemon `threading.Thread`.
    - Deduplicates accidental identical double-submissions while a request is in flight.
    - Queues distinct follow-up messages safely in strict FIFO order so conversation history
      is always updated in exact order without race conditions.
    - Signals background threads to shut down cleanly via `stop_event` when the app closes.
    """

    def __init__(self, state=None, history=None, memories=None, timeout=None, max_retries=DEFAULT_API_MAX_RETRIES):
        self.state = state if isinstance(state, dict) else create_new_state(interactive=False)
        self.history = history if isinstance(history, list) else self.state.setdefault("chat_history", [])
        self.memories = memories if isinstance(memories, dict) else self.state.setdefault("memories", {})
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.stop_event = threading.Event()
        self._lock = threading.RLock()
        self.is_processing = False
        self.active_thread = None
        self.next_seq_id = 0
        self.turn_count = 0
        self.pending_key = None
        self.pending_label = None
        self._last_submitted_msg = None
        self._last_submitted_ts = 0.0

    def submit_message(self, user_msg):
        """
        Submit a user message for background processing.
        Returns (accepted: bool, seq_id: int or None, started_immediately: bool).
        Rejects accidental duplicate rapid-fire submissions of the exact same text within 0.4s.
        """
        if self.stop_event.is_set() or not user_msg or not user_msg.strip():
            return False, None, False

        clean_msg = user_msg.strip()
        now = time.time()
        with self._lock:
            if (
                self.is_processing
                and self._last_submitted_msg == clean_msg
                and (now - self._last_submitted_ts) < 0.45
            ):
                return False, None, False

            self._last_submitted_msg = clean_msg
            self._last_submitted_ts = now
            self.next_seq_id += 1
            self.turn_count += 1
            seq_id = self.next_seq_id

            task_payload = {
                "seq_id": seq_id,
                "user_msg": clean_msg,
                "turn_count": self.turn_count,
                "pending_key": self.pending_key,
                "pending_label": self.pending_label,
                "state": self.state,
                "history": self.history,
                "memories": self.memories,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
            }
            # Clear pending question once consumed by a queued turn
            self.pending_key = None
            self.pending_label = None

            if not self.is_processing:
                self.is_processing = True
                self._spawn_worker(task_payload)
                return True, seq_id, True
            else:
                self.request_queue.put(task_payload)
                return True, seq_id, False

    def _spawn_worker(self, task_payload):
        worker_thread = threading.Thread(
            target=generate_companion_response_worker,
            args=(task_payload, self.response_queue, self.stop_event),
            name=f"CompanionWorker-{task_payload['seq_id']}",
            daemon=True,
        )
        self.active_thread = worker_thread
        worker_thread.start()

    def poll_results(self):
        return self.pop_completed_results()

    def pop_completed_results(self):
        """
        Non-blocking drain of completed worker results from `response_queue`.
        Automatically dispatches the next queued request in FIFO order if one is waiting.
        """
        completed = []
        while True:
            try:
                res = self.response_queue.get_nowait()
                completed.append(res)
            except queue.Empty:
                break

        if completed:
            with self._lock:
                last_res = completed[-1]
                if last_res.get("next_pending_key"):
                    self.pending_key = last_res["next_pending_key"]
                    self.pending_label = last_res["next_pending_label"]

                if not self.stop_event.is_set():
                    try:
                        next_task = self.request_queue.get_nowait()
                        self.is_processing = True
                        self._spawn_worker(next_task)
                    except queue.Empty:
                        self.is_processing = False
                        self.active_thread = None
                else:
                    self.is_processing = False
                    self.active_thread = None

        return completed

    def shutdown(self, wait_timeout=0.4):
        """Signal all background threads to stop and drain pending queues safely."""
        self.stop_event.set()
        with self._lock:
            while not self.request_queue.empty():
                try:
                    self.request_queue.get_nowait()
                except queue.Empty:
                    break
            t = self.active_thread
            self.is_processing = False
            self.active_thread = None
        if t is not None and t.is_alive():
            t.join(timeout=wait_timeout)


def get_active_ai_mode_label(personality):
    """Return a clean human-readable label for the active hybrid conversation engine without exposing keys."""
    conn = get_connection_status()
    return f"{conn['label']} — {personality}"


def nonstop_chat_mode(state):
    """Endless free-text conversation mode powered by get_companion_reply() with SQLite & short-term memory."""
    partner = state["partner_name"]
    player = state["player_name"]
    memories = state.setdefault("memories", {})
    sanitize_memories(memories)
    sync_dict_to_memory_db(memories)
    personality = state.get("personality", "Sweet & Caring")
    tw_enabled = state.get("typewriter", True)
    mode_label = get_active_ai_mode_label(personality)
    history_limit = get_chat_history_limit(state)
    history = normalize_chat_history(
        state.get("chat_history", []), partner_name=partner, player_name=player, max_messages=history_limit
    )

    print(f"\n{C_CYAN}===================================================={C_RESET}")
    print(f"{C_BOLD}  Non-Stop Free Chat with {partner} [{mode_label}]{C_RESET}")
    print(f"  * Type anything to chat endlessly! (Costs 0 Energy, Earns +2 Coins/turn)")
    print(f"  * Type {C_YELLOW}/ask{C_RESET} to have {partner} ask you a question about yourself!")
    print(f"  * Type {C_YELLOW}/vibe{C_RESET} to switch her personality or typewriter speed!")
    print(f"  * Type {C_YELLOW}/memories{C_RESET} to view/edit/delete saved facts, or {C_YELLOW}/back{C_RESET} to exit chat.")
    print(f"{C_CYAN}===================================================={C_RESET}")

    print(f"{C_PINK}{get_mood_portrait(state['mood'])}{C_RESET}")

    pending_key, pending_label, opening_q = get_proactive_question(memories, player, chat_history=history)
    if opening_q:
        typewrite(f'\n{C_PINK}{partner}: "{opening_q}"{C_RESET}', tw_enabled)
    else:
        typewrite(f'\n{C_PINK}{partner}: "Yay, we can just talk for as long as you want, {player}! What\'s on your mind?"{C_RESET}', tw_enabled)

    turn_count = 0

    while True:
        tw_enabled = state.get("typewriter", True)
        personality = state.get("personality", "Sweet & Caring")

        user_msg = input(f"\n{C_BOLD}{player}:{C_RESET} ").strip()
        if not user_msg:
            continue
        if user_msg.lower() in ("/back", "exit", "quit", "/exit"):
            typewrite(f'\n{C_PINK}{partner}: "That was such a nice chat, {player}! I\'ll remember everything you told me!"{C_RESET}', tw_enabled)
            break
        if user_msg.lower() == "/memories":
            view_keepsakes(state["keepsakes"], memories, partner, player)
            continue
        if user_msg.lower().startswith("/forget "):
            del_key = user_msg[8:].strip().lower().replace(" ", "_")
            if delete_saved_memory(del_key, memories_dict=memories):
                save_game(state)
                print(f"{C_GREEN}[Deleted memory '{del_key}' from SQLite and save file.]{C_RESET}")
            continue
        if user_msg.lower() == "/vibe":
            customize_vibe_menu(state)
            save_game(state)
            continue
        if user_msg.lower() == "/ask":
            pending_key, pending_label, q_text = get_proactive_question(memories, player, chat_history=history)
            if q_text:
                state["mood"] = "Curious"
                print(f"{C_PINK}{get_mood_portrait('Curious')}{C_RESET}")
                typewrite(f'{C_PINK}{partner}: "{q_text}"{C_RESET}', tw_enabled)
            else:
                typewrite(
                    f'\n{C_PINK}{partner}: "I already know all your core favorites, {player}! You can still teach me new things anytime by saying \'I love ...\' or \'My favorite ... is ...\'!"{C_RESET}',
                    tw_enabled
                )
            continue

        turn_count += 1
        follow_up_q = None

        saved_label, saved_val = parse_pending_answer(pending_key, pending_label, user_msg, memories)
        pending_key, pending_label = None, None

        if saved_label and saved_val:
            log_diary_event(state, f"{partner} learned that {player}'s {saved_label} is '{saved_val}'.")
            reply_text = f"I'm so glad you told me, {player}! I'll always remember that your {saved_label} is '{saved_val}'!"
            delta = 3
            coins_earned = 4
            new_mood = "Touched"
            append_chat_turn(history, user_msg, reply_text, max_messages=history_limit)
        else:
            before_mem_snapshot = dict(memories)
            reply_text, delta, new_mood = get_companion_reply(
                user_msg, history, memories, state=state, return_metadata=True, max_history=history_limit
            )
            coins_earned = 2 if delta >= 0 else 0
            for k, v in memories.items():
                if before_mem_snapshot.get(k) != v:
                    coins_earned = 4
                    log_diary_event(state, f"{partner} learned that {player}'s {k.replace('_', ' ')} is '{v}'.")

            cur_intent = detect_message_intent(user_msg, chat_history=history, saved_memories=memories)["intent"]
            if turn_count % 3 == 0 and "?" not in reply_text and cur_intent == "casual_conversation":
                next_key, next_label, next_q = get_proactive_question(memories, player, chat_history=history)
                if next_q:
                    pending_key, pending_label = next_key, next_label
                    follow_up_q = next_q
                    new_mood = "Curious"

        state["affection"] = max(0, min(100, state["affection"] + delta))
        state["coins"] = state.get("coins", 0) + coins_earned
        state["mood"] = new_mood
        state["chat_history"] = history[-history_limit:]

        sign = "+" if delta >= 0 else ""
        color = C_GREEN if delta >= 0 else C_RED
        coin_txt = f" | +{coins_earned} Coins" if coins_earned > 0 else ""
        print(f"\n{C_PINK}{get_mood_portrait(new_mood)}{C_RESET}")
        typewrite(
            f'{C_PINK}{partner}: "{reply_text}"{C_RESET} {color}({sign}{delta} Affection | Mood: {new_mood}{coin_txt}){C_RESET}',
            tw_enabled
        )
        if follow_up_q:
            typewrite(f'{C_PINK}{partner}: "{follow_up_q}"{C_RESET}', tw_enabled)

        check_milestones(state)
        save_game(state)


def build_story_scenarios(partner_name, player_name):
    """Return the list of branching Story Conversation scenarios for both CLI and GUI."""
    return [
        {
            "prompt": f'{partner_name}: "Hey {player_name}, I had a really long day today... What should we do tonight?"',
            "options": [
                ("Cook her favorite comfort food and listen to her vent", 12, "Touched",
                 f'{partner_name}: "You really are the best, {player_name}. I feel so much better already!"'),
                ("Suggest watching a cozy movie together", 7, "Happy",
                 f'{partner_name}: "That sounds super cozy. Let\'s grab a blanket!"'),
                ("Tell her you're too busy right now", -10, "Hurt",
                 f'{partner_name}: "Oh... okay. I guess I\'ll talk to you later then."')
            ]
        },
        {
            "prompt": f'{partner_name}: "Look at this new song I found! Do you want to listen to it together?"',
            "options": [
                ("Put on headphones together and ask what she loves about it", 10, "Excited",
                 f'{partner_name}: "I knew you\'d appreciate the melody! Listening with you makes it 10x better."'),
                ("Say you'll add it to your playlist for later", 4, "Happy",
                 f'{partner_name}: "Promise you\'ll tell me what you think when you hear it!"'),
                ("Say it's not really your style without listening", -8, "Hurt",
                 f'{partner_name}: "You didn\'t even give it a chance..."')
            ]
        },
        {
            "prompt": f'{partner_name}: "It\'s raining outside! Want to go grab hot tea together?"',
            "options": [
                ("Share one umbrella and walk together in the rain", 12, "Blushing",
                 f'{partner_name}: "Walking under one umbrella with you feels like a movie scene!"'),
                ("Make warm tea at home so she stays dry", 8, "Caring",
                 f'{partner_name}: "So thoughtful! Homemade tea with you is perfect."'),
                ("Complain about the weather and stay glued to your phone", -9, "Hurt",
                 f'{partner_name}: "Never mind, I was just hoping to spend time with you."')
            ]
        }
    ]


def chat_scene(state):
    """Run a random branching conversation topic where choices affect affection."""
    partner_name = state["partner_name"]
    player_name = state["player_name"]
    affection = state["affection"]
    mood = state["mood"]
    tw_enabled = state.get("typewriter", True)

    scenarios = build_story_scenarios(partner_name, player_name)
    scene = random.choice(scenarios)
    typewrite(f"\n{C_PINK}{scene['prompt']}{C_RESET}", tw_enabled)
    for idx, (option_text, _, _, _) in enumerate(scene["options"], start=1):
        print(f"  {idx}. {option_text}")

    sub_choice = input("\nHow do you respond? (1-3): ").strip()
    if sub_choice in ("1", "2", "3"):
        chosen = scene["options"][int(sub_choice) - 1]
        delta, mood, reply = chosen[1], chosen[2], chosen[3]
        affection += delta
        sign = "+" if delta >= 0 else ""
        color = C_GREEN if delta >= 0 else C_RED
        print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
        typewrite(f"{C_PINK}{reply}{C_RESET} {color}({sign}{delta} Affection){C_RESET}", tw_enabled)
    else:
        typewrite(f'\n{C_PINK}{partner_name}: "Haha, you spaced out for a second there!"{C_RESET} (0 Affection)', tw_enabled)

    return affection, mood


def gift_menu(state):
    """Let the player pick an item from their inventory to gift."""
    partner_name = state["partner_name"]
    player_name = state["player_name"]
    affection = state["affection"]
    mood = state["mood"]
    inventory = state["inventory"]
    tw_enabled = state.get("typewriter", True)

    available_gifts = [item for item, count in inventory.items() if count > 0]
    if not available_gifts:
        print(f"\n{C_RED}Your gift bag is empty! Visit the Gift Shop (Option 5) or rest until tomorrow.{C_RESET}")
        return affection, mood, False

    gift_reactions = {
        "Matcha Latte": (8, "Happy", f'{partner_name}: "Ooh, a warm Matcha Latte! You know my order by heart!"'),
        "Handwritten Note": (14, "Touched", f'{partner_name}: "A handwritten note from you, {player_name}? I\'m keeping this forever!"'),
        "Vinyl Keychain": (12, "Excited", f'{partner_name}: "This Vinyl Keychain is so cool! I\'m putting it on my bag right now!"'),
        "Starlight Bouquet": (18, "Blushing", f'{partner_name}: "These flowers are breathtaking, {player_name}!"')
    }

    print(f"\n{C_CYAN}Your Gift Inventory:{C_RESET}")
    for idx, item in enumerate(available_gifts, start=1):
        bonus = gift_reactions[item][0]
        print(f"  {idx}. {item} (x{inventory[item]}) {C_GREEN}[+{bonus} Affection]{C_RESET}")
    print(f"  {len(available_gifts) + 1}. Cancel")

    choice = input("\nWhich gift would you like to give? ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(available_gifts):
        selected_item = available_gifts[int(choice) - 1]
        inventory[selected_item] -= 1
        bonus, mood, reply = gift_reactions[selected_item]
        affection += bonus
        log_diary_event(state, f"Gifted a {selected_item} to {partner_name}.")
        print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
        typewrite(f"{C_PINK}{reply}{C_RESET} {C_GREEN}(+{bonus} Affection){C_RESET}", tw_enabled)
        return affection, mood, True

    print("\nYou decided to save your gifts for later.")
    return affection, mood, False


def gift_shop_menu(state):
    """Allow the player to spend earned coins to buy gifts (Costs 0 Energy)."""
    items = list(GIFT_CATALOG.keys())
    while True:
        coins = state.get("coins", 0)
        print(f"\n{C_CYAN}=== Cozy Corner Gift Shop (Your Coins: {C_YELLOW}{coins}{C_CYAN}) ==={C_RESET}")
        for idx, item in enumerate(items, start=1):
            info = GIFT_CATALOG[item]
            owned = state["inventory"].get(item, 0)
            afford_tag = f"{C_GREEN}{info['price']} Coins{C_RESET}" if coins >= info["price"] else f"{C_RED}{info['price']} Coins (Need more){C_RESET}"
            print(f"  {idx}. {item} [+{info['bonus']} Affection] — {afford_tag} (Owned: x{owned})")
        print(f"  {len(items) + 1}. Leave Shop")

        choice = input("\nWhat would you like to buy? ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            selected = items[int(choice) - 1]
            price = GIFT_CATALOG[selected]["price"]
            if coins < price:
                print(f"\n{C_RED}Not enough coins! Play mini-games or chat in Free Chat to earn more coins.{C_RESET}")
            else:
                state["coins"] -= price
                state["inventory"][selected] = state["inventory"].get(selected, 0) + 1
                log_diary_event(state, f"Bought a {selected} from the Gift Shop for {price} Coins.")
                save_game(state)
                print(f"\n{C_GREEN}[Purchased {selected} for {price} Coins! Remaining Coins: {state['coins']}]{C_RESET}")
        else:
            break


def build_date_stories(state):
    """Build personalized date outing metadata using saved Free Chat memories."""
    partner_name = state["partner_name"]
    player_name = state["player_name"]
    memories = state.get("memories", {})

    fav_food = memories.get("favorite_food")
    fav_song = memories.get("favorite_song")
    passion = memories.get("passion")
    dream_spot = memories.get("dream_destination")

    cafe_story = (
        f'You and {partner_name} visit the Cozy Book Café. She surprises you by ordering {fav_food} just for you!\n'
        f'{partner_name}: "I remembered you told me {fav_food} is your favorite, {player_name}! Sharing it with you makes my whole week."'
        if fav_food else
        f'You and {partner_name} share pastries and read side by side at the Cozy Book Café.\n'
        f'{partner_name}: "Sitting quietly with you like this is my favorite part of the week."'
    )

    arcade_detail = f"while blasting '{fav_song}' on the jukebox" if fav_song else (f"after talking all about {passion}" if passion else "winning a pile of prize tickets")
    arcade_story = (
        f'You team up on rhythm and co-op arcade games, {arcade_detail}!\n'
        f'{partner_name}: "We make an unbeatable team, {player_name}! Everything is more fun when it\'s our style."'
    )

    beach_story = (
        f'You walk barefoot along the shore as the sky turns gold and violet, daydreaming about your future trip to {dream_spot}.\n'
        f'{partner_name}: "One day soon, {player_name}, we\'ll be watching a sunset just like this together in {dream_spot}!"'
        if dream_spot else
        f'You walk barefoot along the shore as the sky turns gold and violet.\n'
        f'{partner_name}: "I wish we could freeze this moment right here, {player_name}."'
    )

    return [
        ("Cozy Book Café", 30, 14, "Happy", cafe_story, bool(fav_food)),
        ("Retro Arcade Challenge", 50, 18, "Excited", arcade_story, bool(fav_song or passion)),
        ("Sunset Beach Walk", 70, 22, "Blushing", beach_story, bool(dream_spot))
    ]




def plan_custom_date(state, place_name, activity_desc):
    """Create a custom Dream Date designed by the player and run it."""
    partner = state["partner_name"]
    player = state["player_name"]
    personality = state.get("personality", "Sweet & Caring")
    memories = state.get("memories", {})

    mem_touch = ""
    if memories:
        mem_k, mem_v = random.choice(list(memories.items()))
        mem_touch = f" She even brings along a little surprise inspired by your {mem_k.replace('_', ' ')} ({mem_v})!"

    story = (
        f"You and {partner} head out on your custom dream date to {place_name} ({activity_desc}).{mem_touch}\n"
        f'{partner}: "{player}, planning {activity_desc} at {place_name} together was the sweetest idea ever!"'
    )
    styled_story = style_partner_line(story, personality, player)
    bonus = 20
    new_mood = "Blushing"
    state["energy"] -= 2
    state["affection"] = max(0, min(100, state["affection"] + bonus))
    state["coins"] = state.get("coins", 0) + 15
    state["mood"] = new_mood
    log_diary_event(state, f"Designed and went on a custom Dream Date at {place_name} ({activity_desc}).")
    return styled_story, bonus, new_mood


def date_outing(state):
    """Take your partner on a special date outing personalized with your saved Free Chat memories!"""
    affection = state["affection"]
    mood = state["mood"]
    energy = state["energy"]
    tw_enabled = state.get("typewriter", True)

    if energy < 2:
        print(f"\n{C_RED}You need at least 2 Energy to go on a date outing! Rest to recharge for tomorrow.{C_RESET}")
        return affection, mood, False

    dates = build_date_stories(state)

    print(f"\n{C_CYAN}Choose a Date Outing (Costs 2 Energy):{C_RESET}")
    for idx, (place, req_aff, bonus, _, _, is_personalized) in enumerate(dates, start=1):
        lock_status = f"{C_GREEN}Unlocked{C_RESET}" if affection >= req_aff else f"{C_RED}Locked - Need {req_aff} Affection{C_RESET}"
        mem_tag = f" {C_YELLOW}[Personalized with your Memory! +3 Bonus Affection]{C_RESET}" if is_personalized else ""
        print(f"  {idx}. {place} (+{bonus} Affection) [{lock_status}]{mem_tag}")
    print(f"  4. Design Your Own Custom Dream Date (+20 Affection, +15 Coins) [{C_GREEN}Unlocked{C_RESET}]")
    print("  5. Cancel")

    choice = input("\nWhere would you like to go? (1-5): ").strip()
    if choice in ("1", "2", "3"):
        place, req_aff, bonus, new_mood, story, is_personalized = dates[int(choice) - 1]
        if affection < req_aff:
            print(f"\n{C_RED}You need at least {req_aff} Affection to unlock the {place} date!{C_RESET}")
            return affection, mood, False
        total_bonus = bonus + (3 if is_personalized else 0)
        affection += total_bonus
        log_diary_event(state, f"Went on a {place} date together.")
        print(f"\n{C_PINK}{get_mood_portrait(new_mood)}{C_RESET}")
        typewrite(f"{C_PINK}{story}{C_RESET} {C_GREEN}(+{total_bonus} Affection){C_RESET}", tw_enabled)
        return affection, new_mood, True
    elif choice == "4":
        place_name = input("Enter a custom date location (e.g., Rooftop Observatory): ").strip() or "Starlight Rooftop"
        activity_desc = input("What will you do together there? (e.g., stargazing with hot cocoa): ").strip() or "stargazing together"
        # Note: plan_custom_date deducts 2 energy, so restore 2 before caller deducts 2
        state["energy"] += 2
        story, bonus, new_mood = plan_custom_date(state, place_name, activity_desc)
        print(f"\n{C_PINK}{get_mood_portrait(new_mood)}{C_RESET}")
        typewrite(f"{C_PINK}{story}{C_RESET} {C_GREEN}(+{bonus} Affection | +15 Coins){C_RESET}", tw_enabled)
        return state["affection"], new_mood, True

    print("\nYou decided to plan the date for another time.")
    return affection, mood, False


def trigger_morning_memory_event(state, quiet=False):
    """Trigger a sweet morning surprise using the player's saved Free Chat memories when resting."""
    memories = state.get("memories", {})
    partner = state["partner_name"]
    player = state["player_name"]
    tw_enabled = state.get("typewriter", True)

    if not memories:
        return None

    events = []
    if "favorite_food" in memories:
        food = memories["favorite_food"]
        events.append((
            f'{partner} surprises you in the morning with homemade {food} packed in a lunchbox!\n'
            f'{partner}: "I made your favorite {food} so you have the best day today, {player}!"',
            4, "Touched"
        ))
    if "favorite_song" in memories:
        song = memories["favorite_song"]
        events.append((
            f'You wake up to a morning voice note from {partner} humming "{song}".\n'
            f'{partner}: "Good morning, {player}! Hearing \'{song}\' made me think of you right away!"',
            4, "Happy"
        ))
    if "study_field" in memories:
        study = memories["study_field"]
        events.append((
            f'{partner} leaves a sticky note on your desk with a little doodle cheering you on in {study}.\n'
            f'{partner}: "Good luck with {study} today, {player}! I\'m your #1 fan!"',
            4, "Caring"
        ))
    if "dream_destination" in memories:
        dest = memories["dream_destination"]
        events.append((
            f'{partner} sends you a postcard photo of {dest} with a heart drawn on the corner.\n'
            f'{partner}: "One step closer to our dream trip to {dest}, {player}!"',
            4, "Excited"
        ))

    if not events:
        mem_key, mem_val = random.choice(list(memories.items()))
        clean_key = mem_key.replace("_", " ")
        events.append((
            f'{partner} greets you with a warm smile this morning.\n'
            f'{partner}: "Morning, {player}! I was just smiling thinking about how your {clean_key} is {mem_val}!"',
            3, "Happy"
        ))

    story, bonus, new_mood = random.choice(events)
    state["affection"] = min(100, state["affection"] + bonus)
    state["mood"] = new_mood
    if not quiet:
        print(f"\n{C_YELLOW}=== Morning Memory Surprise! ==={C_RESET}")
        typewrite(f"{C_PINK}{story}{C_RESET} {C_GREEN}(+{bonus} Affection){C_RESET}", tw_enabled)
    return story, bonus


def build_personalized_trivia(memories, partner_name, player_name):
    """Build multiple-choice trivia questions dynamically from saved Free Chat memories."""
    distractor_pools = {
        "favorite_food": ["Pepperoni Pizza", "Spicy Ramen", "Cheese Pasta", "Blueberry Pancakes"],
        "favorite_song": ["Midnight City", "Bohemian Rhapsody", "Blinding Lights", "Starboy"],
        "passion": ["Skydiving", "Knitting Sweaters", "Chess Boxing", "Stamp Collecting"],
        "dream_destination": ["Reykjavik", "Antarctica", "Machu Picchu", "Santorini"],
        "study_field": ["Astrophysics", "Marine Biology", "Ancient History", "Culinary Arts"],
        "hometown": ["New York", "Kyoto", "London", "Sydney"]
    }
    default_distractors = ["Pineapple Pizza", "Bungee Jumping", "Underwater Basket Weaving", "Classical Opera"]

    personal_questions = []
    for key, correct_val in memories.items():
        clean_label = key.replace("_", " ")
        pool = distractor_pools.get(key, default_distractors)
        wrong_choices = [d for d in pool if d.lower() != correct_val.lower()]
        picked_wrong = random.sample(wrong_choices, k=min(2, len(wrong_choices)))
        while len(picked_wrong) < 2:
            picked_wrong.append(f"Not {correct_val}")

        all_choices = [correct_val] + picked_wrong
        random.shuffle(all_choices)
        correct_idx = str(all_choices.index(correct_val) + 1)
        formatted_opts = [f"{i}. {opt}" for i, opt in enumerate(all_choices, start=1)]

        personal_questions.append({
            "q": f"[Shared Memory] {partner_name} asks: \"Let's see if we're in sync, {player_name}! What did you tell me your {clean_label} is?\"",
            "options": formatted_opts,
            "ans": correct_idx,
            "is_personal": True,
            "fact_val": correct_val
        })
    return personal_questions


def pick_trivia_question(state):
    """Select one Couple's Trivia question (prioritizing saved Free Chat memories when available)."""
    partner_name = state["partner_name"]
    player_name = state["player_name"]
    memories = state.get("memories", {})

    base_questions = [
        {
            "q": f"What is {partner_name}'s go-to café drink from your gift bag?",
            "options": ["1. Espresso Shot", "2. Matcha Latte", "3. Iced Americano"],
            "ans": "2",
            "is_personal": False
        },
        {
            "q": f"Which date spot unlocks once you reach 70 Affection with {partner_name}?",
            "options": ["1. Cozy Book Café", "2. Retro Arcade Challenge", "3. Sunset Beach Walk"],
            "ans": "3",
            "is_personal": False
        },
        {
            "q": f"What is the highest relationship status tier you can reach with {partner_name}?",
            "options": ["1. Soulmates", "2. Best Friends", "3. Acquaintances"],
            "ans": "1",
            "is_personal": False
        }
    ]
    personal_questions = build_personalized_trivia(memories, partner_name, player_name)
    if personal_questions and random.random() < 0.7:
        return random.choice(personal_questions)
    return random.choice(base_questions + personal_questions)


def play_minigame(state):
    """Play a Couple's Trivia Quiz (with personalized Free Chat memories!) or Duet Rhythm Challenge."""
    partner_name = state["partner_name"]
    player_name = state["player_name"]
    affection = state["affection"]
    mood = state["mood"]
    inventory = state["inventory"]
    memories = state.get("memories", {})
    tw_enabled = state.get("typewriter", True)

    print(f"\n{C_CYAN}Choose a Mini-Game to Play Together (Costs 1 Energy):{C_RESET}")
    print(f"  1. Couple's Trivia Quiz (Includes your {len(memories)} saved Free Chat memories!)")
    print("  2. Duet Rhythm Timing Challenge (Hit the beat at 3.00 seconds!)")
    print("  3. Cancel")

    choice = input("\nEnter your choice (1-3): ").strip()
    if choice == "1":
        quiz = pick_trivia_question(state)
        print(f"\n{C_YELLOW}Trivia Question:{C_RESET} {quiz['q']}")
        for opt in quiz["options"]:
            print(f"  {opt}")
        ans = input("\nYour answer (1-3): ").strip()
        if ans == quiz["ans"]:
            if quiz.get("is_personal"):
                affection += 15
                coins_won = 20
                mood = "Blushing"
                print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
                typewrite(
                    f'{C_PINK}{partner_name}: "Yes, \'{quiz["fact_val"]}\'! I told you I remember everything you share with me, {player_name}!"{C_RESET} '
                    f'{C_GREEN}(+15 Affection | +{coins_won} Coins - Shared Memory Bonus!){C_RESET}',
                    tw_enabled
                )
            else:
                affection += 12
                coins_won = 15
                mood = "Excited"
                print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
                typewrite(
                    f'{C_PINK}{partner_name}: "You remembered, {player_name}! That makes me so happy!"{C_RESET} {C_GREEN}(+12 Affection | +{coins_won} Coins){C_RESET}',
                    tw_enabled
                )
        else:
            affection += 3
            coins_won = 5
            mood = "Happy"
            print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
            typewrite(
                f'{C_PINK}{partner_name}: "Haha, close try! We\'ll just have to hang out more so we stay in sync."{C_RESET} {C_GREEN}(+3 Affection | +{coins_won} Coins){C_RESET}',
                tw_enabled
            )
        state["coins"] = state.get("coins", 0) + coins_won
        return affection, mood, True

    elif choice == "2":
        print(f"\n{C_YELLOW}=== Duet Rhythm Timing Challenge ==={C_RESET}")
        print(f"{partner_name} starts playing a city-pop melody! Press Enter right at {C_BOLD}3.00 seconds{C_RESET} after 'GO!'")
        input("Press Enter when you're ready to start the beat...")
        print(f"\n{C_GREEN}GO! Count 3 seconds in your head and press Enter!{C_RESET}")
        start_time = time.time()
        input()
        elapsed = time.time() - start_time
        diff = abs(elapsed - 3.0)
        print(f"Your timing: {C_BOLD}{elapsed:.2f} seconds{C_RESET} (Off by {diff:.2f}s)")

        if diff <= 0.45:
            affection += 15
            coins_won = 25
            mood = "Excited"
            inventory["Starlight Bouquet"] += 1
            print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
            typewrite(
                f'{C_PINK}{partner_name}: "Perfect sync, {player_name}! Our duet sounded incredible!"{C_RESET} {C_GREEN}(+15 Affection | +{coins_won} Coins + Won a Starlight Bouquet!){C_RESET}',
                tw_enabled
            )
        elif diff <= 1.1:
            affection += 9
            coins_won = 15
            mood = "Happy"
            print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
            typewrite(
                f'{C_PINK}{partner_name}: "Great rhythm! That was super fun playing together!"{C_RESET} {C_GREEN}(+9 Affection | +{coins_won} Coins){C_RESET}',
                tw_enabled
            )
        else:
            affection += 4
            coins_won = 8
            mood = "Happy"
            print(f"\n{C_PINK}{get_mood_portrait(mood)}{C_RESET}")
            typewrite(
                f'{C_PINK}{partner_name}: "Haha, we were a little off-beat, but I loved every second!"{C_RESET} {C_GREEN}(+4 Affection | +{coins_won} Coins){C_RESET}',
                tw_enabled
            )
        state["coins"] = state.get("coins", 0) + coins_won
        return affection, mood, True

    print("\nYou decided to play a mini-game later.")
    return affection, mood, False


def create_new_state(interactive=True):
    """Initialize a fresh game state dictionary."""
    if interactive:
        player_name = input("Enter your name (or press Enter for 'Alex'): ").strip() or "Alex"
        partner_name = input("Enter your partner's name (or press Enter for 'Aiko'): ").strip() or "Aiko"

        print("\nChoose her starting personality vibe:")
        p_names = list(PERSONALITIES.keys())
        for idx, name in enumerate(p_names, start=1):
            print(f"  {idx}. {name} ({PERSONALITIES[name]})")
        p_choice = input("Select 1-3 (or press Enter for 'Sweet & Caring'): ").strip()
        personality = p_names[int(p_choice) - 1] if p_choice in ("1", "2", "3") else "Sweet & Caring"
    else:
        player_name = "Alex"
        partner_name = "Aiko"
        personality = "Sweet & Caring"

    return {
        "player_name": player_name,
        "partner_name": partner_name,
        "personality": personality,
        "typewriter": True,
        "chime": True,
        "affection": 50,
        "coins": 30,
        "mood": "Happy",
        "day": 1,
        "max_energy": 3,
        "energy": 3,
        "inventory": {
            "Matcha Latte": 1,
            "Handwritten Note": 1,
            "Vinyl Keychain": 1,
            "Starlight Bouquet": 0
        },
        "keepsakes": [],
        "memories": {},
        "chat_history": [],
        "last_topic": None,
        "recent_topics": [],
        "diary_log": [f"Day 1: {player_name} and {partner_name} ({personality}) began their journey together."],
        "ending_seen": False
    }


def launch_gui(reset=False):
    """Launch the optional desktop GUI mode using Python's built-in tkinter library."""
    try:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, simpledialog, ttk
    except ImportError:
        print(f"{C_RED}tkinter is not available in this Python environment. Falling back to CLI mode.{C_RESET}")
        return False

    state = None if reset else load_game()
    if not state:
        state = create_new_state(interactive=False)
        save_game(state)

    root = tk.Tk()
    root.title(f"{state['partner_name']} & {state['player_name']} — Companion Simulator")
    root.geometry("820x680")
    root.configure(bg="#1E1B2E")

    # Shared GUI session state
    gui_ctx = {
        "pending_key": None,
        "pending_label": None,
        "history": list(state.get("chat_history", [])),
        "turn_count": 0,
        "busy": False
    }

    # --- Top Status Frame ---
    top_frame = tk.Frame(root, bg="#2A2540", padx=14, pady=10, relief="flat")
    top_frame.pack(fill="x", padx=12, pady=(12, 6))

    portrait_var = tk.StringVar()
    info_var = tk.StringVar()
    aff_label_var = tk.StringVar()

    portrait_lbl = tk.Label(
        top_frame, textvariable=portrait_var, font=("Courier", 10, "bold"),
        bg="#2A2540", fg="#FF8DC7", justify="left"
    )
    portrait_lbl.pack(side="left", padx=(0, 14))

    meta_frame = tk.Frame(top_frame, bg="#2A2540")
    meta_frame.pack(side="left", fill="x", expand=True)

    info_lbl = tk.Label(
        meta_frame, textvariable=info_var, font=("Segoe UI", 10, "bold"),
        bg="#2A2540", fg="#F4EFFA", justify="left", anchor="w"
    )
    info_lbl.pack(fill="x")

    aff_row = tk.Frame(meta_frame, bg="#2A2540")
    aff_row.pack(fill="x", pady=(6, 0))

    aff_bar = ttk.Progressbar(aff_row, orient="horizontal", length=260, mode="determinate", maximum=100)
    aff_bar.pack(side="left", padx=(0, 10))

    aff_lbl = tk.Label(
        aff_row, textvariable=aff_label_var, font=("Segoe UI", 9, "bold"),
        bg="#2A2540", fg="#7EF2B5"
    )
    aff_lbl.pack(side="left")

    # --- Chat Transcript Area ---
    chat_box = scrolledtext.ScrolledText(
        root, wrap="word", font=("Segoe UI", 10), bg="#151321", fg="#EAE6F5",
        insertbackground="#FF8DC7", padx=12, pady=10, state="disabled", relief="flat"
    )
    chat_box.pack(fill="both", expand=True, padx=12, pady=6)

    chat_box.tag_config("partner", foreground="#FF8DC7", font=("Segoe UI", 10, "bold"))
    chat_box.tag_config("player", foreground="#7CE8FF", font=("Segoe UI", 10, "bold"))
    chat_box.tag_config("system", foreground="#FFE07D", font=("Segoe UI", 9, "italic"))
    chat_box.tag_config("delta_pos", foreground="#7EF2B5", font=("Segoe UI", 9))
    chat_box.tag_config("delta_neg", foreground="#FF6B6B", font=("Segoe UI", 9))
    chat_box.tag_config("typing", foreground="#B8C0CC", font=("Segoe UI", 9, "italic"))

    def append_chat(text, tag=None):
        chat_box.configure(state="normal")
        chat_box.insert("end", text + "\n", tag)
        chat_box.see("end")
        chat_box.configure(state="disabled")

    # --- Input Row ---
    input_frame = tk.Frame(root, bg="#1E1B2E")
    input_frame.pack(fill="x", padx=12, pady=(2, 6))

    entry_var = tk.StringVar()
    chat_entry = tk.Entry(
        input_frame, textvariable=entry_var, font=("Segoe UI", 10),
        bg="#2A2540", fg="#F4EFFA", insertbackground="#FF8DC7", relief="flat"
    )
    chat_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))

    send_btn = tk.Button(
        input_frame, text="Send Chat", font=("Segoe UI", 10, "bold"),
        bg="#FF5E99", fg="#FFFFFF", relief="flat", padx=14, pady=5
    )
    send_btn.pack(side="right")

    # --- Two-Row Bottom Action Bar ---
    btn_row1 = tk.Frame(root, bg="#1E1B2E")
    btn_row1.pack(fill="x", padx=12, pady=(2, 2))
    btn_row2 = tk.Frame(root, bg="#1E1B2E")
    btn_row2.pack(fill="x", padx=12, pady=(2, 12))
    action_buttons = []

    def apply_mood_theme():
        theme = MOOD_THEMES.get(state["mood"], MOOD_THEMES["Happy"])
        root.configure(bg=theme["bg"])
        top_frame.configure(bg=theme["panel"])
        meta_frame.configure(bg=theme["panel"])
        aff_row.configure(bg=theme["panel"])
        portrait_lbl.configure(bg=theme["panel"], fg=theme["portrait"])
        info_lbl.configure(bg=theme["panel"])
        aff_lbl.configure(bg=theme["panel"])
        input_frame.configure(bg=theme["bg"])
        chat_entry.configure(bg=theme["panel"], insertbackground=theme["portrait"])
        send_btn.configure(bg=theme["accent"])
        btn_row1.configure(bg=theme["bg"])
        btn_row2.configure(bg=theme["bg"])
        chat_box.tag_config("partner", foreground=theme["portrait"])
        for b in action_buttons:
            b.configure(bg=theme["btn"])

    def refresh_hud():
        tier = get_relationship_tier(state["affection"])
        personality = state.get("personality", "Sweet & Caring")
        coins = state.get("coins", 0)
        chime_txt = "ON" if state.get("chime", True) else "OFF"
        conn = get_connection_status()
        status_badge = f"🟢 {conn['label']}" if conn["mode"] == "Online" else f"🟡 {conn['label']}"
        root.title(f"{state['partner_name']} & {state['player_name']} — Companion Simulator [{conn['mode']}]")
        portrait_var.set(get_mood_portrait(state["mood"]))
        info_var.set(
            f"{state['partner_name']} ({tier})  |  Mood: {state['mood']}  |  Vibe: {personality}  |  {status_badge}\n"
            f"Day {state['day']}  |  Energy: {state['energy']}/{state['max_energy']}  |  "
            f"Coins: {coins}  |  Keepsakes: {len(state['keepsakes'])}/4  |  Memories: {len(state.get('memories', {}))}  |  Chime: {chime_txt}"
        )
        aff_bar["value"] = state["affection"]
        aff_label_var.set(f"Affection: {state['affection']}/100")
        apply_mood_theme()

    def play_chime():
        if state.get("chime", True):
            try:
                root.bell()
            except Exception:
                pass

    def sync_and_check_milestones():
        state["affection"] = max(0, min(100, state["affection"]))
        newly_unlocked, ending_triggered = check_milestones(state, quiet=True)
        for title, desc in newly_unlocked:
            play_chime()
            append_chat(f"\n★ NEW KEEPSAKE UNLOCKED: {title} — {desc}", "system")
        if ending_triggered:
            play_chime()
            append_chat(
                f"\n🎉 TRUE ENDING UNLOCKED: ETERNAL HARMONY! You collected all 4 keepsakes with {state['partner_name']}!",
                "system"
            )
        save_game(state)
        refresh_hud()

    # --- Thread-Safe Background Dispatcher, Typing Indicator & .after() Queue Polling ---
    dispatcher = CompanionAsyncDispatcher(
        state=state,
        history=gui_ctx["history"],
        memories=state.setdefault("memories", {})
    )
    gui_ctx["dispatcher"] = dispatcher
    gui_ctx["poll_after_id"] = None
    gui_ctx["typing_shown"] = False
    gui_ctx["closing"] = False

    def show_typing_indicator():
        if gui_ctx.get("closing") or gui_ctx.get("typing_shown"):
            return
        gui_ctx["typing_shown"] = True
        chat_box.configure(state="normal")
        chat_box.insert("end", f"\n{state['partner_name']}: {TYPING_INDICATOR_TEXT}\n", "typing")
        chat_box.see("end")
        chat_box.configure(state="disabled")
        send_btn.configure(text=TYPING_INDICATOR_TEXT)

    def remove_typing_indicator():
        if gui_ctx.get("closing") or not gui_ctx.get("typing_shown"):
            return
        gui_ctx["typing_shown"] = False
        chat_box.configure(state="normal")
        ranges = chat_box.tag_ranges("typing")
        # Delete tagged typing indicator blocks from back to front
        for idx in range(len(ranges) - 2, -1, -2):
            chat_box.delete(ranges[idx], ranges[idx + 1])
        chat_box.configure(state="disabled")
        if not dispatcher.is_processing:
            send_btn.configure(state="normal", text="Send Chat")

    def apply_worker_result_on_main_thread(res):
        if gui_ctx.get("closing"):
            return
        remove_typing_indicator()

        partner = state["partner_name"]
        reply_text = res["reply_text"]
        delta = res["delta"]
        new_mood = res["new_mood"]
        coins_earned = res["coins_earned"]
        follow_up_q = res["follow_up_q"]

        for fact_label, fact_val in res.get("learned_facts", []):
            log_diary_event(state, f"{partner} learned that {state['player_name']}'s {fact_label} is '{fact_val}'.")

        state["affection"] = max(0, min(100, state["affection"] + delta))
        state["coins"] = state.get("coins", 0) + coins_earned
        state["mood"] = new_mood
        history_limit = get_chat_history_limit(state)
        state["chat_history"] = list(gui_ctx["history"][-history_limit:])

        gui_ctx["pending_key"] = dispatcher.pending_key
        gui_ctx["pending_label"] = dispatcher.pending_label

        sign = "+" if delta >= 0 else ""
        delta_tag = "delta_pos" if delta >= 0 else "delta_neg"
        coin_txt = f" | +{coins_earned} Coins" if coins_earned > 0 else ""
        append_chat(f'{partner}: "{reply_text}"', "partner")
        if follow_up_q:
            append_chat(f'{partner}: "{follow_up_q}"', "partner")
        append_chat(f"   ({sign}{delta} Affection | Mood: {new_mood}{coin_txt})", delta_tag)
        sync_and_check_milestones()

        # If another queued message started processing immediately, show the typing indicator again
        if dispatcher.is_processing:
            show_typing_indicator()

    def poll_response_queue():
        if gui_ctx.get("closing"):
            return
        completed = dispatcher.pop_completed_results()
        for res in completed:
            apply_worker_result_on_main_thread(res)

        gui_ctx["busy"] = dispatcher.is_processing
        if dispatcher.is_processing:
            gui_ctx["poll_after_id"] = root.after(35, poll_response_queue)
        else:
            gui_ctx["poll_after_id"] = None
            remove_typing_indicator()

    def handle_send(event=None):
        if gui_ctx.get("closing"):
            return
        user_msg = entry_var.get().strip()
        if not user_msg:
            return
        entry_var.set("")

        partner = state["partner_name"]
        player = state["player_name"]
        memories = state.setdefault("memories", {})

        if user_msg.lower() == "/ask":
            append_chat(f"\n{player}: {user_msg}", "player")
            q_key, q_label, q_text = get_proactive_question(memories, player, chat_history=gui_ctx["history"])
            if q_text:
                gui_ctx["pending_key"] = q_key
                gui_ctx["pending_label"] = q_label
                dispatcher.pending_key = q_key
                dispatcher.pending_label = q_label
                state["mood"] = "Curious"
                append_chat(f'{partner}: "{q_text}"', "partner")
            else:
                append_chat(f'{partner}: "I already know all your core favorites, {player}! Tell me \'My favorite ... is ...\' anytime!"', "partner")
            refresh_hud()
            return

        if user_msg.lower() == "/memories":
            append_chat(f"\n{player}: {user_msg}", "player")
            do_memories()
            return
        if user_msg.lower() == "/vibe":
            append_chat(f"\n{player}: {user_msg}", "player")
            do_vibe()
            return
        if user_msg.lower() == "/help":
            append_chat(f"\n{player}: {user_msg}", "player")
            do_help()
            return

        # Sync any pending question state into dispatcher before submitting
        if gui_ctx.get("pending_key") and not dispatcher.pending_key:
            dispatcher.pending_key = gui_ctx["pending_key"]
            dispatcher.pending_label = gui_ctx["pending_label"]
        gui_ctx["pending_key"] = None
        gui_ctx["pending_label"] = None

        accepted, _, _ = dispatcher.submit_message(user_msg)
        if not accepted:
            return

        gui_ctx["turn_count"] = dispatcher.turn_count
        gui_ctx["busy"] = True
        append_chat(f"\n{player}: {user_msg}", "player")
        show_typing_indicator()

        if gui_ctx.get("poll_after_id") is None:
            gui_ctx["poll_after_id"] = root.after(25, poll_response_queue)

    def on_gui_close():
        gui_ctx["closing"] = True
        if gui_ctx.get("poll_after_id") is not None:
            try:
                root.after_cancel(gui_ctx["poll_after_id"])
            except Exception:
                pass
            gui_ctx["poll_after_id"] = None
        dispatcher.shutdown(wait_timeout=0.4)
        save_game(state)
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_gui_close)
    chat_entry.bind("<Return>", handle_send)
    send_btn.configure(command=handle_send)

    # --- Action Button Handlers ---
    def do_story_scene():
        gui_ctx["pending_key"] = None
        gui_ctx["pending_label"] = None
        if state["energy"] < 1:
            messagebox.showinfo("Out of Energy", "You're out of energy for today! Click 'Rest' to recharge.")
            return

        scenarios = build_story_scenarios(state["partner_name"], state["player_name"])
        scene = random.choice(scenarios)

        win = tk.Toplevel(root)
        win.title("Story Conversation (Costs 1 Energy)")
        win.configure(bg="#2A2540")
        win.geometry("480x270")

        tk.Label(
            win, text=scene["prompt"], bg="#2A2540", fg="#FF8DC7",
            font=("Segoe UI", 10, "bold"), wraplength=440, justify="left"
        ).pack(padx=16, pady=(14, 10))

        def pick_story_option(opt_tuple):
            opt_text, delta, new_mood, reply = opt_tuple
            state["energy"] -= 1
            state["affection"] += delta
            state["mood"] = new_mood
            sign = "+" if delta >= 0 else ""
            delta_tag = "delta_pos" if delta >= 0 else "delta_neg"
            log_diary_event(state, f"Story Scene: chose '{opt_text}' ({sign}{delta} Affection).")
            append_chat(f"\n[Story Conversation] {scene['prompt']}", "system")
            append_chat(f"{state['player_name']}: {opt_text}", "player")
            append_chat(reply, "partner")
            append_chat(f"   ({sign}{delta} Affection | Mood: {new_mood} | -1 Energy)", delta_tag)
            win.destroy()
            sync_and_check_milestones()

        for idx, opt in enumerate(scene["options"], start=1):
            tk.Button(
                win, text=f"{idx}. {opt[0]}", bg="#3D365C", fg="#F4EFFA",
                relief="flat", pady=7, wraplength=420,
                command=lambda o=opt: pick_story_option(o)
            ).pack(fill="x", padx=18, pady=4)

    def do_compliment():
        gui_ctx["pending_key"] = None
        gui_ctx["pending_label"] = None
        if state["energy"] < 1:
            messagebox.showinfo("Out of Energy", "You're out of energy for today! Click 'Rest' to recharge.")
            return
        state["energy"] -= 1
        state["affection"] += 8
        state["mood"] = "Blushing"
        line = (
            f'{state["partner_name"]}: "{state["player_name"]}, hearing that from you makes my heart race!"'
            if state["affection"] >= 80 else
            f'{state["partner_name"]}: "You always know how to make me smile, {state["player_name"]}!"'
        )
        styled = style_partner_line(line, state.get("personality", "Sweet & Caring"), state["player_name"])
        append_chat(f"\n{styled}", "partner")
        append_chat("   (+8 Affection | -1 Energy)", "delta_pos")
        sync_and_check_milestones()

    def do_gift():
        if state["energy"] < 1:
            messagebox.showinfo("Out of Energy", "You're out of energy for today! Click 'Rest' to recharge.")
            return
        available = [item for item, count in state["inventory"].items() if count > 0]
        if not available:
            messagebox.showinfo("Empty Bag", "Your gift bag is empty! Open the Gift Shop or rest until tomorrow.")
            return

        win = tk.Toplevel(root)
        win.title("Choose a Gift")
        win.configure(bg="#2A2540")
        win.geometry("340x240")
        tk.Label(win, text="Select a gift (Costs 1 Energy):", bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 10, "bold")).pack(pady=10)

        gift_reactions = {
            "Matcha Latte": (8, "Happy", f'{state["partner_name"]}: "Ooh, a warm Matcha Latte! You know my order by heart!"'),
            "Handwritten Note": (14, "Touched", f'{state["partner_name"]}: "A handwritten note from you, {state["player_name"]}? I\'m keeping this forever!"'),
            "Vinyl Keychain": (12, "Excited", f'{state["partner_name"]}: "This Vinyl Keychain is so cool! I\'m putting it on my bag right now!"'),
            "Starlight Bouquet": (18, "Blushing", f'{state["partner_name"]}: "These flowers are breathtaking, {state["player_name"]}!"')
        }

        def send_gift(item_name):
            state["inventory"][item_name] -= 1
            state["energy"] -= 1
            bonus, new_mood, reply = gift_reactions[item_name]
            state["affection"] += bonus
            state["mood"] = new_mood
            log_diary_event(state, f"Gifted a {item_name} to {state['partner_name']}.")
            append_chat(f"\n[Gifted {item_name}]", "system")
            append_chat(reply, "partner")
            append_chat(f"   (+{bonus} Affection | -1 Energy)", "delta_pos")
            win.destroy()
            sync_and_check_milestones()

        for item in available:
            bonus = gift_reactions[item][0]
            tk.Button(
                win, text=f"{item} (x{state['inventory'][item]}) [+{bonus} Aff]",
                bg="#3D365C", fg="#F4EFFA", relief="flat", pady=5,
                command=lambda i=item: send_gift(i)
            ).pack(fill="x", padx=20, pady=3)

    def do_shop():
        win = tk.Toplevel(root)
        win.title("Cozy Corner Gift Shop")
        win.configure(bg="#2A2540")
        win.geometry("400x260")

        coins_var = tk.StringVar()
        tk.Label(win, textvariable=coins_var, bg="#2A2540", fg="#FFE07D", font=("Segoe UI", 10, "bold")).pack(pady=10)

        btns = {}

        def refresh_shop():
            coins_var.set(f"Your Balance: {state.get('coins', 0)} Coins (0 Energy to shop)")
            for item_name, btn in btns.items():
                info = GIFT_CATALOG[item_name]
                owned = state["inventory"].get(item_name, 0)
                btn.configure(text=f"{item_name} (+{info['bonus']} Aff) — {info['price']} Coins [Owned: x{owned}]")

        def buy_item(item_name):
            price = GIFT_CATALOG[item_name]["price"]
            if state.get("coins", 0) < price:
                messagebox.showwarning("Not Enough Coins", f"You need {price} Coins to buy {item_name}!", parent=win)
                return
            state["coins"] -= price
            state["inventory"][item_name] = state["inventory"].get(item_name, 0) + 1
            log_diary_event(state, f"Bought a {item_name} from the Gift Shop for {price} Coins.")
            append_chat(f"\n[Gift Shop: Bought {item_name} for {price} Coins]", "system")
            save_game(state)
            refresh_hud()
            refresh_shop()

        for item_name in GIFT_CATALOG:
            b = tk.Button(
                win, text="", bg="#3D365C", fg="#F4EFFA", relief="flat", pady=6,
                command=lambda i=item_name: buy_item(i)
            )
            b.pack(fill="x", padx=20, pady=4)
            btns[item_name] = b

        refresh_shop()

    def do_date():
        if state["energy"] < 2:
            messagebox.showinfo("Need 2 Energy", "You need at least 2 Energy for a date outing! Click 'Rest' to recharge.")
            return
        dates = build_date_stories(state)
        win = tk.Toplevel(root)
        win.title("Choose a Date Outing")
        win.configure(bg="#2A2540")
        win.geometry("440x285")
        tk.Label(win, text="Select a Date Outing (Costs 2 Energy):", bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 10, "bold")).pack(pady=10)

        def go_date(place, req_aff, bonus, new_mood, story, is_pers):
            if state["affection"] < req_aff:
                messagebox.showwarning("Locked", f"You need at least {req_aff} Affection to unlock {place}!")
                return
            total_bonus = bonus + (3 if is_pers else 0)
            state["energy"] -= 2
            state["affection"] += total_bonus
            state["mood"] = new_mood
            log_diary_event(state, f"Went on a {place} date together.")
            append_chat(f"\n[Date Outing: {place}]", "system")
            append_chat(story, "partner")
            append_chat(f"   (+{total_bonus} Affection | -2 Energy)", "delta_pos")
            win.destroy()
            sync_and_check_milestones()

        for place, req_aff, bonus, new_mood, story, is_pers in dates:
            status = "Unlocked" if state["affection"] >= req_aff else f"Need {req_aff} Aff"
            pers_tag = " ★ Memory Bonus" if is_pers else ""
            tk.Button(
                win, text=f"{place} (+{bonus} Aff) [{status}]{pers_tag}",
                bg="#3D365C", fg="#F4EFFA", relief="flat", pady=6,
                command=lambda p=place, r=req_aff, b=bonus, m=new_mood, s=story, ip=is_pers: go_date(p, r, b, m, s, ip)
            ).pack(fill="x", padx=18, pady=4)

        def go_custom_date():
            place_name = simpledialog.askstring("Custom Dream Date", "Where would you like to take her?", initialvalue="Starlight Observatory", parent=win)
            if not place_name:
                return
            act_desc = simpledialog.askstring("Custom Dream Date", "What will you do together there?", initialvalue="watching constellations with warm cocoa", parent=win)
            if not act_desc:
                return
            story, bonus, _ = plan_custom_date(state, place_name.strip(), act_desc.strip())
            append_chat(f"\n[Custom Dream Date: {place_name.strip()}]", "system")
            append_chat(story, "partner")
            append_chat(f"   (+{bonus} Affection | +15 Coins | -2 Energy)", "delta_pos")
            win.destroy()
            sync_and_check_milestones()

        tk.Button(
            win, text="✨ Design Custom Dream Date (+20 Aff, +15 Coins) [Unlocked]",
            bg="#FF5E99", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="flat", pady=6,
            command=go_custom_date
        ).pack(fill="x", padx=18, pady=(6, 4))

    def do_minigame():
        if state["energy"] < 1:
            messagebox.showinfo("Out of Energy", "You're out of energy for today! Click 'Rest' to recharge.")
            return

        win = tk.Toplevel(root)
        win.title("Play a Mini-Game Together")
        win.configure(bg="#2A2540")
        win.geometry("460x300")

        header_lbl = tk.Label(
            win, text="Choose a Mini-Game (Costs 1 Energy):",
            bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 10, "bold"), wraplength=420, justify="center"
        )
        header_lbl.pack(pady=12)

        body_frame = tk.Frame(win, bg="#2A2540")
        body_frame.pack(fill="both", expand=True, padx=18, pady=6)

        def start_gui_trivia():
            for w in body_frame.winfo_children():
                w.destroy()
            quiz = pick_trivia_question(state)
            header_lbl.configure(text=quiz["q"])

            def answer_trivia(selected_idx):
                state["energy"] -= 1
                partner = state["partner_name"]
                player = state["player_name"]
                if str(selected_idx) == quiz["ans"]:
                    if quiz.get("is_personal"):
                        bonus = 15
                        coins_won = 20
                        state["mood"] = "Blushing"
                        reply = f'{partner}: "Yes, \'{quiz["fact_val"]}\'! I told you I remember everything you share with me, {player}!"'
                    else:
                        bonus = 12
                        coins_won = 15
                        state["mood"] = "Excited"
                        reply = f'{partner}: "You remembered, {player}! That makes me so happy!"'
                else:
                    bonus = 3
                    coins_won = 5
                    state["mood"] = "Happy"
                    reply = f'{partner}: "Haha, close try! We\'ll just have to hang out more so we stay in sync."'

                state["affection"] += bonus
                state["coins"] = state.get("coins", 0) + coins_won
                log_diary_event(state, f"Played Couple's Trivia Quiz (+{bonus} Affection, +{coins_won} Coins).")
                append_chat(f"\n[Mini-Game: Couple's Trivia Quiz]", "system")
                append_chat(reply, "partner")
                append_chat(f"   (+{bonus} Affection | +{coins_won} Coins | -1 Energy)", "delta_pos")
                win.destroy()
                sync_and_check_milestones()

            for idx, opt_text in enumerate(quiz["options"], start=1):
                tk.Button(
                    body_frame, text=opt_text, bg="#3D365C", fg="#F4EFFA",
                    relief="flat", pady=6, command=lambda i=idx: answer_trivia(i)
                ).pack(fill="x", pady=4)

        def start_gui_rhythm():
            for w in body_frame.winfo_children():
                w.destroy()
            partner = state["partner_name"]
            player = state["player_name"]
            header_lbl.configure(
                text=f"Duet Rhythm Timing Challenge!\nClick 'START BEAT', count 3.00 seconds, then click 'HIT BEAT!'."
            )

            timer_lbl = tk.Label(
                body_frame, text="Ready to start the melody...",
                bg="#2A2540", fg="#FFE07D", font=("Segoe UI", 10, "bold")
            )
            timer_lbl.pack(pady=10)

            rhythm_state = {"start": None}

            def on_rhythm_btn():
                if rhythm_state["start"] is None:
                    rhythm_state["start"] = time.time()
                    timer_lbl.configure(text="♪ Melody playing... Click HIT BEAT at 3.00s! ♪", fg="#7EF2B5")
                    action_btn.configure(text="HIT BEAT! (Target: 3.00s)", bg="#FF5E99")
                else:
                    elapsed = time.time() - rhythm_state["start"]
                    diff = abs(elapsed - 3.0)
                    state["energy"] -= 1

                    if diff <= 0.45:
                        bonus = 15
                        coins_won = 25
                        state["mood"] = "Excited"
                        state["inventory"]["Starlight Bouquet"] += 1
                        reply = f'{partner}: "Perfect sync ({elapsed:.2f}s), {player}! You won a Starlight Bouquet!"'
                    elif diff <= 1.1:
                        bonus = 9
                        coins_won = 15
                        state["mood"] = "Happy"
                        reply = f'{partner}: "Great rhythm ({elapsed:.2f}s)! That was super fun playing together!"'
                    else:
                        bonus = 4
                        coins_won = 8
                        state["mood"] = "Happy"
                        reply = f'{partner}: "Haha, {elapsed:.2f}s—a little off-beat, but I loved every second!"'

                    state["affection"] += bonus
                    state["coins"] = state.get("coins", 0) + coins_won
                    log_diary_event(state, f"Played Duet Rhythm Challenge ({elapsed:.2f}s, +{bonus} Affection, +{coins_won} Coins).")
                    append_chat(f"\n[Mini-Game: Duet Rhythm Timing ({elapsed:.2f}s)]", "system")
                    append_chat(reply, "partner")
                    append_chat(f"   (+{bonus} Affection | +{coins_won} Coins | -1 Energy)", "delta_pos")
                    win.destroy()
                    sync_and_check_milestones()

            action_btn = tk.Button(
                body_frame, text="START BEAT", font=("Segoe UI", 10, "bold"),
                bg="#3D365C", fg="#FFFFFF", relief="flat", padx=18, pady=8, command=on_rhythm_btn
            )
            action_btn.pack(pady=8)

        tk.Button(
            body_frame,
            text=f"1. Couple's Trivia Quiz ({len(state.get('memories', {}))} Shared Memories)",
            bg="#3D365C", fg="#F4EFFA", relief="flat", pady=8, command=start_gui_trivia
        ).pack(fill="x", pady=5)

        tk.Button(
            body_frame,
            text="2. Duet Rhythm Timing Challenge (Hit 3.00s!)",
            bg="#3D365C", fg="#F4EFFA", relief="flat", pady=8, command=start_gui_rhythm
        ).pack(fill="x", pady=5)

    def do_rest():
        state["day"] += 1
        state["energy"] = state["max_energy"]
        state["coins"] = state.get("coins", 0) + 10
        found_gift = random.choice(list(state["inventory"].keys()))
        state["inventory"][found_gift] += 1
        state["mood"] = "Happy"
        append_chat(f"\n☀ Rested until Day {state['day']}! Energy refilled, +10 Coins, and found [{found_gift}]!", "system")
        surprise = trigger_morning_memory_event(state, quiet=True)
        if surprise:
            story, bonus = surprise
            append_chat(f"★ Morning Memory Surprise: {story}", "partner")
            append_chat(f"   (+{bonus} Affection)", "delta_pos")
        sync_and_check_milestones()

    def do_memories():
        keepsakes = state.get("keepsakes", [])
        memories = state.setdefault("memories", {})
        sync_dict_to_memory_db(memories)

        win = tk.Toplevel(root)
        win.title(f"Memory Box & SQLite Long-Term Memory Manager — {state['partner_name']}")
        win.configure(bg="#2A2540")
        win.geometry("620x460")

        ks_lines = [f"Unlocked Milestone Keepsakes ({len(keepsakes)}/4):"]
        if keepsakes:
            ks_lines.extend(f"  ★ {k['title']}: {k['description']}" for k in keepsakes)
        else:
            ks_lines.append("  • None yet (reach 60+ Affection or Day 7)")

        tk.Label(
            win, text="\n".join(ks_lines), bg="#2A2540", fg="#FFE07D",
            font=("Segoe UI", 9, "bold"), justify="left", anchor="w", wraplength=580
        ).pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            win, text="Persistent Long-Term Memories (SQLite Database — Select to Edit or Delete):",
            bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", padx=16, pady=(4, 2))

        list_frame = tk.Frame(win, bg="#2A2540")
        list_frame.pack(fill="both", expand=True, padx=16, pady=4)

        mem_listbox = tk.Listbox(
            list_frame, bg="#151321", fg="#EAE6F5", selectbackground="#FF5E99",
            font=("Segoe UI", 9), relief="flat", height=10
        )
        mem_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=mem_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        mem_listbox.configure(yscrollcommand=scrollbar.set)

        records_cache = []

        def refresh_mem_list():
            records_cache.clear()
            mem_listbox.delete(0, "end")
            records = get_all_saved_memories()
            for r in records:
                records_cache.append(r)
                ts = f"  [{r['updated_at']}]" if r.get("updated_at") else ""
                mem_listbox.insert("end", f"[{r['category']}] {r['fact']} (key: {r['memory_key']} = {r['raw_value']}){ts}")

        def add_or_edit_selected():
            sel = mem_listbox.curselection()
            default_key = records_cache[sel[0]]["memory_key"] if sel else "favorite_music"
            default_val = records_cache[sel[0]]["raw_value"] if sel else ""
            default_cat = records_cache[sel[0]]["category"] if sel else "Personal preferences"

            key_in = simpledialog.askstring("Memory Key", "Enter memory key (e.g., favorite_music, favorite_food, personal_goal):", initialvalue=default_key, parent=win)
            if not key_in:
                return
            val_in = simpledialog.askstring("Memory Value", f"Enter value for '{key_in}':", initialvalue=default_val, parent=win)
            if not val_in:
                return
            cat_in = simpledialog.askstring(
                "Memory Category",
                f"Category ({', '.join(MEMORY_CATEGORIES[:4])}, ...):",
                initialvalue=default_cat,
                parent=win
            ) or default_cat
            _, auto_fact = infer_category_and_fact(key_in.strip(), val_in.strip())
            upsert_long_term_memory(key_in.strip(), cat_in.strip(), auto_fact, val_in.strip(), memories_dict=memories)
            save_game(state)
            refresh_hud()
            refresh_mem_list()

        def delete_selected():
            sel = mem_listbox.curselection()
            if not sel:
                messagebox.showinfo("Select a Memory", "Click a memory in the list first to delete it.", parent=win)
                return
            rec = records_cache[sel[0]]
            if messagebox.askyesno("Delete Memory?", f"Delete '{rec['fact']}' from long-term memory?", parent=win):
                delete_saved_memory(rec["memory_key"], memories_dict=memories)
                save_game(state)
                refresh_hud()
                refresh_mem_list()

        btn_bar = tk.Frame(win, bg="#2A2540")
        btn_bar.pack(fill="x", padx=16, pady=(6, 12))

        tk.Button(
            btn_bar, text="Add / Edit Memory", bg="#FF5E99", fg="#FFFFFF",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=5, command=add_or_edit_selected
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_bar, text="Delete Selected", bg="#3D365C", fg="#FF8DC7",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=5, command=delete_selected
        ).pack(side="left")

        tk.Button(
            btn_bar, text="Close", bg="#312B4B", fg="#F4EFFA",
            font=("Segoe UI", 9), relief="flat", padx=12, pady=5, command=win.destroy
        ).pack(side="right")

        refresh_mem_list()

    def do_vibe():
        p_names = list(PERSONALITIES.keys())
        current = state.get("personality", "Sweet & Caring")
        next_idx = (p_names.index(current) + 1) % len(p_names) if current in p_names else 0
        chosen = p_names[next_idx]
        state["personality"] = chosen
        log_diary_event(state, f"Switched {state['partner_name']}'s personality vibe to '{chosen}'.")
        append_chat(f"\n[Personality Vibe switched to: {chosen}]", "system")
        save_game(state)
        refresh_hud()

    def do_chime_toggle():
        state["chime"] = not state.get("chime", True)
        status = "ON" if state["chime"] else "OFF"
        if state["chime"]:
            play_chime()
        append_chat(f"\n[Milestone Chime is now {status}]", "system")
        save_game(state)
        refresh_hud()

    def do_export():
        export_relationship_diary(state, quiet=True)
        append_chat(f"\n[Exported Relationship Diary & Certificate to {DIARY_FILE}]", "system")
        messagebox.showinfo("Diary Exported", f"Saved your relationship diary to {DIARY_FILE}!")

    def do_profile():
        win = tk.Toplevel(root)
        win.title("Edit Profile & Personality")
        win.configure(bg="#2A2540")
        win.geometry("360x260")

        tk.Label(win, text="Your Name:", bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(12, 2))
        player_var = tk.StringVar(value=state["player_name"])
        tk.Entry(win, textvariable=player_var, bg="#1E1B2E", fg="#F4EFFA", insertbackground="#FF8DC7", relief="flat").pack(fill="x", padx=20, ipady=4)

        tk.Label(win, text="Partner's Name:", bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(10, 2))
        partner_var = tk.StringVar(value=state["partner_name"])
        tk.Entry(win, textvariable=partner_var, bg="#1E1B2E", fg="#F4EFFA", insertbackground="#FF8DC7", relief="flat").pack(fill="x", padx=20, ipady=4)

        tk.Label(win, text="Personality Vibe:", bg="#2A2540", fg="#F4EFFA", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(10, 2))
        vibe_var = tk.StringVar(value=state.get("personality", "Sweet & Caring"))
        vibe_menu = ttk.Combobox(win, textvariable=vibe_var, values=list(PERSONALITIES.keys()), state="readonly")
        vibe_menu.pack(fill="x", padx=20)

        def save_profile():
            new_player = player_var.get().strip()
            new_partner = partner_var.get().strip()
            if new_player:
                state["player_name"] = new_player
            if new_partner:
                state["partner_name"] = new_partner
            state["personality"] = vibe_var.get()
            log_diary_event(state, f"Updated profile: {state['player_name']} & {state['partner_name']} ({state['personality']}).")
            save_game(state)
            refresh_hud()
            append_chat(f"\n[Profile updated: {state['player_name']} & {state['partner_name']} | Vibe: {state['personality']}]", "system")
            win.destroy()

        tk.Button(
            win, text="Save Profile", font=("Segoe UI", 9, "bold"),
            bg="#FF5E99", fg="#FFFFFF", relief="flat", pady=6, command=save_profile
        ).pack(pady=14, padx=20, fill="x")

    def do_help():
        help_text = (
            "FREE CHAT COMMANDS (0 Energy, +2 to +4 Coins/turn):\n"
            "  • Type anything naturally to chat non-stop!\n"
            "  • /ask  — Ask her to interview you about a new favorite.\n"
            "  • Say 'My favorite food is ...', 'I study ...', or 'Remember that ...'\n"
            "    so she saves it to partner_save.json!\n"
            "  • Ask 'What do you remember about me?' anytime.\n\n"
            "ENERGY & COIN ECONOMY:\n"
            "  • Story, Compliment, Gift, Mini-Game cost 1 Energy.\n"
            "  • Date Outing costs 2 Energy (+3 Bonus if personalized by memory!).\n"
            "  • Rest refills Energy, grants +10 Coins, and finds 1 random gift.\n"
            "  • Gift Shop costs 0 Energy.\n\n"
            "TERMINAL FLAGS:\n"
            "  • --gui | --chat | --status | --export | --reset"
        )
        messagebox.showinfo("Quick Help & Commands", help_text)

    def do_reset():
        if not messagebox.askyesno("Reset Save?", "Erase your current progress and start a brand-new save?"):
            return
        clear_all_saved_memories()
        fresh = create_new_state(interactive=False)
        state.clear()
        state.update(fresh)
        gui_ctx["pending_key"] = None
        gui_ctx["pending_label"] = None
        gui_ctx["history"] = []
        gui_ctx["turn_count"] = 0
        save_game(state)

        chat_box.configure(state="normal")
        chat_box.delete("1.0", "end")
        chat_box.configure(state="disabled")

        refresh_hud()
        append_chat("[Started a brand-new save file!]", "system")
        q_k, q_l, open_q = get_proactive_question(state["memories"], state["player_name"])
        if open_q:
            gui_ctx["pending_key"] = q_k
            gui_ctx["pending_label"] = q_l
            append_chat(f'\n{state["partner_name"]}: "{open_q}"', "partner")

    row1_buttons = [
        ("Story (1⚡)", do_story_scene),
        ("Compliment (1⚡)", do_compliment),
        ("Gift (1⚡)", do_gift),
        ("Shop", do_shop),
        ("Date (2⚡)", do_date),
        ("Mini-Game (1⚡)", do_minigame),
        ("Rest (Next Day)", do_rest),
    ]
    row2_buttons = [
        ("Memory Box", do_memories),
        ("Vibe", do_vibe),
        ("Chime", do_chime_toggle),
        ("Export Diary", do_export),
        ("Profile", do_profile),
        ("Help", do_help),
        ("Reset Save", do_reset),
    ]

    for parent_row, btn_list in ((btn_row1, row1_buttons), (btn_row2, row2_buttons)):
        for label, cmd in btn_list:
            b = tk.Button(
                parent_row, text=label, font=("Segoe UI", 8, "bold"),
                bg="#312B4B", fg="#EAE6F5", activebackground="#463E6B",
                relief="flat", padx=6, pady=5, command=cmd
            )
            b.pack(side="left", padx=2, expand=True, fill="x")
            action_buttons.append(b)

    # Opening greeting in GUI
    refresh_hud()
    append_chat(f"Welcome to Desktop GUI Mode! Type anything below to chat with {state['partner_name']} non-stop (0 Energy), or click Help.", "system")
    q_key, q_label, opening_q = get_proactive_question(state.get("memories", {}), state["player_name"], chat_history=gui_ctx["history"])
    if opening_q:
        gui_ctx["pending_key"] = q_key
        gui_ctx["pending_label"] = q_label
        dispatcher.pending_key = q_key
        dispatcher.pending_label = q_label
        append_chat(f'\n{state["partner_name"]}: "{opening_q}"', "partner")
    else:
        append_chat(f'\n{state["partner_name"]}: "Hi {state["player_name"]}! Ready to chat anytime!"', "partner")

    chat_entry.focus()
    root.mainloop()
    return True


def parse_cli_args():
    """Parse optional command-line flags for quick terminal or GUI launch."""
    parser = argparse.ArgumentParser(
        description="CLI & GUI Partner Simulator — Run without arguments for the terminal menu, or use a flag below."
    )
    parser.add_argument("--gui", action="store_true", help="Launch the desktop tkinter GUI window")
    parser.add_argument("--chat", action="store_true", help="Jump straight into Non-Stop Free Chat mode in terminal")
    parser.add_argument("--status", action="store_true", help="Print your current relationship status card, keepsakes, and memories")
    parser.add_argument("--export", action="store_true", help="Export relationship_diary.md immediately and exit")
    parser.add_argument("--reset", action="store_true", help="Start a brand-new save file")
    return parser.parse_args()


def main():
    enable_windows_ansi()
    args = parse_cli_args()

    if args.gui:
        if launch_gui(reset=args.reset):
            return

    if args.status or args.export:
        state = load_game()
        if not state:
            print(f"{C_YELLOW}No saved game found yet! Run 'python girlfriend_sim.py' first to set up your names.{C_RESET}")
            return
        if args.status:
            print_status_card(state)
            view_keepsakes(state["keepsakes"], state.get("memories", {}), state["partner_name"], state["player_name"])
        if args.export:
            export_relationship_diary(state)
        return

    print(f"{C_PINK}========================================{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}   Welcome to the CLI Partner Simulator {C_RESET}")
    print(f"{C_PINK}========================================{C_RESET}")

    state = None if args.reset else load_game()
    if state:
        if args.chat:
            nonstop_chat_mode(state)
            return
        print(f"Found saved game: {C_BOLD}{state['player_name']} & {state['partner_name']}{C_RESET} (Day {state['day']}, Affection {state['affection']}/100)")
        resume = input("Continue saved game? (Y/n): ").strip().lower()
        if resume == "n":
            state = create_new_state()
            save_game(state)
    else:
        state = create_new_state()
        save_game(state)
        if args.chat:
            nonstop_chat_mode(state)
            return

    typewrite(
        f'\n{C_PINK}{state["partner_name"]}: "Hi {state["player_name"]}! Let\'s make some wonderful memories together!"{C_RESET}',
        state.get("typewriter", True)
    )

    while True:
        check_milestones(state)
        save_game(state)
        print_status_card(state)

        print("What would you like to do?")
        print("1. Non-Stop Free Chat (Proactive questions & memory recall - 0 Energy!)")
        print("2. Story Conversation (Branching choices - Costs 1 Energy)")
        print("3. Give a heartfelt compliment (Costs 1 Energy)")
        print("4. Give a gift from your bag (Costs 1 Energy)")
        print("5. Visit Gift Shop (Buy gifts with Coins - 0 Energy)")
        print("6. Go on a date outing (Personalized by your memories! - Costs 2 Energy)")
        print("7. Play a mini-game together (Earn Coins + Uses memories! - Costs 1 Energy)")
        print("8. Rest until tomorrow (Refills Energy + 10 Coins + Morning Surprise!)")
        print("9. View Memory Box (Keepsakes & Remembered Facts)")
        print("10. Export Relationship Diary & Certificate (Creates relationship_diary.md)")
        print("11. Customize Personality Vibe & Typewriter FX (0 Energy)")
        print("12. Launch Desktop GUI Window (tkinter)")
        print("13. Save & Say goodbye (Exit)")

        choice = input("\nEnter your choice (1-13): ").strip()

        if choice in ("2", "3", "4", "7") and state["energy"] < 1:
            print(f"\n{C_RED}You're out of energy for today! Choose option 1 for Free Chat or option 8 to rest.{C_RESET}")
            continue

        if choice == "1":
            nonstop_chat_mode(state)
        elif choice == "2":
            state["energy"] -= 1
            state["affection"], state["mood"] = chat_scene(state)
        elif choice == "3":
            state["energy"] -= 1
            state["affection"] += 8
            state["mood"] = "Blushing"
            print(f"\n{C_PINK}{get_mood_portrait('Blushing')}{C_RESET}")
            if state["affection"] >= 80:
                line = f'{state["partner_name"]}: "{state["player_name"]}, hearing that from you makes my heart race!"'
            else:
                line = f'{state["partner_name"]}: "You always know how to make me smile, {state["player_name"]}!"'
            styled = style_partner_line(line, state.get("personality", "Sweet & Caring"), state["player_name"])
            typewrite(f"{C_PINK}{styled}{C_RESET} {C_GREEN}(+8 Affection){C_RESET}", state.get("typewriter", True))
        elif choice == "4":
            state["affection"], state["mood"], used = gift_menu(state)
            if used:
                state["energy"] -= 1
        elif choice == "5":
            gift_shop_menu(state)
        elif choice == "6":
            state["affection"], state["mood"], used = date_outing(state)
            if used:
                state["energy"] -= 2
        elif choice == "7":
            state["affection"], state["mood"], used = play_minigame(state)
            if used:
                state["energy"] -= 1
        elif choice == "8":
            state["day"] += 1
            state["energy"] = state["max_energy"]
            state["coins"] = state.get("coins", 0) + 10
            found_gift = random.choice(list(state["inventory"].keys()))
            state["inventory"][found_gift] += 1
            state["mood"] = "Happy"
            print(f"\n{C_GREEN}You rested until Day {state['day']}! Energy refilled ({state['max_energy']}/{state['max_energy']}) and earned +10 Coins!{C_RESET}")
            print(f"While out in the morning, you picked up a {C_YELLOW}[{found_gift}]{C_RESET} for {state['partner_name']}!")
            trigger_morning_memory_event(state)
        elif choice == "9":
            view_keepsakes(state["keepsakes"], state.get("memories", {}), state["partner_name"], state["player_name"])
        elif choice == "10":
            export_relationship_diary(state)
        elif choice == "11":
            customize_vibe_menu(state)
        elif choice == "12":
            save_game(state)
            if launch_gui():
                state = load_game() or state
        elif choice == "13":
            save_game(state)
            print(f'\n{C_GREEN}[Game Saved to {SAVE_FILE}]{C_RESET}')
            typewrite(
                f'{C_PINK}{state["partner_name"]}: "See you soon, {state["player_name"]}! Take care of yourself!"{C_RESET}',
                state.get("typewriter", True)
            )
            break
        else:
            print(f"\n{C_RED}Please enter a valid number between 1 and 13.{C_RESET}")

        state["affection"] = max(0, min(100, state["affection"]))


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{C_GREEN}[Session closed safely. See you next time!]{C_RESET}")