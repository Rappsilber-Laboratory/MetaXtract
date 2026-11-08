import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import _is_cli, build_arg_parser
from mgf_exporter import MGFExporter, plan_mgf_outputs


class FakeReader:
    filename = "example.raw"
    FirstSpectrumNumber = 7
    LastSpectrumNumber = 10

    def GetMSOrder(self, scan):
        return 1 if scan == 7 else 2

    def GetMGFSpectrumFromScanNumber(self, scan, *, peak_mode="centroid"):
        return dict(masses=[200, 100, float("nan"), 300, -1],
                    intensities=[10, 20, 4, 0, 10], monoisotopic_mz=500.12345678,
                    isolation_target_mz=501.0, isolation_width_mz=20.0,
                    isolation_offset_mz=0.0, charge=3, polarity="Positive",
                    precursor_intensity=12345, retention_time_minutes=1.5,
                    centroid_source="stored_centroid")


class MGFExporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "example.mgf"
        self.reader = FakeReader()

    def metadata(self, result):
        with result.metadata.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t"))

    def test_standard_fields_units_sorted_peaks_and_summary(self):
        updates = []
        result = MGFExporter().export(self.reader, self.output, on_progress=lambda *p: updates.append(p))
        text = self.output.read_text()
        self.assertEqual(result.spectra_written, 3)
        self.assertEqual(result.invalid_peaks_removed, 9)
        self.assertEqual(text.count("BEGIN IONS"), 3)
        self.assertIn("SCANS=8\nPEPMASS=500.1234567800 12345\nCHARGE=3+\nRTINSECONDS=90.00000000", text)
        self.assertIn("100 20\n200 10\nEND IONS", text)
        self.assertNotIn("nan", text)
        self.assertEqual(updates[0], (0, 4, 0))
        self.assertEqual(updates[-1], (4, 4, 3))
        self.assertEqual([r["scan"] for r in self.metadata(result)], ["8", "9", "10"])

    def test_independent_reader_accepts_output(self):
        try:
            from pyteomics import mgf
        except ImportError:
            self.skipTest("Optional independent parser pyteomics is unavailable")
        MGFExporter().export(self.reader, self.output)
        with mgf.MGF(str(self.output)) as spectra:
            parsed = list(spectra)
        self.assertEqual(len(parsed), 3)
        self.assertAlmostEqual(parsed[0]["params"]["pepmass"][0], 500.12345678)
        self.assertEqual(parsed[0]["params"]["rtinseconds"], 90)
        self.assertEqual(list(parsed[0]["m/z array"]), [100, 200])

    def test_dia_uses_isolation_target_without_charge_or_precursor_intensity(self):
        result = MGFExporter("dia").export(self.reader, self.output)
        text = self.output.read_text()
        self.assertIn("PEPMASS=501.0000000000\n", text)
        self.assertNotIn("CHARGE=", text)
        self.assertNotIn("12345", text)
        self.assertEqual(result.isolation_target_spectra, 3)
        row = self.metadata(result)[0]
        self.assertEqual(row["isolation_width_mz"], "20.0")
        self.assertEqual(row["pepmass_source"], "isolation_target")
        self.assertEqual(row["acquisition"], "dia")

    def test_recorded_peak_mode_preserves_zero_intensity_profile_points(self):
        result = MGFExporter(peak_mode="recorded").export(self.reader, self.output)
        self.assertIn("200 10\n300 0\nEND IONS", self.output.read_text())
        self.assertEqual(result.invalid_peaks_removed, 6)
        self.assertEqual(self.metadata(result)[0]["peak_mode"], "recorded")

    def test_dda_can_fill_missing_intensity_from_parent_ms1(self):
        original = self.reader.GetMGFSpectrumFromScanNumber
        self.reader.GetMGFSpectrumFromScanNumber = lambda n: dict(original(n), precursor_intensity=None)
        self.reader.GetMGFPrecursorIntensityFromScanNumber = Mock(return_value=(9999, 7, "ms1_profile_window"))
        result = MGFExporter("dda").export(self.reader, self.output)
        self.assertIn("PEPMASS=500.1234567800 9999\n", self.output.read_text())
        row = self.metadata(result)[0]
        self.assertEqual(row["precursor_intensity_source"], "ms1_profile_window")
        self.assertEqual(row["precursor_ms1_scan"], "7")

    def test_optional_intensity_failure_does_not_discard_ms2(self):
        original = self.reader.GetMGFSpectrumFromScanNumber
        self.reader.GetMGFSpectrumFromScanNumber = lambda n: dict(original(n), precursor_intensity=None)
        self.reader.GetMGFPrecursorIntensityFromScanNumber = Mock(side_effect=ValueError("Missing MS1"))
        result = MGFExporter("dda").export(self.reader, self.output)
        self.assertEqual(result.spectra_written, 3)
        self.assertEqual(self.metadata(result)[0]["precursor_intensity_source"], "unavailable")

    def test_unknown_charge_is_omitted_and_negative_charge_is_preserved(self):
        original = self.reader.GetMGFSpectrumFromScanNumber
        self.reader.GetMGFSpectrumFromScanNumber = lambda n: dict(original(n), charge=None if n == 8 else -2)
        MGFExporter().export(self.reader, self.output)
        text = self.output.read_text()
        self.assertEqual(text.count("CHARGE=2-"), 2)

    def test_unicode_filename_has_consistent_ascii_title_in_both_outputs(self):
        self.reader.filename = "échantillon.raw"
        result = MGFExporter().export(self.reader, self.output)
        row = self.metadata(result)[0]
        text = self.output.read_text(encoding="ascii")
        self.assertIn(f"TITLE={row['title']}\n", text)

    def test_fallback_target_preserves_recorded_charge_for_dda(self):
        original = self.reader.GetMGFSpectrumFromScanNumber
        self.reader.GetMGFSpectrumFromScanNumber = lambda n: dict(original(n), monoisotopic_mz=0)
        result = MGFExporter("dda").export(self.reader, self.output)
        self.assertEqual(self.output.read_text().count("CHARGE=3+"), 3)
        self.assertEqual(result.isolation_target_spectra, 3)

    def test_missing_precursor_empty_and_unreadable_scans_are_reported(self):
        self.reader.LastSpectrumNumber = 11
        original = self.reader.GetMGFSpectrumFromScanNumber

        def spectrum(n):
            data = original(n)
            if n == 8:
                return dict(data, monoisotopic_mz=0, isolation_target_mz=None)
            if n == 9:
                return dict(data, masses=[], intensities=[])
            if n == 10:
                raise ValueError("No centroid stream")
            return data

        self.reader.GetMGFSpectrumFromScanNumber = spectrum
        result = MGFExporter().export(self.reader, self.output)
        self.assertEqual(result.spectra_written, 1)
        self.assertEqual(dict(result.skipped), {"missing_precursor": 1, "empty_spectrum": 1, "read_error": 1})
        self.assertEqual(len(self.metadata(result)), 4)

    def test_no_exportable_ms2_fails_without_publishing_empty_file(self):
        self.reader.GetMSOrder = lambda n: 1
        with self.assertRaisesRegex(ValueError, "No exportable MS2"):
            MGFExporter().export(self.reader, self.output)
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_cancel_leaves_no_partial_files(self):
        stopped = False

        def progress(done, total, written):
            nonlocal stopped
            stopped = done > 0

        with self.assertRaises(InterruptedError):
            MGFExporter().export(self.reader, self.output, on_progress=progress, should_stop=lambda: stopped)
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_cancel_before_publication_preserves_existing_outputs(self):
        first = MGFExporter().export(self.reader, self.output)
        before = (self.output.read_bytes(), first.metadata.read_bytes())
        original = self.reader.GetMGFSpectrumFromScanNumber
        stopped = False

        def spectrum(n):
            nonlocal stopped
            if n == self.reader.LastSpectrumNumber:
                stopped = True
            return original(n)

        self.reader.GetMGFSpectrumFromScanNumber = spectrum
        with self.assertRaises(InterruptedError):
            MGFExporter(overwrite=True).export(self.reader, self.output, should_stop=lambda: stopped)
        self.assertEqual(before, (self.output.read_bytes(), first.metadata.read_bytes()))

    def test_default_prevents_overwrite_and_explicit_option_allows_it(self):
        MGFExporter().export(self.reader, self.output)
        with self.assertRaises(FileExistsError):
            MGFExporter("dia").export(self.reader, self.output)
        MGFExporter("dia", overwrite=True).export(self.reader, self.output)
        self.assertNotIn("CHARGE=", self.output.read_text())

    def test_failure_publishing_companion_removes_new_mgf(self):
        import os
        link = os.link

        def fail_companion(source, target):
            if str(target).endswith(".tsv"):
                raise OSError("disk full")
            return link(source, target)

        with patch("mgf_exporter.os.link", side_effect=fail_companion):
            with self.assertRaises(OSError):
                MGFExporter().export(self.reader, self.output)
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_overwrite_publication_failure_restores_both_old_files(self):
        import os
        first = MGFExporter().export(self.reader, self.output)
        before = (self.output.read_bytes(), first.metadata.read_bytes())
        replace = os.replace

        def fail_companion(source, target):
            if Path(source).name == "metadata.tsv":
                raise OSError("disk full")
            return replace(source, target)

        with patch("mgf_exporter.os.replace", side_effect=fail_companion):
            with self.assertRaises(OSError):
                MGFExporter("dia", overwrite=True).export(self.reader, self.output)
        self.assertEqual(before, (self.output.read_bytes(), first.metadata.read_bytes()))

    def test_same_basename_inputs_receive_distinct_stable_destinations(self):
        inputs = ["/data/a/sample.raw", "/data/b/sample.raw", "/data/a/sample.raw"]
        plan = plan_mgf_outputs(inputs, self.output.parent)
        self.assertEqual(len(set(plan.values())), 2)
        self.assertEqual(plan, plan_mgf_outputs(reversed(inputs), self.output.parent))

    def test_mgf_flags_select_cli(self):
        args = build_arg_parser().parse_args(["--convert-mgf", "--mgf-acquisition", "dia", "--mgf-peak-mode", "recorded"])
        self.assertTrue(_is_cli(args))
        self.assertEqual(args.mgf_acquisition, "dia")
        self.assertEqual(args.mgf_peak_mode, "recorded")


class MGFRawAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import raw_parser
        except (ImportError, RuntimeError, OSError) as exc:
            raise unittest.SkipTest(f"Optional Thermo reader runtime unavailable: {exc}")
        cls.module = raw_parser

    def setUp(self):
        self.source = Mock()
        self.source.GetScanStatsForScanNumber.return_value = SimpleNamespace(IsCentroidScan=True)
        self.scan_filter = SimpleNamespace(Polarity="Positive", GetMass=lambda index: 501.0)
        self.source.GetFilterForScanNumber.return_value = self.scan_filter
        self.reaction = SimpleNamespace(IsolationWidth=20, IsolationWidthOffset=0)
        self.source.GetScanEventForScanNumber.return_value = SimpleNamespace(
            MSOrder=2, GetReaction=lambda index: self.reaction)
        self.extra = SimpleNamespace(Labels=["Monoisotopic M/Z:", "Charge State:"], Values=[500.2, 3])
        self.source.GetTrailerExtraInformation.return_value = self.extra
        self.source.RetentionTimeFromScanNumber.return_value = 2.5
        self.source.GetSegmentedScanFromScanNumber.return_value = SimpleNamespace(Positions=[100], Intensities=[200])
        self.stream = SimpleNamespace(Length=1, Masses=[111], Intensities=[222])
        self.source.GetCentroidStream.return_value = self.stream
        self.source.IncludeReferenceAndExceptionData = False
        self.scan_api = Mock()
        self.scan_api.FromFile.return_value = SimpleNamespace(HasCentroidStream=True, CentroidScan=self.stream)
        self.scan_api.ToCentroid.return_value = SimpleNamespace(HasCentroidStream=True, CentroidScan=self.stream)
        thermo = SimpleNamespace(CommonCore=SimpleNamespace(Data=SimpleNamespace(
            Business=SimpleNamespace(Scan=self.scan_api))))
        for name, replacement in (("IScanEventBase", lambda event: event),
                                  ("DotNetArrayToNPArray", lambda array, dtype: list(array)),
                                  ("ThermoFisher", thermo)):
            patcher = patch.object(self.module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.reader = self.module.MetaXtract.__new__(self.module.MetaXtract)
        self.reader.source = self.source

    def test_legacy_missing_charge_is_not_written_as_negative_one(self):
        for missing in (-1, 0, None):
            self.extra.Values[1] = missing
            self.assertIsNone(self.reader.GetMGFSpectrumFromScanNumber(8)["charge"])
        self.extra.Values[1] = 3
        self.scan_filter.Polarity = "Negative"
        self.assertEqual(self.reader.GetMGFSpectrumFromScanNumber(8)["charge"], -3)

    def test_profile_scan_uses_stored_centroid_stream(self):
        self.source.GetScanStatsForScanNumber.return_value.IsCentroidScan = False
        spectrum = self.reader.GetMGFSpectrumFromScanNumber(8)
        self.assertEqual(spectrum["centroid_source"], "stored_centroid_stream")
        self.assertEqual(spectrum["masses"], [111])
        self.source.GetCentroidStream.assert_called_once_with(8, True)
        self.assertFalse(self.source.IncludeReferenceAndExceptionData)
        self.scan_api.ToCentroid.assert_not_called()

    def test_profile_scan_without_centroid_stream_uses_vendor_centroiding(self):
        self.source.GetScanStatsForScanNumber.return_value.IsCentroidScan = False
        self.source.GetCentroidStream.return_value = None
        self.scan_api.FromFile.return_value.HasCentroidStream = False
        spectrum = self.reader.GetMGFSpectrumFromScanNumber(8)
        self.assertEqual(spectrum["centroid_source"], "vendor_centroiding")
        self.assertEqual(spectrum["intensities"], [222])
        self.scan_api.ToCentroid.assert_called_once()

    def test_profile_scan_cannot_silently_fall_back_to_profile_points(self):
        self.source.GetScanStatsForScanNumber.return_value.IsCentroidScan = False
        self.source.GetCentroidStream.return_value = None
        self.scan_api.FromFile.return_value.HasCentroidStream = False
        self.scan_api.ToCentroid.return_value.HasCentroidStream = False
        with self.assertRaisesRegex(ValueError, "No centroid data"):
            self.reader.GetMGFSpectrumFromScanNumber(8)
        self.source.GetSegmentedScanFromScanNumber.assert_not_called()
        self.assertFalse(self.source.IncludeReferenceAndExceptionData)

    def test_full_precision_monoisotopic_value_uses_typed_api(self):
        self.extra.Values[0] = "500.1235"
        self.source.GetTrailerExtraValue.return_value = 500.123456789012
        data = self.reader.GetMGFSpectrumFromScanNumber(8)
        self.assertEqual(data["monoisotopic_mz"], 500.123456789012)
        self.source.GetTrailerExtraValue.assert_called_once_with(8, 0)

    def test_recorded_profile_does_not_centroid(self):
        self.source.GetScanStatsForScanNumber.return_value.IsCentroidScan = False
        data = self.reader.GetMGFSpectrumFromScanNumber(8, peak_mode="recorded")
        self.assertEqual(data["masses"], [100])
        self.assertEqual(data["peak_source"], "stored_profile")
        self.source.GetCentroidStream.assert_not_called()
        self.scan_api.ToCentroid.assert_not_called()
        self.assertFalse(self.source.IncludeReferenceAndExceptionData)

    def test_ms1_fast_read_tracks_parent_without_reading_peak_arrays(self):
        self.source.GetScanEventForScanNumber.return_value.MSOrder = 1
        self.assertIsNone(self.reader.GetMGFScanData(7))
        self.assertEqual(self.reader._mgf_last_ms1_scan, 7)
        self.source.GetScanStatsForScanNumber.assert_not_called()

    def test_parent_ms1_arrays_are_cached_and_window_is_summed(self):
        self.reader._mgf_last_ms1_scan = 7
        self.source.RunHeaderEx.FirstSpectrum = 1
        stats = self.source.GetScanStatsForScanNumber.return_value
        stats.LowMass, stats.HighMass = 50, 1000
        data = self.source.GetSegmentedScanFromScanNumber.return_value
        data.Positions = [98, 99, 100, 101, 101.5, 102]
        data.Intensities = [10, 20, 30, 40, 50, 60]
        a = self.reader.GetMGFPrecursorIntensityFromScanNumber(8, 100, 1.3)
        b = self.reader.GetMGFPrecursorIntensityFromScanNumber(9, 100, 1.3)
        self.assertEqual(a, (90, 7, "ms1_centroid_window"))
        self.assertEqual(a, b)
        self.source.GetSegmentedScanFromScanNumber.assert_called_once()
        self.assertFalse(self.source.IncludeReferenceAndExceptionData)


if __name__ == "__main__":
    unittest.main()
