import csv
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from scripts.build_public_places import FIELDS, build
from collectors.public_places import PublicPlaces


class PublicPlacesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.csv"
        self.output = self.root / "places.sqlite"

    def write(self, rows):
        with self.source.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def row(self, identity="a", code="11650", lon="127.0"):
        return [identity, code, code + "10100", "I211", "I21101", "주점", lon, "37.5"]

    def test_zip_filters_deduplicates_and_records_provenance(self):
        self.write([self.row(), self.row(), self.row("b", "11680")])
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.write(self.source, "../source.csv")  # Never extracted to disk.
        report = build([archive], self.output, "2026-09-30", ["11650"])
        self.assertEqual(report["rows"], 1)
        self.assertEqual(len(report["inputs"][0]["sha256"]), 64)
        self.assertFalse(report["runtime_enabled"])
        with closing(sqlite3.connect(self.output)) as db:
            saved = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
            self.assertEqual(saved["regions"], {"11650": 1})

    def test_missing_region_and_bad_coordinates_do_not_publish(self):
        self.write([self.row(lon="nan")])
        with self.assertRaisesRegex(ValueError, "자료가 없는"):
            build([self.source], self.output, "2026-09-30", ["11650"])
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_conflicting_duplicates_do_not_publish(self):
        self.write([self.row(), self.row(lon="127.1")])
        with self.assertRaisesRegex(ValueError, "서로 다른"):
            build([self.source], self.output, "2026-09-30", ["11650"])
        self.assertFalse(self.output.exists())

    def test_existing_database_is_preserved(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            build([], self.output, "2026-09-30", ["11650"])
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_keeps_needed_categories_only_without_changing_coordinates(self):
        rows = [self.row("bar")]
        for identity, middle, small, category in [
            ("convenience", "G204", "G20405", "편의점"),
            ("pharmacy", "G215", "G21501", "약국"),
            ("supermarket", "G204", "G20404", "슈퍼마켓"),
            ("restaurant", "I201", "I20101", "음식점"),
        ]:
            row = self.row(identity)
            row[3:6] = [middle, small, category]
            rows.append(row)
        self.write(rows)
        report = build([self.source], self.output, "2026-09-30", ["11650"])
        self.assertEqual(report["rows"], 3)
        self.assertEqual(report["excluded_other_categories"], 2)
        with closing(sqlite3.connect(self.output)) as db:
            self.assertEqual(db.execute("SELECT id, lon, lat FROM place ORDER BY id").fetchall(),
                             [("bar", 127.0, 37.5), ("convenience", 127.0, 37.5), ("pharmacy", 127.0, 37.5)])

    def test_radius_counts_neighbour_regions_and_excludes_far_points(self):
        self.write([self.row("near"), self.row("neighbour", "11680", "127.001"),
                    self.row("far", lon="127.1")])
        build([self.source], self.output, "2026-09-30", ["11650", "11680"])
        places = PublicPlaces(self.output)
        self.assertEqual(places.count("bars", 127.0, 37.5, 500, sgg_code="11650"), 2)
        self.assertEqual(places.count("CS2", 127.0, 37.5, 500, sgg_code="11650"), 0)
        with self.assertRaises(ValueError):
            places.count("bars", 127.0, 37.5, 500, sgg_code="99999")
        with self.assertRaises(ValueError):
            places.count("bars", float("nan"), 37.5, 500, sgg_code="11650")

    def test_national_validation_includes_outside_requested_districts(self):
        self.write([self.row(), self.row("outside", "26110")])
        report = build([self.source], self.output, "2026-09-30", codes=None)
        self.assertTrue(report["all_regions"])
        self.assertEqual(set(report["regions"]), {"11650", "26110"})
        self.assertEqual(report["rows"], 2)


if __name__ == "__main__":
    unittest.main()
