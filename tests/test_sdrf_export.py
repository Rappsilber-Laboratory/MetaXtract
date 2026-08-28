import tempfile
import unittest
from pathlib import Path

from sdrf_export import (
    available_sdrf_columns,
    enrich_sdrf_rows_for_file,
    normalize_acquisition_date,
    validate_sdrf_metadata,
    write_sdrf,
)


class SdrfExportTests(unittest.TestCase):
    def setUp(self):
        self.files = ["/data/control.raw", "/data/treated.raw"]
        self.rows = [
            {
                "file": self.files[0],
                "source_name": "control_1",
                "assay_name": "control_run",
                "organism": "homo sapiens",
                "organism_part": "liver",
                "disease": "normal",
                "biological_replicate": "1",
                "acquisition_method": "DDA",
                "label": "label free sample",
                "cleavage_agent": "Trypsin",
                "fraction_identifier": "1",
                "technical_replicate": "1",
                "instrument_override": "",
                "factor_value": "normal",
            },
            {
                "file": self.files[1],
                "source_name": "treated_1",
                "assay_name": "treated_run",
                "organism": "homo sapiens",
                "organism_part": "liver",
                "disease": "liver cancer",
                "biological_replicate": "1",
                "acquisition_method": "DIA",
                "label": "label free sample",
                "cleavage_agent": "Lys-C",
                "fraction_identifier": "1",
                "technical_replicate": "1",
                "instrument_override": "",
                "factor_value": "liver cancer",
            },
        ]

    def test_validates_complete_dataset(self):
        self.assertEqual(
            validate_sdrf_metadata(self.rows, self.files, factor_name="disease"),
            [],
        )

    def test_reports_missing_and_invalid_values(self):
        invalid = [dict(self.rows[0], organism="", fraction_identifier="0")]
        errors = validate_sdrf_metadata(invalid, self.files, factor_name="disease")
        self.assertTrue(any("organism" in error for error in errors))
        self.assertTrue(any("fraction identifier" in error for error in errors))
        self.assertTrue(any("No SDRF row" in error for error in errors))

    def test_rejects_not_available_for_required_controlled_values(self):
        invalid = [dict(self.rows[0], acquisition_method="not available"), self.rows[1]]
        errors = validate_sdrf_metadata(invalid, self.files, factor_name="disease")
        self.assertTrue(any("acquisition method" in error for error in errors))

    def test_enriches_and_writes_sdrf(self):
        output_rows = []
        for file_path in self.files:
            output_rows.extend(
                enrich_sdrf_rows_for_file(
                    self.rows,
                    file_path,
                    "Orbitrap Fusion Lumos",
                    "09/20/2024 11:36:09",
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = write_sdrf(
                Path(temp_dir) / "metadata.sdrf.tsv",
                output_rows,
                factor_name="disease",
            )
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 3)
        self.assertIn("factor value[disease]", lines[0])
        self.assertIn("NT=Data-dependent acquisition;AC=PRIDE:0000627", lines[1])
        self.assertIn("NT=Lys-C;AC=MS:1001309", lines[2])
        self.assertEqual(len(lines[0].split("\t")), len(lines[1].split("\t")))

    def test_unknown_raw_instrument_requires_an_override(self):
        enriched = enrich_sdrf_rows_for_file(
            self.rows,
            self.files[0],
            "Unknown",
            "09/20/2024 11:36:09",
        )
        self.assertEqual(enriched[0]["instrument"], "")

    def test_normalizes_thermo_creation_date(self):
        self.assertEqual(
            normalize_acquisition_date("09/20/2024 11:36:09"),
            "2024-09-20T11:36:09",
        )

    def test_offers_full_known_column_catalog(self):
        columns = available_sdrf_columns()
        self.assertGreaterEqual(len(columns), 300)
        self.assertIn("characteristics[disease]", columns)
        self.assertIn("comment[collision energy]", columns)
        self.assertIn("characteristics[pH method]", columns)
        self.assertNotIn("comment[data file]", columns)

    def test_validates_and_writes_selected_optional_columns(self):
        extra_columns = [
            "characteristics[disease]",
            "comment[collision energy]",
            "factor value[treatment]",
        ]
        rows = []
        for row in self.rows:
            updated = dict(row)
            updated["characteristics[disease]"] = row["disease"]
            updated["comment[collision energy]"] = "30 NCE"
            updated["factor value[treatment]"] = row["factor_value"]
            rows.append(updated)

        self.assertEqual(
            validate_sdrf_metadata(rows, self.files, extra_columns=extra_columns),
            [],
        )
        output_rows = []
        for file_path in self.files:
            output_rows.extend(
                enrich_sdrf_rows_for_file(
                    rows,
                    file_path,
                    "Orbitrap Fusion Lumos",
                    "09/20/2024 11:36:09",
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = write_sdrf(
                Path(temp_dir) / "metadata.sdrf.tsv",
                output_rows,
                extra_columns=extra_columns,
            )
            header = output.read_text(encoding="utf-8").splitlines()[0].split("\t")

        self.assertIn("characteristics[disease]", header)
        self.assertIn("comment[collision energy]", header)
        self.assertIn("factor value[treatment]", header)

    def test_rejects_empty_or_unknown_added_columns(self):
        rows = [dict(row) for row in self.rows]
        errors = validate_sdrf_metadata(
            rows,
            self.files,
            extra_columns=["characteristics[disease]", "comment[not a real column]"],
        )
        self.assertTrue(any("cannot be empty" in error for error in errors))
        self.assertTrue(any("not a known SDRF column" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
