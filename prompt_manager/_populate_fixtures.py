"""One-shot script to seed test_fixtures into every prompt JSON.

Idempotent: re-running replaces the test_fixtures array but leaves
prompt content, versions[], and validation schema untouched.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from prompt_manager import PromptManager, TestFixture

ROOT = Path(__file__).parent.parent
pm = PromptManager(ROOT / "prompts")


FIXTURES: dict[tuple[str, str], list[TestFixture]] = {
    # ===== email-tracker / extraction =====
    ("email-tracker", "extraction"): [
        TestFixture(
            id="vitol-clean",
            label="Vitol — clean text email",
            description="Happy path. Standard plain-text confirmation from Vitol, all fields visible.",
            expected_outcome="pass",
            expected_notes="All 7 fields extracted, broker='Vitol Trading S.A.', volume=45000, price=82.45",
            input="From: deals@vitol-trading.com\nSubject: POTWIERDZENIE TRANSAKCJI - VT-2026-04821\n\nDear Trading Desk,\n\nReference:    VT-2026-04821\nTrade Date:   25-May-2026\nProduct:      Brent Crude Oil\nVolume:       45,000 MT\nPrice:        82.45 USD per barrel\nDelivery:     FOB Rotterdam, June 2026\n\nVitol Trading S.A.",
        ),
        TestFixture(
            id="mercuria-tbd-price",
            label="Mercuria — price TBD (should auto-reject)",
            description="Tests null-over-guessing rule. Price marked TBD; LLM must return null; validator must reject.",
            expected_outcome="fail_validation",
            expected_notes="price_usd is None → validator complaints 'price_usd nie jest liczbą'",
            input="From: deals-desk@mercuria-energy.com\nSubject: POTWIERDZENIE TRANSAKCJI ME/2026/00725\n\nConfirmation - PRICE TBD:\n\nME/2026/00725 | 28-05-2026 | Naphtha | 22,000 MT | TBD - awaiting benchmark | CIF Rotterdam | September 2026\n\nMercuria Energy Trading",
        ),
        TestFixture(
            id="trafigura-table-format",
            label="Trafigura — HTML table style, DD/MM/YYYY date",
            description="Different broker layout (table) and European date format. LLM must convert DD/MM/YYYY → YYYY-MM-DD.",
            expected_outcome="pass",
            expected_notes="trade_date should be '2026-05-25' (converted from '25/05/2026')",
            input="TRAFIGURA MARKETS LTD - DEAL CONFIRMATION\n\nConfirmation ID | TFG-29384\nTrade Date      | 25/05/2026\nCommodity       | Natural Gas (Henry Hub)\nQuantity        | 120,000 MT\nUnit Price      | USD 3.85 / MMBtu\nDelivery Window | July 2026",
        ),
    ],

    # ===== ecommerce-ops / price_anomaly =====
    ("ecommerce-ops", "price_anomaly"): [
        TestFixture(
            id="leather-case-under-phone",
            label="Leather Case under flagship phone (classic anomaly)",
            description="Accessory offer indexed under main product — drags reference price from 8999 → 299 SEK.",
            expected_outcome="pass",
            expected_notes="severity=HIGH, reason about accessory mismatch",
            input='{"candidates": [{"offer_id": "OFF-NPX12P-XX", "offer_name": "Leather Case for Nordic Phone X12", "product_id": "NPX12P", "product_name": "Nordic Phone X12 Pro", "offer_price": 299.0, "product_base_price": 8999.0, "currency": "SEK"}]}',
        ),
        TestFixture(
            id="legitimate-promo",
            label="Legitimate Black Friday promo",
            description="Same product, ~50% off — a real promotion, not an anomaly.",
            expected_outcome="pass",
            expected_notes="severity=LOW, LLM should recognize semantic match despite price gap",
            input='{"candidates": [{"offer_id": "OFF-NPX12P-01", "offer_name": "Nordic Phone X12 Pro - Black Friday Promo", "product_id": "NPX12P", "product_name": "Nordic Phone X12 Pro", "offer_price": 4499.0, "product_base_price": 8999.0, "currency": "SEK"}]}',
        ),
        TestFixture(
            id="mixed-candidates",
            label="Mixed batch — accessory + storage variant",
            description="Two candidates: a screen protector mismatch AND a legit 256GB variant. Expect two different severities.",
            expected_outcome="pass",
            expected_notes="Two results: first HIGH (accessory), second LOW (legitimate variant)",
            input='{"candidates": [{"offer_id": "OFF-1", "offer_name": "Screen Protector for Fjord Tab 10", "product_id": "FJTAB10", "product_name": "Fjord Tab 10 Plus", "offer_price": 49.0, "product_base_price": 4499.0, "currency": "NOK"}, {"offer_id": "OFF-2", "offer_name": "Fjord Tab 10 Plus 256GB", "product_id": "FJTAB10", "product_name": "Fjord Tab 10 Plus", "offer_price": 3990.0, "product_base_price": 4499.0, "currency": "NOK"}]}',
        ),
    ],

    # ===== ecommerce-ops / deals_anomaly =====
    ("ecommerce-ops", "deals_anomaly"): [
        TestFixture(
            id="bike-85pct-vs-laptop-20pct",
            label="LapBike 85% off + Viking Laptop 20% off",
            description="Mix of suspicious (85%) and legitimate (20%) deals. Tests assessment quality.",
            expected_outcome="pass",
            expected_notes="LapBike assessed as likely pricing error, Viking Laptop as normal promotion",
            input='{"deals": [{"product_id": "LAPBIKE", "product_name": "LapBike Carbon Road", "original_price": 18990.0, "deal_price": 2849.0, "discount_pct": 85.0, "currency": "SEK"}, {"product_id": "VIKLAP", "product_name": "Viking Laptop Ultra 15", "original_price": 14990.0, "deal_price": 11990.0, "discount_pct": 20.0, "currency": "NOK"}]}',
        ),
        TestFixture(
            id="decimal-place-error-99pct",
            label="99% off — decimal shift error",
            description="1799 SEK earbuds 'discounted' to 17.99 SEK — classic decimal-point pricing bug.",
            expected_outcome="pass",
            expected_notes="LLM should identify this as decimal shift / data import error",
            input='{"deals": [{"product_id": "AURBUDS", "product_name": "AuroraBuds Wireless Pro", "original_price": 1799.0, "deal_price": 17.99, "discount_pct": 99.0, "currency": "SEK"}]}',
        ),
        TestFixture(
            id="seasonal-55pct-clearance",
            label="SkiBoot 55% — end-of-season clearance",
            description="May = end of winter sport season in Norway. 55% discount on ski boots is plausible.",
            expected_outcome="pass",
            expected_notes="Assessment should mention seasonal clearance / plausible promotion",
            input='{"deals": [{"product_id": "SKIBOOT", "product_name": "SkiBoot Elite 2026", "original_price": 2499.0, "deal_price": 1124.55, "discount_pct": 55.0, "currency": "NOK"}]}',
        ),
    ],

    # ===== ecommerce-ops / sales_anomaly =====
    ("ecommerce-ops", "sales_anomaly"): [
        TestFixture(
            id="sales-surge-pre-launch",
            label="Sales surge — pre-launch tailwind",
            description="Phone sales +92% with X13 launch in 10 days. Should be attributed to upcoming event.",
            expected_outcome="pass",
            expected_notes="likely_cause should reference the Nordic Phone X13 Launch event",
            input='{"flagged_products": [{"product_id": "NPX12P", "product_name": "Nordic Phone X12 Pro", "category": "Electronics", "sold_today": 48, "sold_yesterday": 22, "avg_7day": 25.0, "pct_vs_avg": 92.0}], "upcoming_events": [{"name": "Nordic Phone X13 Launch", "event_date": "2026-06-05", "affected_categories": ["Electronics"]}]}',
        ),
        TestFixture(
            id="sales-collapse-no-event",
            label="Sales collapse — no event explanation",
            description="-81% drop with no relevant event. Likely supply/data issue.",
            expected_outcome="pass",
            expected_notes="likely_cause should suggest data error, stock-out, or indexing issue",
            input='{"flagged_products": [{"product_id": "ICEPOT", "product_name": "IcePot Espresso Maker", "category": "Home", "sold_today": 4, "sold_yesterday": 22, "avg_7day": 21.0, "pct_vs_avg": -81.0}], "upcoming_events": []}',
        ),
        TestFixture(
            id="sales-mixed-with-midsommar",
            label="Mixed surge/drop ahead of Midsommar",
            description="SaunaTowel surge (Midsommar tailwind), LapBike drop (suspect). Two different hypotheses needed.",
            expected_outcome="pass",
            expected_notes="Two causes: SaunaTowel = seasonal/event, LapBike = anomaly to investigate",
            input='{"flagged_products": [{"product_id": "SAUNATWL", "product_name": "SaunaTowel Bamboo XL", "category": "Home", "sold_today": 65, "sold_yesterday": 30, "avg_7day": 28.0, "pct_vs_avg": 132.0}, {"product_id": "LAPBIKE", "product_name": "LapBike Carbon Road", "category": "Sport", "sold_today": 2, "sold_yesterday": 12, "avg_7day": 14.0, "pct_vs_avg": -85.7}], "upcoming_events": [{"name": "Midsommar", "event_date": "2026-06-21", "affected_categories": ["Home", "Sport"]}]}',
        ),
    ],

    # ===== ecommerce-ops / event_manager =====
    ("ecommerce-ops", "event_manager"): [
        TestFixture(
            id="black-friday-imminent",
            label="Black Friday — 3 days out (HIGH)",
            description="Mass retail event very close. Should generate HIGH severity + concrete prep actions.",
            expected_outcome="pass",
            expected_notes="severity=HIGH, recommendation with specific actions for Electronics+Sport",
            input='{"events": [{"name": "Black Friday SE", "event_date": "2026-05-29", "days_until": 3, "countries": ["SE", "FI"], "affected_categories": ["Electronics", "Sport"], "description": "Largest discount event of the year."}]}',
        ),
        TestFixture(
            id="midsommar-distant",
            label="Midsommar — 26 days out (INFO)",
            description="Cultural event still distant. Should be INFO severity with long-lead recommendation.",
            expected_outcome="pass",
            expected_notes="severity=INFO (>10 days), recommendation about supplier lead times / stock planning",
            input='{"events": [{"name": "Midsommar", "event_date": "2026-06-21", "days_until": 26, "countries": ["SE", "FI"], "affected_categories": ["Home", "Sport"], "description": "Peak summer holiday — outdoor and homeware demand spikes."}]}',
        ),
        TestFixture(
            id="three-events-mixed-severities",
            label="Three events — mixed severities",
            description="Tomorrow (HIGH), in 10 days (MEDIUM), in 169 days (INFO). Tests classification logic.",
            expected_outcome="pass",
            expected_notes="Three recommendations with severities HIGH, MEDIUM, INFO respectively",
            input='{"events": [{"name": "Norwegian Constitution Day", "event_date": "2026-05-27", "days_until": 1, "countries": ["NO"], "affected_categories": ["Home"], "description": "National celebration."}, {"name": "Singles\' Day SE", "event_date": "2026-11-11", "days_until": 169, "countries": ["SE", "NO", "DK", "FI"], "affected_categories": ["Electronics", "Home"], "description": "Imported retail event."}, {"name": "Nordic Phone X13 Launch", "event_date": "2026-06-05", "days_until": 10, "countries": ["SE", "NO", "DK", "FI"], "affected_categories": ["Electronics"], "description": "Fictional flagship launch."}]}',
        ),
    ],

    # ===== ecommerce-ops / click_spike =====
    ("ecommerce-ops", "click_spike"): [
        TestFixture(
            id="phone-spike-explained-by-launch",
            label="Phone click spike — explained by launch event",
            description="220% spike with X13 launch in 10 days. Should be classified as ORGANIC, severity LOW.",
            expected_outcome="pass",
            expected_notes="severity=LOW, interpretation references organic pre-launch interest",
            input='{"flagged_products": [{"product_id": "NPX12P", "product_name": "Nordic Phone X12 Pro", "category": "Electronics", "clicks_today": 3833, "clicks_yesterday": 1198, "pct_change": 219.9, "dominance_in_category": 1.85}], "upcoming_events": [{"name": "Nordic Phone X13 Launch", "event_date": "2026-06-05", "affected_categories": ["Electronics"]}]}',
        ),
        TestFixture(
            id="sauna-heater-unexplained-spike",
            label="Sauna heater spike — no event (HIGH anomaly)",
            description="336% spike + 4.4x category dominance, no relevant event. Likely data anomaly.",
            expected_outcome="pass",
            expected_notes="severity=HIGH, interpretation='data_anomaly' — should suggest verification",
            input='{"flagged_products": [{"product_id": "SAUNAFX", "product_name": "SaunaFlex Smart Heater", "category": "Home", "clicks_today": 4800, "clicks_yesterday": 1100, "pct_change": 336.4, "dominance_in_category": 4.38}], "upcoming_events": []}',
        ),
        TestFixture(
            id="mixed-organic-and-anomaly",
            label="Mixed: SkiBoot suspicious, AuroraBuds organic",
            description="SkiBoot 328% off-season → anomaly. AuroraBuds 165% with phone launch nearby → organic halo.",
            expected_outcome="pass",
            expected_notes="Two interpretations: SkiBoot HIGH/data_anomaly, AuroraBuds LOW/organic",
            input='{"flagged_products": [{"product_id": "SKIBOOT", "product_name": "SkiBoot Elite 2026", "category": "Sport", "clicks_today": 1200, "clicks_yesterday": 280, "pct_change": 328.6, "dominance_in_category": 2.1}, {"product_id": "AURBUDS", "product_name": "AuroraBuds Wireless Pro", "category": "Electronics", "clicks_today": 4500, "clicks_yesterday": 1700, "pct_change": 164.7, "dominance_in_category": 1.2}], "upcoming_events": [{"name": "Nordic Phone X13 Launch", "event_date": "2026-06-05", "affected_categories": ["Electronics"]}]}',
        ),
    ],
}


def main():
    added = 0
    for (project, name), fixtures in FIXTURES.items():
        try:
            record = pm.load(project, name)
        except FileNotFoundError:
            print(f"  [SKIP] {project}/{name} — file not found")
            continue
        record.test_fixtures = fixtures
        # Direct write through the private helper — we're seeding, not appending
        pm._write(project, name, record)
        added += len(fixtures)
        print(f"  [OK]  {project}/{name} — {len(fixtures)} fixtures")
    print(f"\nDone. Total fixtures seeded: {added}")


if __name__ == "__main__":
    main()
