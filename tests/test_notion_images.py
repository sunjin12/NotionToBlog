from __future__ import annotations

from pathlib import Path

from dayblog.notion.images import FALLBACK_EXT, ImageCollector, download_all


def test_register_produces_deterministic_hashed_filename():
    c = ImageCollector(page_id="page-1")
    ref = c.register(block_id="blk-A", url="https://example.com/photo.png")
    assert ref.filename.startswith("img-")
    assert ref.filename.endswith(".png")
    assert ref.markdown_href == f"./{ref.filename}"

    # Same inputs → same filename (deterministic across runs)
    c2 = ImageCollector(page_id="page-1")
    ref2 = c2.register(block_id="blk-A", url="https://another-host/else.png")
    assert ref.filename == ref2.filename


def test_register_differentiates_by_page_and_block():
    a = ImageCollector(page_id="page-1").register(block_id="blk-A", url="https://e/x.png")
    b = ImageCollector(page_id="page-1").register(block_id="blk-B", url="https://e/x.png")
    c = ImageCollector(page_id="page-2").register(block_id="blk-A", url="https://e/x.png")
    assert a.filename != b.filename
    assert a.filename != c.filename


def test_register_falls_back_when_extension_unknown():
    c = ImageCollector(page_id="p")
    ref = c.register(block_id="b", url="https://notion.s3/signed?X=1")
    assert ref.filename.endswith(FALLBACK_EXT)


def test_register_detects_extension_from_path_ignoring_query():
    c = ImageCollector(page_id="p")
    ref = c.register(block_id="b", url="https://s3.aws/secret/photo.JPEG?sig=abc")
    assert ref.filename.endswith(".jpeg")


def test_download_all_writes_bytes_and_returns_paths(tmp_path: Path):
    c = ImageCollector(page_id="p")
    c.register(block_id="b1", url="https://e/a.png")
    c.register(block_id="b2", url="https://e/b.webp")
    store = {"https://e/a.png": b"AAA", "https://e/b.webp": b"BBB"}
    paths = download_all(c.refs, tmp_path, http_get=store.__getitem__)
    assert [p.read_bytes() for p in paths] == [b"AAA", b"BBB"]
    assert all(p.parent == tmp_path for p in paths)


def test_download_all_skips_files_already_present(tmp_path: Path):
    c = ImageCollector(page_id="p")
    ref = c.register(block_id="b1", url="https://e/x.png")
    (tmp_path / ref.filename).write_bytes(b"cached")
    fetched: list[str] = []

    def spy_get(url: str) -> bytes:
        fetched.append(url)
        return b"fresh"

    paths = download_all(c.refs, tmp_path, http_get=spy_get)
    assert paths[0].read_bytes() == b"cached"
    assert fetched == []  # never hit the network


def test_download_all_warns_on_oversize_image(tmp_path: Path):
    c = ImageCollector(page_id="p")
    c.register(block_id="b1", url="https://e/big.png")
    warnings: list[str] = []
    download_all(
        c.refs,
        tmp_path,
        http_get=lambda _u: b"x" * 11,
        max_bytes_warn=10,
        warn=warnings.append,
    )
    assert warnings
    assert "exceeds soft limit" in warnings[0]
    assert "11" in warnings[0] and "10" in warnings[0]
