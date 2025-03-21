# -*- coding: utf-8 -*-
import collections
import threading
from typing import Callable, DefaultDict

import requests

from . import config, exits, logs, threads

LOGGER = logs.get_logger(__name__)


class SimpleCounter:

    def __init__(self):
        super().__init__()
        self.count: int = 0
        self.count_prev: int = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self.count += 1

    def get(self):
        with self._lock:
            return self.count

    def delta(self):
        with self._lock:
            count = self.count - self.count_prev
            self.count_prev = self.count
            return count

    def reset(self):
        with self._lock:
            self.count = 0
            self.count_prev = 0

    def __str__(self, *args, **kwargs):
        return self.get()


class SimpleMetrics(exits.OnExit):

    def __init__(self, logger=None, interval=15):
        super().__init__()
        self._logger = logger or LOGGER
        self._interval = interval
        self._meters: DefaultDict[str, SimpleCounter] = collections.defaultdict(SimpleCounter)
        self._gauges = {}
        self._reporter = threads.PeriodicalTask(interval, self._report)
        self._n_cycle = 0
        self.prometheus_gateway = config.get('prometheus.gateway')
        self.prometheus_key = config.get('prometheus.key')

    def start(self):
        if self._reporter.is_alive():
            return self
        self.reset()
        self._reporter.start()
        return self

    def stop(self):
        if self._reporter.is_alive():
            self._reporter.stop()

    def reset(self):
        self._meters: DefaultDict[str, SimpleCounter] = collections.defaultdict(SimpleCounter)
        self._n_cycle = 0

    def on_exit(self):
        for key in self._meters:
            self._remove_from_prometheus(key)

    def mark(self, key):
        self._meters[str(key)].increment()

    def register_gauge(self, key, gauge: Callable, overwrite=True):
        if not overwrite and key in self._gauges:
            return
        self._gauges[key] = gauge

    def _report(self):
        try:
            self._report_meters()
            self._report_gauges()
        except Exception as e:
            self._logger.error(e)

    def _report_meters(self):
        self._n_cycle += 1
        if len(self._meters) == 0:
            return
        pad_size = max([len(key) for key in self._meters]) + 8
        for key, counter in self._meters.items():
            delta = counter.delta()
            total = counter.get()
            rate = self._fmt_rate(delta, self._interval)
            rate_total = self._fmt_rate(total, self._interval * self._n_cycle)
            self._logger.info(f"{f'[meter-{key}]': <{pad_size}} count: {delta: >5}, rate: {rate}; total: {total: >8}, avg: {rate_total}")
            self._report_to_prometheus(key, rate)

    @staticmethod
    def _fmt_rate(n, interval, n_pad=6) -> str:
        rate, unit, n_digits = 0.0, 'it/s', 1
        if interval > 0:
            rate = n / interval
            if rate < 0.1:
                rate, unit, n_digits = 1 / rate, 's/it', 0
        return f"{f'{rate:.{n_digits}f}': >{n_pad}} {unit}"

    def _report_gauges(self):
        for key, gauge in self._gauges.items():
            try:
                value = gauge()
                if value is not None:
                    self._logger.info(f"[{key}] gauge: {value}")
            except Exception as e:
                self._logger.warning(e)

    def _report_to_prometheus(self, job_name, value):
        if self.prometheus_gateway and self.prometheus_key:
            url = f"{self.prometheus_gateway}/metrics/job/{job_name}/instance/{config.HOSTNAME}"
            data = f'''# TYPE {self.prometheus_key} gauge\n{self.prometheus_key} {value}\n'''.encode()
            try:
                requests.put(url, data=data, timeout=5)
            except Exception as e:
                LOGGER.info(e)

    def _remove_from_prometheus(self, job_name):
        if self.prometheus_gateway and self.prometheus_key:
            self._logger.info(f"[meter-{job_name}] removing from prometheus")
            url = f"{self.prometheus_gateway}/metrics/job/{job_name}/instance/{config.HOSTNAME}"
            try:
                requests.delete(url, timeout=5)
            except Exception as e:
                LOGGER.info(e)
