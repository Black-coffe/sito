from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sito.core.snapshots import create_snapshot
from sito.models import RUN_RUNNING, Cluster, Keyword, Project, Run, SerpResult, Snapshot
from sito.web.app import create_app


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def pid(app):
    with app.state.sito.session_factory() as s:
        p = Project(name="Demo", context="")
        s.add(p)
        s.commit()
        return p.id


def _add(client, pid, *keywords):
    client.post(f"/projects/{pid}/keywords/add", data={"keywords": "\n".join(keywords)})


# --- keywords tab ------------------------------------------------------------------------


def test_keywords_tab_empty_state(client, pid):
    resp = client.get(f"/projects/{pid}/keywords")
    assert resp.status_code == 200
    assert "No keywords yet" in resp.text


def test_add_keywords_and_list(client, pid):
    resp = _add(client, pid, "buy server", "cheap vps")
    resp = client.get(f"/projects/{pid}/keywords")
    assert "buy server" in resp.text
    assert "cheap vps" in resp.text


def test_add_keywords_skips_duplicates(client, app, pid):
    _add(client, pid, "buy server")
    resp = client.post(f"/projects/{pid}/keywords/add", data={"keywords": "buy server\nnew term"})
    assert "Skipped 1" in resp.text
    with app.state.sito.session_factory() as s:
        assert s.scalar(select(Keyword).where(Keyword.project_id == pid, Keyword.keyword == "new term")) is not None


def test_keywords_search_filter(client, pid):
    _add(client, pid, "rent gpu cluster", "cheap vps hosting")
    resp = client.get(f"/projects/{pid}/keywords", params={"q": "vps"})
    assert "cheap vps hosting" in resp.text
    assert "rent gpu cluster" not in resp.text


def test_keywords_status_filter(client, app, pid):
    _add(client, pid, "alpha", "beta")
    with app.state.sito.session_factory() as s:
        kw = s.scalars(select(Keyword).where(Keyword.project_id == pid, Keyword.keyword == "beta")).one()
        kw.excluded = True
        kw.excluded_reason = "manual"
        s.commit()
    resp = client.get(f"/projects/{pid}/keywords", params={"status": "excluded"})
    assert "beta" in resp.text
    assert "alpha" not in resp.text


def test_keywords_sort_by_volume(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(Keyword(project_id=pid, keyword="low", source="manual", volume=10))
        s.add(Keyword(project_id=pid, keyword="high", source="manual", volume=90))
        s.commit()
    resp = client.get(f"/projects/{pid}/keywords", params={"sort": "volume", "dir": "asc"})
    assert resp.text.index("low") < resp.text.index("high")


def test_keywords_pagination(client, app, pid):
    with app.state.sito.session_factory() as s:
        for i in range(5):
            s.add(Keyword(project_id=pid, keyword=f"kw {i}", source="manual"))
        s.commit()
    resp = client.get(f"/projects/{pid}/keywords", params={"per": "50", "page": "2"})
    assert resp.status_code == 200


# --- inline edit ---------------------------------------------------------------------------


def test_inline_edit_row_fragment(client, app, pid):
    _add(client, pid, "buy server")
    with app.state.sito.session_factory() as s:
        kid = s.scalars(select(Keyword.id).where(Keyword.project_id == pid)).one()
    resp = client.get(f"/projects/{pid}/keywords/{kid}/edit", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'name="keyword"' in resp.text


def test_inline_edit_saves(client, app, pid):
    _add(client, pid, "buy server")
    with app.state.sito.session_factory() as s:
        kid = s.scalars(select(Keyword.id).where(Keyword.project_id == pid)).one()
    resp = client.post(
        f"/projects/{pid}/keywords/{kid}/edit",
        data={"keyword": "buy dedicated server", "volume": "150", "kd": "", "cpc": "", "data": "intent: commercial"},
    )
    assert "Keyword updated" in resp.text
    with app.state.sito.session_factory() as s:
        kw = s.get(Keyword, kid)
        assert kw.keyword == "buy dedicated server"
        assert kw.volume == 150
        assert kw.data == {"intent": "commercial"}


def test_inline_edit_rejects_duplicate(client, app, pid):
    _add(client, pid, "alpha", "beta")
    with app.state.sito.session_factory() as s:
        kid = s.scalars(select(Keyword.id).where(Keyword.project_id == pid, Keyword.keyword == "beta")).one()
    resp = client.post(
        f"/projects/{pid}/keywords/{kid}/edit",
        data={"keyword": "alpha", "volume": "", "kd": "", "cpc": "", "data": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "already in this project" in resp.text


def test_inline_edit_only_volume_preserves_data_types(client, app, pid):
    _add(client, pid, "buy server")
    original_data = {"relevance": 8, "language": ["en", "ru"], "ads": {"h1": "Buy"}}
    with app.state.sito.session_factory() as s:
        kw = s.scalars(select(Keyword).where(Keyword.project_id == pid)).one()
        kw.data = original_data
        kid = kw.id
        s.commit()

    edit_resp = client.get(f"/projects/{pid}/keywords/{kid}/edit", headers={"HX-Request": "true"})
    match = re.search(r'name="data"[^>]*>(.*?)</textarea>', edit_resp.text, re.S)
    data_text = html.unescape(match.group(1))
    assert "relevance: 8" in data_text
    assert 'language: ["en", "ru"]' in data_text
    assert 'ads: {"h1": "Buy"}' in data_text

    # Only volume changes; the data textarea round-trips through the same format/parse rule.
    resp = client.post(
        f"/projects/{pid}/keywords/{kid}/edit",
        data={"keyword": "buy server", "volume": "300", "kd": "", "cpc": "", "data": data_text},
    )
    assert "Keyword updated" in resp.text
    with app.state.sito.session_factory() as s:
        kw = s.get(Keyword, kid)
        assert kw.volume == 300
        assert kw.data == original_data
        assert isinstance(kw.data["relevance"], int)
        assert isinstance(kw.data["language"], list)
        assert isinstance(kw.data["ads"], dict)


def test_inline_edit_preserves_ambiguous_string_values(client, app, pid):
    _add(client, pid, "buy server")
    original_data = {"relevance": 8, "zip": "01234", "flag": "true", "verified": True}
    with app.state.sito.session_factory() as s:
        kw = s.scalars(select(Keyword).where(Keyword.project_id == pid)).one()
        kw.data = original_data
        kid = kw.id
        s.commit()

    edit_resp = client.get(f"/projects/{pid}/keywords/{kid}/edit", headers={"HX-Request": "true"})
    match = re.search(r'name="data"[^>]*>(.*?)</textarea>', edit_resp.text, re.S)
    data_text = html.unescape(match.group(1))
    assert "zip: 01234" in data_text  # unquoted: the leading zero already makes it unambiguous
    assert 'flag: "true"' in data_text  # quoted: bare "true" would parse back as a bool
    assert "verified: true" in data_text  # a real bool, shown unquoted

    # Change only relevance; everything else must survive the full reparse unchanged.
    changed_text = data_text.replace("relevance: 8", "relevance: 9")
    resp = client.post(
        f"/projects/{pid}/keywords/{kid}/edit",
        data={"keyword": "buy server", "volume": "", "kd": "", "cpc": "", "data": changed_text},
    )
    assert "Keyword updated" in resp.text
    with app.state.sito.session_factory() as s:
        kw = s.get(Keyword, kid)
        assert kw.data["relevance"] == 9
        assert kw.data["zip"] == "01234"
        assert kw.data["flag"] == "true"
        assert isinstance(kw.data["flag"], str)
        assert kw.data["verified"] is True


# --- bulk actions --------------------------------------------------------------------------


def test_bulk_exclude_and_include(client, app, pid):
    _add(client, pid, "alpha", "beta", "gamma")
    with app.state.sito.session_factory() as s:
        ids = [str(i) for i in s.scalars(select(Keyword.id).where(Keyword.project_id == pid))]

    resp = client.post(
        f"/projects/{pid}/keywords/bulk",
        data={"action": "exclude", "reason": "not relevant", "ids": ids[:2]},
    )
    assert "Excluded 2" in resp.text
    with app.state.sito.session_factory() as s:
        query = select(Keyword).where(Keyword.project_id == pid, Keyword.excluded.is_(True))
        excluded = {k.keyword for k in s.scalars(query)}
    assert len(excluded) == 2

    resp = client.post(f"/projects/{pid}/keywords/bulk", data={"action": "include", "ids": ids[:2]})
    assert "Restored 2" in resp.text
    with app.state.sito.session_factory() as s:
        assert s.scalar(select(Keyword).where(Keyword.project_id == pid, Keyword.excluded.is_(True))) is None


def test_bulk_delete(client, app, pid):
    _add(client, pid, "alpha", "beta")
    with app.state.sito.session_factory() as s:
        ids = [str(s.scalars(select(Keyword.id).where(Keyword.project_id == pid, Keyword.keyword == "alpha")).one())]
    client.post(f"/projects/{pid}/keywords/bulk", data={"action": "delete", "ids": ids})
    with app.state.sito.session_factory() as s:
        remaining = {k.keyword for k in s.scalars(select(Keyword).where(Keyword.project_id == pid))}
    assert remaining == {"beta"}


def test_bulk_apply_to_all_matching_filter(client, app, pid):
    _add(client, pid, "buy server", "buy vps", "rent office")
    resp = client.post(
        f"/projects/{pid}/keywords/bulk",
        data={"action": "exclude", "reason": "not it", "apply_all": "1", "q": "buy"},
    )
    assert "Excluded 2" in resp.text
    with app.state.sito.session_factory() as s:
        query = select(Keyword).where(Keyword.project_id == pid, Keyword.excluded.is_(True))
        excluded = {k.keyword for k in s.scalars(query)}
    assert excluded == {"buy server", "buy vps"}


def test_bulk_set_field(client, app, pid):
    _add(client, pid, "alpha")
    with app.state.sito.session_factory() as s:
        ids = [str(k) for k in s.scalars(select(Keyword.id).where(Keyword.project_id == pid))]
    client.post(
        f"/projects/{pid}/keywords/bulk",
        data={"action": "set_field", "field_key": "intent", "field_value": "commercial", "ids": ids},
    )
    with app.state.sito.session_factory() as s:
        kw = s.scalars(select(Keyword).where(Keyword.project_id == pid)).one()
        assert kw.data["intent"] == "commercial"


def test_mutations_blocked_while_run_active(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(Run(project_id=pid, stage_id="clean", status=RUN_RUNNING))
        s.commit()
    resp = client.post(f"/projects/{pid}/keywords/add", data={"keywords": "buy server"})
    assert "running in this project" in resp.text
    with app.state.sito.session_factory() as s:
        assert s.scalar(select(Keyword).where(Keyword.project_id == pid)) is None


def test_keyword_row_routes_404_across_projects(client, app, pid):
    with app.state.sito.session_factory() as s:
        other = Project(name="Other")
        s.add(other)
        s.commit()
        s.add(Keyword(project_id=other.id, keyword="not yours", source="manual"))
        s.commit()
        kid = s.scalars(select(Keyword.id).where(Keyword.project_id == other.id)).one()

    assert client.get(f"/projects/{pid}/keywords/{kid}/row").status_code == 404
    assert client.get(f"/projects/{pid}/keywords/{kid}/edit").status_code == 404
    resp = client.post(
        f"/projects/{pid}/keywords/{kid}/edit",
        data={"keyword": "hijacked", "volume": "", "kd": "", "cpc": "", "data": ""},
    )
    assert resp.status_code == 404
    with app.state.sito.session_factory() as s:
        assert s.get(Keyword, kid).keyword == "not yours"


# --- import wizard -------------------------------------------------------------------------


def test_import_upload_txt_file(client, app, pid):
    resp = client.post(
        f"/projects/{pid}/import",
        files={"file": ("keywords.txt", b"buy server\ncheap vps\n", "text/plain")},
    )
    assert resp.status_code == 200
    assert "Map columns" in resp.text
    token = resp.url.path.rsplit("/", 1)[-1]

    resp = client.post(
        f"/projects/{pid}/import/{token}",
        data={"target_0": "keyword", "mode": "add", "source_label": "upload"},
    )
    assert "Imported" in resp.text
    with app.state.sito.session_factory() as s:
        keywords = {k.keyword for k in s.scalars(select(Keyword).where(Keyword.project_id == pid))}
    assert keywords == {"buy server", "cheap vps"}


def test_import_paste_flow(client, app, pid):
    resp = client.post(f"/projects/{pid}/import", data={"paste": "buy server\ncheap vps"})
    assert resp.status_code == 200
    assert "Map columns" in resp.text

    resp = client.post(
        f"/projects/{pid}/import/paste",
        data={"raw_text": "buy server\ncheap vps", "target_0": "keyword", "mode": "add", "source_label": "pasted"},
    )
    assert "Imported" in resp.text
    with app.state.sito.session_factory() as s:
        keywords = {k.keyword for k in s.scalars(select(Keyword).where(Keyword.project_id == pid))}
    assert keywords == {"buy server", "cheap vps"}


def test_import_paste_over_1mb_does_not_400(client, pid):
    # Regression: Starlette's Request.form() defaults to a 1 MB max_part_size, which used to
    # turn a large pasted list into a raw 400 instead of a friendly page.
    paste_text = "\n".join(f"keyword number {i:06d}" for i in range(80_000))
    assert len(paste_text.encode()) > 1_500_000
    resp = client.post(f"/projects/{pid}/import", data={"paste": paste_text})
    assert resp.status_code == 200
    assert "Map columns" in resp.text


def test_import_creates_safety_snapshot(client, app, pid):
    client.post(f"/projects/{pid}/import", data={"paste": "buy server"})
    client.post(
        f"/projects/{pid}/import/paste",
        data={"raw_text": "buy server", "target_0": "keyword", "mode": "add", "source_label": "pasted"},
    )
    with app.state.sito.session_factory() as s:
        labels = [sn.label for sn in s.scalars(select(Snapshot).where(Snapshot.project_id == pid))]
    assert any("Before import" in label for label in labels)


# --- export downloads ----------------------------------------------------------------------


def test_export_csv_download(client, pid):
    _add(client, pid, "buy server")
    resp = client.get(f"/projects/{pid}/export", params={"format": "csv", "scope": "active"})
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "buy server" in resp.content.decode("utf-8-sig")


def test_export_xlsx_and_json_downloads(client, pid):
    _add(client, pid, "buy server")
    resp = client.get(f"/projects/{pid}/export", params={"format": "xlsx", "scope": "all"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")

    resp = client.get(f"/projects/{pid}/export", params={"format": "json", "scope": "all"})
    assert resp.status_code == 200
    assert b"buy server" in resp.content


def test_export_snapshot_download(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(Keyword(project_id=pid, keyword="buy server", source="manual"))
        s.commit()
        snap = create_snapshot(s, pid, "checkpoint")
        s.commit()
        sid = snap.id
    resp = client.get(f"/projects/{pid}/snapshots/{sid}/export", params={"format": "csv"})
    assert resp.status_code == 200
    assert "buy server" in resp.content.decode("utf-8-sig")


# --- snapshots -----------------------------------------------------------------------------


def test_snapshot_restore_creates_safety_snapshot(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(Keyword(project_id=pid, keyword="alpha", source="manual"))
        s.commit()
        snap = create_snapshot(s, pid, "checkpoint")
        s.commit()
        sid = snap.id
        s.add(Keyword(project_id=pid, keyword="beta", source="manual"))
        s.commit()

    resp = client.post(f"/projects/{pid}/snapshots/{sid}/restore")
    assert "Restored" in resp.text

    with app.state.sito.session_factory() as s:
        keywords = {k.keyword for k in s.scalars(select(Keyword).where(Keyword.project_id == pid))}
        assert keywords == {"alpha"}
        labels = [sn.label for sn in s.scalars(select(Snapshot).where(Snapshot.project_id == pid))]
    assert any(label.startswith("Before restore") for label in labels)


def test_snapshot_restore_blocked_while_run_active(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(Keyword(project_id=pid, keyword="alpha", source="manual"))
        s.commit()
        snap = create_snapshot(s, pid, "checkpoint")
        s.commit()
        sid = snap.id
        s.add(Run(project_id=pid, stage_id="clean", status=RUN_RUNNING))
        s.commit()
    resp = client.post(f"/projects/{pid}/snapshots/{sid}/restore")
    assert "running in this project" in resp.text


# --- clusters & SERP tabs -------------------------------------------------------------------


def test_clusters_tab_empty_state(client, pid):
    resp = client.get(f"/projects/{pid}/clusters")
    assert resp.status_code == 200
    assert "No clusters yet" in resp.text


def test_clusters_tab_with_data(client, app, pid):
    with app.state.sito.session_factory() as s:
        s.add(
            Cluster(
                project_id=pid,
                name="Servers",
                main_keyword="buy server",
                size=3,
                total_volume=500,
                data={"intent": "commercial"},
            )
        )
        s.commit()
    resp = client.get(f"/projects/{pid}/clusters")
    assert "Servers" in resp.text
    assert "commercial" in resp.text


def test_serp_tab_empty_state(client, pid):
    resp = client.get(f"/projects/{pid}/serp")
    assert resp.status_code == 200
    assert "No SERP data yet" in resp.text


def test_serp_tab_and_keyword_page_with_data(client, app, pid):
    with app.state.sito.session_factory() as s:
        kw = Keyword(project_id=pid, keyword="buy server", source="manual")
        s.add(kw)
        s.commit()
        s.add(
            SerpResult(
                project_id=pid,
                keyword_id=kw.id,
                position=1,
                url="https://example.com/a",
                domain="example.com",
                title="Example result",
            )
        )
        s.commit()
        kid = kw.id

    resp = client.get(f"/projects/{pid}/serp")
    assert "example.com" in resp.text

    resp = client.get(f"/projects/{pid}/serp/{kid}")
    assert "Example result" in resp.text
