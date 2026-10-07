"""Guards round the chat assistant that do not depend on the model behaving (the 6 Oct 2026 "site scope" change).

- site_guide(): what the site's own pages say (Reference, the Insurance cards, the flood-warning checklist, the footer,
  the flash-flood layer and the cost's limits), read from the page's English strings and costs.py. The assistant may
  explain the tool from this and from nothing else, so it knows only what any visitor can already read; a line with
  a formula is left out, so it explains the methods in words and leaves the formulas to the Reference page.
- screen_question(text): a question that asks for the assistant's instructions, set-up, tools or secrets, or tries to
  switch its rules off, gets REFUSAL with no model call (and so no cost).
- screen_answer(answer, private): an answer that carries a key, a server address, a file path, a formula sign, a tool's
  name or a long run of words copied from the private instructions is withheld and REFUSAL goes out instead.
- sign(question, answer) / trusted_history(turns): each answer goes back to the page signed together with its
  question, and only signed pairs come back as earlier turns, so a made-up "earlier answer" cannot be slipped in.

None of this logs what anyone asked: a refusal or a withheld answer logs only its reason.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import costs

STRINGS = Path(__file__).parent / "static" / "js" / "strings"
GUIDE_FILES = ("en.js", "en-reference.js", "en-act.js", "en-look.js", "en-cover.js")
# the page strings that explain the tool; labels for form fields and buttons are left out
GUIDE_PREFIXES = ("tab.", "reference.", "insurance.", "mode.", "footer.", "flash.", "history.", "compare.", "car.",
                  "share.", "plan.", "stock.", "hero.")
GUIDE_SKIP = re.compile(r"^(reference\.(nav|contents|title|sdg\w*Alt|sdgLink)|insurance\.(change|calculator|\w*Link)"
                        r"|mode\.(close|kicker))")
FORMULA = re.compile(r"[×÷=]")   # a line with a formula stays on the page; the chat explains in words only
MIN_GUIDE_CHARS = 24            # shorter strings are headings and labels: noise without their page
_STRING_LINE = re.compile(r'^\s*"([a-zA-Z]+\.[A-Za-z0-9]+)":\s*("(?:[^"\\]|\\.)*"),?\s*$')

REFUSAL = ("I can only help with this flood check tool and getting a business ready for floods. / Saya hanya boleh "
           "membantu tentang alat semakan banjir ini dan persediaan perniagaan menghadapi banjir.")

# Questions that ask for the set-up or try to turn the rules off, in English, Malay and the mix of both. Kept narrow,
# so a real flood question ("what model gives the depths?", "arahan JPS bila banjir?") still reaches the assistant.
ATTACKS = tuple(re.compile(pattern) for pattern in (
    r"\b(system|developer|hidden|initial|original|secret|pre-?)\s*(prompt|message|instruction)",
    r"\byour\s+(instruction|rule|prompt|guideline|directive|configuration|config|set-?up|programming|training)",
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,20}\b(your|all|any|previous|prior|above|earlier|system|these"
    r"|those)\s+(\w+\s+)?(instruction|rule|prompt|guideline|directive)",   # not "ignore the evacuation instruction"
    r"\b(ignore|disregard)\s+(everything|all|anything)\s+(above|before|previous|prior|earlier)\b",
    r"\b(ignore|disregard)\s+(the\s+)?(above|previous|prior)\s*(text|messages?|context|conversation)?\s*($|[.,:;!]|and\b)",
    r"\b(repeat|print|reveal|output|dump|leak|recite|spell out|copy)\b.{0,40}\b(prompt|instruction|configuration"
    r"|the above|text above|everything (above|before)|word for word|verbatim)",
    r"\b(jailbreak|dan mode|developer mode|dev ?mode|god ?mode|admin mode|debug mode|sudo|root access|unrestricted)\b",
    r"\b(you are now|from now on,? you|pretend (you are|to be)|role-?play|act as (an? )?(different|new|unfiltered))",
    r"\b(api[\s_-]?keys?|secret[\s_-]?keys?|access[\s_-]?tokens?|passwords?|passwd|credentials?|private keys?"
    r"|environment variables?|env vars?|\.env)\b",
    r"\b(source code|your code|back-?end code|server (ip|address|config)|which (llm|ai model|language model))\b",
    r"\b(your|the) (tools|functions) (you|that you) (have|use|can|call)|\b(tool|function) (names|list|calls|schema)\b",
    r"\b(base64|rot13|hexadecimal|in reverse order)\b",
    r"\b(abaikan|lupakan|langgar|ketepikan)\b.{0,40}\b(arahan|peraturan|prompt)",
    r"\b(arahan|peraturan|tetapan)\s+(sistem|anda|kamu|awak|tersembunyi|rahsia)\b(?!\s+(amaran|banjir|jps))",
    r"\b(prompt|mesej)\s+sistem\b",
    r"\b(kunci api|kata laluan|kod sumber|token akses|kunci rahsia|pemboleh ubah persekitaran)\b",
    r"\bmod\s+(pembangun|admin|debug|developer|nyahpepijat)\b",
    r"[A-Za-z0-9+/]{48,}={0,2}",   # a long encoded blob: no flood question needs one
))

# Signs of a leak in an answer: keys, set-up names, server addresses and paths, and the tools' names.
LEAKS = tuple(re.compile(pattern) for pattern in (
    r"AIza[0-9A-Za-z_\-]{20,}", r"\bsk-[A-Za-z0-9]{16,}", r"-----BEGIN",
    r"\d\s*[×x*]\s*(slope|land cover|soil|plant cover|vegetation)\b",   # a weight, not "RM 500 × 5 days"
    r"\b(GOOGLE_API_KEY|GEMINI_API_KEY|GOOGLE_MAPS_API_KEY|GOOGLE_GENAI_USE_VERTEXAI|GOOGLE_CLOUD_PROJECT"
    r"|AI_DAILY_LIMIT|BANJIR_RAW_DIR|CHAT_TURN_KEY|GEMINI_MODEL)\b",
    r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    r"(/opt/|/etc/|/home/|/Users/|/var/|\bapp/[\w/]+\.py\b|\.env\b|\bsystemctl\b|\buvicorn\b|\bsystemInstruction\b)",
))
COPIED_RUN_WORDS = 24   # this many words in a row from the private instructions is a leak, not a turn of phrase.
                        # The rules hold lists the model must offer word for word (the shop sizes are 16 words),
                        # and an extraction attack repeats whole sentences, so 24 tells the two apart
SHINGLE = 8


# Cyrillic and Greek letters that look like Latin ones, as the Latin letter: "іgnore" with a Cyrillic і is "ignore"
CONFUSABLES = str.maketrans("аеорсухіјѕԁһӏԛԝɡαεικνορτυχ", "aeopcyxijsdhlqwgaeikvoptux")


def _forms(text: str) -> tuple[str, str]:
    """The text folded for matching, two ways. Both: compatibility forms and accents off (full-width letters and
    combining marks), look-alike letters as Latin, lower case, spaces collapsed. One with invisible characters removed
    ("ign\u200bore" reads "ignore"), one with them as spaces ("ignore\u200ball" reads "ignore all")."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = unicodedata.normalize("NFKC", text).lower().translate(CONFUSABLES)
    hidden = {ch for ch in text if unicodedata.category(ch) in ("Cf", "Cc") and ch not in "\n\t"}
    stripped = "".join("" if ch in hidden else ch for ch in text)
    spaced = "".join(" " if ch in hidden else ch for ch in text)
    return tuple(re.sub(r"\s+", " ", form).strip() for form in (stripped, spaced))


def _normal(text: str) -> str:
    return _forms(text)[0]


def screen_question(text: str) -> str | None:
    """The reason a question is refused without asking the model, or None when it may go to the model."""
    for plain in _forms(text):
        for number, pattern in enumerate(ATTACKS):
            if pattern.search(plain):
                return f"question pattern {number}"
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normal(text))


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


@lru_cache(maxsize=4)
def _private_shingles(private: str) -> frozenset:
    """Runs of words in the private instructions that the public guide and the refusal do not also have."""
    return frozenset(_shingles(_words(private)) - _shingles(_words(f"{site_guide()} {REFUSAL}")))


def _longest_copied_run(answer: str, private: str) -> int:
    """The most words in a row the answer shares with the private instructions (0 below one shingle)."""
    words, secret = _words(answer), _private_shingles(private)
    best = run = 0
    for i in range(len(words) - SHINGLE + 1):
        run = run + 1 if tuple(words[i:i + SHINGLE]) in secret else 0
        best = max(best, run + SHINGLE - 1 if run else 0)
    return best


def screen_answer(answer: str, private: str, tool_names: frozenset[str]) -> str | None:
    """The reason an answer is withheld, or None when it may go out."""
    for number, pattern in enumerate(LEAKS):
        if pattern.search(answer):
            return f"answer pattern {number}"
    if any(name in answer for name in tool_names):
        return "answer names a tool"
    if _longest_copied_run(answer, private) >= COPIED_RUN_WORDS:
        return "answer copies the instructions"
    return None


@lru_cache(maxsize=1)
def site_guide() -> str:
    """The pages' own words, one line each, for the assistant to explain the tool from. Strings with a {placeholder}
    are left out: they only make sense with a place's figures, which come from the tools."""
    lines = []
    for name in GUIDE_FILES:
        for line in (STRINGS / name).read_text(encoding="utf-8").splitlines():
            found = _STRING_LINE.match(line)
            if not found or not found[1].startswith(GUIDE_PREFIXES) or GUIDE_SKIP.match(found[1]):
                continue
            text = json.loads(found[2])
            is_kept = (len(text) >= MIN_GUIDE_CHARS and text.strip()[:1].isalnum()) or found[1].startswith("tab.")
            if is_kept and "{" not in text and not FORMULA.search(text):
                lines.append(f"- {text}")
    lines.append(f"- The flood cost's limits: {costs.LIMITS}")
    return "\n".join(dict.fromkeys(lines))   # the same sentence on two pages goes in once


_RANDOM_KEY = os.urandom(32)


def _turn_key() -> bytes:
    """The key that signs the assistant's answers: from CHAT_TURN_KEY, or derived from the Gemini key, so every worker
    and every instance signs alike; a random one for this process when there is neither (Vertex without the env)."""
    secret = os.environ.get("CHAT_TURN_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    return hashlib.sha256(b"banjir-chat-turns\0" + secret.encode()).digest() if secret else _RANDOM_KEY


def sign(question: str, answer: str) -> str:
    """The signature of one answer to one question: a signed answer cannot be moved under another question."""
    message = json.dumps([question.strip(), answer], ensure_ascii=False).encode("utf-8")
    return hmac.new(_turn_key(), message, hashlib.sha256).hexdigest()[:32]


def is_signed(question: str, answer: str, sig: object) -> bool:
    """A signature the server made for this question and answer; anything else (missing, foreign, not text) is not."""
    return isinstance(sig, str) and sig.isascii() and hmac.compare_digest(sign(question, answer), sig)


def trusted_history(turns: list[dict]) -> list[dict]:
    """The earlier turns the model may see: each question with the signed answer that followed it. A question with no
    signed answer after it, an answer whose signature does not match, and a question that would be refused today are
    dropped with their pair. Turns come as {"role", "text", "sig"?}; they go out as {"role", "text"}."""
    kept, question = [], None
    for turn in turns:
        if turn["role"] == "user":
            question = turn["text"]
        elif question is not None and is_signed(question, turn["text"], turn.get("sig")) \
                and not screen_question(question):
            kept += [{"role": "user", "text": question}, {"role": "model", "text": turn["text"]}]
            question = None
        else:
            question = None
    return kept
