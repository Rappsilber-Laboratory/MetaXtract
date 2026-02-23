# python .\main.py --config .\config.yml
#pyinstaller --noconfirm --onedir --console --name MetaXtract   --icon assets/icon.ico   --add-data "os_data;os_data"   --add-data "assets;assets"   --hidden-import=clr --hidden-import=System --hidden-import=pythonnet   --hidden-import=matplotlib.backends.backend_pdf --hidden-import=matplotlib.backends   --collect-all PySide6   --collect-all h5py   --collect-submodules h5py   --exclude-module PyQt6 --exclude-module PyQt6.sip --exclude-module PyQt6.QtCore --exclude-module PyQt6.QtGui --exclude-module PyQt6.QtWidgets   main.py
from __future__ import annotations

import sys
import argparse
from pathlib import Path


def _is_cli(args: argparse.Namespace) -> bool:
    return any(
        [
            bool(getattr(args, "config", None)),
            bool(getattr(args, "input", None)),
            bool(getattr(args, "output_dir", None)),
            bool(getattr(args, "file_based_details", False)),
            bool(getattr(args, "ms_method", False)),
            bool(getattr(args, "lc_method", False)),
            bool(getattr(args, "graphical_representation", False)),
            bool(getattr(args, "complete_ms1", False)),
            bool(getattr(args, "complete_ms2", False)),
            bool(getattr(args, "ms2_peaklist_export", False)),
            bool(getattr(args, "ms1_peaklist_export", False))
        ]
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MetaXtract")

    p.add_argument("--config", type=str, help="Path to YAML configuration file")

    p.add_argument("--input", nargs="+", help="Path(s) to RAW files (overrides config io.input)")
    p.add_argument("--output-dir", dest="output_dir", help="Output directory (overrides config io.output_dir)")

    p.add_argument("--file-based-details", dest="file_based_details", action="store_true", help="Extract file-based details")
    p.add_argument("--ms-method", dest="ms_method", action="store_true", help="Extract MS method")
    p.add_argument("--lc-method", dest="lc_method", action="store_true", help="Extract LC method")
    p.add_argument(
        "--hdf5-export",
        dest="hdf5_export",
        action="store_true",
        help="Export MS2 as AnnData HDF5 (.h5ad)",
    )

    p.add_argument(
        "--graphical-representation",
        dest="graphical_representation",
        action="store_true",
        help="Generate HTML visualisations",
    )

    p.add_argument("--complete-ms1", dest="complete_ms1", action="store_true", help="Select all MS1 scan header columns")
    p.add_argument("--complete-ms2", dest="complete_ms2", action="store_true", help="Select all MS2 scan header columns")
    p.add_argument("--ms2-peaklist-export", dest="ms2_peaklist_export", action="store_true", help="Export MS2 extended peak list as Parquet",)
    p.add_argument("--ms1-peaklist-export", dest="ms1_peaklist_export", action="store_true", help="Export MS1 peak list as Parquet",)

    return p


def main() -> None:
    parser = build_arg_parser()
    args, _unknown = parser.parse_known_args()

    if _is_cli(args):
        from cli_parser import run_cli

        run_cli(args)
        return

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon

    from gui import MetaXtract_GUI

    app = QApplication(sys.argv)

    icon_path = Path(__file__).parent / "assets" / "icon.ico"
    app.setWindowIcon(QIcon(str(icon_path)))
    window = MetaXtract_GUI()
    window.resize(650, 800)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
