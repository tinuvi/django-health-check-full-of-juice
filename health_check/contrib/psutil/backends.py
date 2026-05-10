import locale
import socket

import psutil

from health_check.backends import BaseHealthCheckBackend
from health_check.conf import get_setting
from health_check.exceptions import ServiceReturnedUnexpectedResult, ServiceWarning

host = socket.gethostname()


class DiskUsage(BaseHealthCheckBackend):
    def check_status(self):
        disk_usage_max = get_setting("DISK_USAGE_MAX")
        try:
            du = psutil.disk_usage("/")
            if disk_usage_max and du.percent >= disk_usage_max:
                raise ServiceWarning(f"{host} {du.percent}% disk usage exceeds {disk_usage_max}%")
        except ValueError as e:
            self.add_error(ServiceReturnedUnexpectedResult("ValueError"), e)


class MemoryUsage(BaseHealthCheckBackend):
    def check_status(self):
        memory_min = get_setting("MEMORY_MIN")
        try:
            memory = psutil.virtual_memory()
            if memory_min and memory.available < (memory_min * 1024 * 1024):
                locale.setlocale(locale.LC_ALL, "")
                avail = f"{int(memory.available / 1024 / 1024):n}"
                threshold = f"{memory_min:n}"
                raise ServiceWarning(f"{host} {avail} MB available RAM below {threshold} MB")
        except ValueError as e:
            self.add_error(ServiceReturnedUnexpectedResult("ValueError"), e)
