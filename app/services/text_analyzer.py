"""NLP analysis of listing descriptions.

Two layers, both explainable:

1. **Rule layer** - curated regular expressions grouped into risk categories
   (advance payment, payment before viewing, no viewing, owner away, urgency,
   unusual payment channels, off-platform contact, sensitive-information
   requests). Each match records the exact phrase so the UI can show evidence.
   A negation window ("no advance required") suppresses false positives, and
   routine availability phrases ("immediately available") are explicitly
   excluded from urgency.
2. **TF-IDF layer** - character n-gram TF-IDF vectors of each sentence are
   compared (cosine similarity) with a bank of risky prototype sentences and a
   bank of benign rental sentences. This catches paraphrases and misspellings
   ("snd advnce befor visit") that exact rules miss. It is only reported when
   the sentence is clearly closer to a risky prototype than to a benign one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MAX_TEXT_CHARS = 5000

_NEGATION_RE = re.compile(r"\b(no|not|never|without|zero|nil|don'?t|do not|doesn'?t|won'?t|nor)\b[^.!?]{0,25}$", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+|\s*[;|]\s*")


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern
    label: str
    negatable: bool = True
    weight: float = 1.0  # used for urgency score only


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.I)


PAY = r"(?:pay|send|transfer|deposit|remit|wire)"
MONEY = r"(?:advance|token(?: amount| money)?|booking (?:amount|fee)|deposit|security deposit|money|amount|payment|rent)"
VIEW = r"(?:visit(?:ing)?|view(?:ing)?|see(?:ing)?|seen|site visit|inspection|showing|meet(?:ing)?)"

RULES: list[Rule] = [
    # --- advance payment -------------------------------------------------
    Rule("advance_payment", _r(rf"\b{PAY}(?:ing)?\s+(?:the\s+|an?\s+|us\s+|me\s+)?{MONEY}\s+(?:in\s+)?advance\b"),
         "Request to pay money in advance"),
    Rule("advance_payment", _r(rf"\b{PAY}(?:ing)?\s+(?:the\s+|an?\s+|us\s+|me\s+)?(?:advance|token(?: amount| money)?|booking (?:amount|fee))\b"),
         "Request to send an advance / token amount"),
    Rule("advance_payment", _r(r"\badvance\s+(?:payment|amount|money)\s+(?:is\s+)?(?:required|needed|mandatory|compulsory|first)\b"),
         "Advance payment stated as mandatory"),
    Rule("advance_payment", _r(r"\b(?:token|booking)\s+(?:amount|money|fee)\s+(?:is\s+)?(?:required|needed|mandatory|to (?:book|block|reserve))\b"),
         "Token/booking amount required to reserve"),
    # --- payment before viewing -------------------------------------------
    Rule("payment_before_viewing", _r(rf"\b{PAY}\w*\b[^.!?]{{0,60}}\b(?:before|prior to|without)\s+(?:any\s+|the\s+|a\s+)?(?:physical\s+)?{VIEW}"),
         "Payment requested before viewing the property", negatable=False),
    Rule("payment_before_viewing", _r(rf"\b(?:before|prior to)\s+(?:the\s+|a\s+|any\s+)?(?:physical\s+)?{VIEW}[^.!?]{{0,40}}\b{PAY}\w*"),
         "Payment requested before viewing the property", negatable=False),
    Rule("payment_before_viewing", _r(r"\bkeys?\s+(?:will be|shall be|can be|would be)\s+(?:sent|couriered|delivered|posted|mailed|handed over)\s+(?:after|once|on|upon)\s+(?:payment|receiving|receipt|transfer)"),
         "Keys promised by courier after payment"),
    Rule("payment_before_viewing", _r(rf"\b(?:after|once|on)\s+(?:receiving|receipt of|getting)\s+(?:the\s+)?{MONEY}[^.!?]{{0,40}}\b(?:send|courier|share|give)\s+(?:you\s+)?(?:the\s+)?keys?"),
         "Keys released only after money is received"),
    # --- no viewing ---------------------------------------------------------
    Rule("no_viewing", _r(r"\bno\s+(?:physical\s+|site\s+|in[- ]person\s+)?(?:viewing|visit|visits|inspection|showing)s?\b"),
         "States that no physical viewing is possible", negatable=False),
    Rule("no_viewing", _r(r"\b(?:viewing|visit|inspection|showing)s?\s+(?:is\s+|are\s+)?(?:not\s+(?:possible|allowed|available)|impossible)\b"),
         "States that viewing is not possible", negatable=False),
    Rule("no_viewing", _r(r"\b(?:can'?t|cannot|can not|unable to|won'?t be able to)\s+(?:show|arrange a visit|meet)\b"),
         "Landlord unable to show the property", negatable=False),
    Rule("no_viewing", _r(r"\b(?:only\s+(?:video|online|virtual)\s+(?:tour|viewing|call)|(?:video|virtual|online)\s+(?:tour|viewing)\s+only)\b"),
         "Only online/video viewing offered", negatable=False),
    # --- owner away -----------------------------------------------------------
    Rule("owner_away", _r(r"\b(?:i am|i'm|im|owner is|landlord is|we are|currently|presently)\s+(?:\w+\s+){0,3}(?:in|at)\s+(?:abroad|overseas|dubai|usa|the us|uk|london|canada|singapore|australia|the gulf|germany|qatar|kuwait)\b"),
         "Owner says they are abroad", negatable=False),
    Rule("owner_away", _r(r"\b(?:owner|landlord|i am|i'm)\s+(?:is\s+)?(?:currently\s+)?(?:abroad|overseas|out of (?:the )?(?:country|station|town|city|mumbai)|outside (?:india|mumbai|the city))\b"),
         "Owner says they are away / outside the city", negatable=False),
    Rule("owner_away", _r(r"\b(?:posted|transferred|deployed)\s+(?:to|in|at|outside)\s+(?:another|a different|[a-z]+)\s*(?:city|state|country)?\b[^.!?]{0,40}\b(?:can'?t|cannot|unable|not able)\b"),
         "Owner claims relocation and unavailability", negatable=False),
    # --- urgency / pressure -------------------------------------------------
    Rule("urgency", _r(r"\b(?:will|may|would|shall)\s+be\s+(?:given|rented|let out|allotted)\s+to\s+(?:someone|somebody|another|others|the next|other)\b"),
         "Pressure: property will go to someone else", negatable=False, weight=0.6),
    Rule("urgency", _r(r"\b(?:many|several|lots of|other)\s+(?:people|parties|clients|tenants|families)\s+(?:are\s+)?(?:interested|waiting|in line|in queue)\b"),
         "Pressure: many others interested", negatable=False, weight=0.5),
    # NB: "within 10 minutes" is almost always walking distance, so only hours count.
    Rule("urgency", _r(r"\b(?:today only|offer valid today|within\s+(?:\d+|twenty[- ]four|few)\s+(?:hours?|hrs?)(?!\s+(?:drive|walk|journey|travel|from|of|by))|last chance|hurry(?: up)?|act fast|limited time)\b"),
         "Deadline pressure", negatable=False, weight=0.6),
    Rule("urgency", _r(r"\b(?:pay|transfer|send|decide|confirm)\s+(?:\w+\s+){0,3}(?:immediately|right now|right away|asap|urgently|today)\b"),
         "Immediate payment/decision demanded", negatable=False, weight=0.7),
    Rule("urgency", _r(r"\b(?:urgent(?:ly)?|asap)\b(?![^.!?]{0,20}\b(?:required|requirement|need(?:ed)?)\s+(?:for\s+)?(?:a\s+)?(?:tenant|family|client))"),
         "Urgency language", negatable=False, weight=0.3),
    # --- unusual payment channel --------------------------------------------
    Rule("unusual_payment", _r(r"\b(?:western union|moneygram|money gram|gift ?cards?|itunes cards?|amazon (?:pay )?(?:voucher|gift)|bitcoin|crypto(?:currency)?|usdt)\b"),
         "Untraceable payment method requested", negatable=False),
    Rule("unusual_payment", _r(rf"\b{PAY}\w*\b[^.!?]{{0,40}}\bto\s+(?:my|his|her|our)\s+(?:friend|relative|brother|sister|cousin|agent|secretary|caretaker|lawyer)(?:'s)?\b"),
         "Payment to a third party's account"),
    Rule("unusual_payment", _r(r"\bcourier\s+(?:you\s+)?(?:the\s+)?keys?\b|\bkeys?\s+(?:by|via|through)\s+courier\b"),
         "Keys delivered by courier instead of in person", negatable=False),
    # --- off-platform contact -------------------------------------------------
    # "brokers do not call" is routine, so plain "do not call" is deliberately not a rule.
    Rule("off_platform", _r(r"\b(?:contact|reach|message|text|ping)\s+(?:me\s+)?(?:only\s+)?(?:on|via|through)\s+(?:whats ?app|telegram|signal|e-?mail)\s+only\b|\b(?:whats ?app|telegram|e-?mail)\s+only\b|\bonly\s+(?:on\s+)?(?:whats ?app|telegram)\b"),
         "Contact restricted to messaging / e-mail", negatable=False),
    # --- sensitive information ------------------------------------------------
    Rule("sensitive_info", _r(r"\b(?:send|share|provide|give|tell)\s+(?:me\s+|us\s+)?(?:the\s+|your\s+)?(?:otp|one[- ]time password|bank (?:details|account details|password)|card (?:details|number)|cvv|upi pin|net ?banking)\b"),
         "Request for OTP / banking credentials", negatable=False),
]

CATEGORY_LABELS = {
    "advance_payment": "Advance payment request",
    "payment_before_viewing": "Payment before viewing",
    "no_viewing": "No physical viewing",
    "owner_away": "Owner abroad / unavailable",
    "urgency": "Urgency or pressure language",
    "unusual_payment": "Unusual payment method",
    "off_platform": "Restricted contact channel",
    "sensitive_info": "Sensitive information request",
}

# Phrases that look like urgency but are routine in Indian rental listings.
_BENIGN_URGENCY_RE = re.compile(
    r"\b(?:immediately available|available immediately|immediate(?:ly)? (?:possession|shift|move)|"
    r"ready to (?:move|shift)|urgent(?:ly)? (?:required|requirement|need)|urgent rent)\b", re.I)

RISKY_PROTOTYPES = [
    "send the advance payment before visiting the flat",
    "transfer token amount first then i will send the keys",
    "pay the deposit online and we will courier the keys",
    "i am currently abroad so i cannot show you the apartment",
    "owner is out of the country and cannot meet",
    "no physical viewing is possible, pay to book",
    "pay immediately or the flat will be given to someone else",
    "many people are interested so transfer the booking amount today",
    "send money via western union or gift card",
    "pay the rent to my friend's account and he will hand over keys",
    "share the otp to confirm your booking",
    "contact on whatsapp only, do not call",
    "keys will be sent by courier after payment",
    "deposit the money in my account to reserve the flat without visiting",
    "i am working in dubai, pay first and move in",
    "only video tour available, send advance to block",
]
BENIGN_PROTOTYPES = [
    "2 bhk flat available for rent near the station",
    "the apartment is semi furnished with modular kitchen",
    "security deposit of three months rent is required",
    "immediately available for family",
    "tenant needs to make a security deposit",
    "rent is negotiable for a good family",
    "society has gym swimming pool and security",
    "please call to schedule a visit to the property",
    "brokerage of one month applicable",
    "the owner is an nri, the agent will show the flat",
    "available for bachelors and working professionals",
    "full power backup and covered parking",
    "visit the site and pay token amount after finalising",
    "rent agreement and police verification mandatory",
    "fastest connectivity to western and central suburbs",
    "interested people feel free to contact us",
    "walking distance from the railway station",
    "cheque payment accepted for rent",
]

# A sentence must contain at least one of these stems before the TF-IDF layer
# may report it; this stops purely lexical look-alikes ("western" suburbs vs
# "western union") from being reported.
_ANCHORS = ("pay", "send", "snd", "transf", "advan", "advn", "token", "deposit", "key", "visit",
            "view", "abroad", "dubai", "otp", "courier", "money", "book", "whatsapp", "wire", "someone")
SEMANTIC_THRESHOLD = 0.5


class TextAnalyzer:
    def __init__(self) -> None:
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._vec.fit(RISKY_PROTOTYPES + BENIGN_PROTOTYPES)
        self._risky = self._vec.transform(RISKY_PROTOTYPES)
        self._benign = self._vec.transform(BENIGN_PROTOTYPES)

    # ------------------------------------------------------------------
    @staticmethod
    def _negated(text: str, start: int) -> bool:
        window = text[max(0, start - 30):start]
        return bool(_NEGATION_RE.search(window))

    def _semantic(self, text: str) -> tuple[float, str | None, str | None]:
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text)
                     if len(s.strip()) >= 12 and any(a in s.lower() for a in _ANCHORS)][:60]
        if not sentences:
            return 0.0, None, None
        X = self._vec.transform([s.lower() for s in sentences])
        risky = cosine_similarity(X, self._risky)
        benign = cosine_similarity(X, self._benign)
        best, best_sentence, best_proto = 0.0, None, None
        for i, sent in enumerate(sentences):
            j = int(risky[i].argmax())
            r, b = float(risky[i, j]), float(benign[i].max())
            if r > best and r > b + 0.1:
                best, best_sentence, best_proto = r, sent, RISKY_PROTOTYPES[j]
        return best, best_sentence, best_proto

    # ------------------------------------------------------------------
    def analyze(self, description: str | None) -> dict:
        text = (description or "")[:MAX_TEXT_CHARS]
        categories = {c: False for c in CATEGORY_LABELS}
        matches: list[dict] = []
        seen: set[tuple[str, str]] = set()   # set for de-duplicating evidence
        urgency = 0.0

        benign_spans = [m.span() for m in _BENIGN_URGENCY_RE.finditer(text)]

        for rule in RULES:
            for m in rule.pattern.finditer(text):
                if rule.negatable and self._negated(text, m.start()):
                    continue
                if rule.category == "urgency" and any(s <= m.start() < e for s, e in benign_spans):
                    continue
                phrase = m.group(0).strip()
                key = (rule.category, phrase.lower())
                if key in seen:
                    continue
                seen.add(key)
                categories[rule.category] = True
                if rule.category == "urgency":
                    urgency += rule.weight
                matches.append({"category": rule.category, "label": rule.label, "phrase": phrase})

        sem_score, sem_sentence, sem_proto = self._semantic(text) if text else (0.0, None, None)
        words = len(text.split())
        return {
            "available": bool(text.strip()),
            "word_count": words,
            "categories": categories,
            "category_labels": {c: CATEGORY_LABELS[c] for c, v in categories.items() if v},
            "matches": matches,
            "risk_phrases": sorted({m["phrase"] for m in matches}),
            "urgency_score": round(min(1.0, urgency), 2),
            "advance_payment_detected": categories["advance_payment"] or categories["payment_before_viewing"],
            "no_viewing_detected": categories["no_viewing"],
            "owner_abroad_detected": categories["owner_away"],
            "semantic_risk_similarity": round(sem_score, 3),
            "semantic_match": ({"sentence": sem_sentence[:240], "closest_pattern": sem_proto}
                               if sem_score >= SEMANTIC_THRESHOLD else None),
            "short_description": words < 12,
        }
