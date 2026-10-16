from app.path_guard import looks_like_private_banking_area


def test_public_campaign_paths_are_not_flagged():
    assert not looks_like_private_banking_area("https://bank.example/kampanyalar")
    assert not looks_like_private_banking_area("https://bank.example/kart-kampanyalari")


def test_common_authenticated_paths_are_flagged():
    assert looks_like_private_banking_area("https://bank.example/internet-subesi")
    assert looks_like_private_banking_area("https://bank.example/hesap-hareketleri")
    assert looks_like_private_banking_area("https://bank.example/login")
