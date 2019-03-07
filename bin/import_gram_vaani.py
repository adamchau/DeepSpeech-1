import os
import csv
import sys
import math
import urllib
import logging
import argparse
import subprocess
from os import path
from pathlib import Path

import swifter
import pandas as pd
from sox import Transformer

from util.text import validate_label


__version__ = "0.1.0"
_logger = logging.getLogger(__name__)


MAX_SECS = 10
BITDEPTH = 16
N_CHANNELS = 1
SAMPLE_RATE = 16000

DEV_PERCENTAGE = 0.10
TRAIN_PERCENTAGE = 0.80


def parse_args(args):
    """Parse command line parameters
    Args:
      args ([str]): Command line parameters as list of strings
    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(
        description="Imports GramVaani data for Deep Speech"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="GramVaaniImporter {ver}".format(ver=__version__),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        required=False,
        help="set loglevel to INFO",
        dest="loglevel",
        const=logging.INFO,
    )
    parser.add_argument(
        "-vv",
        "--very-verbose",
        action="store_const",
        required=False,
        help="set loglevel to DEBUG",
        dest="loglevel",
        const=logging.DEBUG,
    )
    parser.add_argument(
        "-f",
        "--file",
        required=True,
        help="Path to the GramVaani csv",
        dest="csv_filename",
    )
    parser.add_argument(
        "-d",
        "--directory",
        required=True,
        help="Directory in which to save the importer GramVaani data",
        dest="directory",
    )
    return parser.parse_args(args)

def setup_logging(level):
    """Setup basic logging
    Args:
      level (int): minimum log level for emitting messages
    """
    format = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=level, stream=sys.stdout, format=format, datefmt="%Y-%m-%d %H:%M:%S"
    )

class GramVaaniCSV:
    """GramVaaniCSV representing a GramVaani dataset.
    Args:
      csv_filename (str): Path to the GramVaani csv
    Attributes:
        data (:class:`pandas.DataFrame`): `pandas.DataFrame` Containing the GramVaani csv data
    """

    def __init__(self, csv_filename):
        self.data = self._parse_csv(csv_filename)

    def _parse_csv(self, csv_filename):
        _logger.info("Parsing csv file...%s", os.path.abspath(csv_filename))
        data = pd.read_csv(
            os.path.abspath(csv_filename),
            names=["piece_id","audio_url","transcript_labelled","transcript","labels","content_filename","audio_length","user_id"],
            usecols=["audio_url","transcript","audio_length"],
            skiprows=[0],
            engine="python",
            encoding="utf-8",
            quotechar='"',
            quoting=csv.QUOTE_ALL,
        )
        _logger.info("Parsed %d lines csv file." % len(data))
        return data

class GramVaaniDownloader:
    """GramVaaniDownloader downloads a GramVaani dataset.
    Args:
      gram_vaani_csv (GramVaaniCSV): A GramVaaniCSV representing the data to download
      directory (str): The path to download the data from
    Attributes:
        data (:class:`pandas.DataFrame`): `pandas.DataFrame` Containing the GramVaani csv data
    """

    def __init__(self, gram_vaani_csv, directory):
        self.directory = directory
        self.data = gram_vaani_csv.data

    def download(self):
        """Downloads the data associated with this instance
        Return:
          mp3_directory (os.path): The directory into which the associated mp3's were downloaded
        """
        mp3_directory = self._pre_download()
        self.data.swifter.apply(func=lambda arg: self._download(*arg, mp3_directory), axis=1)
        return mp3_directory

    def _pre_download(self):
        mp3_directory = path.join(self.directory, "mp3")
        if not path.exists(self.directory):
            _logger.info("Creating directory...%s", self.directory)
            os.mkdir(self.directory)
        if not path.exists(mp3_directory):
            _logger.info("Creating directory...%s", mp3_directory)
            os.mkdir(mp3_directory)
        return mp3_directory

    def _download(self, audio_url, transcript, audio_length, mp3_directory):
        mp3_filename = path.join(mp3_directory, os.path.basename(audio_url))
        if not path.exists(mp3_filename):
            _logger.debug("Downloading mp3 file...%s", audio_url)
            urllib.request.urlretrieve(audio_url, mp3_filename)
        else:
            _logger.debug("Already downloaded mp3 file...%s", audio_url)

class GramVaaniConverter:
    """GramVaaniConverter converts the mp3's to wav's for a GramVaani dataset.
    Args:
      directory (str): The path to download the data from
      mp3_directory (os.path): The path containing the GramVaani mp3's
    Attributes:
        directory (str): The target directory passed as a command line argument
        mp3_directory (os.path): The path containing the GramVaani mp3's
    """

    def __init__(self, directory, mp3_directory):
        self.directory = directory
        self.mp3_directory = Path(mp3_directory)

    def convert(self):
        """Converts the mp3's associated with this instance to wav's
        Return:
          wav_directory (os.path): The directory into which the associated wav's were downloaded
        """
        wav_directory = self._pre_convert()
        for mp3_filename in self.mp3_directory.glob('**/*.mp3'):
            wav_filename = path.join(wav_directory, os.path.splitext(os.path.basename(mp3_filename))[0] + ".wav")
            if not path.exists(wav_filename):
                _logger.debug("Converting mp3 file %s to wav file %s" % (mp3_filename, wav_filename))
                transformer = Transformer()
                transformer.convert(samplerate=SAMPLE_RATE, n_channels=N_CHANNELS, bitdepth=BITDEPTH)
                transformer.build(str(mp3_filename), str(wav_filename))
            else:
                _logger.debug("Already converted mp3 file %s to wav file %s" % (mp3_filename, wav_filename))
        return wav_directory

    def _pre_convert(self):
        wav_directory = path.join(self.directory, "wav")
        if not path.exists(self.directory):
            _logger.info("Creating directory...%s", self.directory)
            os.mkdir(self.directory)
        if not path.exists(wav_directory):
            _logger.info("Creating directory...%s", wav_directory)
            os.mkdir(wav_directory)
        return wav_directory

class GramVaaniDataSets:
    def __init__(self, directory, wav_directory, gram_vaani_csv):
        self.directory = directory
        self.wav_directory = wav_directory
        self.csv_data = gram_vaani_csv.data
        self.raw = pd.DataFrame(columns=["wav_filename","wav_filesize","transcript"])
        self.valid = pd.DataFrame(columns=["wav_filename","wav_filesize","transcript"])
        self.train = pd.DataFrame(columns=["wav_filename","wav_filesize","transcript"])
        self.dev = pd.DataFrame(columns=["wav_filename","wav_filesize","transcript"])
        self.test = pd.DataFrame(columns=["wav_filename","wav_filesize","transcript"])

    def create(self):
        self._convert_csv_data_to_raw_data()
        self.valid = self.raw.drop(self.raw[self._is_row_invalid(self.raw.wav_filename, self.raw.wav_filesize, self.raw.transcript)].index)
        self.valid = self.valid.sample(frac=1).reset_index(drop=True)
        train_size, dev_size, test_size = self._calculate_data_set_sizes()
        train = self.valid.loc[0:train_size]
        dev = self.valid.loc[train_size:train_size+dev_size]
        test = self.valid.loc[train_size+dev_size:train_size+dev_size+test_size]

    def _convert_csv_data_to_raw_data(self):
        self.raw[["wav_filename","wav_filesize","transcript"]] = self.csv_data[
            ["audio_url","transcript","audio_length"]
        ].swifter.apply(func=lambda arg: self._convert_csv_data_to_raw_data_impl(*arg), axis=1)

    def _convert_csv_data_to_raw_data_impl(self, audio_url, transcript, audio_length):
        mp3_filename = os.path.basename(audio_url)
        wav_relative_filename = path.join("wav", os.path.splitext(os.path.basename(mp3_filename))[0] + ".wav")
        wav_filesize = path.getsize(path.join(self.directory, wav_relative_filename))
        transcript = validate_label(transcript)
        if None == transcript:
            transcript = ""
        return pd.Series([wav_relative_filename, wav_filesize, transcript]) 

    def _is_row_invalid(self, wav_filename, wav_filesize, transcript):
        if not transcript.strip():
            return True
        wav_filename = path.join(self.directory, wav_filename)
        frames = int(subprocess.check_output(['soxi', '-s', wav_filename], stderr=subprocess.STDOUT))
        if int(frames/SAMPLE_RATE*1000/10/2) < len(str(transcript)):
            return True
        elif frames/SAMPLE_RATE > MAX_SECS:
            return True
        return False

    def _calculate_data_set_sizes(self):
        total_size = len(self.valid)
        dev_size = math.floor(total_size * DEV_PERCENTAGE)
        train_size = math.floor(total_size * TRAIN_PERCENTAGE)
        test_size = total_size - (train_size + dev_size)
        return (train_size, dev_size, test_size)

    def save(self):
        datasets = ["train", "dev", "test"]
        for dataset in datasets:
            self._save(dataset)

    def _save(self, dataset):
        dataset_path = os.path.join(self.directory, dataset + ".csv")
        dataframe = getattr(self, dataset)
        dataframe.to_csv(path, index=False, encoding="utf-8", escapechar='\\', quoting=csv.QUOTE_MINIMAL)

def main(args):
    """Main entry point allowing external calls
    Args:
      args ([str]): command line parameter list
    """
    args = parse_args(args)
    setup_logging(args.loglevel)
    _logger.info("Starting GramVaani importer...")
    _logger.info("Starting loading GramVaani csv...")
    csv = GramVaaniCSV(args.csv_filename)
    _logger.info("Starting downloading GramVaani mp3's...")
    downloader = GramVaaniDownloader(csv, args.directory)
    mp3_directory = downloader.download()
    _logger.info("Starting converting GramVaani mp3's to wav's...")
    converter = GramVaaniConverter(args.directory, mp3_directory)
    wav_directory = converter.convert()
    datasets = GramVaaniDataSets(args.directory, wav_directory, csv) 
    datasets.create()
    create.save()
    _logger.info("Finished GramVaani importer...")

main(sys.argv[1:])
