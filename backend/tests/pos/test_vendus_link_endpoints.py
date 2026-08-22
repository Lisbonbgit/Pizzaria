"""Endpoints de ligação produtos<->Vendus: sugestões e gravação."""
import asyncio
import pytest
from fastapi import HTTPException

import server
from server import create_token, save_vendus_links, VendusLinkRequest, VendusLink


class _Products:
    def __init__(self, docs):
        self.docs = {d["id"]: d for d in docs}
        self.updates = []
    async def update_one(self, query, update):
        pid = query.get("id")
        if pid in self.docs:
            self.docs[pid].update(update["$set"]); self.updates.append((pid, update["$set"]))
            class R: matched_count = 1
            return R()
        class R: matched_count = 0
        return R()


class _FakeDb:
    def __init__(self, prods):
        self.products = _Products(prods)


def test_save_links_grava_vendus_id(monkeypatch):
    fake = _FakeDb([{"id": "p1", "name": "Calabresa"}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    body = VendusLinkRequest(links=[VendusLink(product_id="p1", vendus_id=2)])

    async def run():
        return await save_vendus_links(body, authorization=f"Bearer {admin}")
    res = asyncio.run(run())
    assert res["updated"] == 1
    assert fake.products.docs["p1"]["vendus_id"] == 2


def test_save_links_none_desliga(monkeypatch):
    fake = _FakeDb([{"id": "p1", "name": "Calabresa", "vendus_id": 2}])
    monkeypatch.setattr(server, "db", fake)
    admin = create_token("admin-1", "gestor@lenhaebrasa.com")
    body = VendusLinkRequest(links=[VendusLink(product_id="p1", vendus_id=None)])

    async def run():
        return await save_vendus_links(body, authorization=f"Bearer {admin}")
    asyncio.run(run())
    assert fake.products.docs["p1"]["vendus_id"] is None
