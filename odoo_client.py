"""Cliente JSON-RPC para Odoo 18 Enterprise."""

import json
import requests
from config import ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD


class OdooClient:
    def __init__(self):
        self.url = ODOO_URL
        self.db = ODOO_DB
        self.username = ODOO_USER
        self.password = ODOO_PASSWORD
        self.uid = None
        self.session = requests.Session()
        self._request_id = 0

    def _json_rpc(self, endpoint, params):
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": params,
            "id": self._request_id,
        }
        resp = self.session.post(
            f"{self.url}{endpoint}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            error_data = result["error"]
            msg = error_data.get("data", {}).get("message", error_data.get("message", str(error_data)))
            raise Exception(f"Odoo RPC Error: {msg}")
        return result.get("result")

    def authenticate(self):
        result = self._json_rpc("/web/session/authenticate", {
            "db": self.db,
            "login": self.username,
            "password": self.password,
        })
        self.uid = result.get("uid")
        if not self.uid:
            raise Exception("Autenticación fallida con Odoo")
        return self.uid

    def call_kw(self, model, method, args=None, kwargs=None):
        if self.uid is None:
            self.authenticate()
        return self._json_rpc("/web/dataset/call_kw", {
            "model": model,
            "method": method,
            "args": args or [],
            "kwargs": kwargs or {},
        })

    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        kwargs = {
            "domain": domain or [],
            "fields": fields or [],
            "offset": offset,
        }
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.call_kw(model, "search_read", [], kwargs)

    def search_count(self, model, domain=None):
        return self.call_kw(model, "search_count", [domain or []])

    def read_group(self, model, domain=None, fields=None, groupby=None, orderby=None, limit=None):
        kwargs = {
            "domain": domain or [],
            "fields": fields or [],
            "groupby": groupby or [],
        }
        if orderby:
            kwargs["orderby"] = orderby
        if limit:
            kwargs["limit"] = limit
        return self.call_kw(model, "read_group", [], kwargs)


odoo = OdooClient()
