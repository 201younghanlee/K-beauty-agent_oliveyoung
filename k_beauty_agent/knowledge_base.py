from __future__ import annotations

import re

from .models import EvidenceLevel, IngredientEvidence

EVIDENCE_WEIGHT: dict[EvidenceLevel, float] = {
    "high": 3.0,
    "moderate": 2.0,
    "low": 0.75,
    "insufficient": 0.0,
}

INGREDIENT_EVIDENCE: tuple[IngredientEvidence, ...] = (
    IngredientEvidence(
        name="niacinamide",
        aliases=("vitamin b3", "nicotinamide"),
        supports=("oil_control", "barrier_support", "pores", "hyperpigmentation"),
        suitable_for=("oily", "combination", "dry", "normal"),
        cautions=("May sting on a damaged barrier at higher percentages.",),
        evidence_level="moderate",
        rationale="Niacinamide has human-use evidence for barrier support, sebum regulation, and tone appearance.",
    ),
    IngredientEvidence(
        name="salicylic acid",
        aliases=("bha", "beta hydroxy acid", "betaine salicylate"),
        supports=("oil_control", "acne", "clogged_pores", "exfoliation"),
        suitable_for=("oily", "combination"),
        cautions=(
            "Can irritate sensitive or compromised skin.",
            "Avoid if the user reports aspirin/salicylate allergy.",
        ),
        evidence_level="high",
        rationale="Salicylic acid is an established comedolytic exfoliant for oily and acne-prone skin.",
    ),
    IngredientEvidence(
        name="green tea extract",
        aliases=("camellia sinensis", "green tea"),
        supports=("oil_control", "redness", "antioxidant_support"),
        suitable_for=("oily", "combination", "sensitive", "normal"),
        cautions=("Botanical extracts can still trigger individual sensitivity.",),
        evidence_level="moderate",
        rationale="Green tea polyphenols have supportive evidence for soothing and sebum-related concerns.",
    ),
    IngredientEvidence(
        name="panthenol",
        aliases=("pro-vitamin b5", "dexpanthenol"),
        supports=("barrier_support", "hydration", "redness"),
        suitable_for=("dry", "sensitive", "combination", "normal"),
        cautions=(),
        evidence_level="moderate",
        rationale="Panthenol is a well-established humectant and skin-conditioning ingredient.",
    ),
    IngredientEvidence(
        name="ceramide np",
        aliases=("ceramide", "ceramides", "ceramide ap", "ceramide eop"),
        supports=("barrier_support", "hydration", "dryness"),
        suitable_for=("dry", "sensitive", "normal", "combination"),
        cautions=(),
        evidence_level="high",
        rationale="Ceramides are core barrier lipids and are appropriate when barrier support is a goal.",
    ),
    IngredientEvidence(
        name="glycerin",
        aliases=("glycerol",),
        supports=("hydration", "barrier_support", "dryness"),
        suitable_for=("dry", "sensitive", "normal", "combination", "oily"),
        cautions=(),
        evidence_level="high",
        rationale="Glycerin is a widely supported humectant for hydration across skin types.",
    ),
    IngredientEvidence(
        name="hyaluronic acid",
        aliases=("sodium hyaluronate", "hydrolyzed hyaluronic acid"),
        supports=("hydration", "plumping"),
        suitable_for=("dry", "normal", "combination", "oily", "sensitive"),
        cautions=("Can feel tight if used without an occlusive layer in very dry climates.",),
        evidence_level="moderate",
        rationale="Hyaluronic acid and its salts are common humectants with supportive hydration evidence.",
    ),
    IngredientEvidence(
        name="retinol",
        aliases=("retinal", "retinaldehyde", "retinyl propionate"),
        supports=("anti_aging", "acne", "texture"),
        suitable_for=("normal", "oily", "combination"),
        cautions=(
            "Avoid during pregnancy or nursing unless cleared by a clinician.",
            "Can irritate sensitive skin and requires sunscreen use.",
        ),
        evidence_level="high",
        rationale="Topical retinoids have strong evidence for acne and photoaging-related texture concerns.",
    ),
    IngredientEvidence(
        name="azelaic acid",
        aliases=("azelaic",),
        supports=("redness", "acne", "hyperpigmentation"),
        suitable_for=("sensitive", "oily", "combination", "normal"),
        cautions=("May tingle or dry the skin at first.",),
        evidence_level="high",
        rationale="Azelaic acid has clinical use for acne, redness-prone skin, and uneven tone.",
    ),
    IngredientEvidence(
        name="centella asiatica",
        aliases=("cica", "madecassoside", "asiaticoside"),
        supports=("redness", "barrier_support", "soothing"),
        suitable_for=("sensitive", "dry", "combination", "normal"),
        cautions=("Botanical derivatives can still cause individual reactions.",),
        evidence_level="moderate",
        rationale="Centella derivatives have supportive data for soothing and barrier-adjacent benefits.",
    ),
    IngredientEvidence(
        name="zinc pca",
        aliases=(),
        supports=("oil_control", "acne"),
        suitable_for=("oily", "combination"),
        cautions=("Can feel drying for already dry skin.",),
        evidence_level="moderate",
        rationale="Zinc PCA is commonly used for sebum-prone skin and has supportive mechanistic evidence.",
    ),
    IngredientEvidence(
        name="fragrance",
        aliases=("parfum", "perfume", "essential oil", "limonene", "linalool"),
        supports=(),
        suitable_for=(),
        cautions=("Fragrance is a common avoid flag for sensitive or allergy-prone users.",),
        evidence_level="insufficient",
        rationale="Fragrance does not provide necessary skin-care benefit and may increase irritation risk.",
    ),
)


def normalize_token(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def evidence_by_alias() -> dict[str, IngredientEvidence]:
    index: dict[str, IngredientEvidence] = {}
    for item in INGREDIENT_EVIDENCE:
        index[normalize_token(item.name)] = item
        for alias in item.aliases:
            index[normalize_token(alias)] = item
    return index


def find_evidence_for_ingredient(ingredient: str) -> IngredientEvidence | None:
    normalized = normalize_token(ingredient)
    index = evidence_by_alias()
    if normalized in index:
        return index[normalized]
    for alias, evidence in sorted(index.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized):
            return evidence
    return None
