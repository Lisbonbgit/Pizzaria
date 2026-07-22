import server


def test_rodizio_default_well_formed():
    assert set(server.RODIZIO_DEFAULT["tiers"]) == {"simples", "completo"}
    assert server.RODIZIO_DEFAULT["tiers"]["completo"]["price"] > 0
    assert server.RODIZIO_DEFAULT["tax_id"] == "INT"
    assert server.RODIZIO_DEFAULT["child_free_max_age"] < server.RODIZIO_DEFAULT["child_half_max_age"]
