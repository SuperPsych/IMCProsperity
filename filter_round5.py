"""Filter round5 CSVs down to TRADED_PRODUCTS.

Writes a parallel tree at data_filtered/round5/ that the backtester can
read via `prosperity4bt ... --data data_filtered`. Edit TRADED_PRODUCTS
below, then re-run this script.
"""
from pathlib import Path
import csv

# Edit me: products to keep in the filtered CSVs.
TRADED_PRODUCTS = {
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_GARLIC",
    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_MORNING_BREATH",
}

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "round5"
DST = ROOT / "data_filtered" / "round5"
DST.mkdir(parents=True, exist_ok=True)


def filter_file(src: Path, dst: Path, product_col: str) -> tuple[int, int]:
    with src.open("r", newline="") as f_in:
        reader = csv.DictReader(f_in, delimiter=";")
        rows = list(reader)
        fieldnames = reader.fieldnames

    kept = [r for r in rows if r[product_col] in TRADED_PRODUCTS]

    with dst.open("w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(kept)

    return len(rows), len(kept)


def main() -> None:
    print(f"Filtering to {len(TRADED_PRODUCTS)} products: {sorted(TRADED_PRODUCTS)}")
    for csv_path in sorted(SRC.glob("*.csv")):
        is_prices = csv_path.name.startswith("prices_")
        product_col = "product" if is_prices else "symbol"
        out_path = DST / csv_path.name
        total, kept = filter_file(csv_path, out_path, product_col)
        print(f"  {csv_path.name}: {kept:,}/{total:,} rows -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
