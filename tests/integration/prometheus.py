#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import List, Literal

import aiohttp

logger = logging.getLogger(__name__)


class Prometheus:
    """A class that represents a running instance of Prometheus."""

    def __init__(self, host="localhost", port=9090):
        """Manage a Prometheus application.

        Args:
            host: Optional; host address of Prometheus application.
            port: Optional; port on which Prometheus service is exposed.
        """
        self.base_url = f"http://{host}:{port}"

        # Set a timeout of 5 second - should be sufficient for all the checks here.
        # The default (5 min) prolongs itests unnecessarily.
        self.timeout = aiohttp.ClientTimeout(total=5)

    async def rules(self, rules_type: Literal["alert", "record"] = None) -> list:
        """Send a GET request to get Prometheus rules.

        Args:
          rules_type: the type of rules to fetch, or all types if not provided.

        Returns:
          Rule Groups list or empty list
        """
        url = f"{self.base_url}/api/v1/rules{'?type=' + rules_type if rules_type else ''}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                # {"status":"success","data":{"groups":[]}
                return result["data"]["groups"] if result["status"] == "success" else []

    async def active_targets(self) -> List[dict]:
        """Send a GET request to get active scrape targets.

        Returns:
          A lists of targets.
        """
        url = f"{self.base_url}/api/v1/targets"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                #
                # {
                #   "status": "success",
                #   "data": {
                #     "activeTargets": [
                #       {
                #         "discoveredLabels": {
                #           "__address__": "localhost:9090",
                #           "__metrics_path__": "/metrics",
                #           "__scheme__": "http",
                #           "job": "prometheus"
                #         },
                #         "labels": {
                #           "instance": "localhost:9090",
                #           "job": "prometheus"
                #         },
                #         "scrapePool": "prometheus",
                #         "scrapeUrl": "http://localhost:9090/metrics",
                #         "globalUrl": "http://prom-0....local:9090/metrics",
                #         "lastError": "",
                #         "lastScrape": "2022-05-12T16:54:19.019386006Z",
                #         "lastScrapeDuration": 0.003985463,
                #         "health": "up"
                #       }
                #     ],
                #     "droppedTargets": []
                #   }
                # }
                return result["data"]["activeTargets"] if result["status"] == "success" else []
