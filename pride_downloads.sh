#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="MetaXtract_Thermo_RAW_Showcase"
MANIFEST="${BASE_DIR}/raw_file_manifest.tsv"

mkdir -p "${BASE_DIR}"

download_raw() {
    local instrument="$1"
    local pxd="$2"
    local acquisition="$3"
    local url="$4"

    local filename
    local folder
    local output

    filename="$(basename "${url}")"
    folder="${BASE_DIR}/${instrument}_${pxd}"
    output="${folder}/${filename}"

    mkdir -p "${folder}"

    echo
    echo "============================================================"
    echo "Instrument : ${instrument}"
    echo "PXD        : ${pxd}"
    echo "Acquisition: ${acquisition}"
    echo "File       : ${filename}"
    echo "============================================================"

    wget \
        --continue \
        --show-progress \
        --output-document="${output}" \
        "${url}"
}


# ============================================================
# Orbitrap Astral
# PXD072131
# DIA
# ============================================================

download_raw \
    "Orbitrap_Astral" \
    "PXD072131" \
    "DIA" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/07/PXD072131/AST_SJE_20241213_E24_003_8_15cm.raw"

download_raw \
    "Orbitrap_Astral" \
    "PXD072131" \
    "DIA" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/07/PXD072131/AST_SJE_20241213_E24_003_7.raw"


# ============================================================
# Orbitrap Ascend
# PXD070486
#
# Top-down / targeted MS/MS
# File name explicitly indicates targeted ETD.
# ============================================================

download_raw \
    "Orbitrap_Ascend" \
    "PXD070486" \
    "Targeted_ETD" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/02/PXD070486/20240326_SPM_50nl_25ng_OT_7p5_120k_res_Targeted_ETD_3ms_10.raw"


# ============================================================
# Orbitrap Exploris 480
# PXD069212
# DIA
# ============================================================

download_raw \
    "Orbitrap_Exploris_480" \
    "PXD069212" \
    "DIA" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/04/PXD069212/01_TK_ENplus_Hu_Plasma_DIA_Source-1_1.raw"


# ============================================================
# Orbitrap Fusion Lumos
# PXD081636
#
# TMTpro MS3 experiment. DDA
# This is essentially a DDA/TMT-MS3 workflow rather than DIA.
# ============================================================

download_raw \
    "Orbitrap_Fusion_Lumos" \
    "PXD081636" \
    "DDA_TMTpro_MS3" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/07/PXD081636/YeastAgingvsWhi5atc_Std_F10_R1_T1_TMTMS3pro001_002522_JASK013_FL1.raw"


# ============================================================
# PXD083028
# Q Exactive HF
# DDA library fraction.
#
# The filename explicitly contains DDALib.
# I keep the instrument folder conservative here until the
# ============================================================

download_raw \
    "Q_Exactive_HF" \
    "PXD083028" \
    "DDA_Library" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/08/PXD083028/20220106_QE5_YABH_RDS3363_PlasmaProt_Mouse_GDF15_DDALib_NonDe_F02.raw"


# ============================================================
# Orbitrap Eclipse
# PXD082542
# Proteomics experiment
# ============================================================

download_raw \
    "Orbitrap_Eclipse" \
    "PXD082542" \
    "DDA" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/08/PXD082542/20250417_Khavari_IFerguson_15015_5_C1.raw"


# ============================================================
# PXD080728
#
# Orbitrap Astral Zoom
# DIA
# ============================================================

download_raw \
    "Orbitrap_Astral_Zoom" \
    "PXD080728" \
    "DIA" \
    "https://ftp.pride.ebi.ac.uk/pride/data/archive/2026/08/PXD080728/20260629_AZ2_NEO6_SCL-IAH_50ID_HeLa_250pg_425-625_10.raw"



printf "Instrument\tPXD\tAcquisition\tFilename\tSize_bytes\tsize_gb\n" \
    > "${MANIFEST}"

add_to_manifest() {
    local instrument="$1"
    local pxd="$2"
    local acquisition="$3"
    local filename="$4"

    local path="${BASE_DIR}/${instrument}_${pxd}/${filename}"

    if [[ ! -f "${path}" ]]; then
        echo "WARNING: file not found: ${path}" >&2
        return
    fi

    local size_bytes
    local size_gb

    size_bytes="$(stat -c '%s' "${path}")"
    size_gb="$(du -h "${path}" | cut -f1)"

    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
        "${instrument}" \
        "${pxd}" \
        "${acquisition}" \
        "${filename}" \
        "${size_bytes}" \
        "${size_gb}" \
        >> "${MANIFEST}"
}


add_to_manifest \
    "Orbitrap_Astral" \
    "PXD072131" \
    "DIA" \
    "AST_SJE_20241213_E24_003_8_15cm.raw"

add_to_manifest \
    "Orbitrap_Astral" \
    "PXD072131" \
    "DIA" \
    "AST_SJE_20241213_E24_003_7.raw"

add_to_manifest \
    "Orbitrap_Ascend" \
    "PXD070486" \
    "Targeted_ETD" \
    "20240326_SPM_50nl_25ng_OT_7p5_120k_res_Targeted_ETD_3ms_10.raw"

add_to_manifest \
    "Orbitrap_Exploris_480" \
    "PXD069212" \
    "DIA" \
    "01_TK_ENplus_Hu_Plasma_DIA_Source-1_1.raw"

add_to_manifest \
    "Orbitrap_Fusion_Lumos" \
    "PXD081636" \
    "DDA_TMTpro_MS3" \
    "YeastAgingvsWhi5atc_Std_F10_R1_T1_TMTMS3pro001_002522_JASK013_FL1.raw"

add_to_manifest \
    "Q_Exactive_HF" \
    "PXD083028" \
    "DDA_Library" \
    "20220106_QE5_YABH_RDS3363_PlasmaProt_Mouse_GDF15_DDALib_NonDe_F02.raw"

add_to_manifest \
    "Orbitrap_Eclipse" \
    "PXD082542" \
    "DDA" \
    "20250417_Khavari_IFerguson_15015_5_C1.raw"

add_to_manifest \
    "Orbitrap_Astral_Zoom" \
    "PXD080728" \
    "DIA" \
    "20260629_AZ2_NEO6_SCL-IAH_50ID_HeLa_250pg_425-625_10.raw"


echo
echo "============================================================"
echo "Downloads complete."
echo "Manifest: ${MANIFEST}"
echo "============================================================"
echo

column -t -s $'\t' "${MANIFEST}" || cat "${MANIFEST}"