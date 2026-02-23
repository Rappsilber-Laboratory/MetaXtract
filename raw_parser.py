import os
import sys
import numpy as np
import time
import clr
import System
from tqdm import tqdm
import pyarrow as pa
import pyarrow.parquet as pq
import re
import ctypes


clr.AddReference('System')
from System.Threading import Thread
from System.Globalization import CultureInfo
CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture
CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture
System.Threading.Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture
System.Threading.Thread.CurrentThread.CurrentUICulture = CultureInfo.InvariantCulture

de_fr = CultureInfo('fr-FR')
other = CultureInfo('en-US')

Thread.CurrentThread.CurrentCulture = other
Thread.CurrentThread.CurrentUICulture = other

path = os.path.dirname(os.path.abspath(__file__))
clr.AddReference(os.path.join(path, "os_data/ThermoFisher.CommonCore.Data.dll"))
clr.AddReference(os.path.join(path, "os_data/ThermoFisher.CommonCore.RawFileReader.dll"))
import ThermoFisher
from ThermoFisher.CommonCore.Data.Interfaces import IScanEventBase, IScanEvent

from System.Runtime.InteropServices import GCHandle, GCHandleType

#from scan_dumper import ScanDumper

_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

def _to_float(x, default=np.nan):
    if x is None:
        return default
    if isinstance(x, (int, float, np.floating, np.integer)):
        try:
            return float(x)
        except Exception:
            return default
    s = str(x).strip()
    if not s:
        return default
    m = _NUM_RE.search(s)
    if not m:
        return default
    token = m.group(0).replace(",", ".")
    try:
        return float(token)
    except Exception:
        return default

def _to_int(x, default=-1):
    v = _to_float(x, default=np.nan)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    try:
        return int(v)
    except Exception:
        return default
    

def DotNetArrayToNPArray(src, dtype=None):
    '''
    See https://mail.python.org/pipermail/pythondotnet/2014-May/001527.html
    '''
    if src is None:
        return np.array([], dtype=np.float64)
    src_hndl = GCHandle.Alloc(src, GCHandleType.Pinned)
    try:
        src_ptr = src_hndl.AddrOfPinnedObject().ToInt64()
        bufType = ctypes.c_double*len(src)
        cbuf = bufType.from_address(src_ptr)
        dest = np.frombuffer(cbuf, dtype=cbuf._type_).copy()
    finally:
        if src_hndl.IsAllocated: src_hndl.Free()
        return dest
    

class MetaXtract:
    # Inspired by pyRawFileReader in [pDeep3](https://github.com/pFindStudio/pDeep3)@Zeng,Wen-Feng
    
    def __init__(self, filename, **kwargs):

        self.filename = os.path.abspath(filename)
        self.filename = os.path.normpath(self.filename)

        self.source = ThermoFisher.CommonCore.RawFileReader.RawFileReaderAdapter.FileFactory(self.filename)

        if not self.source.IsOpen:
            raise IOError(
                "RAWfile '{0}' could not be opened, is the file accessible ?".format(
                    self.filename))
        self.source.SelectInstrument(ThermoFisher.CommonCore.Data.Business.Device.MS, 1)

        try:
            self.StartTime = self.source.RunHeaderEx.StartTime # Start time of the first scan or reading for the current controller
            self.EndTime = self.source.RunHeaderEx.EndTime # End time of the last scan or reading for the current controller
            self.FirstSpectrumNumber = self.source.RunHeaderEx.FirstSpectrum # First scan or reading number for the current controller
            self.LastSpectrumNumber = self.source.RunHeaderEx.LastSpectrum # Last scan or reading number for the current controller
            self.LowMass = self.source.RunHeaderEx.LowMass # Lowest mass or wavelength recorded for the current controller.
            self.HighMass = self.source.RunHeaderEx.HighMass # Highest mass or wavelength recorded for the current controller
            self.MassResolution = self.source.RunHeaderEx.MassResolution # Mass resolution value recorded for the current controller. The value is returned as one half of the mass resolution. 
            self.InstrumentCount = self.source.InstrumentCount # Number of instruments
            self.NumSpectra = self.source.RunHeaderEx.SpectraCount # Total number of MS1 and MS2 spectra
            self.NumMS2Centroid = 0
            self.NumMS2Profile = 0
            self.NumMS1 = 0
            self.MS2ScanNumbers = []
            self.MS1ScanNumbers = []
            self.DiffScans = 0
            self.AccScans = 0
            self.PositiveTestFile = None
            self.NegativeTestFile = None
            self.PositiveTestFile = "./p.log" # This file contains the positive selected precursor masses with digits improvement
            self.NegativeTestFile = "./n.log" # This file contains the mono preucursor masses, which contains only four digits
            
            #with open(self.PositiveTestFile, 'w') as file:
            #    pass
            #with open(self.NegativeTestFile, 'w') as file:
            #    pass
            
        except Exception as e:
            raise IOError(f'{e}')
        
    def GetMS2PeakListArraysFromScanNumber(self, scanNumber: int):
        return self.GetMS2PeakListArraysFromScanNumberTest(scanNumber)

    def CountMS2(self) -> None:
        """
        Count number of MS2 spectra in the raw file.

        This function takes a no arguments, it fills the internal class variables NumMS2Centroid, NumMS2Profile, and NumMS1.

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            None.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and count the different spectras from it.
        """

        try:
            if not hasattr(self, 'NumSpectra') or not isinstance(self.NumSpectra, int):
                raise ValueError("Invalid or missing 'NumSpectra' attribute.")

            self.NumMS2Centroid = 0
            self.NumMS2Profile = 0
            self.NumMS1 = 0

            for scanNumber in range(1, self.NumSpectra + 1):
                try:
                    scanStatistics = self.source.GetScanStatsForScanNumber(scanNumber)
                    scanEvent = self.source.GetScanEventForScanNumber(scanNumber)

                    if scanStatistics is None or scanEvent is None:
                        print(f"Warning: Scan {scanNumber} returned None values and was skipped.")
                        continue

                    scanMSOrder = int(IScanEventBase(scanEvent).MSOrder)

                    if getattr(scanStatistics, 'IsCentroidScan', False):
                        if scanMSOrder == 2:
                            self.NumMS2Centroid += 1
                            self.MS2ScanNumbers.append(scanNumber)
                        else:
                            self.NumMS1 += 1
                            self.MS1ScanNumbers.append(scanNumber)
                    else:
                        if scanMSOrder == 2:
                            self.NumMS2Profile += 1
                        else:
                            self.NumMS1 += 1
                            self.MS1ScanNumbers.append(scanNumber)

                except AttributeError as e:
                    print(f"Error processing scan {scanNumber}: {e}")
                    continue

                except Exception as e:
                    print(f"Unexpected error at scan {scanNumber}: {e}")
                    continue

        except ValueError as e:
            print(f"ValueError encountered: {e}")

        except Exception as e:
            print(f"Critical error during CountMS2 execution: {e}")
                    
                    
    def GetMS2MonoMzFromScanNumber(self, scanNumber: int) -> float:
        
        """
        Get MS2 monoisotopic M/Z from specific scan.

        This function takes the scan number as argument and use it to map the trailer information from the raw file to 
        the index of the scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            float conversion from the monoisotopic M/Z mass.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the 'Monoisotopic M/Z' from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data structure missing required attributes for scan {scanNumber}")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in trailerData.Labels or []]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            mono_mz = trailerDataDict.get('Monoisotopic M/Z', np.nan)
            #return float(mono_mz) if mono_mz is not None else np.nan
            return _to_float(mono_mz, default=np.nan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.nan

    
    def GetTrailerExtraInformaionEdited(self, scanNumber: int) -> dict:
        """
        Get trailer extra information edited

        This function takes the scan number as argument and use it to extract the trailer information and change them regarding 
        the target dict.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            dict conversion from the raw dict.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the 'trailer information from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data for scan {scanNumber} is missing required attributes")

            trailerDataLabels = [
                x[:-1] if x and x[-1] == ":" else x for x in (trailerData.Labels or [])
            ]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            return trailerDataDict

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return {}

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return {} 
    

    def GetMS2ChargeFromScanNumber(self, scanNumber: int) -> int:
        """
        Get MS2-scan's charge from specific scan.

        This function takes the scan number as argument and use it to map the trailer information from the raw file to 
        the index of the scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            int conversion from the charge state of the precursor.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the 'Charge State' from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data for scan {scanNumber} is missing required attributes")

            trailerDataLabels = [
                x[:-1] if x and x[-1] == ":" else x for x in (trailerData.Labels or [])
            ]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            charge_state = trailerDataDict.get('Charge State', -1)
            return int(charge_state) if charge_state is not None else -1

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return -1

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return -1
    
    
    def GetMS2MZArrayFromScanNumber(self, scanNumber: int) -> np.array:
        """
        Get MS2 MZ array from specific scan.

        This function takes the scan number as argument and use it to map the trailer information from the raw file to 
        the index of the scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            np.array[float] of the M/Z masses of the corresponding scan.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the spectra masses from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            scanStatistics = self.source.GetScanStatsForScanNumber(scanNumber)
            if scanStatistics is None:
                raise ValueError(f"No scan statistics found for scan number {scanNumber}")

            if not hasattr(scanStatistics, 'IsCentroidScan') or not scanStatistics.IsCentroidScan:
                raise ValueError(f"Scan {scanNumber} is not a centroid scan")

            scanEvent = self.source.GetScanEventForScanNumber(scanNumber)
            if scanEvent is None:
                raise ValueError(f"No scan event found for scan number {scanNumber}")

            scanMSOrder = int(IScanEventBase(scanEvent).MSOrder)
            if scanMSOrder != 2:
                raise ValueError(f"Scan {scanNumber} is not an MS2 scan")

            stream = self.source.GetCentroidStream(scanNumber, False)
            if stream is None or not hasattr(stream, 'Masses'):
                raise ValueError(f"Failed to retrieve centroid data for scan {scanNumber}")

            mz_array = np.array(DotNetArrayToNPArray(stream.Masses, float))

            return mz_array

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.array([])  

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.array([])
    
    
    def CheckMS2Centroid(self, scanNumber: int) -> bool:
        """
        Check if scan is centroid.

        This function takes the scan number as argument and use it to map the trailer information from the raw file to 
        the index of the scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            bool the bool value indicates if the scan is centroid.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the scan realted identifier from it.
        """
        #return (self.source.GetScanStatsForScanNumber(scanNumber)).IsCentroidScan
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            scanStats = self.source.GetScanStatsForScanNumber(scanNumber)
            if scanStats is None:
                raise ValueError(f"No scan statistics found for scan number {scanNumber}")

            if not hasattr(scanStats, 'IsCentroidScan'):
                raise ValueError(f"Scan statistics do not contain centroid scan information for scan {scanNumber}")

            return bool(scanStats.IsCentroidScan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return False  

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return False 
    
    
    def CheckRoundDigits(self, isolationMzPossiblyWithOffset: float, monoMZ: float) -> bool:
        """
        Check the possibility of masses improvement regarding MS2 scan.

        This function is used as a feedback stop to use new value of the mass or keep 
        the one read directly from the raw file. The function checks if rounding 
        three digits of each masses will give the same value. Using this step, we 
        are able to improve the precursor mass of some scans without any need to 
        do any extra computations.

        Args:
            self (class object): the main class object of the Raw_Parser.
            isolationMzPossiblyWithOffset (float): precursor mass from the reaction.
            monoMZ (float): precursor mass which is extracted from the raw file as 
            monoisotopic M/Z mass.

        Returns:
            bool the bool value indicates if both values are same with digits improvement.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the scan realted identifier from it.
        """
        rounded_isolationMzPossiblyWithOffset = round(isolationMzPossiblyWithOffset, 3)
        rounded_monoMZ = round(monoMZ, 3)
        
        return (rounded_isolationMzPossiblyWithOffset == rounded_monoMZ)
    
    
    def GetMS2IntensitiesArrayFromScanNumber(self, scanNumber: int) -> np.array:
        """
        Get intensity list from the scan number.

        This function extracts the intensities list using the scan number from
        the raw file by parsing the statistics c# object.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            np.array[float] values of the intensites called from raw file.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the inteisites list from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            if not self.CheckMS2Centroid(scanNumber):
                raise ValueError(f"Scan {scanNumber} is not a centroid scan.")

            scanEvent = self.source.GetScanEventForScanNumber(scanNumber)
            if scanEvent is None:
                raise ValueError(f"No scan event found for scan number {scanNumber}")

            scanMSOrder = int(IScanEventBase(scanEvent).MSOrder)
            if scanMSOrder != 2:
                raise ValueError(f"Scan {scanNumber} is not an MS2 scan.")

            stream = self.source.GetCentroidStream(scanNumber, False)
            if stream is None or not hasattr(stream, 'Intensities'):
                raise ValueError(f"Failed to retrieve intensity data for scan {scanNumber}")

            intensity_array = np.array(DotNetArrayToNPArray(stream.Intensities, float))

            return intensity_array

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.array([]) 

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.array([])
    
    
    def GetMasterScanNumber(self, MS2ScarNumber: int) -> int:
        """
        Get master scan number of the MS2 scan.

        This function extracts the master scan number from the MS2 scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            MS2ScarNumber (int): number of the MS2 scan.

        Returns:
            int master scan number as integer value.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the master scan number from it.
        """

        try:
            if not isinstance(MS2ScarNumber, int) or MS2ScarNumber < 1:
                raise ValueError(f"Invalid MS2 scan number provided: {MS2ScarNumber}")

            trailerData = self.source.GetTrailerExtraInformation(MS2ScarNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {MS2ScarNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data for scan {MS2ScarNumber} is missing required attributes")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in (trailerData.Labels or [])]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            master_scan_number = trailerDataDict.get('Master Scan Number', -1)
            
            return int(master_scan_number) if master_scan_number is not None else -1

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return -1

        except Exception as e:
            print(f"Unexpected error while processing scan {MS2ScarNumber}: {e}")
            return -1 
    
    
    def GetSPSMass(self, MS2ScarNumber: int) -> np.array:
        """
        Get list of SPSMass from MS2 scan number.

        This function uses trainer information to extraxt SPS mass if available.

        Args:
            self (class object): the main class object of the Raw_Parser.
            MS2ScarNumber (int): number of the MS2 scan.

        Returns:
            np.array[float] list of sps masses.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the sps masses from it.
        """

        try:
            if not isinstance(MS2ScarNumber, int) or MS2ScarNumber < 1:
                raise ValueError(f"Invalid MS2 scan number provided: {MS2ScarNumber}")

            trailerData = self.source.GetTrailerExtraInformation(MS2ScarNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {MS2ScarNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data for scan {MS2ScarNumber} is missing required attributes")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in (trailerData.Labels or [])]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            sps_masses = trailerDataDict.get('SPS Masses', None)
            if sps_masses is None or sps_masses == -1:
                raise ValueError(f"SPS Masses not found for scan number {MS2ScarNumber}")

            return np.array(DotNetArrayToNPArray(sps_masses, float))

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.array([])

        except Exception as e:
            print(f"Unexpected error while processing scan {MS2ScarNumber}: {e}")
            return np.array([])
    
    
    def GetMSOrder(self, scanNumber: int) -> int:
        """
        Get MS order from the input scan (MS1 or MS2)

        This function uses the scan event .

        Args:
            self (class object): the main class object of the Raw_Parser.
            MS2ScarNumber (int): number of the MS2 scan.

        Returns:
            np.array[float] list of sps masses.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the sps masses from it.
        """
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            scanEvent = self.source.GetScanEventForScanNumber(scanNumber)
            if scanEvent is None:
                raise ValueError(f"No scan event found for scan number {scanNumber}")

            ms_order = IScanEventBase(scanEvent).MSOrder

            if ms_order is None:
                raise ValueError(f"MS order could not be determined for scan number {scanNumber}")

            return int(ms_order)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return -1  

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return -1


    def GetMS2PrecursorMassFromScanNumber(self, scanNumber: int) -> float:
        """
        Get MS2 precursor mass 

        This function compare the mono isotopic mass with the reactions mass, 
        which has been used for fragmentation and retrives the correct or 
        improved precursor mass (with more digits)

        Args:
            self (class object): the main class object of the Raw_Parser.
            MS2ScarNumber (int): number of the MS2 scan.

        Returns:
            float precursor mass.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the precursor mass from the raw file.
        """
        
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            scanMSOrder = self.GetMSOrder(scanNumber)
            if scanMSOrder != 2:
                raise ValueError(f"Scan {scanNumber} is not an MS2 scan.")

            filterObj = self.source.GetFilterForScanNumber(scanNumber)
            if filterObj is None:
                raise ValueError(f"No filter found for scan number {scanNumber}")
            
            isolationMzPossiblyWithOffset = filterObj.GetMass(scanMSOrder - 2)

            scanEvent = self.source.GetScanEventForScanNumber(scanNumber)
            if scanEvent is None:
                raise ValueError(f"No scan event found for scan number {scanNumber}")

            reaction = scanEvent.GetReaction(0)
            if reaction is None:
                raise ValueError(f"No reaction data found for scan number {scanNumber}")

            trailerDataExtra = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerDataExtra is None or not hasattr(trailerDataExtra, 'Labels') or not hasattr(trailerDataExtra, 'Values'):
                raise ValueError(f"Trailer data is incomplete for scan number {scanNumber}")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in (trailerDataExtra.Labels or [])]
            trailerDataDict = dict(zip(trailerDataLabels, trailerDataExtra.Values or []))

            # Retrieve monoisotopic mass and isolation width
            isolationWidth = self.GetMS2IsolationWidthFromScanNumber(scanNumber)
            monoMZ = self.GetMS2MonoMzFromScanNumber(scanNumber)

            precursorMass = None
            if self.CheckRoundDigits(isolationMzPossiblyWithOffset, monoMZ) or (isolationMzPossiblyWithOffset - monoMZ) < 0:
                self.AccScans += 1
                charge = self.GetMS2ChargeFromScanNumber(scanNumber)
                offset = reaction.IsolationWidthOffset
                diff = isolationMzPossiblyWithOffset - monoMZ
                log = f'scan {scanNumber} monoMZ {monoMZ} precursorMZ {isolationMzPossiblyWithOffset} diff {diff} charge {charge} offset {offset} iso.width {isolationWidth}\n'
                #with open(self.PositiveTestFile, 'a') as file: file.write(log)
                precursorMass = isolationMzPossiblyWithOffset
            else:
                self.DiffScans += 1
                charge = self.GetMS2ChargeFromScanNumber(scanNumber)
                offset = reaction.IsolationWidthOffset
                diff = isolationMzPossiblyWithOffset - monoMZ
                log = f'scan {scanNumber} monoMZ {monoMZ} precursorMZ {isolationMzPossiblyWithOffset} diff {diff} charge {charge} offset {offset} iso.width {isolationWidth}\n'
                #with open(self.NegativeTestFile, 'a') as file: file.write(log)
                precursorMass = monoMZ

            return precursorMass

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan 

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.nan

    
    def GetMS2IsolationWidthFromScanNumber(self, scanNumber: int)-> float:
        """
        Get MS2 isolation width

        This function creates the trailer extra information to parse the 
        applied MS2 isolation width while creating the raw file.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scarNumber (int): number of the MS2 scan.

        Returns:
            float isolation width.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the ms2 isolation width from the raw file.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data for scan {scanNumber} is missing required attributes")

            trailerDataLabels = [
                x[:-1] if x and x[-1] == ":" else x for x in (trailerData.Labels or [])
            ]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            isolation_width = trailerDataDict.get('MS2 Isolation Width', np.nan)
            
            #return float(isolation_width) if isolation_width is not None else np.nan
            return _to_float(isolation_width, default=np.nan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.nan
    
     
    def GetPrecursorIntensityFromScanNumber(self, scanNumber: int) -> float:
        """
        Get MS2 precursor intensity from MS2 or MS1 scans

        This function reads from scan statisticsthe MS2/MS1 masses.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scarNumber (int): number of the MS2 scan.

        Returns:
            np.array[float] list of MS1/MS2 masses.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the ms2/ms1 masses lists from the raw file.
        """
        MS1MasterScan = self.GetMasterScanNumber(scanNumber)
        monoMZ = self.GetMS2MonoMzFromScanNumber(scanNumber)

        if MS1MasterScan is None or np.isnan(monoMZ):
            raise ValueError(f"Could not retrieve valid data for scan number {scanNumber}")

        try:
            scanStatistics = self.source.GetScanStatsForScanNumber(MS1MasterScan)
            if scanStatistics is None:
                raise ValueError(f"No scan statistics found for master scan {MS1MasterScan}")
            intensitiesArray = []
            MZArray = []

            if (scanStatistics.IsCentroidScan):
                stream = self.source.GetCentroidStream(MS1MasterScan, False)
                if stream is None or not hasattr(stream, 'Masses') or not hasattr(stream, 'Intensities'):
                    raise ValueError(f"Failed to retrieve centroid data for scan {MS1MasterScan}")
                
                MZArray = np.array(stream.Masses)
                intensitiesArray = np.array(stream.Intensities)

            else:
                segmentedScan = self.source.GetSegmentedScanFromScanNumber(MS1MasterScan, scanStatistics)
                if segmentedScan is None or not hasattr(segmentedScan, 'Positions') or not hasattr(segmentedScan, 'Intensities'):
                    raise ValueError(f"Failed to retrieve segmented scan data for scan {MS1MasterScan}")
                
                MZArray = np.array(segmentedScan.Positions)
                intensitiesArray = np.array(segmentedScan.Intensities)
            idx = np.searchsorted(MZArray, monoMZ, side='left')
            if idx >= len(intensitiesArray):
                raise ValueError(f"MonoMZ {monoMZ} is out of range for scan {scanNumber}")
            intensity = intensitiesArray[idx]
            #print(intensity)
            
            return _to_float(intensity) if not np.isnan(intensity) else np.nan

        except Exception:
            return np.nan
        
        
    def CloseRAWFile(self) -> None:
        """
        Close the raw file

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            None.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        self.source.Dispose()
    
        
    def GetRAWFileName(self) -> str:
        """
        Get the raw file name

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            str input file name.

        Raises:
            ValueError: If the structure of the raw file uncompleted or not found.
        """
        return self.source.FileName
    
    
    def GetUserID(self) -> str: #the login ID of the user who acquired the data
        """
        Get the login ID of the user who acquired the data

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            str user id.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return self.source.CreatorId
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            user_id = getattr(self.source, 'CreatorId', None)
            if user_id is None:
                raise ValueError("User ID could not be retrieved from the raw file.")

            return str(user_id)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return ""

        except Exception as e:
            print(f"Unexpected error while retrieving user ID: {e}")
            return ""
    
    
    def GetFileCreationDate(self) -> str:
        """
        Get raw file creation date 
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            str raw file creation date. 
                Example: 4/10/2019 8:45:37 PM

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return str(self.source.CreationDate)
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            creation_date = getattr(self.source, 'CreationDate', None)
            if creation_date is None:
                raise ValueError("File creation date could not be retrieved from the raw file.")

            return str(creation_date)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return ""

        except Exception as e:
            print(f"Unexpected error while retrieving file creation date: {e}")
            return ""


    def GetElaspedScanTimeFromScanNumber(self, scanNumber: int) -> float:
        """
        Get Elapsed Scan Time (sec) of specific scan

        This function returns the Elapsed Scan Time (sec) from the target scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): scan number.

        Returns:
            float Elapsed Scan Time (sec).

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the Elapsed Scan Time (sec) for target scan.
        """
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data structure missing required attributes for scan {scanNumber}")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in trailerData.Labels or []]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            injection_time = trailerDataDict.get('Elapsed Scan Time (sec)', np.nan)
            return _to_float(injection_time, default=np.nan)
            #return float(injection_time) if injection_time is not None else np.nan

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.nan
        
        
    def GetIonInjectionTimeFromScanNumber(self, scanNumber: int) -> float:
        """
        Get ion injection time of specific scan

        This function returns the ion injection time from the target scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): scan number.

        Returns:
            float ion injection time.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the ion injection time for target scan.
        """
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number: {scanNumber}")

            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            if trailerData is None:
                raise ValueError(f"No trailer data found for scan number {scanNumber}")

            if not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data structure missing required attributes for scan {scanNumber}")

            trailerDataLabels = [x[:-1] if x and x[-1] == ":" else x for x in trailerData.Labels or []]
            trailerDataDict = dict(zip(trailerDataLabels, trailerData.Values or []))

            injection_time = trailerDataDict.get('Ion Injection Time (ms)', np.nan)
            return _to_float(injection_time, default=np.nan)
            #return float(injection_time) if injection_time is not None else np.nan

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.nan
        
    def GetRetentionTimeFromScanNumber(self, scanNumber: int) -> float:
        """
        Get retention time of specific scan

        This function returns the retention time from the target scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): scan number.

        Returns:
            float retention time.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the retention time for target scan.
        """
        #return self.source.RetentionTimeFromScanNumber(scanNumber)
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'RetentionTimeFromScanNumber'):
                raise ValueError("Retention time retrieval method not available in raw file source.")

            retention_time = self.source.RetentionTimeFromScanNumber(scanNumber)

            if retention_time is None:
                raise ValueError(f"No retention time found for scan number {scanNumber}")

            #return float(retention_time)
            return _to_float(retention_time, default=np.nan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan # RT error nan or 0.0? 

        except Exception as e:
            print(f"Unexpected error while retrieving retention time for scan {scanNumber}: {e}")
            return np.nan  
    
    
    def GetStatusLogForScanNumber(self, scanNumber: int) -> dict:
        """
        Get status log of specific scan

        This function returns the status log from the target scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): scan number.

        Returns:
            dict retention time.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the status log for target scan.
        """
        #LogSet = self.source.GetStatusLogForRetentionTime(self.GetRetentionTimeFromScanNumber(scanNumber))
        #return dict(zip(LogSet.Labels, LogSet.Values))
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")
            
            if not hasattr(self.source, 'GetStatusLogForRetentionTime'):
                raise ValueError("Method GetStatusLogForRetentionTime not available in source.")

            retention_time = self.GetRetentionTimeFromScanNumber(scanNumber)
            if np.isnan(retention_time):
                raise ValueError(f"No retention time found for scan number {scanNumber}")

            LogSet = self.source.GetStatusLogForRetentionTime(retention_time)
            if LogSet is None or not hasattr(LogSet, 'Labels') or not hasattr(LogSet, 'Values'):
                raise ValueError(f"Status log data not available for scan number {scanNumber}")

            return dict(zip(LogSet.Labels or [], LogSet.Values or []))

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return {}
        except Exception as e:
            print(f"Unexpected error while retrieving status log for scan {scanNumber}: {e}")
            return {}
    
    
    def CheckFileQuality(self) -> None:
        """
        Check quality of the file, if the file contains error or missing information

        This function returns the the error msg from c# objects if the file
        is incomplete or contains error.

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            str if erro-based file otherwise None.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        if self.source.IsError:
            return str(self.source.GetErrorCode), str(self.source.GetErrorMessage)
        else:
            pass
        
        
    def RAWHasMSData(self) -> bool: #true if the file contains MS data
        """
        Check if the file contains MS spectra

        This function checks if the file contains spectra data or only headers
        information.

        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            bool true if the file contains MS data.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        return self.source.HasMsData
    
    
    def RefreshViewOfFile(self) -> None:
        """
        Refresh the loading of the raw file

        Refreshes the view of a file currently being acquired. This function provides a more efficient
        mechanism for gaining access to new data in a raw file during acquisition without closing and
        reopening the raw file. This function has no effect with files that are not being acquired.
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            None.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        return self.source.RefreshViewOfFile
    
    
    def GetNumTrailerExtraInTotal(self) -> int:
        """
        Get the number of trailer counts inside the raw file

        This function counts the number of trailer information in the file, 
        this number should be exactly same as the number of spectra presented in 
        the file, otherwise some scans are not complete.
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            int total number of trailer counts.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        return self.source.RunHeaderEx.TrailerExtraCount
    
    
    def GetMaxIntegratedIntensity(self) -> float:
        """
        Get the highest integrated intensity of all the scans
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            float highest intensity value between all scans.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return self.source.RunHeaderEx.MaxIntegratedIntensity
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'RunHeaderEx') or self.source.RunHeaderEx is None:
                raise ValueError("RunHeaderEx is not available in raw file source.")

            if not hasattr(self.source.RunHeaderEx, 'MaxIntegratedIntensity'):
                raise ValueError("MaxIntegratedIntensity attribute not found in RunHeaderEx.")

            max_intensity = self.source.RunHeaderEx.MaxIntegratedIntensity

            if max_intensity is None:
                raise ValueError("MaxIntegratedIntensity is missing from the raw file.")

            #return float(max_intensity)
            return _to_float(max_intensity, default=np.nan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan  # Return NaN if an expected issue occurs

        except Exception as e:
            print(f"Unexpected error while retrieving max integrated intensity: {e}")
            return np.nan 
    
    
    def GetHighestBasePeakOfRawFile(self) -> float:
        """
        Get the highest base peak of all the scans
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            float highest base peak value between all scans.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return self.source.RunHeaderEx.MaxIntensity
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'RunHeaderEx') or self.source.RunHeaderEx is None:
                raise ValueError("RunHeaderEx is not available in the raw file source.")

            if not hasattr(self.source.RunHeaderEx, 'MaxIntensity'):
                raise ValueError("MaxIntensity attribute not found in RunHeaderEx.")

            max_intensity = self.source.RunHeaderEx.MaxIntensity

            if max_intensity is None:
                raise ValueError("MaxIntensity is missing from the raw file.")

            #return float(max_intensity)
            return _to_float(max_intensity, default=np.nan)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.nan

        except Exception as e:
            print(f"Unexpected error while retrieving the highest base peak: {e}")
            return np.nan
    

    def GetNumberOfUniqueScanFilters(self) -> int:
        """
        Get the number of unique scans' filters presented in the
        raw file.
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            int number of the unique scans.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return len(self.source.GetFilters())
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'GetFilters'):
                raise ValueError("Method GetFilters not available in raw file source.")

            filters = self.source.GetFilters()

            if filters is None:
                raise ValueError("Failed to retrieve scan filters from the raw file.")

            return len(filters)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return 0  

        except Exception as e:
            print(f"Unexpected error while retrieving number of unique scan filters: {e}")
            return 0
    
    
    def GetInstrumentName(self) -> str:
        """
        Get the instrument name.
        
        Args:
            self (class object): the main class object of the Raw_Parser.

        Returns:
            str name of the instruments.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return((self.source.GetInstrumentData().Name))
        try:
            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'GetInstrumentData'):
                raise ValueError("Method GetInstrumentData not available in raw file source.")

            instrument_data = self.source.GetInstrumentData()

            if instrument_data is None or not hasattr(instrument_data, 'Name'):
                raise ValueError("Instrument data is missing or incomplete.")

            return str(instrument_data.Name)

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return ""
        except Exception as e:
            print(f"Unexpected error while retrieving instrument name: {e}")
            return ""
    
    
    def GetScanEventStringForScanNumber(self, scanNumber: int) -> str:
        """
        Get scan event information as a string for the specified scan number.
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number

        Returns:
            str event name.
                Example: FTMS + c NSI d Full ms2 782.3635@hcd30.00 [120.0000-2000.0000]

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return self.source.GetScanEventStringForScanNumber(scanNumber)
        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            if not hasattr(self, 'source') or self.source is None:
                raise ValueError("The raw file source is not available.")

            if not hasattr(self.source, 'GetScanEventStringForScanNumber'):
                raise ValueError("Method GetScanEventStringForScanNumber not available in raw file source.")

            scan_event_string = self.source.GetScanEventStringForScanNumber(scanNumber)

            if scan_event_string is None or not isinstance(scan_event_string, str):
                raise ValueError(f"Scan event string is missing or invalid for scan number {scanNumber}")

            return scan_event_string

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return "" 
        except Exception as e:
            print(f"Unexpected error while retrieving scan event string for scan {scanNumber}: {e}")
            return "" 
    
    
    def GetNumberOfMassRangesFromScanNumber(self, scanNumber: int) -> int:
        """
        Get the number of MassRange data items in the scan.
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number

        Returns:
            int number of mass ranges.
                Example: 1

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).MassRangeCount 
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).MassRangeCount
        except Exception as e:
            print(f"Error retrieving number of mass ranges for scan {scanNumber}: {e}")
            return 0 
    
    
    def GetMassRangeFromScanNumber(self, scanNumber: int, massRangeIndex: int) -> float:
        """
        Get mass range data of a scan (high and low masses)
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
            massRangeIndex (int): the taget mass range index (if one mass (usually) is 0)

        Returns:
            tuple(float, float) name of the instruments.
                Example: (120.0, 2000.0)

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """

        try:
            massRangeIndex = 0 if self.GetNumberOfMassRangesFromScanNumber(scanNumber) == 1 else 1

            scan_event = IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber))
            mass_range = scan_event.GetMassRange(massRangeIndex)

            return mass_range.Low, mass_range.High

        except Exception as e:
            print(f"Error retrieving mass range for scan {scanNumber}: {e}")
            return None, None 
    
    
    def GetNumberOfSourceFragmentsFromScanNumber(self, scanNumber: int) -> int:
        """
        Get the number of source fragments (or compensation voltages) in the scan
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            int total number of source fagments

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).SourceFragmentationInfoCount
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).SourceFragmentationInfoCount
        except Exception as e:
            print(f"Error retrieving source fragments for scan {scanNumber}: {e}")
            return 0
    

    def GetCollisionEnergyForScanNumber(self, scanNumber: int) -> float:
        """
        Get collision energy for the scan
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            float isolation energy

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).GetEnergy(0)
        except Exception as e:
            print(f"Error retrieving collision energy for scan {scanNumber}: {e}")
            return None
    
    
    def GetActivationTypeForScanNumber(self, scanNumber: int) -> str:
        """
        Get activation type
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            str activation type of the input scan
                Example: HigherEnergyCollisionalDissociation

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        # return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).GetActivation(0)
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).GetActivation(0)
        except Exception as e:
            print(f"Error retrieving activation for scan {scanNumber}: {e}")
            return None
    
    
    def GetMassAnalyzerTypeFromScanNumber(self, scanNumber: int) -> str:
        """
        Get mass analyzer type
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            str mass analyzer type of the input scan
                Example: MassAnalyzerFTMS

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).MassAnalyzer
        except Exception as e:
            print(f"Error retrieving mass analyzer type for scan {scanNumber}: {e}")
            return None
    
    
    def GetDetectorTypeFromScanNumber(self, scanNumber: int) -> str:
        """
        Get detector type
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            str detector type of the input scan
                Example: any

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            return IScanEventBase(self.source.GetScanEventForScanNumber(scanNumber)).Detector
        except Exception as e:
            print(f"Error retrieving detector type for the scan {scanNumber}: {e}")
            return None 
        
        
    def GetNumberOfMassCalibratorsFromScanNumber(self, scanNumber: int) -> int:
        """
        Get the number of mass calibrators 
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            int number of used mass calibrators
                Example: 6

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            return IScanEvent(self.source.GetScanEventForScanNumber(scanNumber)).MassCalibratorCount
        except Exception as e:
            print(f"Error retrieving number of mass calibrators for scan {scanNumber}: {e}")
            return None
    
    
    def GetMassCalibrationValueFromScanNumber(self, scanNumber: int) -> str:
        """
        Get information about one of the mass calibration data values of a scan
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan number
        Returns:
            str information about each mass calibrator

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            for massCalibrationIndex in range(1, self.GetNumberOfMassCalibratorsFromScanNumber(scanNumber)):
                #print(f'Mass Calibration Index: {massCalibrationIndex}\n')
                return IScanEvent(self.source.GetScanEventForScanNumber(scanNumber)).GetMassCalibrator(massCalibrationIndex)
        except Exception as e:
            print(f"Error retrieving mass calibration data values for scan {scanNumber}: {e}")
            return None
        
        
    def GetMassResolution(self) -> float:
        """
        Get the mass resolution value recorded for the current controller
        
        Args:
            self (class object): the main class object of the Raw_Parser.
        Returns:
            float mass resolution

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            return self.source.RunHeaderEx.MassResolution
        except Exception as e:
            print(f"Error retrieving mass resolution value: {e}")
            return None


    def GetScanNumberFromRT(self, RT: float, inSeconds: bool) -> int:
        """
        Get the closest matching scan number that corresponds to RT for the current controller
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            RT (float): retention time
            inSeconds (bool): true if the input RT value is in seconds or not
            
        Returns:
            int scan number

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            if inSeconds:
                return self.source.ScanNumberFromRetentionTime(RT/60)
            else:
                return self.source.ScanNumberFromRetentionTime(RT)
        except Exception as e:
            print(f"Error retrieving scan number from the RT {RT}: {e}")
            return None
    

    def IsProfileScanForScanNumber(self, scanNumber: int) -> bool:
        """
        Check if the scan is an profile scan
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            bool True is the scan is profile scan

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #return not self.source.GetScanStatsForScanNumber(scanNumber).IsCentroidScan
        try:
            return not self.source.GetScanStatsForScanNumber(scanNumber).IsCentroidScan
        except Exception as e:
            print(f"Error checking scan profile for scan {scanNumber}: {e}")
            return False

    
    def GetBasePeakForScanNumber(self, scanNumber: int) -> float:
        """
        Get the base peak mass and intensity of mass spectrum from input scan number
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            float,float base peak mass and base peak intensity

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #stat = self.source.GetScanStatsForScanNumber(scanNumber)
        #return stat.BasePeakMass, stat.BasePeakIntensity
        try:
            stat = self.source.GetScanStatsForScanNumber(scanNumber)
            return _to_float(stat.BasePeakMass), _to_float(stat.BasePeakIntensity)
        except Exception as e:
            print(f"Error retrieving base peak for scan {scanNumber}: {e}")
            return None, None 


    def GetFrequencyForScanNumber(self, scanNumber: int) -> int:
        """
        Get the total number of channels from input scan number
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            int Frequency

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #stat = self.source.GetScanStatsForScanNumber(scanNumber)
        #return stat.Frequency
        try:
            stat = self.source.GetScanStatsForScanNumber(scanNumber)
            return stat.Frequency
        except Exception as e:
            print(f"Error retrieving frequency for scan {scanNumber}: {e}")
            return None
    

    def GetNumChannelsForScanNumber(self, scanNumber: int) -> int:
        """
        Get the total number of channels from input scan number
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            int NumberOfChannels

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #stat = self.source.GetScanStatsForScanNumber(scanNumber)
        #return stat.NumberOfChannels
        try:
            stat = self.source.GetScanStatsForScanNumber(scanNumber)
            return stat.NumberOfChannels
        except Exception as e:
            print(f"Error retrieving number of channels for scan {scanNumber}: {e}")
            return 0
    

    def GetNumPeaksForScanNumber(self, scanNumber: int) -> int:
        """
        Get the total number of peaks from input scan number
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            int PacketCount

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #stat = self.source.GetScanStatsForScanNumber(scanNumber)
        #return stat.PacketCount
        try:
            stat = self.source.GetScanStatsForScanNumber(scanNumber)
            #print(stat.PacketCount)
            return stat.PacketCount
        except Exception as e:
            print(f"Error retrieving number of peaks for scan {scanNumber}: {e}")
            return 0 
    

    def GetTICForScanNumber(self, scanNumber: int) -> float:
        """
        Get the total ion current mass spectrum from input scan number
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            float TIC

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        #stat = self.source.GetScanStatsForScanNumber(scanNumber)
        #return stat.TIC
        try:
            stat = self.source.GetScanStatsForScanNumber(scanNumber)
            return stat.TIC
        except Exception as e:
            print(f"Error retrieving TIC for scan {scanNumber}: {e}")
            return 0.0 
        
    
    def GetTrailerExtraForScanNumber(self, scanNumber: int) -> dict:
        """
        Get the recorded trailer extra entry labels and values for the current controller
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            dict contains the trainler information

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """

        try:
            trailerData = self.source.GetTrailerExtraInformation(scanNumber)
            
            if trailerData is None or not hasattr(trailerData, 'Labels') or not hasattr(trailerData, 'Values'):
                raise ValueError(f"Trailer data is missing or incomplete for scan number {scanNumber}")

            return dict(zip(trailerData.Labels or [], trailerData.Values or []))
        
        except Exception as e:
            print(f"Error retrieving trailer extra information for scan {scanNumber}: {e}")
            return {} 
        
    
    def GetProfileMassListFromScanNumber(self, scanNumber: int) -> np.array:
        """
        Get the profile masses and intensities of MS1 scan 
        
        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan
            
        Returns:
            np.array[[float], [float]] two lists combined containing the profile masses and intensities of ms1 scan

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """

        try:
            scanStatistics = self.source.GetScanStatsForScanNumber(scanNumber)
            if scanStatistics is None:
                raise ValueError(f"Scan statistics not found for scan number {scanNumber}")

            segmentedScan = self.source.GetSegmentedScanFromScanNumber(scanNumber, scanStatistics)
            if segmentedScan is None or not hasattr(segmentedScan, 'Positions') or not hasattr(segmentedScan, 'Intensities'):
                raise ValueError(f"Segmented scan data is missing or incomplete for scan number {scanNumber}")

            masses = DotNetArrayToNPArray(segmentedScan.Positions, float)
            intensities = DotNetArrayToNPArray(segmentedScan.Intensities, float)

            return np.array([masses, intensities])
        
        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.array([[], []])
        
        except Exception as e:
            print(f"Error retrieving profile mass list for scan {scanNumber}: {e}")
            return np.array([[], []])


    def GetCentroidMassListFromScanNumber(self, scanNumber: int) -> np.array:
        # ToDo test
        """
        Get the centroid stream mass list from scan number

        This function tests first if the scan is centroid, if not it tries to
        find an centroid stream, trying to get the centroid stream for it.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): target scan

        Returns:
            np.array[float] centroid masses

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error.
        """
        try:
            scanStatistics = self.source.GetScanStatsForScanNumber(scanNumber)

            if scanStatistics is None:
                raise ValueError(f"No scan statistics found for scan number {scanNumber}")

            if scanStatistics.IsCentroidScan:
                segmentedScan = self.source.GetSegmentedScanFromScanNumber(scanNumber, scanStatistics)
            else:
                scan = ThermoFisher.CommonCore.Data.Business.Scan.FromFile(self.source, scanNumber)
                if scan.HasCentroidStream:
                    stream = self.source.GetCentroidStream(scanNumber, False)
                    masses = DotNetArrayToNPArray(stream.Masses, float)
                    intensities = DotNetArrayToNPArray(stream.Intensities, float)
                    return np.array([masses, intensities])
                else:
                    print(f"Profile scan {scanNumber} cannot be centroided!")
                    segmentedScan = self.source.GetSegmentedScanFromScanNumber(scanNumber, scanStatistics)

            masses = DotNetArrayToNPArray(segmentedScan.Positions, float)
            intensities = DotNetArrayToNPArray(segmentedScan.Intensities, float)
            return np.array([masses, intensities])

        except Exception as e:
            print(f"Error retrieving centroid mass list for scan {scanNumber}: {e}")
            return np.array([[], []])

    #@ Doing....       
    def GetPrecursorSpectrumIndex(self, scanNumber,isolationMZToFind, precursorMsLevel, isolationMz, precursorIsolationMz, index, nonPrecursorMasterScanNumber, MS1MasterScan):
        """
        Get the precursor spectrum index from a scan number.

        This function iterates through the scan numbers to locate the precursor
        spectrum based on the MS level and isolation m/z. It handles special cases 
        like non-precursor master scans and scans with multiple mass ranges.

        Args:
            self (class object): The main class object of the Raw_Parser.
            scanNumber (int): The scan number to process.
            isolationMZToFind (float): The corrected version of the isolation m/z to find.
            precursorMsLevel (int): The MS level of the precursor spectrum.
            isolationMz (float): The isolation m/z for the current scan.
            precursorIsolationMz (float): The isolation m/z of the precursor.
            index (int): The current scan index to start processing.
            nonPrecursorMasterScanNumber (int): Placeholder for non-precursor master scans.
            MS1MasterScan (int): The master scan number for MS1 scans.

        Returns:
            int: The index of the precursor spectrum.

        Raises:
            None: Does not explicitly raise exceptions but expects valid data structures
            within the raw file for correct processing.

        Notes:
            - Handles multiple mass ranges within scans.
            - Incorporates validation of MS levels and isolation m/z ranges.
        """
        #isolationMZToFind: corrected version from it
        
        nonPrecursorMasterScanNumber = 0
        scanRangeCount = self.GetNumberOfMassRangesFromScanNumber(scanNumber)
        firstScanRange, secondScanRange = self.GetMassRangeFromScanNumber(scanNumber, 0)
        
        print("precursorMsLevel: ", precursorMsLevel)
        print("isolationMz: ", isolationMz)
        print("precursorIsolationMz: ", precursorIsolationMz)
        print("index: ", index)
        print("nonPrecursorMasterScanNumber: ", nonPrecursorMasterScanNumber)
        print("MS1MasterScan ", MS1MasterScan)
        print("scanRangeCount: ", scanRangeCount)
        print("first: ", firstScanRange)
        print("last: ", secondScanRange)
        
        while index > 0:
            index -= 1
            
            indexMSOrder = self.GetMSOrder(index)
            if indexMSOrder < precursorMsLevel:
                continue
            
            if MS1MasterScan > -1:
                if MS1MasterScan == index: # exactly the one before
                    if indexMSOrder == precursorMsLevel:
                        return index
                    nonPrecursorMasterScanNumber = MS1MasterScan
                    MS1MasterScan = -1
                    continue
                
                # Master scan not in index
                if MS1MasterScan > index:
                    return None
                continue
            
            isolationMZOfIndex = self.source.GetFilterForScanNumber(index).GetMass(indexMSOrder - 2)
            if int(indexMSOrder) == precursorMsLevel and (precursorIsolationMz == 0 or precursorIsolationMz == isolationMZOfIndex):

            # Check if isolation_mz_to_find is in scan window
                MZInRange = False
                scanRangeCount = self.GetNumberOfMassRangesFromScanNumber(index)

                if (scanRangeCount > 1):
                    for i in range(scanRangeCount):
                        firstScanRange, secondScanRange = self.GetMassRangeFromScanNumber(scanNumber, 0)
                        MZInRange = isolationMZToFind >= firstScanRange and isolationMZToFind <= secondScanRange
                        if MZInRange:
                            break
                else:
                    MZInRange = isolationMZToFind >= firstScanRange and isolationMZToFind <= secondScanRange

            if not MZInRange:
                continue

            return index

        return None
    
    #@ Doing.... 
    def GetPrecursorIntensityMSConvert(self, scanNumber, isolationMz):
        """
        Get the precursor intensity (MSConvert method).

        This function calculates the precursor intensity for a given MS2 scan 
        by summing the intensities of ions within the isolation window. The function
        identifies the precursor spectrum and extracts relevant m/z and intensity values.

        Args:
            self (class object): The main class object of the Raw_Parser.
            scanNumber (int): The scan number for which the precursor intensity is required.
            isolationMz (float): The isolation m/z value, equivalent to `isolationMzPossiblyWithOffset`.

        Returns:
            float: The summed precursor intensity within the isolation window.

        Notes:
            - Uses the isolation width to define the m/z range for intensity calculation.
            - Assumes MS2 scans for precursor intensity computation.
            - Incorporates logic for default isolation window offsets.

        Raises:
            ValueError: If the precursor spectrum index is invalid or the raw data structure 
            is incomplete for the given scan.
        """
        #isolationMZ is same as isolationMzPossiblyWithOffset
        msLevel = 2 #as we check only ms2
        precursorMsLevel = msLevel - 1
        index = scanNumber - 1
        precursorIsolationMz = 0.000000
        isolationMZToFind = self.GetMS2PrecursorMassFromScanNumber(scanNumber)
        nonPrecursorMasterScanNumber = 0
        MS1MasterScan = self.GetMasterScanNumber(scanNumber)
        precursorSpectrumIDX = self.GetPrecursorSpectrumIndex(scanNumber, isolationMZToFind, precursorMsLevel, isolationMz, precursorIsolationMz, index, nonPrecursorMasterScanNumber, MS1MasterScan)
        
        defaultIsolationWindowLowerOffset = 1.5
        defaultIsolationWindowUpperOffset = 2.5
        isolationWidth = self.GetMS2IsolationWidthFromScanNumber(scanNumber)
        isolationQueryWidth = isolationWidth if isolationWidth == 0 else defaultIsolationWindowLowerOffset
        isolationHalfWidth = isolationQueryWidth
        resultsArray = self.GetCentroidMassListFromScanNumber(precursorSpectrumIDX)
        massesOfPrecursorIndex = resultsArray[0]
        intensitiesOfPrecursorIndex = resultsArray[1]
        
        mzStart = isolationMz - isolationHalfWidth
        mzEnd = isolationMz + isolationHalfWidth
        
        mzIndexStart = next(i for i, mz in enumerate(massesOfPrecursorIndex) if mz >= mzStart)
        
        # Sum intensities within the isolation window
        precursorIntensity = 0
        for mz, intensity in zip(massesOfPrecursorIndex[mzIndexStart:], intensitiesOfPrecursorIndex[mzIndexStart:]):
            if mz > mzEnd:
                break
            precursorIntensity += intensity
        
        #print(massesOfPrecursorIndex)
        #print(intensitiesOfPrecursorIndex)
        return precursorIntensity
    

    def GetNumberOfMethods(self):
        """
        Get the number of methods associated with the instrument.

        This function checks if the `source` attribute exists and has the property 
        `InstrumentMethodsCount`, which represents the number of methods configured 
        for the instrument. If available, it retrieves and returns this value.

        Args:
            self (class object): The main class object of the Raw_Parser.

        Returns:
            int: The number of instrument methods. Returns 0 if the source or 
            `InstrumentMethodsCount` attribute is not available.

        Notes:
            - Assumes the `source` attribute is properly initialized and represents 
            the data source.
            - Provides debugging output to indicate whether the method count is available.

        Raises:
            None: Handles missing attributes gracefully.
        """
        try:
            method_count = self.source.InstrumentMethodsCount
            print(f"Number of methods: {method_count}")
            return method_count
        except AttributeError:
            print("InstrumentMethodsCount is not available.")
            return 0
        except Exception as e:
            print(f"Unexpected error retrieving instrument methods: {e}")
            return 0
        

    def GetInstrumentDetails(self):
        """
        Get detailed information about the instrument.

        This function retrieves instrument details such as model, serial number, name, 
        and software/hardware versions by accessing the `GetInstrumentData` method 
        from the `source` object.

        Args:
            self (class object): The main class object of the Raw_Parser.

        Returns:
            dict: A dictionary containing the following instrument details:
                - Instrument Model (str): The model of the instrument.
                - Instrument Serial Number (str): The serial number of the instrument.
                - Instrument Name (str): The name of the instrument.
                - SoftwareVersion (str): The version of the software used by the instrument.
                - HardwareVersion (str): The version of the hardware.

        Notes:
            - Assumes the `source` object is properly initialized and the 
            `GetInstrumentData` method is available.

        Raises:
            AttributeError: If `GetInstrumentData` or any of its attributes are missing.
        """

        try:
            if not hasattr(self, 'source') or not hasattr(self.source, 'GetInstrumentData'):
                raise AttributeError("Instrument data source is not available.")

            instrument_data = self.source.GetInstrumentData()

            return {
                "Instrument Model": getattr(instrument_data, 'Model', 'Unknown'),
                "Instrument Serial Number": getattr(instrument_data, 'SerialNumber', 'Unknown'),
                "Instrument Name": getattr(instrument_data, 'Name', 'Unknown'),
                "Software Version": getattr(instrument_data, 'SoftwareVersion', 'Unknown'),
                "Hardware Version": getattr(instrument_data, 'HardwareVersion', 'Unknown')
            }

        except AttributeError as ae:
            print(f"AttributeError: {ae}")
            return {}

        except Exception as e:
            print(f"Error retrieving instrument details: {e}")
            return {}
        

    def GetLCMethod(self):
        """
        Get the Liquid Chromatography (LC) method details.

        This function retrieves the LC method details if the system is running 
        on a Windows platform. On non-Windows systems, it returns a message indicating 
        that method extraction is not supported.

        Args:
            self (class object): The main class object of the Raw_Parser.

        Returns:
            str: The LC method details if running on Windows.
            str: A message indicating unsupported platforms if not running on Windows.

        Notes:
            - Uses `sys.platform` to determine the operating system.
            - Assumes the `source` object provides the `GetInstrumentMethod` method.
        """
        try:
            if sys.platform.startswith('win'):
                if hasattr(self.source, 'GetInstrumentMethod'):
                    return self.source.GetInstrumentMethod(0)
                else:
                    raise AttributeError("GetInstrumentMethod is not available in the source object.")
            else:
                return "Method extraction is only possible on Windows devices!"
        except Exception as e:
            print(f"Error retrieving LC method: {e}")
            return "Failed to retrieve LC method details."


    def GetMSMethod(self):
        """
        Get the Mass Spectrometry (MS) method details.

        This function retrieves the MS method details if the system is running 
        on a Windows platform. On non-Windows systems, it returns a message indicating 
        that method extraction is not supported.

        Args:
            self (class object): The main class object of the Raw_Parser.

        Returns:
            str: The MS method details if running on Windows.
            str: A message indicating unsupported platforms if not running on Windows.

        Notes:
            - Uses `sys.platform` to determine the operating system.
            - Assumes the `source` object provides the `GetInstrumentMethod` method.
        """
        try:
            if sys.platform.startswith('win'):
                if hasattr(self.source, 'GetInstrumentMethod'):
                    return self.source.GetInstrumentMethod(1)
                else:
                    raise AttributeError("GetInstrumentMethod is not available in the source object.")
            else:
                return "Method extraction is only possible on Windows devices!"
        except Exception as e:
            print(f"Error retrieving MS method: {e}")
            return "Failed to retrieve MS method details."
    

    def GetSampleInformation(self):
        """
        Get the sample information.

        This function retrieves thesample details if the system is running 
        on platform.

        Args:
            self (class object): The main class object of the Raw_Parser.

        Returns:
            dict: Dict keys are the main informations and the values are the extracted information
        Notes:
            - Uses `sys.platform` to determine the operating system.
            - Assumes the `source` object provides the `GetSampleInformation` method.
        """
        try:
            if not hasattr(self.source, 'SampleInformation') or self.source.SampleInformation is None:
                raise AttributeError("SampleInformation is not available in the source object.")

            sample_info = self.source.SampleInformation

            sample_summary = {
                "sample.name": str(getattr(sample_info, 'SampleName', 'Unknown')),
                "sample.id": str(getattr(sample_info, 'SampleId', 'Unknown')),
                "user.comment": str(getattr(sample_info, 'Comment', 'Unknown')),
                "user.text": list(getattr(sample_info, 'UserText', [])),
                "sample.volume": float(getattr(sample_info, 'SampleVolume', 0.0)),
                "sample.weight": float(getattr(sample_info, 'SampleWeight', 0.0)),
                "sample.type": str(getattr(sample_info, 'SampleType', 'Unknown')),
                "processing.method.file": str(getattr(sample_info, 'ProcessingMethodFile', 'Unknown')),
                "original.path": str(getattr(sample_info, 'Path', 'Unknown')),
                "row.number": int(getattr(sample_info, 'RowNumber', 0)),
                "ISTD.amount": float(getattr(sample_info, 'IstdAmount', 0.0)),
                "calibration.file": str(getattr(sample_info, 'CalibrationFile', 'Unknown')),
                "instrument.method.file": str(getattr(sample_info, 'InstrumentMethodFile', 'Unknown')),
                "bulk.dilution.factor": float(getattr(sample_info, 'DilutionFactor', 0.0)),
                "calibration.level": str(getattr(sample_info, 'CalibrationLevel', 'Unknown')),
                "barcode.status": str(getattr(sample_info, 'BarcodeStatus', 'Unknown')),
                "barcode": str(getattr(sample_info, 'Barcode', 'Unknown')),
                "injection.volume": float(getattr(sample_info, 'InjectionVolume', 0.0)),
                "vial": str(getattr(sample_info, 'Vial', 'Unknown')),
            }

            return sample_summary

        except AttributeError as ae:
            print(f"AttributeError: {ae}")
            return {}

        except Exception as e:
            print(f"Error retrieving sample information: {e}")
            return {}
    #ToDo: calculate_mass_precision, get_average_spectrum, get_chromatogram, 


    def GetMS2PeakListArraysFromScanNumberTest(self, scanNumber: int) -> np.array:
        """
        Get MS2 peak list arrays from specific scan.

        This function takes the scan number as argument and use it to map the trailer information from the raw file to 
        the index of the scan.

        Args:
            self (class object): the main class object of the Raw_Parser.
            scanNumber (int): number of the target scan.

        Returns:
            np.array[float] of each array for the peak list of the corresponding scan.

        Raises:
            ValueError: If the structure of the raw file uncompleted or contains error, which makes no possibility to 
            parse and extract the spectra peak list from it.
        """

        try:
            if not isinstance(scanNumber, int) or scanNumber < 1:
                raise ValueError(f"Invalid scan number provided: {scanNumber}")

            scanStatistics = self.source.GetScanStatsForScanNumber(scanNumber)
            if scanStatistics is None:
                raise ValueError(f"No scan statistics found for scan number {scanNumber}")

            if not hasattr(scanStatistics, 'IsCentroidScan') or not scanStatistics.IsCentroidScan:
                raise ValueError(f"Scan {scanNumber} is not a centroid scan")

            scanEvent = self.source.GetScanEventForScanNumber(scanNumber)
            if scanEvent is None:
                raise ValueError(f"No scan event found for scan number {scanNumber}")

            scanMSOrder = int(IScanEventBase(scanEvent).MSOrder)
            if scanMSOrder != 2:
                raise ValueError(f"Scan {scanNumber} is not an MS2 scan")

            #stream = self.source.GetCentroidStream(scanNumber, False)
            #dumper = ScanDumper()
            #dumper.dump_scan(stream, ms_order=2)

            #mz_array = np.array(DotNetArrayToNPArray(stream.Masses, float))
            #intensity_array = np.array(DotNetArrayToNPArray(stream.Intensities, float))
            #resolution_array = np.array(DotNetArrayToNPArray(stream.Resolutions, float))
            #noises_array = np.array(DotNetArrayToNPArray(stream.Noises, float))
            #baselines_array = np.array(DotNetArrayToNPArray(stream.Baselines, float))
            #charges_array = np.array(DotNetArrayToNPArray(stream.Charges, float))
            mz_array = np.array([], dtype=float)
            intensity_array = np.array([], dtype=float)
            resolution_array = np.array([], dtype=float)
            noises_array = np.array([], dtype=float)
            baselines_array = np.array([], dtype=float)
            charges_array = np.array([], dtype=float)
            
            try:
                stream = self.source.GetCentroidStream(scanNumber, False)
                mz_array = np.array(DotNetArrayToNPArray(getattr(stream, "Masses", None), float))
                intensity_array = np.array(DotNetArrayToNPArray(getattr(stream, "Intensities", None), float))
                resolution_array = np.array(DotNetArrayToNPArray(getattr(stream, "Resolutions", None), float))
                noises_array = np.array(DotNetArrayToNPArray(getattr(stream, "Noises", None), float))
                baselines_array = np.array(DotNetArrayToNPArray(getattr(stream, "Baselines", None), float))
                charges_array = np.array(DotNetArrayToNPArray(getattr(stream, "Charges", None), float))
            
            except Exception:
                pass
            
            if mz_array.size == 0 or intensity_array.size == 0:
                segmented = self.source.GetSegmentedScanFromScanNumber(scanNumber, scanStatistics)
                mz_array = np.array(DotNetArrayToNPArray(getattr(segmented, "Positions", None), float))
                intensity_array = np.array(DotNetArrayToNPArray(getattr(segmented, "Intensities", None), float))
                n = mz_array.size
                resolution_array = np.full(n, np.nan, dtype=float)
                noises_array = np.full(n, np.nan, dtype=float)
                baselines_array = np.full(n, np.nan, dtype=float)
                charges_array = np.full(n, np.nan, dtype=float)

            assert(len(mz_array) == len(intensity_array))
            assert(len(mz_array) == len(resolution_array))
            assert(len(mz_array) == len(noises_array))
            assert(len(mz_array) == len(baselines_array))
            assert(len(mz_array) == len(charges_array))
            return mz_array, intensity_array, resolution_array, noises_array, baselines_array, charges_array

        except ValueError as ve:
            print(f"ValueError: {ve}")
            return np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([])

        except Exception as e:
            print(f"Unexpected error while processing scan {scanNumber}: {e}")
            return np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([])
        
    
    def ExportMS1PeakList(self, output_filename: str = None) -> None:
       if output_filename is None:
          base, _ext = os.path.splitext(self.filename)
          output_filename = f"{base}_ms1_peaklist.parquet"

       output_directory = os.path.dirname(output_filename)
       if output_directory:
           os.makedirs(output_directory, exist_ok=True)

       self.CountMS2()
       num_scans = len(getattr(self, "MS1ScanNumbers", []) or [])
       chunk_size = 100

       print(f"[INFO] Start writing {num_scans} MS1 scans to the output file: {output_filename} in chunks of {chunk_size}.")

       all_scan_data = []
       writer = None

       try:
           for scan_number in tqdm(self.MS1ScanNumbers, desc="Exporting MS1 Peak List"):
               try:
                   if self.IsProfileScanForScanNumber(scan_number):
                       mz_int = self.GetProfileMassListFromScanNumber(scan_number)
                       mz_array = np.array(mz_int[0], dtype=float)
                       intensity_array = np.array(mz_int[1], dtype=float)
                       is_centroid = False
                   else:
                       mz_int = self.GetCentroidMassListFromScanNumber(scan_number)
                       mz_array = np.array(mz_int[0], dtype=float)
                       intensity_array = np.array(mz_int[1], dtype=float)
                       is_centroid = True

                   if mz_array.size == 0 or intensity_array.size == 0:
                       raise ValueError("Empty peak list")
                   if mz_array.size != intensity_array.size:
                       raise ValueError("m/z and intensity arrays have different lengths")

                   all_scan_data.append(
                       {
                           "scan_number": int(scan_number),
                           "is_centroid": bool(is_centroid),
                           "mz_array": mz_array.tolist(),
                           "intensity_array": intensity_array.tolist(),
                       }
                   )

                   if len(all_scan_data) == chunk_size:
                       table = pa.Table.from_pylist(all_scan_data)
                       if writer is None:
                           writer = pq.ParquetWriter(output_filename, table.schema, compression="snappy")
                       writer.write_table(table)
                       all_scan_data = []

               except ValueError as ve:
                   tqdm.write(f"Skipping MS1 scan {scan_number} due to data error: {ve}")
               except Exception as e:
                   tqdm.write(f"Skipping MS1 scan {scan_number} due to unexpected error: {e}")

           if all_scan_data:
               table = pa.Table.from_pylist(all_scan_data)
               if writer is None:
                   writer = pq.ParquetWriter(output_filename, table.schema, compression="snappy")
               writer.write_table(table)

       finally:
           if writer:
               writer.close()

       print(f"[INFO] MS1 peak list successfully exported to {output_filename}.")

    def ExportPeakList(self, output_filename: str = None) -> None:
        """
        Exports processed peak list data to a Parquet file in memory-efficient chunks.

        Args:
            output_filename (str, optional): The name of the Parquet file to create.
                                            Defaults to the original filename with a "_peaklist.parquet" suffix.
        
        Returns:
            None
        """
        if output_filename is None:
            base, ext = os.path.splitext(self.filename)
            output_filename = f"{base}_peaklist.parquet"

        output_directory = os.path.dirname(output_filename)
        if output_directory:
            os.makedirs(output_directory, exist_ok=True)
                
        self.CountMS2()
        #num_scans = len(self.MS2ScanNumbers)
        num_scans = len(getattr(self, "MS2ScanNumbers", []) or [])
        chunk_size = 100

        print(f"[INFO] Start writing {num_scans} scans to the output file: {output_filename} in chunks of {chunk_size}.")

        all_scan_data = []
        writer = None

        try:
            for i, scan_number in enumerate(tqdm(self.MS2ScanNumbers, desc="Exporting Peak List")):
                try:
                    mz_array, intensity_array, resolution_array, noises_array, baselines_array, charges_array = \
                        self.GetMS2PeakListArraysFromScanNumber(scan_number)
                    
                    all_scan_data.append({
                        'scan_number': scan_number,
                        'mz_array': mz_array.tolist(),
                        'intensity_array': intensity_array.tolist(),
                        'resolution_array': resolution_array.tolist(),
                        'noises_array': noises_array.tolist(),
                        'baselines_array': baselines_array.tolist(),
                        'charges_array': charges_array.tolist()
                    })

                    if len(all_scan_data) == chunk_size:
                        table = pa.Table.from_pylist(all_scan_data)
                        if writer is None:
                            writer = pq.ParquetWriter(output_filename, table.schema, compression='snappy')
                        writer.write_table(table)
                        all_scan_data = []  # Clear the list for the next chunk

                except ValueError as ve:
                    tqdm.write(f"Skipping scan {scan_number} due to data error: {ve}")
                except Exception as e:
                    tqdm.write(f"Skipping scan {scan_number} due to unexpected error: {e}")

            if all_scan_data:
                table = pa.Table.from_pylist(all_scan_data)
                if writer is None: # In case there's only one small chunk
                    writer = pq.ParquetWriter(output_filename, table.schema, compression='snappy')
                writer.write_table(table)

        finally:
            if writer:
                writer.close()
                
        if writer is None:
            print(f"[WARN] No MS2 scans were written (method missing / all scans failed). Output may be empty: {output_filename}")
        else:
            print(f"[INFO] Peak list successfully exported to {output_filename}.")