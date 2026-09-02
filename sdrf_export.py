from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from sdrf_columns import KNOWN_SDRF_HEADERS


SDRF_VERSION = "v1.1.0"
SDRF_TEMPLATE = "ms-proteomics v1.1.0"
SDRF_ANNOTATION_TOOL = "MetaXtract"
TECHNOLOGY_TYPE = "proteomic profiling by mass spectrometry"

ACQUISITION_METHODS = {
    "dda": "NT=Data-dependent acquisition;AC=PRIDE:0000627",
    "data-dependent acquisition": "NT=Data-dependent acquisition;AC=PRIDE:0000627",
    "dia": "NT=Data-independent acquisition;AC=PRIDE:0000450",
    "data-independent acquisition": "NT=Data-independent acquisition;AC=PRIDE:0000450",
    "prm": "NT=Parallel reaction monitoring;AC=PRIDE:0000629",
    "parallel reaction monitoring": "NT=Parallel reaction monitoring;AC=PRIDE:0000629",
    "srm": "NT=Selected reaction monitoring;AC=PRIDE:0000630",
    "selected reaction monitoring": "NT=Selected reaction monitoring;AC=PRIDE:0000630",
}

CLEAVAGE_AGENTS = {
    "trypsin": "NT=Trypsin;AC=MS:1001251",
    "lys-c": "NT=Lys-C;AC=MS:1001309",
    "lysc": "NT=Lys-C;AC=MS:1001309",
    "chymotrypsin": "NT=Chymotrypsin;AC=MS:1001306",
}

INSTRUMENT_MODELS = {
    "Exactive": "MS:1000649",
    "Exactive Plus": "MS:1002526",
    "LTQ FT": "MS:1000448",
    "LTQ FT Ultra": "MS:1000557",
    "LTQ Orbitrap": "MS:1000449",
    "LTQ Orbitrap Classic": "MS:1002835",
    "LTQ Orbitrap Discovery": "MS:1000555",
    "LTQ Orbitrap Velos": "MS:1001742",
    "LTQ Orbitrap Velos/ETD": "MS:1003499",
    "LTQ Orbitrap XL": "MS:1000556",
    "LTQ Orbitrap XL ETD": "MS:1000639",
    "MALDI LTQ Orbitrap": "MS:1000643",
    "MALDI LTQ Orbitrap Discovery": "MS:1003497",
    "MALDI LTQ Orbitrap XL": "MS:1003496",
    "Orbitrap Astral": "MS:1003378",
    "Orbitrap Astral Zoom": "MS:1003442",
    "Orbitrap Eclipse": "MS:1003029",
    "Orbitrap Elite": "MS:1001910",
    "Orbitrap Exploris 120": "MS:1003095",
    "Orbitrap Exploris 240": "MS:1003094",
    "Orbitrap Exploris 480": "MS:1003028",
    "Orbitrap Exploris GC 240": "MS:1003423",
    "Orbitrap Exploris GC-MS": "MS:1002992",
    "Orbitrap Fusion": "MS:1002416",
    "Orbitrap Fusion ETD": "MS:1002417",
    "Orbitrap Fusion Lumos": "MS:1002732",
    "Orbitrap Velos Pro": "MS:1003096",
    "Q Exactive": "MS:1001911",
    "Q Exactive Focus": "MS:1002993",
    "Q Exactive GC Orbitrap": "MS:1003395",
    "Q Exactive HF": "MS:1002523",
    "Q Exactive HF-X": "MS:1002877",
    "Q Exactive Plus": "MS:1002634",
    "Q Exactive UHMR": "MS:1003245",
    "TSQ": "MS:1000750",
    "TSQ 7000": "MS:1000749",
    "TSQ 8000": "MS:1003503",
    "TSQ 8000 Evo": "MS:1002525",
    "TSQ 9000": "MS:1002876",
    "TSQ Altis": "MS:1002874",
    "TSQ Altis Plus": "MS:1003292",
    "TSQ Certis": "MS:1003800",
    "TSQ Endura": "MS:1002419",
    "TSQ Quantum": "MS:1000199",
    "TSQ Quantum Access": "MS:1000644",
    "TSQ Quantum Access MAX": "MS:1003498",
    "TSQ Quantum Ultra": "MS:1000751",
    "TSQ Quantum Ultra AM": "MS:1000743",
    "TSQ Quantis": "MS:1002875",
    "TSQ Quantiva": "MS:1002418",
    "TSQ Vantage": "MS:1001510",
}

INSTRUMENT_MODELS_BY_KEY = {
    re.sub(r"[^a-z0-9]+", "", name.casefold()): name
    for name in INSTRUMENT_MODELS
}

USER_REQUIRED_FIELDS = (
    ("source_name", "source name"),
    ("assay_name", "assay name"),
    ("organism", "characteristics[organism]"),
    ("organism_part", "characteristics[organism part]"),
    ("biological_replicate", "characteristics[biological replicate]"),
    ("acquisition_method", "comment[proteomics data acquisition method]"),
    ("label", "comment[label]"),
    ("cleavage_agent", "comment[cleavage agent details]"),
    ("fraction_identifier", "comment[fraction identifier]"),
    ("technical_replicate", "comment[technical replicate]"),
)

REQUIRED_SDRF_HEADERS = {
    "source name",
    "assay name",
    "technology type",
    "characteristics[organism]",
    "characteristics[organism part]",
    "characteristics[biological replicate]",
    "comment[proteomics data acquisition method]",
    "comment[instrument]",
    "comment[cleavage agent details]",
    "comment[label]",
    "comment[fraction identifier]",
    "comment[technical replicate]",
    "comment[data file]",
}

AUTOMATIC_SDRF_HEADERS = {
    "technology type",
    "comment[data file]",
    "comment[acquisition date]",
    "comment[sdrf annotation tool]",
    "comment[sdrf version]",
    "comment[sdrf template]",
}

FIXED_SDRF_HEADERS = REQUIRED_SDRF_HEADERS | AUTOMATIC_SDRF_HEADERS
KNOWN_SDRF_HEADER_SET = set(KNOWN_SDRF_HEADERS)
KNOWN_SDRF_HEADERS_BY_CASEFOLD = {
    header.casefold(): header for header in KNOWN_SDRF_HEADERS
}


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _known_text(value) -> str:
    cleaned = _text(value)
    if cleaned.casefold() in {"", "unknown", "n/a", "not available"}:
        return ""
    return cleaned


def raw_instrument_name(raw_parser) -> str:
    """Return the best instrument model reported by an open RAW parser."""
    try:
        instrument_details = raw_parser.GetInstrumentDetails() or {}
    except Exception:
        instrument_details = {}

    candidates = [
        instrument_details.get("Instrument Model"),
        instrument_details.get("Instrument Name"),
    ]
    try:
        candidates.append(raw_parser.GetInstrumentName())
    except Exception:
        pass

    return next((_known_text(value) for value in candidates if _known_text(value)), "")


def normalize_acquisition_method(value: str) -> str:
    cleaned = _text(value)
    return ACQUISITION_METHODS.get(cleaned.casefold(), cleaned)


def normalize_cleavage_agent(value: str) -> str:
    cleaned = _text(value)
    return CLEAVAGE_AGENTS.get(cleaned.casefold(), cleaned)


def _instrument_key(value: str) -> str:
    cleaned = _text(value).casefold()
    cleaned = re.sub(r"\bthermo(?: fisher)? scientific\b", " ", cleaned)
    cleaned = re.sub(r"\bmass spectrometer\b|\bspectrometer\b", " ", cleaned)
    cleaned = re.sub(r"\bms\b", " ", cleaned)
    cleaned = re.sub(r"\borbitrap$", " ", cleaned)
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def normalize_instrument(value: str) -> str:
    cleaned = _known_text(value)
    if not cleaned or cleaned.startswith("NT="):
        return cleaned

    key = _instrument_key(cleaned)
    exact_name = INSTRUMENT_MODELS_BY_KEY.get(key)
    if exact_name:
        return f"NT={exact_name};AC={INSTRUMENT_MODELS[exact_name]}"

    for name in sorted(INSTRUMENT_MODELS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name.casefold())}\b", cleaned.casefold()):
            return f"NT={name};AC={INSTRUMENT_MODELS[name]}"
    return cleaned


def normalize_acquisition_date(value) -> str:
    cleaned = _text(value)
    if not cleaned:
        return "not available"
    try:
        return datetime.fromisoformat(cleaned).isoformat(timespec="seconds")
    except ValueError:
        pass

    for date_format in (
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, date_format).isoformat(timespec="seconds")
        except ValueError:
            continue
    return "not available"


def available_sdrf_columns(existing_headers=()) -> list[str]:
    """Return official registry columns that are not already in the editor."""
    existing = {_text(header).casefold() for header in existing_headers}
    return [
        header
        for header in KNOWN_SDRF_HEADERS
        if header.casefold() not in existing
        and header not in FIXED_SDRF_HEADERS
    ]


def _normalized_extra_columns(extra_columns) -> list[str]:
    normalized = []
    seen = set()
    for value in extra_columns or []:
        cleaned = _text(value)
        folded = cleaned.casefold()
        header = KNOWN_SDRF_HEADERS_BY_CASEFOLD.get(folded, folded)
        if not header or folded in seen:
            continue
        normalized.append(header)
        seen.add(folded)
    return normalized


def _valid_factor_header(header: str) -> bool:
    return bool(re.fullmatch(r"factor value\[[^\[\]\t\r\n]+\]", header))


def _user_field_for_header(header: str) -> str | None:
    normalized = _text(header).casefold()
    if normalized in {"file", "raw file", "raw_file", "comment[data file]"}:
        return "file"
    if normalized == "source name":
        return "source_name"
    if normalized == "assay name":
        return "assay_name"
    if normalized == "characteristics[organism]":
        return "organism"
    if normalized == "characteristics[organism part]":
        return "organism_part"
    if normalized == "characteristics[biological replicate]":
        return "biological_replicate"
    if normalized == "comment[proteomics data acquisition method]":
        return "acquisition_method"
    if normalized == "comment[label]":
        return "label"
    if normalized == "comment[cleavage agent details]":
        return "cleavage_agent"
    if normalized == "comment[fraction identifier]":
        return "fraction_identifier"
    if normalized == "comment[technical replicate]":
        return "technical_replicate"
    if normalized == "comment[instrument]":
        return "instrument_override"
    return None


def _selected_file_lookup(selected_files: list[str]) -> dict[str, str]:
    lookup = {}
    for file_path in selected_files:
        file_text = str(file_path)
        lookup[file_text] = file_text
        lookup[Path(file_text).name] = file_text
    return lookup


def read_sdrf_user_metadata(
    metadata_path: str | Path,
    selected_files: list[str],
) -> tuple[list[dict], list[str]]:
    """Read user-supplied SDRF fields for CLI runs."""
    selected_lookup = _selected_file_lookup(selected_files)
    metadata_path = Path(metadata_path)
    with metadata_path.open("r", newline="", encoding="utf-8-sig") as metadata_file:
        reader = csv.DictReader(metadata_file, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"{metadata_path} does not contain a TSV header.")

        extra_columns = []
        internal_fields = {}
        for header in reader.fieldnames:
            cleaned_header = _text(header)
            field = _user_field_for_header(cleaned_header)
            if field is not None:
                internal_fields[cleaned_header] = field
            elif cleaned_header in AUTOMATIC_SDRF_HEADERS:
                continue
            else:
                canonical = _normalized_extra_columns([cleaned_header])
                extra_columns.append(canonical[0] if canonical else cleaned_header)

        rows = []
        for source_row in reader:
            row = {}
            for header, value in source_row.items():
                cleaned_header = _text(header)
                field = internal_fields.get(cleaned_header)
                cleaned_value = _text(value)
                if field == "file":
                    row[field] = selected_lookup.get(cleaned_value, cleaned_value)
                elif field:
                    row[field] = cleaned_value
                elif cleaned_header in AUTOMATIC_SDRF_HEADERS:
                    continue
                else:
                    canonical = _normalized_extra_columns([cleaned_header])
                    row[canonical[0] if canonical else cleaned_header] = cleaned_value
            rows.append(row)

    return rows, _normalized_extra_columns(extra_columns)


def write_sdrf_cli_template(
    output_path: str | Path,
    selected_files: list[str],
) -> Path:
    """Write a fillable TSV containing the SDRF fields CLI users must provide."""
    headers = [
        "RAW file",
        *[label for _, label in USER_REQUIRED_FIELDS],
        "comment[instrument]",
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file, delimiter="\t", lineterminator="\n")
        writer.writerow(headers)
        for file_path in selected_files:
            base = Path(file_path).stem
            writer.writerow(
                [
                    str(file_path),
                    base,
                    base,
                    "",
                    "not available",
                    "1",
                    "",
                    "",
                    "",
                    "1",
                    "1",
                    "",
                ]
            )
    return output_path


def validate_sdrf_metadata(
    rows: list[dict],
    selected_files: list[str],
    factor_name: str = "",
    extra_columns: list[str] | None = None,
) -> list[str]:
    errors = []
    if not rows:
        return ["Add at least one sample-to-file row."]

    selected = set(map(str, selected_files))
    represented = set()
    uniqueness_keys = set()
    extra_headers = _normalized_extra_columns(extra_columns)
    legacy_factor_header = ""
    if factor_name:
        legacy_factor_header = f"factor value[{_text(factor_name).casefold()}]"
        if legacy_factor_header not in extra_headers:
            extra_headers.append(legacy_factor_header)

    for header in extra_headers:
        if header in FIXED_SDRF_HEADERS:
            errors.append(f"{header} is already a required or automatically filled column.")
        elif header not in KNOWN_SDRF_HEADER_SET and not _valid_factor_header(header):
            errors.append(f"{header} is not a known SDRF column name.")

    for row_number, row in enumerate(rows, start=1):
        file_path = _text(row.get("file"))
        if file_path not in selected:
            errors.append(f"Row {row_number}: select one of the loaded RAW files.")
        else:
            represented.add(file_path)

        for field, label in USER_REQUIRED_FIELDS:
            if not _text(row.get(field)):
                errors.append(f"Row {row_number}: {label} is required.")

        for field, label in (
            ("source_name", "source name"),
            ("assay_name", "assay name"),
            ("organism", "characteristics[organism]"),
            ("acquisition_method", "comment[proteomics data acquisition method]"),
            ("label", "comment[label]"),
            ("cleavage_agent", "comment[cleavage agent details]"),
        ):
            if _text(row.get(field)).casefold() == "not available":
                errors.append(f"Row {row_number}: {label} cannot be 'not available'.")

        biological_replicate = _text(row.get("biological_replicate"))
        if biological_replicate != "pooled" and not _positive_integer(biological_replicate):
            errors.append(f"Row {row_number}: biological replicate must be a positive integer or 'pooled'.")
        for field, label in (
            ("fraction_identifier", "fraction identifier"),
            ("technical_replicate", "technical replicate"),
        ):
            if not _positive_integer(_text(row.get(field))):
                errors.append(f"Row {row_number}: {label} must be a positive integer.")

        for header in extra_headers:
            value = row.get("factor_value") if header == legacy_factor_header else row.get(header)
            if not _text(value):
                errors.append(f"Row {row_number}: {header} cannot be empty once added.")

        has_dynamic_factor = any(_valid_factor_header(header) for header in extra_headers)
        if not factor_name and not has_dynamic_factor and _text(row.get("factor_value")):
            errors.append(
                f"Row {row_number}: enter a factor name or clear the factor value."
            )

        uniqueness_key = tuple(
            _text(row.get(field)) for field in ("source_name", "assay_name", "label")
        )
        if uniqueness_key in uniqueness_keys:
            errors.append(
                f"Row {row_number}: source name + assay name + label must be unique."
            )
        uniqueness_keys.add(uniqueness_key)

    for missing_file in sorted(selected - represented):
        errors.append(f"No SDRF row is assigned to {missing_file}.")

    if factor_name and not re.fullmatch(r"[^\[\]\t\r\n]+", factor_name):
        errors.append("Factor name cannot contain brackets, tabs, or line breaks.")

    return errors


def _positive_integer(value: str) -> bool:
    try:
        return int(value) >= 1 and str(int(value)) == value
    except (TypeError, ValueError):
        return False


def enrich_sdrf_rows_for_file(
    user_rows: list[dict],
    file_path: str,
    instrument: str,
    acquisition_date,
) -> list[dict]:
    enriched = []
    for user_row in user_rows:
        if _text(user_row.get("file")) != str(file_path):
            continue
        row = dict(user_row)
        row["file"] = str(file_path)
        row["data_file"] = Path(file_path).name
        row["instrument"] = normalize_instrument(
            _known_text(row.get("instrument_override")) or _known_text(instrument)
        )
        row["acquisition_date"] = normalize_acquisition_date(acquisition_date)
        row["acquisition_method"] = normalize_acquisition_method(row.get("acquisition_method", ""))
        row["cleavage_agent"] = normalize_cleavage_agent(row.get("cleavage_agent", ""))
        enriched.append(row)
    return enriched


def draft_sdrf_row_for_file(
    file_path: str,
    instrument: str,
    acquisition_date,
) -> dict:
    base = Path(file_path).stem
    return {
        "file": str(file_path),
        "source_name": base,
        "assay_name": base,
        "organism": "",
        "organism_part": "",
        "biological_replicate": "",
        "acquisition_method": "",
        "label": "",
        "instrument": normalize_instrument(instrument),
        "cleavage_agent": "",
        "fraction_identifier": "",
        "technical_replicate": "",
        "data_file": Path(file_path).name,
        "acquisition_date": normalize_acquisition_date(acquisition_date),
    }


def write_sdrf(
    output_path: str | Path,
    rows: list[dict],
    factor_name: str = "",
    extra_columns: list[str] | None = None,
) -> Path:
    factor_name = _text(factor_name).casefold()
    extra_headers = _normalized_extra_columns(extra_columns)
    legacy_factor_header = f"factor value[{factor_name}]" if factor_name else ""
    if legacy_factor_header and legacy_factor_header not in extra_headers:
        extra_headers.append(legacy_factor_header)

    characteristic_headers = [
        header for header in extra_headers if header.startswith("characteristics[")
    ]
    factor_headers = [header for header in extra_headers if _valid_factor_header(header)]
    other_headers = [
        header
        for header in extra_headers
        if header not in characteristic_headers and header not in factor_headers
    ]

    headers = [
        "source name",
        "characteristics[organism]",
        "characteristics[organism part]",
        "characteristics[biological replicate]",
        *characteristic_headers,
        "assay name",
        "technology type",
        "comment[proteomics data acquisition method]",
        "comment[label]",
        "comment[instrument]",
        "comment[cleavage agent details]",
        "comment[fraction identifier]",
        "comment[technical replicate]",
        "comment[data file]",
        "comment[acquisition date]",
        "comment[sdrf annotation tool]",
        "comment[sdrf version]",
        "comment[sdrf template]",
        *other_headers,
        *factor_headers,
    ]

    output_rows = []
    for row in rows:
        fixed_values = {
            "source name": row.get("source_name"),
            "characteristics[organism]": row.get("organism"),
            "characteristics[organism part]": row.get("organism_part"),
            "characteristics[biological replicate]": row.get("biological_replicate"),
            "assay name": row.get("assay_name"),
            "technology type": TECHNOLOGY_TYPE,
            "comment[proteomics data acquisition method]": row.get("acquisition_method"),
            "comment[label]": row.get("label"),
            "comment[instrument]": row.get("instrument"),
            "comment[cleavage agent details]": row.get("cleavage_agent"),
            "comment[fraction identifier]": row.get("fraction_identifier"),
            "comment[technical replicate]": row.get("technical_replicate"),
            "comment[data file]": row.get("data_file"),
            "comment[acquisition date]": row.get("acquisition_date") or "not available",
            "comment[sdrf annotation tool]": SDRF_ANNOTATION_TOOL,
            "comment[sdrf version]": SDRF_VERSION,
            "comment[sdrf template]": SDRF_TEMPLATE,
        }
        values = []
        for header in headers:
            if header in fixed_values:
                values.append(fixed_values[header])
            elif header == legacy_factor_header:
                values.append(row.get(header) or row.get("factor_value"))
            else:
                values.append(row.get(header))
        output_rows.append([_text(value) for value in values])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.writer(output_file, delimiter="\t", lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(output_rows)
    return output_path
