import runpy
import tempfile
import unittest
from pathlib import Path


comparison = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "compare_mgf.py"))
compare = comparison["compare"]
iter_spectra = comparison["iter_spectra"]


class MGFComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.reference = Path(temporary.name) / "reference.mgf"
        self.candidate = Path(temporary.name) / "candidate.mgf"
        self.reference.write_text('BEGIN IONS\nTITLE=sample NativeID:"scan=2"\nPEPMASS=500 100\nCHARGE=2+\nRTINSECONDS=60\n100 0\n200 10\nEND IONS\n')

    def test_compares_native_scan_id_against_explicit_scans(self):
        self.candidate.write_text(self.reference.read_text().replace('TITLE=sample NativeID:"scan=2"', 'SCANS=2\nTITLE=another title'))
        report = compare(self.reference, self.candidate)
        self.assertEqual(report["shared_spectra"], 1)
        self.assertEqual(report["spectra_with_matching_peak_intensities"], 1)
        self.assertEqual(report["reference_zero_intensity_peaks"], 1)
        self.assertEqual(report["charge_mismatches"], 0)

    def test_profile_and_centroid_data_are_not_reported_as_matching(self):
        self.candidate.write_text(self.reference.read_text().replace("100 0\n", ""))
        report = compare(self.reference, self.candidate)
        self.assertEqual(report["shared_spectra"], 1)
        self.assertEqual(report["spectra_with_equal_peak_counts"], 0)
        self.assertEqual(report["spectra_with_matching_peak_mz"], 0)

    def test_rejects_truncated_reference(self):
        self.reference.write_text(self.reference.read_text().replace("END IONS", ""))
        with self.assertRaisesRegex(ValueError, "Truncated"):
            list(iter_spectra(self.reference))

    def test_reports_missing_scan(self):
        self.candidate.write_text(self.reference.read_text().replace("scan=2", "scan=3"))
        report = compare(self.reference, self.candidate)
        self.assertEqual(report["missing_scan_examples"], [2])
        self.assertEqual(report["extra_scan_examples"], [3])


if __name__ == "__main__":
    unittest.main()
