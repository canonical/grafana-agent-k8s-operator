#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from typing import Optional

import aiohttp
from urllib3 import make_headers


class Grafana:
    """A class which abstracts access to a running instance of Grafana."""

    def __init__(
        self,
        host: Optional[str] = "localhost",
        port: Optional[int] = 3000,
        username: Optional[str] = "admin",
        pw: Optional[str] = "",
    ):
        """Manage a Grafana application.

        Args:
            host: Optional host address of Grafana application, defaults to `localhost`
            port: Optional port on which Grafana service is exposed, defaults to `3000`
            username: Optional username to connect with, defaults to `admin`
            pw: Optional password to connect with, defaults to `""`
        """
        self.base_uri = "http://{}:{}".format(host, port)
        self.headers = make_headers(basic_auth="{}:{}".format(username, pw))

    async def datasources(self) -> list:
        """Fetch datasources.

        Returns:
          Configured datasources, if any
        """
        api_path = "api/datasources"
        uri = "{}/{}".format(self.base_uri, api_path)
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(uri) as response:
                result = await response.json()
                return result if response.status == 200 else []

    async def dashboards_all(self) -> list:
        """Try to get 'all' dashboards, since relation dashboards are not starred.

        Returns:
          Found dashboards, if any
        """
        api_path = "api/search"
        uri = "{}/{}".format(self.base_uri, api_path)
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(uri, params={"starred": "false"}) as response:
                result = await response.json()
                return result if response.status == 200 else []
