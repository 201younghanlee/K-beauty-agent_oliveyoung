#!/usr/bin/env python3
"""Build a deterministic recommendation catalog from Open Beauty Facts.

The default input is the official Open Beauty Facts JSONL gzip export.  The
reader is streaming: it keeps only normalized, supported skincare products in
memory and never expands the whole source dump on disk.  Tests and reviewers
can pass ``--input`` with a local ``.jsonl`` or ``.jsonl.gz`` fixture so no
network access is required.

Open Beauty Facts database records are provided under ODbL 1.0.  Product
images are provided under CC BY-SA 3.0.  Both licenses and the attribution URL
are written to every generated row and to the catalog manifest.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import email.utils
import gzip
import hashlib
import html
import io
import json
import math
import os
import re
import statistics
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, TextIO


DEFAULT_DUMP_URL = "https://static.openbeautyfacts.org/data/openbeautyfacts-products.jsonl.gz"
PRODUCT_BASE_URL = "https://world.openbeautyfacts.org/product"
IMAGE_BASE_URL = "https://images.openbeautyfacts.org/images/products"
ATTRIBUTION_URL = "https://world.openbeautyfacts.org/data"
DATABASE_LICENSE_ID = "ODbL-1.0"
DATABASE_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
IMAGE_LICENSE_ID = "CC-BY-SA-3.0"
IMAGE_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
DATA_LICENSE_LABEL = f"{DATABASE_LICENSE_ID} (database); {IMAGE_LICENSE_ID} (product images)"
USER_AGENT = (
    "KBeautyAgentCatalogRefresh/1.0 "
    "(+https://github.com/201younghanlee/K-beauty-agent_oliveyoung; scheduled Open Beauty Facts import)"
)

CATALOG_COLUMNS = (
    "id",
    "name",
    "brand",
    "category",
    "country",
    "ingredients",
    "claims",
    "source_url",
    "ingredient_source_url",
    "verified_at",
    "image_url",
    "image_verified_source",
    "image_source_type",
    "image_confidence",
    "image_view_type",
    "official_url",
    "catalog_source",
    "source_product_id",
    "source_updated_at",
    "fetched_at",
    "ingredient_status",
    "recommendation_tier",
    "data_license",
    "data_attribution_url",
)

# More specific categories must come first. These expanded groups are only
# accepted when the source name or taxonomy carries an explicit product-form
# signal. This keeps generic hygiene records out while allowing the catalog to
# cover the wider beauty assortment users expect.
SPECIALTY_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "eye_care",
        (
            "eye creams",
            "eye cream",
            "eye serums",
            "eye serum",
            "eye contour",
            "eye treatments",
            "eye treatment",
            "under eye cream",
            "under eye treatment",
            "eye patches",
            "eye patch",
            "eye masks",
            "eye mask",
        ),
    ),
    (
        "face_mask",
        (
            "facial masks",
            "facial mask",
            "face masks",
            "face mask",
            "sheet masks",
            "sheet mask",
            "sleeping masks",
            "sleeping mask",
            "clay masks",
            "clay mask",
            "gel masks",
            "gel mask",
            "masques pour le visage",
            "masque visage",
        ),
    ),
    (
        "exfoliator",
        (
            "facial scrubs",
            "facial scrub",
            "face scrubs",
            "face scrub",
            "facial exfoliators",
            "facial exfoliator",
            "face exfoliators",
            "face exfoliator",
            "chemical peels",
            "chemical peel",
            "facial peeling",
            "exfoliating toner",
            "gommage visage",
        ),
    ),
    (
        "lip_care",
        (
            "lip balms",
            "lip balm",
            "lip care",
            "lip masks",
            "lip mask",
            "lip treatments",
            "lip treatment",
            "lip moisturizers",
            "lip moisturizer",
            "stick levres",
            "soin des levres",
        ),
    ),
    (
        "base_makeup",
        (
            "face makeup",
            "foundations",
            "foundation",
            "concealers",
            "concealer",
            "bb creams",
            "bb cream",
            "cc creams",
            "cc cream",
            "tinted moisturizers",
            "tinted moisturizer",
            "blushes",
            "blush",
            "bronzers",
            "bronzer",
            "face powders",
            "face powder",
        ),
    ),
    (
        "eye_makeup",
        (
            "eyes makeup",
            "eye makeup",
            "mascaras",
            "mascara",
            "eyeshadows",
            "eyeshadow",
            "eye shadow",
            "eyeliners",
            "eyeliner",
            "eye liner",
        ),
    ),
    (
        "lip_makeup",
        (
            "lip cosmetics",
            "lipsticks",
            "lipstick",
            "lip glosses",
            "lip gloss",
        ),
    ),
    (
        "shampoo",
        (
            "shampoos",
            "shampoo",
        ),
    ),
    (
        "conditioner",
        (
            "hair conditioners",
            "hair conditioner",
            "conditioners",
            "conditioner",
        ),
    ),
    (
        "hair_treatment",
        (
            "hair masks",
            "hair mask",
            "hair serums",
            "hair serum",
            "hair oils",
            "hair oil",
            "scalp care",
            "scalp treatments",
            "scalp treatment",
        ),
    ),
    (
        "body_exfoliator",
        (
            "body scrubs",
            "body scrub",
        ),
    ),
    (
        "body_cleanser",
        (
            "body washes",
            "body wash",
            "shower gels",
            "shower gel",
            "gel douche",
            "duschgel",
            "bath products",
            "showers and baths",
        ),
    ),
    (
        "body_moisturizer",
        (
            "body lotions",
            "body lotion",
            "body creams",
            "body cream",
            "body oils",
            "body oil",
            "hand creams",
            "hand cream",
            "foot creams",
            "foot cream",
        ),
    ),
)

# Facial-routine categories retain the stricter explicit face-scope rule used
# by the original catalog. For example, "sun cream" is a sunscreen rather than
# a generic moisturizer only when the record is explicitly facial.
CORE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "sunscreen",
        (
            "facial sunscreen",
            "face sunscreen",
            "sunscreens",
            "sunscreen",
            "sun protection",
            "sun care",
            "sun cream",
            "sun stick",
            "uv protection",
            "spf cream",
        ),
    ),
    (
        "cleanser",
        (
            "facial cleansers",
            "facial cleanser",
            "face cleanser",
            "face wash",
            "cleansing foam",
            "cleansing gel",
            "cleansing oil",
            "cleansing balm",
            "micellar water",
            "cleansers",
            "cleanser",
        ),
    ),
    (
        "toner",
        (
            "facial toners",
            "facial toner",
            "face toner",
            "toner pads",
            "toner pad",
            "skin toner",
            "toners",
            "toner",
        ),
    ),
    (
        "serum",
        (
            "facial serums",
            "facial serum",
            "face serum",
            "skin serum",
            "ampoule",
            "facial essence",
            "face essence",
            "serums",
            "serum",
        ),
    ),
    (
        "moisturizer",
        (
            "facial moisturizers",
            "facial moisturizer",
            "face moisturizer",
            "face moisturiser",
            "facial creams",
            "facial cream",
            "face cream",
            "day cream",
            "night cream",
            "skin moisturizer",
            "skin moisturiser",
            "moisturizers",
            "moisturizer",
            "moisturisers",
            "moisturiser",
        ),
    ),
)

CATEGORY_RULES = (*SPECIALTY_CATEGORY_RULES, *CORE_CATEGORY_RULES)
REQUIRED_CORE_CATEGORIES = tuple(category for category, _ in CORE_CATEGORY_RULES)
PUBLIC_RECOMMENDATION_CATEGORIES = tuple(category for category, _ in CATEGORY_RULES)
LEGACY_CATEGORY_FAMILIES = {
    "body_care": ("body_cleanser", "body_moisturizer", "body_exfoliator"),
    "hair_care": ("shampoo", "conditioner", "hair_treatment"),
    "makeup": ("base_makeup", "eye_makeup", "lip_makeup"),
}
LEGACY_CATEGORY_MIGRATION_MAX_DROP_RATIO = 0.60
MAX_SOURCE_AGE_DAYS = 365 * 3
FRESHNESS_POLICY_MIGRATION_MAX_DROP_RATIO = 0.85

HARD_EXCLUDED_NAME_SIGNALS = (
    "after shave",
    "aftershave",
    "anti lice",
    "anti poux",
    "antifungal",
    "acne relief",
    "baby",
    "babies",
    "baard",
    "barba",
    "barbe",
    "bart",
    "bebe",
    "bébé",
    "beard",
    "bougie de massage",
    "cellulite",
    "child",
    "children",
    "boys",
    "girls",
    "madchen",
    "deodorant",
    "diaper",
    "enfant",
    "enfants",
    "face & body",
    "face and body",
    "visage et corps",
    "cara y cuerpo",
    "rostro y cuerpo",
    "gesicht und korper",
    "hand sanitizer",
    "igienizzante mani",
    "hair root concealer",
    "root concealer",
    "hair color",
    "hair colour",
    "head lice",
    "healing ointment",
    "intimate",
    "junior",
    "kid",
    "kids",
    "läuse",
    "lentes",
    "medicated",
    "medicinal",
    "nail",
    "lash adhesive",
    "cuticle",
    "ongle",
    "ongles",
    "nagel",
    "nagelcreme",
    "nagelpflege",
    "unghie",
    "paznokci",
    "unas",
    "newborn",
    "eau de parfum",
    "parfum spray",
    "perfume",
    "pet conditioner",
    "pet shampoo",
    "pet wash",
    "dog conditioner",
    "dog shampoo",
    "cat conditioner",
    "cat shampoo",
    "for dogs",
    "for cats",
    "psoriasis",
    "pour chiens",
    "pour chats",
    "reinigendes handgel",
    "rasage",
    "eczema",
    "shave",
    "therapeutic shampoo",
    "tolnaftate",
    "tattoo",
    "toilet cleaner",
    "vaginal",
    "wash & shampoo",
    "wash and shampoo",
)

HARD_EXCLUDED_CATEGORY_SIGNALS = (
    "anti perspirant",
    "antiperspirant",
    "baby care",
    "desserts",
    "frozen desserts",
    "frozen foods",
    "ice creams",
    "cat shampoo",
    "cleaning product",
    "deodorant",
    "detergent",
    "diaper",
    "disinfectant",
    "dog shampoo",
    "eau de toilette",
    "fragrance",
    "hair dyes",
    "hair dye",
    "household",
    "intimate hygiene",
    "medicine",
    "mouthwash",
    "nail makeup",
    "nail polish",
    "oral care",
    "pet care",
    "pet grooming",
    "pet shampoo",
    "plant based foods",
    "shampoos for babies",
    "shampoos for children",
    "perfume",
    "shaving",
    "toilet cleaner",
    "toothpaste",
)

HARD_EXCLUDED_BRAND_SIGNALS = (
    "babylove",
    "babyganics",
    "bebe cadum",
    "bébé cadum",
    "dermaclay junior",
    "mixa bebe",
    "mixa bébé",
    "nizoral",
    "eczema honey",
    "pet head",
    "pethead",
)

HARD_EXCLUDED_INGREDIENT_SIGNALS = (
    "benzoyl peroxide",
    "butylphenyl methylpropional",
    "hicc",
    "hydroxyisohexyl 3 cyclohexene carboxaldehyde",
    "chloroacetamide",
    "isobutyl paraben",
    "isobutylparaben",
    "isopropyl paraben",
    "isopropylparaben",
    "lilial",
    "lyral",
    "pentasodium pentetate",
    "pyrithione zinc",
    "selenium sulfide",
    "tolnaftate",
    "zinc pyrithion",
    "zinc pyrithione",
)
LEAVE_ON_CATEGORIES = {
    "base_makeup",
    "body_moisturizer",
    "eye_care",
    "eye_makeup",
    "face_mask",
    "hair_treatment",
    "lip_care",
    "lip_makeup",
    "moisturizer",
    "serum",
    "sunscreen",
    "toner",
}
LEAVE_ON_PROHIBITED_INGREDIENT_SIGNALS = (
    "methylchloroisothiazolinone",
    "methylisothiazolinone",
)

STRONG_CLEANSER_NAME_SIGNALS = (
    "cleanser",
    "cleansing balm",
    "cleansing foam",
    "cleansing gel",
    "cleansing oil",
    "face wash",
    "facial wash",
    "skin cleanser",
)

STRONG_SUNSCREEN_NAME_SIGNALS = (
    "face sunscreen",
    "facial sunscreen",
    "sun cream",
    "sun stick",
    "sunscreen",
    "solaire",
    "sonnencreme",
    "선크림",
)

CLEANSER_OVERRIDE_BLOCKING_SIGNALS = (
    "body",
    "cat",
    "dog",
    "foot",
    "hair",
    "hand",
    "pet",
    "scalp",
    "shampoo",
)

KNOWN_SOURCE_CATEGORY_CORRECTIONS = {
    # Open Beauty Facts currently tags this facial Laneige moisturizer as a
    # body cream. Keep the correction source-specific and barcode-stable.
    "8809925136649": "moisturizer",
    # Community taxonomy corrections verified against the product form.
    "5037156228144": "hair_treatment",
    "0694419061358": "body_moisturizer",
    "7707305543203": "face_mask",
    "3380810108996": "serum",
    "8720354199138": "body_cleanser",
    "4084500380622": "shampoo",
    "4010355347329": "conditioner",
    "4015100336764": "conditioner",
    "7700304143955": "conditioner",
}

KNOWN_SOURCE_EXCLUDED_BARCODES = {
    # Community records whose taxonomy points to an unrelated beauty form.
    "00066656",  # body glitter tagged as shampoo
    "3574661516332",  # Natusan baby wash tagged as BB cream
    "7421002044619",  # probable veterinary shampoo with no human-use evidence
    # Child-directed records whose English display names or primary brand omit
    # the age restriction carried elsewhere on the label/source record.
    "4058172703072",
    "0381371174614",
    "0860001118643",
    "3614810004034",
    "5013692226998",
    "5013692231541",
    "8720604317619",
    "5010525042954",
    "7613035299726",
    "8718924879818",
    # Misclassified shower oil with a product-specific safety concern.
    "4005808134427",
    # Explicit face/body or hair/body multi-use products cannot be represented
    # safely by the catalog's single product-form field.
    "0190679004789",
    "3222474495305",
    "3222474495312",
    "3245678599235",
    "3250391896493",
    "3401360668911",
    "3468080150157",
    "3560070211623",
    "3560070881673",
    "3574134711332",
    "3760020733100",
    "3600523900787",
    "3607340722127",
    "4008233129518",
    "4008233153599",
    "4058172184765",
    "5055936817661",
    "8470003165549",
    "8710908307188",
    "8711700956796",
    "8712561018050",
    "8712561397650",
    "8712561397759",
    "8719134163100",
    "8720181336041",
    # Numeric multi-use body cleansers whose source labels explicitly span
    # body, face, and/or hair despite a single-form taxonomy tag.
    "0072140810849",
    "3600523881598",
    "4058172585692",
    "4066447576696",
    "4305615647647",
    "4305615754635",
    "4311501677834",
    "8710447253779",
    "8710447329207",
    "8710847952869",
    "8710847953040",
    "8710847962301",
    "8710847962325",
    "8710908839252",
    "8711600477650",
    "8712561397551",
    "8714100016978",
    "8714100474990",
    "8717163648636",
    "8717163648643",
    "8717163668863",
    "8717644521120",
    "8720181136399",
    "8720181136405",
    "8720181607752",
    # Current product/source pages confirm hidden drug facts or multi-use
    # scope that is missing from the normalized display row.
    "0884486453617",
    "5410306882746",
    "3760194652948",
    "3600542298391",
    "8052862440090",
    "3256224363316",
    "0073930568964",
    "3760354680101",
    "0056594014169",
    "5901887016601",
    "8015700169317",
}

WEAK_NAME_ONLY_SIGNALS = {
    "base_makeup": {"blush", "blushes", "bronzer", "bronzers"},
}

MAKEUP_REMOVER_SIGNALS = (
    "makeup removers",
    "makeup remover",
    "make up removers",
    "make up remover",
    "make-up entferner",
    "make up entferner",
    "augen make up entferner",
    "demaquillant",
    "démaquillant",
    "micellar water",
    "cleansing water",
)

FACE_MASK_CLEANSER_CONFLICTS = (
    "cleansing foam",
    "face wash",
    "facial wash",
    "foam cleanser",
    "mud foam",
    "savon",
    "soap",
)

# Product names override noisy community category tags. These signals describe
# products that should not be surfaced as facial skincare even when a source
# contributor has attached a generic serum, cream, cleanser, or sunscreen tag.
NON_FACIAL_NAME_SIGNALS = (
    "after shave",
    "aftershave",
    "after sun",
    "baby",
    "babies",
    "beard",
    "body",
    "cellulite",
    "child",
    "children",
    "concealer",
    "crepey skin",
    "creepy skin",
    "deodorant",
    "diaper",
    "elbow",
    "eye",
    "eyes",
    "eyebrow",
    "eyelash",
    "feet",
    "foot",
    "foundation",
    "hair",
    "hand",
    "heel",
    "intimate",
    "kid",
    "kids",
    "lip",
    "mask",
    "nail",
    "pack",
    "patch",
    "perfume",
    "scalp",
    "shave",
    "stretch mark",
    "tattoo",
    "tinted moisturizer",
    "toilet cleaner",
    "vaginal",
    "wc reiniger",
    "bb cream",
    "cabelo",
    "cabello",
    "capelli",
    "cheveu",
    "cheveux",
    "ciało",
    "cialo",
    "corpo",
    "corporal",
    "corps",
    "cuerpo",
    "füße",
    "fusse",
    "fuss",
    "haar",
    "haare",
    "körper",
    "korper",
    "labbra",
    "levres",
    "lèvres",
    "mains",
    "maschera",
    "masque",
    "nagels",
    "nägel",
    "ongle",
    "ongles",
    "paznokci",
    "pied",
    "pieds",
    "regard",
    "unghie",
    "wlosy",
    "włosy",
)

NON_FACIAL_CATEGORY_SIGNALS = (
    "body",
    "deodorant",
    "eye",
    "eyes",
    "fragrance",
    "hair",
    "hand",
    "hygiene",
    "lip",
    "nail",
    "perfume",
    "shampoo",
    "soap",
    "cleaning product",
    "detergent",
    "household",
    "toilet cleaner",
    "yeux",
)

FACIAL_SCOPE_SIGNALS = (
    "face",
    "facial",
    "faccia",
    "gesicht",
    "gezicht",
    "gelaat",
    "rostro",
    "cara",
    "viso",
    "visage",
    "twarz",
    "twarzy",
    "ansikte",
    "ansigt",
    "kasvo",
    "oblicej",
    "obličej",
    "лицо",
    "얼굴",
    "面部",
    "脸",
)

AMBIGUOUS_NON_FACE_FORMS = (
    "body mist",
    "mist sunscreen",
    "sonnenmilch",
    "sollotion",
    "sun milk",
    "sun lotion",
    "sun spray",
    "sunscreen spray",
)

HAIR_COLOR_INGREDIENT_SIGNALS = (
    "2 amino 3 hydroxypyridine",
    "2 4 diaminophenoxyethanol",
    "p phenylenediamine",
    "toluene 2 5 diamine",
)

INGREDIENT_LABEL_NOISE_SIGNALS = (
    "amphoteric surfactants",
    "anionic surfactants",
    "avoid contact",
    "contains d limonene",
    "continued",
    "continua",
    "directions for use",
    "fabricado por",
    "for external use",
    "fortsetzung",
    "hecho en",
    "how to use",
    "made in",
    "manufactured by",
    "net weight",
    "para uso externo",
    "questions comments",
    "recycl",
    "refund",
    "www.",
)

PLACEHOLDER_TEXT = {
    "-",
    "?",
    "coming later",
    "kommer senere",
    "n/a",
    "na",
    "none",
    "not available",
    "please see photo",
    "see photo",
    "siehe bitte foto",
    "unknown",
    "unknown ingredients",
    "wird geladen",
}


class CatalogRefreshError(RuntimeError):
    """Raised when source data fails a catalog safety gate."""


@dataclass(frozen=True)
class SourceMetadata:
    mode: str
    source_url: str
    last_modified: str | None = None
    etag: str | None = None


@dataclass
class RefreshStats:
    lines_seen: int = 0
    malformed_json: int = 0
    non_object_rows: int = 0
    accepted_candidates: int = 0
    duplicate_rows: int = 0
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class RefreshResult:
    product_count: int
    csv_sha256: str
    manifest: dict[str, object]


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("\x00", " ").replace("\r", " ").replace("\n", " ").split())


def _normalized_search_text(value: object) -> str:
    text = _clean_text(value).lower()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"\b[a-z]{2,3}:", " ", text)
    text = re.sub(r"[_/\-]+", " ", text)
    return " ".join(text.split())


def _values(value: object) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,;|]", text) if item.strip()]


def _first_localized_text(record: dict[str, object], base_key: str) -> str:
    preferred_keys = (base_key, f"{base_key}_en", f"{base_key}_ko")
    for key in preferred_keys:
        text = _clean_text(record.get(key))
        if text:
            return text
    for key in sorted(record):
        if key.startswith(f"{base_key}_"):
            text = _clean_text(record.get(key))
            if text:
                return text
    return ""


def _valid_product_name(value: str) -> bool:
    normalized = _normalized_search_text(value)
    punctuation_stripped = " ".join(re.sub(r"[^\w]+", " ", normalized).split())
    if normalized in PLACEHOLDER_TEXT or punctuation_stripped in PLACEHOLDER_TEXT:
        return False
    return sum(character.isalnum() for character in normalized) >= 2


def _longest_localized_text(record: dict[str, object], base_key: str) -> str:
    candidates: list[str] = []
    for key in sorted(record):
        if key == base_key or key.startswith(f"{base_key}_"):
            text = _clean_text(record.get(key))
            if text:
                candidates.append(text)
    return max(candidates, key=lambda value: (len(value), value), default="")


def _stable_barcode(value: object) -> str | None:
    barcode = re.sub(r"\s+", "", _clean_text(value))
    if not barcode.isdigit() or len(barcode) not in {8, 12, 13, 14}:
        return None
    return barcode


def _brand(record: dict[str, object]) -> str:
    raw = _clean_text(record.get("brands"))
    if raw:
        return _clean_text(re.split(r"[,;|]", raw, maxsplit=1)[0])
    tags = _values(record.get("brands_tags"))
    if not tags:
        return ""
    tag = re.sub(r"^[a-z]{2,3}:", "", tags[0], flags=re.IGNORECASE)
    return _clean_text(tag.replace("-", " "))


def _looks_like_soap_cleanser(record: dict[str, object]) -> bool:
    ingredient_text = re.sub(
        r"[^a-z0-9]+",
        " ",
        _longest_localized_text(record, "ingredients_text").lower(),
    )
    fatty_acids = ("lauric acid", "myristic acid", "palmitic acid", "stearic acid")
    return "potassium hydroxide" in ingredient_text and sum(
        signal in ingredient_text for signal in fatty_acids
    ) >= 2


def _category(record: dict[str, object], name: str) -> str | None:
    normalized_name = _normalized_search_text(name)
    normalized_brands = _normalized_search_text(
        " ".join(
            [
                _clean_text(record.get("brands")),
                *_values(record.get("brands_tags")),
            ]
        )
    )
    normalized_generic_name = _normalized_search_text(
        _longest_localized_text(record, "generic_name")
    )
    category_values: list[str] = []
    for key in ("categories_tags", "categories_hierarchy", "categories"):
        category_values.extend(_values(record.get(key)))
    category_haystack = _normalized_search_text(" ".join(category_values))
    haystack = _normalized_search_text(" ".join([*category_values, name]))
    safety_haystack = _normalized_search_text(
        " ".join([name, normalized_generic_name, *category_values])
    )
    if not haystack:
        return None
    if any(_contains_phrase(safety_haystack, signal) for signal in HARD_EXCLUDED_NAME_SIGNALS):
        return None
    if any(
        _contains_phrase(normalized_brands, signal)
        for signal in HARD_EXCLUDED_BRAND_SIGNALS
    ):
        return None
    normalized_ingredients = _normalized_search_text(
        _longest_localized_text(record, "ingredients_text")
    )
    if any(
        _contains_phrase(normalized_ingredients, signal)
        for signal in HARD_EXCLUDED_INGREDIENT_SIGNALS
    ):
        return None
    barcode = _stable_barcode(record.get("code"))
    if barcode and barcode in KNOWN_SOURCE_EXCLUDED_BARCODES:
        return None
    if barcode and barcode in KNOWN_SOURCE_CATEGORY_CORRECTIONS:
        return KNOWN_SOURCE_CATEGORY_CORRECTIONS[barcode]
    if any(_contains_phrase(category_haystack, signal) for signal in HARD_EXCLUDED_CATEGORY_SIGNALS):
        return None
    name_has_hair_wash = any(
        _contains_phrase(normalized_name, signal)
        for signal in ("conditioner", "shampoo", "shampooing", "shampoing")
    )
    name_has_body_wash = any(
        _contains_phrase(normalized_name, signal)
        for signal in ("bath", "body", "douche", "duschgel", "shower", "shower gel")
    )
    if name_has_hair_wash and name_has_body_wash:
        return None

    has_facial_scope = any(_contains_phrase(haystack, signal) for signal in FACIAL_SCOPE_SIGNALS)
    has_facial_name = any(
        _contains_phrase(normalized_name, signal) for signal in ("face", "facial")
    )
    category_has_body_scope = _contains_phrase(category_haystack, "body")
    category_has_face_scope = any(
        _contains_phrase(category_haystack, signal) for signal in ("face", "facial")
    )
    # A facial form in the name must not override an explicitly body-scoped
    # source taxonomy. No single recommendation category can represent both.
    if has_facial_name and category_has_body_scope and not category_has_face_scope:
        return None

    # "Makeup remover" is a cleanser, not makeup. Require an explicit facial
    # signal or a well-known facial cleansing form to avoid household wipes.
    if any(_contains_phrase(haystack, signal) for signal in MAKEUP_REMOVER_SIGNALS):
        return "cleanser"
    if (
        any(_contains_phrase(normalized_name, signal) for signal in STRONG_CLEANSER_NAME_SIGNALS)
        and not any(
            _contains_phrase(normalized_name, signal)
            for signal in CLEANSER_OVERRIDE_BLOCKING_SIGNALS
        )
    ):
        return "cleanser"
    if (
        any(_contains_phrase(normalized_name, signal) for signal in STRONG_SUNSCREEN_NAME_SIGNALS)
        and not any(
            _contains_phrase(normalized_name, signal)
            for signal in ("body", "hair", "hand", "lip", "levres")
        )
    ):
        return "sunscreen"

    # An explicit form in the product name is more reliable than a conflicting
    # community taxonomy tag. This resolves shampoo-vs-shower-gel and
    # conditioner-vs-makeup errors without trusting a generic "beauty" label.
    for category, signals in SPECIALTY_CATEGORY_RULES:
        weak_signals = WEAK_NAME_ONLY_SIGNALS.get(category, set())
        if any(
            _contains_phrase(normalized_name, signal)
            for signal in signals
            if signal not in weak_signals
        ):
            return category
    if (
        _contains_phrase(normalized_name, "serum")
        and has_facial_scope
        and not any(
            _contains_phrase(normalized_name, signal)
            for signal in ("eye", "eyebrow", "eyelash", "hair", "lash", "lip", "scalp")
        )
    ):
        return "serum"

    category_has_hair_scope = _contains_phrase(category_haystack, "hair")
    category_has_body_cleanser_scope = any(
        _contains_phrase(category_haystack, signal)
        for signal in ("body wash", "shower gel", "showers and baths")
    )
    if category_has_face_scope and category_has_body_scope:
        return None
    if category_has_hair_scope and category_has_body_cleanser_scope:
        return None

    for category, signals in SPECIALTY_CATEGORY_RULES:
        if any(_contains_phrase(category_haystack, signal) for signal in signals):
            if category == "face_mask" and any(
                _contains_phrase(normalized_name, signal) for signal in FACE_MASK_CLEANSER_CONFLICTS
            ):
                return "cleanser" if has_facial_scope else None
            return category

    if any(_contains_phrase(normalized_name, signal) for signal in NON_FACIAL_NAME_SIGNALS):
        return None
    if not has_facial_name and any(signal in normalized_name for signal in AMBIGUOUS_NON_FACE_FORMS):
        return None
    if not has_facial_name and _contains_phrase(normalized_name, "soap"):
        return None
    if any(_contains_phrase(category_haystack, signal) for signal in NON_FACIAL_CATEGORY_SIGNALS):
        return None

    if has_facial_scope and _looks_like_soap_cleanser(record):
        return "cleanser"
    for category, signals in CORE_CATEGORY_RULES:
        if any(_contains_phrase(haystack, signal) for signal in signals):
            # Toner is a facial-care form in the beauty catalog even when the
            # contributor omitted an explicit "face" qualifier. Other forms
            # must carry an explicit facial-scope signal to avoid body, hair,
            # nail, and general sun-care false positives.
            if category != "toner" and not has_facial_scope:
                return None
            if category == "toner":
                ingredient_haystack = re.sub(
                    r"[^a-z0-9]+",
                    " ",
                    _longest_localized_text(record, "ingredients_text").lower(),
                )
                ingredient_haystack = " ".join(ingredient_haystack.split())
                if any(signal in ingredient_haystack for signal in HAIR_COLOR_INGREDIENT_SIGNALS):
                    return None
            return category
    return None


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalized_search_text(phrase)
    if not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", text) is not None


def _ingredient_text(record: dict[str, object]) -> str:
    text = _longest_localized_text(record, "ingredients_text")
    if not text:
        return ""
    markers = list(
        re.finditer(
            r"\b(?:ingredients?|ingredientes?|ingredienti|ingrédients?|inhaltsstoffe|inci)\s*:\s*",
            text,
            flags=re.IGNORECASE,
        )
    )
    if markers:
        text = text[markers[-1].end() :]
    end_marker = re.search(
        r"\b(?:made in|hecho en|fabricado(?: y exportado)? por|manufactured by|for external use|para uso externo)\b",
        text,
        flags=re.IGNORECASE,
    )
    if end_marker:
        text = text[: end_marker.start()]
    normalized = _normalized_search_text(text)
    if normalized in PLACEHOLDER_TEXT or len(normalized) < 3:
        return ""
    return text


def _split_ingredients(text: str) -> list[str]:
    """Split an INCI list without breaking commas inside parentheses."""

    values: list[str] = []
    current: list[str] = []
    depth = 0
    for index, character in enumerate(text):
        if character in "([":
            depth += 1
        elif character in ")]" and depth:
            depth -= 1
        numeric_comma = (
            character == ","
            and index > 0
            and index + 1 < len(text)
            and text[index - 1].isdigit()
            and text[index + 1].isdigit()
        )
        period_separator = (
            character == "."
            and index + 1 < len(text)
            and text[index + 1].isspace()
        )
        if (character in {",", ";", "\n", "|", "•", "·"} or period_separator) and depth == 0 and not numeric_comma:
            value = _clean_text("".join(current))
            if value:
                values.append(value)
            current = []
        else:
            current.append(character)
    value = _clean_text("".join(current))
    if value:
        values.append(value)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduplicated.append(value)
    return deduplicated


def _ingredient_quality_reason(ingredients: list[str]) -> str | None:
    if len(ingredients) < 3:
        return "too_few_ingredients"
    if len(ingredients) > 120:
        return "too_many_ingredients"
    if any(len(ingredient) > 180 for ingredient in ingredients):
        return "malformed_ingredient_text"
    normalized = _normalized_search_text(" ".join(ingredients))
    if any(signal in normalized for signal in INGREDIENT_LABEL_NOISE_SIGNALS):
        return "packaging_text_in_ingredients"
    return None


def _source_updated_at(record: dict[str, object]) -> str:
    for key in ("last_modified_t", "last_updated_t"):
        value = record.get(key)
        try:
            timestamp = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            timestamp = 0.0
        if timestamp > 0:
            return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key in ("last_modified_datetime", "last_updated_datetime"):
        value = _clean_text(record.get(key))
        if value:
            try:
                return _canonical_timestamp(value)
            except ValueError:
                continue
    return ""


def _source_record_age_days(source_updated_at: str, *, as_of: str) -> int | None:
    if not source_updated_at:
        return None
    try:
        updated = dt.datetime.fromisoformat(source_updated_at.replace("Z", "+00:00"))
        reference = dt.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=dt.timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=dt.timezone.utc)
    return max(
        0,
        (
            reference.astimezone(dt.timezone.utc)
            - updated.astimezone(dt.timezone.utc)
        ).days,
    )


def _https_url(value: object) -> str:
    url = _clean_text(value)
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith("https://") else ""


def _image_product_path(barcode: str) -> str:
    normalized = barcode.zfill(13) if len(barcode) < 13 else barcode
    return "/".join((normalized[:3], normalized[3:6], normalized[6:9], normalized[9:]))


def _front_image_url(record: dict[str, object], barcode: str) -> str:
    direct = _https_url(record.get("image_front_url") or record.get("image_url"))
    if direct:
        return direct

    images = record.get("images")
    if not isinstance(images, dict):
        return ""
    language = _clean_text(record.get("lc") or record.get("lang")).lower()
    preferred = [f"front_{language}" if language else "", "front_en", "front"]
    front_keys = [key for key in images if isinstance(key, str) and (key == "front" or key.startswith("front_"))]
    ordered_keys = [key for key in preferred if key in images]
    ordered_keys.extend(key for key in sorted(front_keys) if key not in ordered_keys)
    for key in ordered_keys:
        metadata = images.get(key)
        if not isinstance(metadata, dict):
            continue
        revision = _clean_text(metadata.get("rev"))
        sizes = metadata.get("sizes")
        if not revision or not isinstance(sizes, dict):
            continue
        size = "400" if "400" in sizes else "full" if "full" in sizes else ""
        if not size:
            continue
        return f"{IMAGE_BASE_URL}/{_image_product_path(barcode)}/{key}.{revision}.{size}.jpg"
    return ""


def _normalize_record(
    record: dict[str, object],
    *,
    fetched_at: str,
) -> tuple[dict[str, str] | None, str | None]:
    product_type = _clean_text(record.get("product_type")).lower()
    if product_type and product_type != "beauty":
        return None, "wrong_product_type"

    barcode = _stable_barcode(record.get("code") or record.get("_id"))
    if barcode is None:
        return None, "invalid_barcode"

    name = _first_localized_text(record, "product_name")
    if not name:
        return None, "missing_name"
    if not _valid_product_name(name):
        return None, "invalid_name"
    brand = _brand(record)
    if not brand:
        return None, "missing_brand"
    category = _category(record, name)
    if category is None:
        return None, "unsupported_category"
    source_updated_at = _source_updated_at(record)
    source_age_days = _source_record_age_days(source_updated_at, as_of=fetched_at)
    if source_age_days is None:
        return None, "missing_source_updated_at"
    if source_age_days > MAX_SOURCE_AGE_DAYS:
        return None, "stale_source_record"
    ingredient_text = _ingredient_text(record)
    if not ingredient_text:
        return None, "missing_ingredients"
    normalized_ingredient_text = _normalized_search_text(ingredient_text)
    if category in LEAVE_ON_CATEGORIES and any(
        _contains_phrase(normalized_ingredient_text, signal)
        for signal in LEAVE_ON_PROHIBITED_INGREDIENT_SIGNALS
    ):
        return None, "prohibited_leave_on_ingredient"
    ingredients = _split_ingredients(ingredient_text)
    if not ingredients:
        return None, "missing_ingredients"
    ingredient_quality_reason = _ingredient_quality_reason(ingredients)
    if ingredient_quality_reason:
        return None, ingredient_quality_reason
    image_url = _front_image_url(record, barcode)
    if not image_url:
        return None, "missing_image"

    source_url = f"{PRODUCT_BASE_URL}/{barcode}"
    return (
        {
            "id": f"open-beauty-facts-{barcode}",
            "name": name,
            "brand": brand,
            "category": category,
            # Open Beauty Facts country tags describe sale markets, not a
            # reliable manufacturing origin. Do not expose them as origin.
            "country": "Unknown",
            "ingredients": "|".join(ingredients),
            "claims": "",
            "source_url": source_url,
            "ingredient_source_url": source_url,
            "verified_at": source_updated_at,
            "image_url": image_url,
            "image_verified_source": source_url,
            "image_source_type": "open_beauty_facts",
            "image_confidence": "reported",
            "image_view_type": "single_product",
            "official_url": "",
            "catalog_source": "open_beauty_facts",
            "source_product_id": barcode,
            "source_updated_at": source_updated_at,
            # Snapshot retrieval time belongs in the manifest. Keeping it out
            # of every row prevents an unchanged daily dump timestamp from
            # rewriting the entire CSV and obscuring meaningful data diffs.
            "fetched_at": "",
            "ingredient_status": "reported",
            "recommendation_tier": "eligible",
            "data_license": DATA_LICENSE_LABEL,
            "data_attribution_url": ATTRIBUTION_URL,
        },
        None,
    )


def _canonical_timestamp(value: str | None) -> str:
    if not value:
        now = dt.datetime.now(dt.timezone.utc)
    else:
        normalized = value.strip().replace("Z", "+00:00")
        now = dt.datetime.fromisoformat(normalized)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        now = now.astimezone(dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def _open_jsonl_source(
    *,
    input_path: Path | None,
    source_url: str,
    timeout_seconds: float,
) -> Iterator[tuple[TextIO, SourceMetadata]]:
    with contextlib.ExitStack() as stack:
        if input_path is not None:
            if not input_path.is_file():
                raise CatalogRefreshError(f"Local catalog fixture does not exist: {input_path}")
            raw = stack.enter_context(input_path.open("rb"))
            metadata = SourceMetadata(mode="local_fixture", source_url=source_url)
            compressed = input_path.suffix.lower() == ".gz"
        else:
            request = urllib.request.Request(source_url, headers={"User-Agent": USER_AGENT})
            try:
                response = stack.enter_context(urllib.request.urlopen(request, timeout=timeout_seconds))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise CatalogRefreshError(f"Unable to open Open Beauty Facts dump: {exc}") from exc
            raw = response
            metadata = SourceMetadata(
                mode="remote_dump",
                source_url=source_url,
                last_modified=_http_timestamp(response.headers.get("Last-Modified")),
                etag=response.headers.get("ETag"),
            )
            compressed = source_url.lower().endswith(".gz") or "gzip" in response.headers.get("Content-Type", "").lower()

        binary = gzip.GzipFile(fileobj=raw, mode="rb") if compressed else raw
        if binary is not raw:
            stack.callback(binary.close)
        text_stream = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")
        stack.callback(text_stream.detach)
        yield text_stream, metadata


def _row_rank(row: dict[str, str]) -> tuple[str, str]:
    # ISO UTC timestamps sort lexicographically.  The JSON tie-breaker makes a
    # duplicate choice stable even if the input dump changes line order.
    return row["source_updated_at"], json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_previous_count(csv_path: Path, manifest_path: Path) -> int | None:
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8")).get("product_count")
            if isinstance(value, int) and value >= 0:
                return value
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    if not csv_path.is_file():
        return None
    try:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return None


def _read_previous_category_counts(manifest_path: Path) -> dict[str, int]:
    if not manifest_path.is_file():
        return {}
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8")).get("category_counts", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(category): count
        for category, count in value.items()
        if isinstance(count, int) and count >= 0
    }


def _read_previous_max_source_age_days(manifest_path: Path) -> int | None:
    if not manifest_path.is_file():
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        age_days = value.get("safety_thresholds", {}).get("max_source_age_days")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return age_days if isinstance(age_days, int) and age_days > 0 else None


def _validate_threshold(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise CatalogRefreshError(f"{name} must be between 0 and 1")


def _record_freshness(rows: list[dict[str, str]], *, as_of: str) -> dict[str, object]:
    reference = dt.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    dated: list[tuple[dt.datetime, int]] = []
    for row in rows:
        value = row.get("source_updated_at", "")
        if not value:
            continue
        try:
            updated = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=dt.timezone.utc)
        updated = updated.astimezone(dt.timezone.utc)
        dated.append((updated, max(0, (reference - updated).days)))

    ages = [age for _, age in dated]
    return {
        "as_of": as_of,
        "dated_products": len(dated),
        "missing_source_updated_at": len(rows) - len(dated),
        "newest_source_updated_at": max((value for value, _ in dated), default=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if dated
        else None,
        "oldest_source_updated_at": min((value for value, _ in dated), default=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if dated
        else None,
        "median_age_days": int(statistics.median(ages)) if ages else None,
        "updated_within_365_days": sum(age <= 365 for age in ages),
        "older_than_365_days": sum(age > 365 for age in ages),
        "older_than_3_years": sum(age > 365 * 3 for age in ages),
        "older_than_5_years": sum(age > 365 * 5 for age in ages),
    }


def _required_categories_for_validation(
    previous_category_counts: dict[str, int],
) -> tuple[str, ...]:
    has_expanded_history = any(
        previous_category_counts.get(category, 0)
        for category in (*LEGACY_CATEGORY_FAMILIES, *PUBLIC_RECOMMENDATION_CATEGORIES)
        if category not in REQUIRED_CORE_CATEGORIES
    )
    return PUBLIC_RECOMMENDATION_CATEGORIES if has_expanded_history else REQUIRED_CORE_CATEGORIES


def _validate_catalog(
    *,
    rows: list[dict[str, str]],
    stats: RefreshStats,
    previous_count: int | None,
    previous_category_counts: dict[str, int],
    min_products: int,
    max_drop_ratio: float,
    max_duplicate_ratio: float,
    max_malformed_ratio: float,
    migration_max_drop_ratio: float | None = None,
) -> None:
    _validate_threshold("max_drop_ratio", max_drop_ratio)
    _validate_threshold("max_duplicate_ratio", max_duplicate_ratio)
    _validate_threshold("max_malformed_ratio", max_malformed_ratio)
    if migration_max_drop_ratio is not None:
        _validate_threshold("migration_max_drop_ratio", migration_max_drop_ratio)
    effective_max_drop_ratio = max(
        max_drop_ratio,
        migration_max_drop_ratio or 0.0,
    )
    if min_products < 1:
        raise CatalogRefreshError("min_products must be at least 1")
    if stats.lines_seen == 0:
        raise CatalogRefreshError("The source dump contained no JSONL records")
    if len(rows) < min_products:
        raise CatalogRefreshError(f"Catalog has {len(rows)} products; minimum is {min_products}")

    candidate_total = stats.accepted_candidates + stats.duplicate_rows
    duplicate_ratio = stats.duplicate_rows / candidate_total if candidate_total else 0.0
    if duplicate_ratio > max_duplicate_ratio:
        raise CatalogRefreshError(
            f"Duplicate barcode ratio {duplicate_ratio:.3f} exceeds maximum {max_duplicate_ratio:.3f}"
        )
    malformed_ratio = stats.malformed_json / stats.lines_seen
    if malformed_ratio > max_malformed_ratio:
        raise CatalogRefreshError(
            f"Malformed JSON ratio {malformed_ratio:.3f} exceeds maximum {max_malformed_ratio:.3f}"
        )
    if previous_count:
        minimum_from_previous = math.ceil(
            previous_count * (1.0 - effective_max_drop_ratio)
        )
        if len(rows) < minimum_from_previous:
            drop_ratio = 1.0 - (len(rows) / previous_count)
            raise CatalogRefreshError(
                f"Catalog dropped from {previous_count} to {len(rows)} products "
                f"({drop_ratio:.1%}); maximum allowed drop is {effective_max_drop_ratio:.1%}"
            )

    current_category_counts = Counter(row["category"] for row in rows)
    for category in _required_categories_for_validation(previous_category_counts):
        current_count = current_category_counts[category]
        if current_count < 1:
            raise CatalogRefreshError(f"Catalog category {category} has no eligible products")
    for category, previous_category_count in previous_category_counts.items():
        if previous_category_count:
            migrated_categories = LEGACY_CATEGORY_FAMILIES.get(category)
            current_count = (
                sum(current_category_counts[value] for value in migrated_categories)
                if migrated_categories
                else current_category_counts[category]
            )
            allowed_drop_ratio = (
                LEGACY_CATEGORY_MIGRATION_MAX_DROP_RATIO
                if migrated_categories
                else max_drop_ratio
            )
            allowed_drop_ratio = max(
                allowed_drop_ratio,
                migration_max_drop_ratio or 0.0,
            )
            minimum_from_previous = math.ceil(
                previous_category_count * (1.0 - allowed_drop_ratio)
            )
            if current_count < minimum_from_previous:
                raise CatalogRefreshError(
                    f"Catalog category {category} dropped from {previous_category_count} to {current_count}; "
                    f"maximum allowed drop is {allowed_drop_ratio:.1%}"
                )


def _fsync_text_file(handle: TextIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _temporary_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, value = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(descriptor)
    return Path(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_outputs_atomically(
    *,
    rows: list[dict[str, str]],
    manifest: dict[str, object],
    csv_path: Path,
    manifest_path: Path,
) -> str:
    csv_temp = _temporary_path(csv_path)
    manifest_temp = _temporary_path(manifest_path)
    try:
        with csv_temp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            _fsync_text_file(handle)
        csv_sha256 = _sha256(csv_temp)
        manifest["csv_sha256"] = csv_sha256
        with manifest_temp.open("w", encoding="utf-8", newline="") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            _fsync_text_file(handle)

        # Both complete temporary files have passed validation before either
        # public path is replaced.  os.replace is atomic for each destination.
        os.replace(csv_temp, csv_path)
        os.replace(manifest_temp, manifest_path)
        return csv_sha256
    finally:
        csv_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)


def refresh_catalog(
    *,
    csv_path: Path,
    manifest_path: Path,
    input_path: Path | None = None,
    source_url: str = DEFAULT_DUMP_URL,
    fetched_at: str | None = None,
    min_products: int = 100,
    max_drop_ratio: float = 0.25,
    max_duplicate_ratio: float = 0.05,
    max_malformed_ratio: float = 0.001,
    timeout_seconds: float = 60.0,
) -> RefreshResult:
    rows_by_barcode: dict[str, dict[str, str]] = {}
    stats = RefreshStats()

    with _open_jsonl_source(
        input_path=input_path,
        source_url=source_url,
        timeout_seconds=timeout_seconds,
    ) as (stream, source_metadata):
        # The remote dump's Last-Modified timestamp makes repeated processing
        # of the same snapshot byte-for-byte deterministic.  Local fixtures
        # can supply --fetched-at explicitly, as the focused tests do.
        fetched_at_value = _canonical_timestamp(fetched_at or source_metadata.last_modified)
        for raw_line in stream:
            if not raw_line.strip():
                continue
            stats.lines_seen += 1
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError:
                stats.malformed_json += 1
                continue
            if not isinstance(value, dict):
                stats.non_object_rows += 1
                continue
            row, reason = _normalize_record(value, fetched_at=fetched_at_value)
            if row is None:
                stats.skipped[reason or "unknown"] += 1
                continue

            barcode = row["source_product_id"]
            existing = rows_by_barcode.get(barcode)
            if existing is not None:
                stats.duplicate_rows += 1
                if _row_rank(row) > _row_rank(existing):
                    rows_by_barcode[barcode] = row
                continue
            rows_by_barcode[barcode] = row
            stats.accepted_candidates += 1

    rows = sorted(rows_by_barcode.values(), key=lambda row: row["id"])
    previous_count = _read_previous_count(csv_path, manifest_path)
    previous_category_counts = _read_previous_category_counts(manifest_path)
    previous_max_source_age_days = _read_previous_max_source_age_days(manifest_path)
    migration_max_drop_ratio = (
        FRESHNESS_POLICY_MIGRATION_MAX_DROP_RATIO
        if previous_count and previous_max_source_age_days != MAX_SOURCE_AGE_DAYS
        else None
    )
    _validate_catalog(
        rows=rows,
        stats=stats,
        previous_count=previous_count,
        previous_category_counts=previous_category_counts,
        min_products=min_products,
        max_drop_ratio=max_drop_ratio,
        max_duplicate_ratio=max_duplicate_ratio,
        max_malformed_ratio=max_malformed_ratio,
        migration_max_drop_ratio=migration_max_drop_ratio,
    )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "catalog_source": "open_beauty_facts",
        "source_dump_url": source_metadata.source_url,
        "source_mode": source_metadata.mode,
        "source_last_modified": source_metadata.last_modified,
        "source_etag": source_metadata.etag,
        "generated_at": fetched_at_value,
        "product_count": len(rows),
        "previous_product_count": previous_count,
        "category_counts": dict(sorted(Counter(row["category"] for row in rows).items())),
        "country_counts": dict(sorted(Counter(row["country"] for row in rows).items())),
        "record_freshness": _record_freshness(rows, as_of=fetched_at_value),
        "processing": {
            "lines_seen": stats.lines_seen,
            "malformed_json": stats.malformed_json,
            "non_object_rows": stats.non_object_rows,
            "accepted_candidates": stats.accepted_candidates,
            "duplicate_rows": stats.duplicate_rows,
            "skipped": dict(sorted(stats.skipped.items())),
        },
        "safety_thresholds": {
            "min_products": min_products,
            "max_drop_ratio": max_drop_ratio,
            "max_duplicate_ratio": max_duplicate_ratio,
            "max_malformed_ratio": max_malformed_ratio,
            "minimum_products_per_required_category": 1,
            "required_categories": list(
                _required_categories_for_validation(previous_category_counts)
            ),
            "legacy_category_migration_max_drop_ratio": LEGACY_CATEGORY_MIGRATION_MAX_DROP_RATIO,
            "freshness_policy_migration_max_drop_ratio": FRESHNESS_POLICY_MIGRATION_MAX_DROP_RATIO,
            "max_source_age_days": MAX_SOURCE_AGE_DAYS,
        },
        "licenses": {
            "database": {
                "id": DATABASE_LICENSE_ID,
                "name": "Open Database License 1.0",
                "url": DATABASE_LICENSE_URL,
            },
            "product_images": {
                "id": IMAGE_LICENSE_ID,
                "name": "Creative Commons Attribution-ShareAlike 3.0",
                "url": IMAGE_LICENSE_URL,
            },
        },
        "attribution": {
            "name": "Open Beauty Facts",
            "url": ATTRIBUTION_URL,
            "notice": (
                "Contains information from Open Beauty Facts, licensed under ODbL 1.0. "
                "Open Beauty Facts product images are licensed under CC BY-SA 3.0."
            ),
        },
        "data_quality": {
            "ingredient_status": "reported",
            "recommendation_tier": "eligible",
            "notice": (
                "Ingredient lists are community-reported label transcriptions and are not guaranteed complete. "
                "Only records updated within the configured source-age limit are eligible, but current packaging "
                "must still be verified; allergy and avoid-ingredient recommendations must exclude these rows."
            ),
        },
        "columns": list(CATALOG_COLUMNS),
    }
    csv_sha256 = _write_outputs_atomically(
        rows=rows,
        manifest=manifest,
        csv_path=csv_path,
        manifest_path=manifest_path,
    )
    return RefreshResult(product_count=len(rows), csv_sha256=csv_sha256, manifest=manifest)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Local .jsonl or .jsonl.gz fixture; skips network access")
    parser.add_argument("--source-url", default=DEFAULT_DUMP_URL, help="Official JSONL gzip dump URL")
    parser.add_argument("--output", type=Path, default=Path("data/catalog_generated.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("data/catalog_manifest.json"))
    parser.add_argument("--fetched-at", help="Fixed ISO-8601 timestamp, useful for deterministic tests")
    parser.add_argument("--min-products", type=int, default=100)
    parser.add_argument("--max-drop-ratio", type=float, default=0.25)
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.05)
    parser.add_argument("--max-malformed-ratio", type=float, default=0.001)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = refresh_catalog(
            csv_path=args.output,
            manifest_path=args.manifest,
            input_path=args.input,
            source_url=args.source_url,
            fetched_at=args.fetched_at,
            min_products=args.min_products,
            max_drop_ratio=args.max_drop_ratio,
            max_duplicate_ratio=args.max_duplicate_ratio,
            max_malformed_ratio=args.max_malformed_ratio,
            timeout_seconds=args.timeout_seconds,
        )
    except (CatalogRefreshError, OSError, ValueError) as exc:
        print(f"catalog refresh failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "product_count": result.product_count,
                "csv_sha256": result.csv_sha256,
                "output": str(args.output),
                "manifest": str(args.manifest),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
