# this file is adapted from dicompyle-core(https://github.com/dicompyler/dicompyler-core)

import re, scienceplots
from typing import List, Union
import numpy as np
import matplotlib.pyplot as plt
from torch import expand_copy
from config import scienceplots_available

# Set default absolute dose and volume units
abs_dose_units = 'Gy'
abs_volume_units = 'cm3'
relative_units = '%'


class DVH:
    """Class that stores dose volume histogram (DVH) data."""

    def __init__(self, counts, bins,
                 dvh_type='cumulative',
                 dose_units=abs_dose_units,
                 volume_units=abs_volume_units,
                 rx_dose=None, name=None, color=None, notes=None):
        """Initialization for a DVH from existing histogram counts and bins.

        Parameters
        ----------
        counts : iterable or numpy array
            An iterable of volume or percent count data
        bins : iterable or numpy array
            An iterable of dose bins
        dvh_type : str, optional
            Choice of 'cumulative' or 'differential' type of DVH
        dose_units : str, optional
            Absolute dose units, i.e. 'Gy' or relative units '%'
        volume_units : str, optional
            Absolute volume units, i.e. 'cm3' or relative units '%'
        rx_dose : number, optional
            Prescription dose value used to normalize dose bins (in Gy)
        name : String, optional
            Name of the structure of the DVH
        color : numpy array, optional
            RGB color triplet used for plotting the DVH
        notes : String, optional
            Additional notes about the DVH instance
        """
        self.counts = np.array(counts)
        self.bins = np.array(bins) if bins[0] == 0 else np.append([0], bins)
        self.dvh_type = dvh_type
        self.dose_units = dose_units
        self.volume_units = volume_units
        self.rx_dose = rx_dose
        self.name = name
        self.color = color
        self.notes = notes

    @classmethod
    def from_dicom_dvh(cls, dataset, roi_num, rx_dose=None, name=None, color=None):
        """Initialization for a DVH from a pydicom RT Dose DVH sequence."""
        sequence_num = -1
        for i, d in enumerate(dataset.DVHSequence):
            if 'DVHReferencedROISequence' in d:
                if 'ReferencedROINumber' in d.DVHReferencedROISequence[0]:
                    if roi_num == d.DVHReferencedROISequence[0].ReferencedROINumber:
                        sequence_num = i
                        break
        if sequence_num == -1:
            raise AttributeError("'DVHSequence' has no DVH with ROI Number '%d'." % roi_num)
        dvh = dataset.DVHSequence[sequence_num]
        data = np.array(dvh.DVHData)
        return cls(counts=data[1::2] * dvh.DVHDoseScaling,
                   bins=data[0::2].cumsum(),
                   dvh_type=dvh.DVHType.lower(),
                   dose_units=dvh.DoseUnits.capitalize(),
                   volume_units=dvh.DVHVolumeUnits.lower(),
                   rx_dose=rx_dose,
                   name=name,
                   color=color)

    @classmethod
    def from_data(cls, data, bin_num=1001, spacing=[1, 1, 1],
                  dvh_type='cumulative',
                  dose_units=abs_dose_units,
                  volume_units=abs_volume_units,
                  rx_dose=None, name=None, color=None, notes=None):
        """Initialization for a DVH from raw data.

        Parameters
        ----------
        data : iterable or numpy array
            An iterable of dose data that is used to create the histogram
        bin_num : int, optional
            The number of bins
        spacing: iterable
            Used to calculate the volume of a voxel
        """
        data = np.array(data)
        bins = np.linspace(0, data.max(), bin_num)
        counts, bins = np.histogram(data, bins)
        counts = counts * np.prod(spacing)
        if dvh_type == 'cumulative':
            counts = counts[::-1].cumsum()[::-1]

        return cls(counts, bins,
                   dvh_type=dvh_type,
                   dose_units=dose_units,
                   volume_units=volume_units,
                   rx_dose=rx_dose, name=name, color=color, notes=notes)

    def __repr__(self):
        """String representation of the class."""
        return 'DVH(%s, %r bins: [%r:%r] %s, volume: %r %s, name: %r, rx_dose: %d %s%s)' % \
                (self.dvh_type, self.counts.size, 
                 self.bins.min(), self.bins.max(), self.dose_units,
                 self.volume, self.volume_units,
                 self.name,
                 0 if not self.rx_dose else self.rx_dose,
                 self.dose_units,
                 ', *Notes: ' + self.notes if self.notes else '')

    def describe(self):
        """Describe a summary of DVH statistics in a text-based format."""
        print("Structure: {}".format(self.name))
        print("-----")
        dose = "rel dose" if self.dose_units == relative_units else \
               "abs dose: {}".format(self.dose_units)
        vol = "rel volume" if self.volume_units == relative_units else \
              "abs volume: {}".format(self.volume_units)
        print("DVH Type:  {}, {}, {}".format(self.dvh_type, dose, vol))
        print("Volume:    {:0.2f} {}".format(self.volume, self.volume_units))
        print("Max Dose:  {:0.2f} {}".format(self.max, self.dose_units))
        print("Min Dose:  {:0.2f} {}".format(self.min, self.dose_units))
        print("Mean Dose: {:0.2f} {}".format(self.mean, self.dose_units))
        print("D100:      {}".format(self.D100))
        print("D98:       {}".format(self.D98))
        print("D95:       {}".format(self.D95))
        print("D50:       {}".format(self.D50))
        print("D2:        {}".format(self.D2))
        if self.dose_units == relative_units:
            print("V100:      {}".format(self.V100))
            print("V95:       {}".format(self.V95))
            print("V5:        {}".format(self.V5))
        print("D2cc:      {}".format(self.D2cc))
        if self.notes:
            print("Notes:     *{}".format(self.notes))

    @property
    def differential(self):
        """Return a differential DVH from a cumulative DVH."""
        dvh_type = 'differential'
        if self.dvh_type == dvh_type:
            return self
        else:
            return DVH(**dict(
                self.__dict__,
                counts=np.abs(np.diff(np.append(self.counts, 0))),
                dvh_type=dvh_type))

    @property
    def cumulative(self):
        """Return a cumulative DVH from a differential DVH."""
        dvh_type = 'cumulative'
        if self.dvh_type == dvh_type:
            return self
        else:
            return DVH(**dict(
                self.__dict__,
                counts=self.counts[::-1].cumsum()[::-1],
                dvh_type=dvh_type))

    def absolute_dose(self, rx_dose=None, dose_units=abs_dose_units):
        """Return an absolute dose DVH."""
        if not (self.dose_units == relative_units):
            return self
        else:
            if not self.rx_dose and not rx_dose:
                raise AttributeError("'DVH' has no defined prescription dose.")
            else:
                rxdose = rx_dose if self.rx_dose is None else self.rx_dose
            return DVH(**dict(
                self.__dict__,
                bins=self.bins * rxdose / 100,
                dose_units=dose_units))

    def relative_dose(self, rx_dose=None):
        """Return a relative dose DVH based on a prescription dose."""
        if self.dose_units == relative_units:
            return self
        else:
            if not self.rx_dose and not rx_dose:
                raise AttributeError("'DVH' has no defined prescription dose.")
            else:
                rxdose = rx_dose if self.rx_dose is None else self.rx_dose
            return DVH(**dict(
                self.__dict__,
                bins=100 * self.bins / rxdose,
                dose_units=relative_units))

    def absolute_volume(self, volume, volume_units=abs_volume_units):
        """Return an absolute volume DVH."""
        if not (self.volume_units == relative_units):
            return self
        else:
            return DVH(**dict(
                self.__dict__,
                counts=volume * self.counts / 100,
                volume_units=volume_units))

    def relative_volume(self):
        """Return a relative volume DVH."""
        if self.volume_units == relative_units:
            return self
        elif self.dvh_type == 'differential':
            return self.cumulative.relative_volume().differential
        else:
            return DVH(**dict(
                self.__dict__,
                counts=100 * self.counts / (1 if (self.max.value == 0) else self.counts.max()),
                volume_units=relative_units))

    @property
    def volume(self):
        """Return the volume of the structure."""
        return self.differential.counts.sum()

    @property
    def max(self):
        """Return the maximum dose."""
        if self.counts.size <= 1 or max(self.counts) == 0:
            return DVHValue(0, self.dose_units)
        diff = self.differential
        return DVHValue(diff.bins[1:][diff.counts > 0][-1], self.dose_units)

    @property
    def min(self):
        """Return the minimum dose."""
        if self.counts.size <= 1 or max(self.counts) == 0:
            return DVHValue(0, self.dose_units)
        diff = self.differential
        return DVHValue(diff.bins[1:][diff.counts > 0][0], self.dose_units)

    @property
    def mean(self):
        """Return the mean dose."""
        if self.counts.size <= 1 or max(self.counts) == 0:
            return DVHValue(0, self.dose_units)
        diff = self.differential
        bincenters = 0.5 * (diff.bins[1:] + diff.bins[:-1])
        return DVHValue((bincenters * diff.counts).sum() / diff.counts.sum(), self.dose_units)

    def _volume_constraint(self, dose, dose_units=None):
        """Calculate the volume that receives at least a specific dose."""
        if not dose_units:
            dose_bins = self.relative_dose().bins
        else:
            dose_bins = self.absolute_dose().bins
        index = np.argmin(np.fabs(dose_bins - dose))
        if index >= self.counts.size:
            return DVHValue(0.0, self.volume_units)
        else:
            return DVHValue(self.counts[index], self.volume_units)

    def _dose_constraint(self, volume, volume_units=None):
        """Calculate the maximum dose that a specific volume receives."""
        if not volume_units:
            volume_counts = self.relative_volume().counts
        else:
            volume_counts = self.absolute_volume(self.volume).counts

        if volume_counts.size == 0 or volume > volume_counts.max():
            return DVHValue(0.0, self.dose_units)

        if volume == 100 and not volume_units:
            reversed_difference_of_volume = np.flip(np.fabs(volume_counts - volume), 0)
            index_min_value = np.argmin(reversed_difference_of_volume)
            index_range = len(reversed_difference_of_volume) - 1
            return DVHValue(self.bins[index_range - index_min_value], self.dose_units)

        return DVHValue(self.bins[np.argmin(np.fabs(volume_counts - volume))], self.dose_units)

    def _statistic(self, name):
        """Return a DVH dose or volume statistic."""
        p = re.compile(r'(\S+)?(D|V)(\d+)(cc|%)?')
        match = p.match(name)
        if match:
            p_value = match.group(2)
            number_value = match.group(3)
            unit_value = match.group(4)
        else:
            raise AttributeError(f'DVH has no statistic for {name}')

        if p_value == 'D':
            return self._dose_constraint(float(number_value), unit_value)
        else:
            return self._volume_constraint(float(number_value), unit_value)

    @property
    def D100(self):
        """D100."""
        return self._statistic('D100')

    @property
    def D98(self):
        """D98."""
        return self._statistic('D98')

    @property
    def D95(self):
        """D95."""
        return self._statistic('D95')

    @property
    def D50(self):
        """D50."""
        return self._statistic('D50')

    @property
    def D2(self):
        """D2."""
        return self._statistic('D2')

    @property
    def D2cc(self):
        """D2cc."""
        return self._statistic('D2cc')

    @property
    def V100(self):
        """V100."""
        return self._statistic('V100')

    @property
    def V95(self):
        """V95."""
        return self._statistic('V95')

    @property
    def V5(self):
        """V5."""
        return self._statistic('V5')
