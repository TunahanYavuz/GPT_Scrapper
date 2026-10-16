from pathlib import Path

from app.models import CampaignRecord
from app.storage import Storage


def sample_campaign():
    return CampaignRecord(
        id="camp-1",
        source_id="source-1",
        bank_name="Örnek Banka",
        title="Market alışverişine indirim",
        description="Açık kampanya sayfasından alınan özet.",
        url="https://8.8.8.8/campaign/market",
        content_hash="sha256-test-value",
    )


def test_campaign_storage_deduplicates_and_exports(tmp_path: Path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.init()

    assert storage.save_campaigns([sample_campaign()]) == 1
    assert storage.save_campaigns([sample_campaign()]) == 0
    rows = storage.campaigns()
    assert len(rows) == 1
    assert rows[0]["bank_name"] == "Örnek Banka"
    assert "Market alışverişine indirim" in storage.export_json()
    assert "title" in storage.export_csv()


def test_run_history_is_finalized(tmp_path: Path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.init()
    storage.create_run("run-1", 1)
    storage.finish_run("run-1", "success", [{
        "source_id": "source-1",
        "status": "success",
        "found": 3,
        "saved": 2,
    }])
    run = storage.runs()[0]
    assert run["status"] == "success"
    assert run["campaigns_found"] == 3
    assert run["campaigns_saved"] == 2
