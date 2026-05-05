"""Cleanup and analyze the experiment database.

Performs:
1. Reclassify "general" domain questions to proper domains based on keywords
2. Remove low-quality micro-duration Bitcoin markets
3. Report final distribution against experiment targets
4. Optionally deduplicate questions with very similar text

Usage:
    # Analyze only (no changes)
    python scripts/cleanup_experiment_db.py --db experiment.db --dry-run

    # Apply reclassification and cleanup
    python scripts/cleanup_experiment_db.py --db experiment.db

    # Also remove micro-duration Bitcoin markets
    python scripts/cleanup_experiment_db.py --db experiment.db --remove-micro
"""

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Keyword-based domain classification rules
# Order matters: first match wins
DOMAIN_RULES = [
    # Finance
    ("finance", [
        r"\bbitcoin\b", r"\bbtc\b", r"\bcrypto\b", r"\bethereum\b", r"\beth\b",
        r"\bsolana\b", r"\bdoge\b", r"\bstock\b", r"\bmarket\b", r"\bs&p\b",
        r"\bnasdaq\b", r"\bdow\b", r"\bfed\b", r"\binterest rate\b", r"\binflation\b",
        r"\bgdp\b", r"\bearnings\b", r"\bipo\b", r"\btrading\b", r"\bbond\b",
        r"\btreasury\b", r"\bcurrency\b", r"\bforex\b", r"\bgold\b", r"\boil\b",
        r"\bcrude\b", r"\bprice\b.*\b(above|below|reach|hit)\b",
        r"\bcommodit\b", r"\bfinancial\b", r"\bbank\b.*\b(rate|crisis|fail)\b",
        r"\brecession\b", r"\beconom\b",
        r"\bxrp\b", r"\bcardano\b", r"\bada\b", r"\bbnb\b", r"\bavax\b",
        r"\blink\b.*\b(up|down|price)\b", r"\bdefi\b",
    ]),
    # Politics
    ("politics", [
        r"\belection\b", r"\bvote\b", r"\bpresident\b", r"\bsenate\b",
        r"\bcongress\b", r"\bparliament\b", r"\blegislat\b", r"\bpolicy\b",
        r"\bsanction\b", r"\btariff\b", r"\bgovernment\b", r"\bprime minister\b",
        r"\bdemocrat\b", r"\brepublican\b", r"\btrump\b", r"\bbiden\b",
        r"\bwar\b", r"\bmilitary\b", r"\bnato\b", r"\bdiploma\b",
        r"\bgeopolit\b", r"\bun\b.*\bresolution\b", r"\bimpeach\b",
    ]),
    # Sports
    ("sports", [
        r"\bnfl\b", r"\bnba\b", r"\bmlb\b", r"\bnhl\b", r"\bmls\b",
        r"\bfifa\b", r"\bolympic\b", r"\bworld cup\b", r"\btennis\b",
        r"\bsoccer\b", r"\bfootball\b.*\b(game|match|season|win)\b",
        r"\bbasketball\b", r"\bbaseball\b", r"\bhockey\b",
        r"\bchampion\b", r"\btournament\b", r"\bplayoff\b", r"\bsuper bowl\b",
        r"\bufc\b", r"\bboxing\b", r"\bf1\b", r"\bformula\b",
        r"\bgrand prix\b", r"\bwrestl\b",
        # International soccer/football patterns: "Club vs. Club"
        r"\w+ fc\b", r"\bfc \w+", r"\w+ fk\b", r"\bfk \w+",
        r"\bvs\.?\b.*\b(fc|fk|united|city|rovers|athletic|sc|sv|cf)\b",
        r"\b(united|city|rovers|athletic|sc|sv|cf)\b.*\bvs\.?\b",
        # Team vs Team pattern (common in sports markets)
        r"\w+\s+vs\.?\s+\w+.*\b(fc|fk|sc|sv|cf|ac|as|ss)\b",
        r"\bpsv\b", r"\bbraga\b.*\bvs\b", r"\bvs\b.*\bbraga\b",
        # US college sports
        r"\b(wildcats|tigers|bulldogs|longhorns|bruins|illini|cavaliers|gators|seminoles|aggies|bears|cardinals|eagles|hawks|wolverines|spartans|cyclones|mountaineers|jayhawks|razorbacks|commodores|volunteers|rebels|sooners|beavers|ducks|cougars|huskies|hoosiers|terrapins|cornhuskers|badgers|hornets|vandals|friars|demons|gauchos|warriors|rainbow)\b",
        # International clubs: "Club vs Club" / "de Madrid" / "de Barcelona" / "Saudi" etc.
        r"\batlético\b", r"\batletico\b", r"\bbarcelona\b", r"\bmadrid\b",
        r"\bal hilal\b", r"\bal ittihad\b", r"\bal ahli\b", r"\bal nassr\b",
        r"\breal\b.*\bvs\b", r"\bvs\b.*\breal\b",
        r"\bmore markets\b",  # Polymarket "More Markets" = sports sub-markets
        r"\w+spor\b.*\bvs\b", r"\bvs\b.*\w+spor\b",  # Turkish soccer (Kayserispor)
        r"\bopen\b.*\bvs\b",  # Tennis opens
        # Boxing / MMA patterns
        r"\bhigh stakes\b", r"\bfight night\b", r"\bbout\b",
        r"\bvs\.?\b.*\b(welterweight|heavyweight|middleweight|lightweight|featherweight|bantamweight)\b",
        r"\b(welterweight|heavyweight|middleweight|lightweight|featherweight|bantamweight)\b",
        # Soccer league names
        r"\bpremier league\b", r"\bla liga\b", r"\bserie a\b", r"\bbundesliga\b",
        r"\bligue 1\b", r"\bcopa\b", r"\bchampions league\b",
    ]),
    # Culture / Entertainment
    ("culture", [
        r"\bmovie\b", r"\bfilm\b", r"\boscar\b", r"\bacademy award\b",
        r"\bgrammy\b", r"\bemmy\b", r"\balbum\b", r"\bsong\b", r"\bmusic\b",
        r"\bnetflix\b", r"\bdisney\b", r"\bbox office\b", r"\bstreaming\b",
        r"\btv show\b", r"\bseries\b", r"\bcelebrit\b", r"\bentertain\b",
        r"\bfestival\b", r"\bconcert\b", r"\bart\b.*\b(exhibit|auction|gallery)\b",
        r"\bgaming\b", r"\bvideo game\b", r"\besports\b",
        r"\byoutub\b", r"\binfluencer\b", r"\bmrbeast\b", r"\btiktok\b",
        r"\bpodcast\b", r"\binstagram\b", r"\btwitter\b",
    ]),
    # Climate
    ("climate", [
        r"\bclimate\b", r"\bglobal warming\b", r"\bcarbon\b", r"\bemission\b",
        r"\brenewable\b", r"\bsolar\b", r"\bwind energy\b", r"\bev\b",
        r"\belectric vehicle\b", r"\bdrought\b", r"\bflood\b", r"\bhurricane\b",
        r"\bwildfire\b", r"\bdeforest\b", r"\bparis agreement\b",
        r"\btemperature\b.*\b(record|rise|above)\b", r"\bweather\b",
        r"\benvironment\b", r"\bpollution\b", r"\bsea level\b",
    ]),
    # Health
    ("health", [
        r"\bfda\b", r"\bvaccine\b", r"\bcovid\b", r"\bpandemic\b",
        r"\bdrug\b.*\b(approv|trial|fda)\b", r"\bmedic\b", r"\bhealth\b",
        r"\bhospital\b", r"\bcancer\b", r"\btreatment\b", r"\bclinical trial\b",
        r"\bwho\b.*\b(declar|report|warn)\b", r"\bdisease\b", r"\bvirus\b",
        r"\bpharma\b", r"\bbiotech\b", r"\bmental health\b",
        r"\bobesity\b", r"\bdiabet\b", r"\balzheimer\b",
    ]),
]


def classify_domain(question_text: str) -> Optional[str]:
    """Classify a question into a domain based on keyword matching.
    
    Returns domain string or None if no match.
    """
    text_lower = question_text.lower()
    for domain, patterns in DOMAIN_RULES:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return domain
    return None


def is_micro_bitcoin_market(question_text: str, start_time: str, resolution_date: str) -> bool:
    """Check if a question is a micro-duration Bitcoin market (sub-daily).
    
    These are low-quality for forecasting experiments.
    """
    text_lower = question_text.lower()
    is_bitcoin = bool(re.search(r"\bbitcoin\b|\bbtc\b", text_lower))
    
    if not is_bitcoin:
        return False
    
    # Check for time-specific patterns like "3:00PM-3:05PM" or "12:00AM"
    has_time_range = bool(re.search(r"\d{1,2}:\d{2}\s*(AM|PM|ET)", question_text, re.IGNORECASE))
    
    # Check for very short duration (sub-daily)
    if start_time and resolution_date:
        try:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(resolution_date)
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours < 24 and has_time_range:
                return True
        except:
            pass
    
    return has_time_range


def main():
    parser = argparse.ArgumentParser(description="Cleanup experiment database")
    parser.add_argument("--db", default="experiment.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only, no changes")
    parser.add_argument("--remove-micro", action="store_true",
                       help="Remove micro-duration Bitcoin markets (sub-daily)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Error: Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    c = conn.cursor()

    # Get current state
    c.execute("SELECT COUNT(*) FROM questions")
    total = c.fetchone()[0]
    print(f"\n{'='*60}")
    print(f"  EXPERIMENT DB CLEANUP")
    print(f"{'='*60}")
    print(f"\n  Database: {args.db}")
    print(f"  Total questions: {total}")
    if args.dry_run:
        print(f"  Mode: DRY RUN (no changes)")
    print()

    # === Step 1: Analyze general domain questions ===
    c.execute("SELECT id, question_text, domain, source, estimated_start_time, resolution_date FROM questions WHERE domain = 'general'")
    general_qs = c.fetchall()
    print(f"  General domain questions: {len(general_qs)}")

    reclassifications = defaultdict(list)  # domain -> [(id, text)]
    unclassified = []
    micro_bitcoin = []

    for qid, text, domain, source, start_time, res_date in general_qs:
        # Check micro-bitcoin
        if args.remove_micro and is_micro_bitcoin_market(text, start_time or "", res_date or ""):
            micro_bitcoin.append((qid, text))
            continue

        new_domain = classify_domain(text)
        if new_domain:
            reclassifications[new_domain].append((qid, text))
        else:
            unclassified.append((qid, text))

    # Report reclassifications
    print(f"\n  Reclassification plan:")
    for domain, items in sorted(reclassifications.items()):
        print(f"    general -> {domain:12}: {len(items)} questions")
        for qid, text in items[:3]:
            print(f"      - {text[:80]}")
        if len(items) > 3:
            print(f"      ... and {len(items) - 3} more")

    if unclassified:
        print(f"\n    Still unclassified: {len(unclassified)}")
        for qid, text in unclassified[:5]:
            print(f"      - {text[:80]}")
        if len(unclassified) > 5:
            print(f"      ... and {len(unclassified) - 5} more")

    if micro_bitcoin:
        print(f"\n    Micro-duration Bitcoin markets to remove: {len(micro_bitcoin)}")
        for qid, text in micro_bitcoin[:3]:
            print(f"      - {text[:80]}")
        if len(micro_bitcoin) > 3:
            print(f"      ... and {len(micro_bitcoin) - 3} more")

    # === Step 2: Apply changes ===
    if not args.dry_run:
        # Reclassify
        reclass_count = 0
        for domain, items in reclassifications.items():
            for qid, text in items:
                c.execute("UPDATE questions SET domain = ? WHERE id = ?", (domain, qid))
                reclass_count += 1
        print(f"\n  Applied {reclass_count} reclassifications")

        # Remove micro-bitcoin if requested
        if args.remove_micro and micro_bitcoin:
            for qid, text in micro_bitcoin:
                c.execute("DELETE FROM questions WHERE id = ?", (qid,))
            print(f"  Removed {len(micro_bitcoin)} micro-duration Bitcoin markets")

        conn.commit()

    # === Step 3: Report final distribution ===
    print(f"\n  {'='*50}")
    print(f"  FINAL DISTRIBUTION {'(projected)' if args.dry_run else ''}")
    print(f"  {'='*50}")

    # Recompute after changes
    c.execute("SELECT COUNT(*) FROM questions")
    final_total = c.fetchone()[0]
    if args.dry_run:
        final_total = total - len(micro_bitcoin) if args.remove_micro else total

    print(f"\n  Total: {final_total} (target: 300)")

    # By type
    c.execute("SELECT question_type, COUNT(*) FROM questions GROUP BY question_type")
    print(f"\n  By Type:")
    targets_type = {"binary": 180, "mcq": 60, "quantity": 30, "timeframe": 30}
    for qtype, count in c.fetchall():
        target = targets_type.get(qtype, 0)
        status = "OK" if count >= target else f"NEED {target - count}"
        print(f"    {qtype:15} {count:4}/{target:4}  {status}")

    # By domain
    c.execute("SELECT domain, COUNT(*) FROM questions GROUP BY domain")
    print(f"\n  By Domain:")
    targets_domain = {"finance": 50, "politics": 50, "sports": 50, "culture": 50, "climate": 50, "health": 50}
    for domain, count in c.fetchall():
        target = targets_domain.get(domain, 0)
        if target == 0:
            status = f"(not in target)"
        else:
            status = "OK" if count >= target else f"NEED {target - count}"
        print(f"    {domain:15} {count:4}/{target:4}  {status}")

    # By time horizon
    c.execute("SELECT resolution_date, estimated_start_time FROM questions WHERE resolution_date IS NOT NULL AND estimated_start_time IS NOT NULL")
    short, medium, long_h = 0, 0, 0
    for res, start in c.fetchall():
        try:
            rd = datetime.fromisoformat(res)
            sd = datetime.fromisoformat(start)
            days = (rd - sd).days
            if days <= 7: short += 1
            elif days <= 90: medium += 1
            else: long_h += 1
        except:
            pass
    print(f"\n  By Time Horizon:")
    print(f"    {'short':15} {short:4}/{100:4}  {'OK' if short >= 100 else f'NEED {100 - short}'}")
    print(f"    {'medium':15} {medium:4}/{100:4}  {'OK' if medium >= 100 else f'NEED {100 - medium}'}")
    print(f"    {'long':15} {long_h:4}/{100:4}  {'OK' if long_h >= 100 else f'NEED {100 - long_h}'}")

    # By source
    c.execute("SELECT source, COUNT(*) FROM questions GROUP BY source")
    print(f"\n  By Source:")
    for source, count in c.fetchall():
        print(f"    {source:15} {count:4}")

    # Ground truth
    c.execute("SELECT COUNT(*) FROM questions WHERE ground_truth IS NOT NULL")
    gt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM questions")
    current_total = c.fetchone()[0]
    print(f"\n  Ground truth: {gt}/{current_total}")

    print(f"\n{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
