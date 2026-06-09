#!/usr/bin/env python3
"""Generate DS9-era Star Trek-style stardates for personal notebook entries.

This script uses a practical mapping from the real world into a Star Trek timeline.
Star Trek stardates are canonically inconsistent, so this tool is intentionally
simple and notebook-friendly: it advances roughly 1000 stardate units per year
and keeps current notes in the Deep Space Nine / late TNG era.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
import sys


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Invalid date format. Use 'YYYY-MM-DD HH:MM', for example: 2026-06-07 21:14."
        )


def parse_precision(value):
    try:
        precision = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Precision must be an integer.")
    if precision < 0:
        raise argparse.ArgumentTypeError("Precision must be zero or a positive integer.")
    return precision


def parse_offset_years(value):
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Offset years must be an integer.")


def build_personal_reference(stardate, color=None, tag=None):
    reference = f"(stardate: {stardate})"
    parts = []
    if color:
        parts.append(color)
    if tag:
        parts.append(tag)
    if parts:
        reference += " [" + " / ".join(parts) + "]"
    return reference


def compute_fraction_of_year(dt):
    start = datetime(dt.year, 1, 1, tzinfo=dt.tzinfo)
    end = datetime(dt.year + 1, 1, 1, tzinfo=dt.tzinfo)
    elapsed = dt - start
    year_length = end - start
    return elapsed / year_length


def format_datetime(dt):
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.astimezone(dt.tzinfo).strftime("%Y-%m-%d %H:%M %Z")


def compute_stardate(dt, offset_years):
    adjusted_year = dt.year + offset_years
    fraction_of_year = compute_fraction_of_year(dt.replace(year=adjusted_year))
    stardate_value = ((adjusted_year - 2323) * 1000) + (fraction_of_year * 1000)
    return adjusted_year, stardate_value


def explain_text():
    return (
        "Stardates here map real calendar time into a DS9-era timeline using a fixed year offset.\n"
        "The script adds the offset to the year, determines how far through that year the date is,\n"
        "then multiplies by 1000. This keeps stardates roughly 1000 units per year and places\n"
        "2026 inside the 2373 / Deep Space Nine era by default."
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate a DS9-era personal notebook stardate reference."
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        help="Calculate for a specific datetime in local time by default. Format: 'YYYY-MM-DD HH:MM'.",
    )
    parser.add_argument(
        "--utc",
        action="store_true",
        help="Interpret the provided date or the current time as UTC.",
    )
    parser.add_argument(
        "--precision",
        type=parse_precision,
        default=1,
        help="Decimal places for the stardate output (default: 1).",
    )
    parser.add_argument(
        "--offset-years",
        type=parse_offset_years,
        default=347,
        help="Timeline year offset from real-world year (default: 347).",
    )
    parser.add_argument(
        "--no-offset",
        action="store_true",
        help="Do not apply the default timeline offset and use the real year directly.",
    )
    parser.add_argument(
        "--color",
        help="Optional notebook color-code label.",
    )
    parser.add_argument(
        "--tag",
        help="Optional short note tag such as Project, Priority, Personal, Reference, Done, Idea.",
    )
    parser.add_argument(
        "--personal",
        action="store_true",
        help="Print the compact personal-note format. This is also the default output style.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the stardate data as JSON.",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print a short explanation of the formula used to compute the stardate.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    offset_years = 0 if args.no_offset else args.offset_years
    if args.no_offset and args.offset_years != 347:
        offset_years = 0

    if args.date is not None:
        dt = args.date
        if args.utc:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=None)
    else:
        dt = datetime.now(timezone.utc) if args.utc else datetime.now()

    if dt.tzinfo is None:
        local_dt = dt
        utc_dt = dt.astimezone(timezone.utc)
    else:
        if args.utc:
            utc_dt = dt
            local_dt = dt.astimezone()
        else:
            local_dt = dt.astimezone()
            utc_dt = dt.astimezone(timezone.utc)

    adjusted_timeline_year, stardate_value = compute_stardate(dt, offset_years)
    stardate_string = f"{stardate_value:.{args.precision}f}"

    personal_reference = build_personal_reference(
        stardate_string, color=args.color, tag=args.tag
    )

    if args.explain:
        print(explain_text())

    if args.json:
        output = {
            "real_local_datetime": format_datetime(local_dt),
            "real_utc_datetime": format_datetime(utc_dt),
            "adjusted_timeline_year": adjusted_timeline_year,
            "offset_years": offset_years,
            "stardate": float(stardate_string),
            "color": args.color,
            "tag": args.tag,
            "personal_reference": personal_reference,
        }
        print(json.dumps(output, indent=2))
    else:
        print(personal_reference)


if __name__ == "__main__":
    main()
