# -*- coding: utf-8 -*-

import xmlrpclib
import datetime
import time
import collections
import itertools

from . import codes


ArchiveProperties = collections.namedtuple('ArchiveProperties', 'key start_time end_time')
ChannelLimits = collections.namedtuple('ChannelLimits', 'low high')


def datetime_for_seconds_and_nanoseconds(seconds, nanoseconds=0.0):
    timestamp = seconds + 1.e-9 * nanoseconds
    return datetime.datetime.utcfromtimestamp(timestamp)


def seconds_and_nanoseconds_from_datetime(dt):
    seconds = int(time.mktime(dt.utctimetuple()))
    nanoseconds = int(dt.microsecond * 1e3)
    return seconds, nanoseconds


def overlap_between_datetime_ranges(first_range_start, first_range_end,
                                    second_range_start, second_range_end):
    latest_start = max(first_range_start, second_range_start)
    earliest_end = min(first_range_end, second_range_end)
    return max((earliest_end - latest_start).total_seconds(), 0.0)


class ChannelData(object):

    def __init__(self, archive_data):
        super(ChannelData, self).__init__()
        self.name = archive_data['name']
        self.data_type = archive_data['type']
        meta_data = archive_data['meta']
        if meta_data['type'] == 0:
            self.states = meta_data['states']
            self.display_limits = None
            self.alarm_limits = None
            self.warn_limits = None
            self.precision = None
            self.units = None
        else:
            self.states = None
            self.display_limits = ChannelLimits(meta_data['disp_low'], meta_data['disp_high'])
            self.alarm_limits = ChannelLimits(meta_data['alarm_low'], meta_data['alarm_high'])
            self.warn_limits = ChannelLimits(meta_data['warn_low'], meta_data['warn_high'])
            self.precision = meta_data['prec']
            self.units = meta_data['units']
            
        self.elements_per_sample = archive_data['count']
        status = []
        severity = []
        time = []
        values = []
        for sample in archive_data['values']:
            status.append(sample['stat'])
            severity.append(sample['sevr'])
            time.append(datetime_for_seconds_and_nanoseconds(sample['secs'], sample['nano']))
            values.append(sample['value'])
        self.status = status
        self.severity = severity
        self.time = time
        self.values = values


class Archiver(object):

    def __init__(self, host):
        super(Archiver, self).__init__()
        self.server = xmlrpclib.Server(host)
        self.archiver = self.server.archiver
        self.archives_for_name = collections.defaultdict(list)
    
    def scan_archives(self, channel_names=None):
        if channel_names is None:
            channel_names = []
        channel_name_pattern = '|'.join(channel_names)
        list_emptied_for_channel = collections.defaultdict(bool)
        for archive in self.archiver.archives():
            archive_key = archive['key']
            for archive_details in self.archiver.names(archive_key, channel_name_pattern):
                name = archive_details['name']
                start_time = datetime_for_seconds_and_nanoseconds(archive_details['start_sec'], archive_details['start_nano'])
                end_time = datetime_for_seconds_and_nanoseconds(archive_details['end_sec'], archive_details['end_nano'])
                archive_properties = ArchiveProperties(archive_key, start_time, end_time)
                if list_emptied_for_channel[name]:
                    self.archives_for_name[name].append(archive_properties)
                else:
                    self.archives_for_name[name][:] = [archive_properties]
                    list_emptied_for_channel[name] = True
    
    def values(self, channel_names, start_datetime, end_datetime, count=10000,
               interpolation=codes.interpolate.RAW, scan_archives=True, archive_keys=None):
        
        # Convert datetimes to seconds and nanoseconds for archiver request
        start_seconds, start_nanoseconds = seconds_and_nanoseconds_from_datetime(start_datetime)
        end_seconds, end_nanoseconds = seconds_and_nanoseconds_from_datetime(end_datetime)

        if scan_archives:
            self.scan_archives(channel_names)
        
        if archive_keys is None:
            names_for_key = collections.defaultdict(list)
            for channel_name in channel_names:
                greatest_overlap = None
                key_with_greatest_overlap = None
                if channel_name not in self.archives_for_name:
                    raise Exception('Channel {} not found in any archive.'.format(channel_name))
                for archive_key, archive_start_time, archive_end_time in self.archives_for_name[channel_name]:
                    overlap = overlap_between_datetime_ranges(start_datetime, end_datetime, archive_start_time, archive_end_time)
                    if overlap > greatest_overlap:
                        key_with_greatest_overlap = archive_key
                        greatest_overlap = overlap
                names_for_key[key_with_greatest_overlap].append(channel_name)
        else:
            if len(channel_names) != len(archive_keys):
                    raise Exception('Number of archive keys ({}) must equal number of channels ({}).'.format(len(archive_keys), len(channel_names)))
            # Group by archive key so we can request multiple channels with a single query
            key_for_name = dict(zip(channel_names, archive_keys))
            sorted_channel_names = sorted(channel_names, key=key_for_name.__getitem__)
            names_for_key = dict([(key, list(value)) for key, value in itertools.groupby(sorted_channel_names, key=key_for_name.__getitem__)])
        
        return_data = [ None ] * len(channel_names)
        
        for archive_key, channels in names_for_key.iteritems():
            data = self.archiver.values(archive_key, channels, start_seconds, start_nanoseconds, end_seconds, end_nanoseconds, count, interpolation)
            for archive_data in data:
                channel_data = ChannelData(archive_data)
                return_data[channel_names.index(channel_data.name)] = channel_data
                
        return return_data
