#!/usr/bin/env python
# -*- coding: utf-8 -*-
import concurrent.futures
import os
import gzip
import sys
import glob
import logging
import collections
import time
import multiprocessing
from optparse import OptionParser
from threading import Thread

import appsinstalled_pb2
import memcache

NORMAL_ERR_RATE = 0.01
AppsInstalled = collections.namedtuple("AppsInstalled", ["dev_type", "dev_id", "lat", "lon", "apps"])
NUM_OF_WORKERS = 4
NUM_OF_THREADS = 8
BATCH_SIZE = 65000
main_opts = None
device_memc = None
processed = 0
errors = 0


def dot_rename(path):
    head, fn = os.path.split(path)
    # atomic in most cases
    os.rename(path, os.path.join(head, "." + fn))


def insert_appsinstalled(memc_addr, values, dry_run=False):
    try:
        if dry_run:
            logging.debug("%s - %s" % (memc_addr, values))
        else:
            memc = memcache.Client([memc_addr])
            memc.set_multi(values)
    except Exception as e:
        logging.exception("Cannot write to memc %s: %s" % (memc_addr, e))
        return False
    return True


def parse_appsinstalled(line):
    line_parts = line.strip().split("\t")
    if len(line_parts) < 5:
        return
    dev_type, dev_id, lat, lon, raw_apps = line_parts
    if not dev_type or not dev_id:
        return
    try:
        apps = [int(a.strip()) for a in raw_apps.split(",")]
    except ValueError:
        apps = [int(a.strip()) for a in raw_apps.split(",") if a.isidigit()]
        logging.info("Not all user apps are digits: `%s`" % line)
    try:
        lat, lon = float(lat), float(lon)
    except ValueError:
        logging.info("Invalid geo coords: `%s`" % line)
    return AppsInstalled(dev_type, dev_id, lat, lon, apps)


def thread_worker(lines, device_memc, options):
    global processed, errors
    devices_map = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue

        appsinstalled = parse_appsinstalled(line)
        if not appsinstalled:
            errors += 1
            continue

        memc_addr = device_memc.get(appsinstalled.dev_type)
        if not memc_addr:
            errors += 1
            logging.error("Unknow device type: %s" % appsinstalled.dev_type)
            continue

        ua = appsinstalled_pb2.UserApps()
        ua.lat = appsinstalled.lat
        ua.lon = appsinstalled.lon
        key = "%s:%s" % (appsinstalled.dev_type, appsinstalled.dev_id)
        ua.apps.extend(appsinstalled.apps)
        packed = ua.SerializeToString()

        if memc_addr in devices_map:
            devices_map[memc_addr].update({key: packed})
        else:
            devices_map[memc_addr] = {key: packed}

    for memc_addr, values in devices_map.items():
        ok = insert_appsinstalled(memc_addr, values, options.dry)
        if ok:
            processed += 1
        else:
            errors += 1


def process_file(fn, device_memc, options):
    logging.info('Processing %s' % fn)
    fd = gzip.open(fn, mode='rt')
    batch = []
    tasks = []
    for line in fd:
        batch.append(line)
        if len(batch) == BATCH_SIZE:
            task = Thread(target=thread_worker, args=(batch, device_memc, options))
            tasks.append(task)
            task.start()
            batch = []

    if len(batch) > 0:
        task = Thread(target=thread_worker, args=(batch, device_memc, options))
        tasks.append(task)
        task.start()

    for task in tasks:
        task.join()

    if not processed:
        fd.close()
        dot_rename(fn)
        return

    err_rate = float(errors) / processed
    if err_rate < NORMAL_ERR_RATE:
        logging.info("Acceptable error rate (%s). Successfull load" % err_rate)
    else:
        logging.error("High error rate (%s > %s). Failed load" % (err_rate, NORMAL_ERR_RATE))
    fd.close()
    dot_rename(fn)


def process_fn(fn):
    process_file(fn, device_memc, main_opts)


def main(options):
    global processed, errors, main_opts, device_memc
    main_opts = options
    device_memc = {
        "idfa": options.idfa,
        "gaid": options.gaid,
        "adid": options.adid,
        "dvid": options.dvid,
    }
    with multiprocessing.Pool(NUM_OF_WORKERS) as pool:
        pool.map(process_fn, [fn for fn in glob.iglob(options.pattern)])


def prototest():
    sample = "idfa\t1rfw452y52g2gq4g\t55.55\t42.42\t1423,43,567,3,7,23\ngaid\t7rfw452y52g2gq4g\t55.55\t42.42\t7423,424"
    for line in sample.splitlines():
        dev_type, dev_id, lat, lon, raw_apps = line.strip().split("\t")
        apps = [int(a) for a in raw_apps.split(",") if a.isdigit()]
        lat, lon = float(lat), float(lon)
        ua = appsinstalled_pb2.UserApps()
        ua.lat = lat
        ua.lon = lon
        ua.apps.extend(apps)
        packed = ua.SerializeToString()
        unpacked = appsinstalled_pb2.UserApps()
        unpacked.ParseFromString(packed)
        assert ua == unpacked


if __name__ == '__main__':
    start = time.time()
    op = OptionParser()
    op.add_option("-t", "--test", action="store_true", default=False)
    op.add_option("-l", "--log", action="store", default=None)
    op.add_option("--dry", action="store_true", default=False)
    op.add_option("--pattern", action="store", default="/home/makarovaiv/PycharmProjects/MemcLoad/*.tsv.gz")
    op.add_option("--idfa", action="store", default="127.0.0.1:33013")
    op.add_option("--gaid", action="store", default="127.0.0.1:33014")
    op.add_option("--adid", action="store", default="127.0.0.1:33015")
    op.add_option("--dvid", action="store", default="127.0.0.1:33016")
    (opts, args) = op.parse_args()
    logging.basicConfig(filename=opts.log, level=logging.INFO if not opts.dry else logging.DEBUG,
                        format='[%(asctime)s] %(levelname).1s %(message)s', datefmt='%Y.%m.%d %H:%M:%S')
    if opts.test:
        prototest()
        sys.exit(0)

    logging.info("Memc loader started with options: %s" % opts)
    try:
        main(opts)
    except Exception as e:
        logging.exception("Unexpected error: %s" % e)
        sys.exit(1)
    timelapse = time.time() - start
    print("timelapse:", timelapse)
