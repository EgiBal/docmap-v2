import openpyxl
import pytest

from docmap.convert import convert
from docmap.slim import slim

N = 5000


@pytest.fixture()
def big(tmp_path):
    p = tmp_path / "big.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Big"
    ws.append(["id", "amount", "region", "empty"])
    for i in range(1, N + 1):
        ws.append([i, i * 2.5, ["North", "South", "East"][i % 3] if i % 7 else "West", None])
    sm = wb.create_sheet("Small")
    sm.append(["k", "v"])
    for i in range(10):
        sm.append([f"key{i}", i])
    wb.save(p)
    return p


def test_digest_stats(big):
    r = convert(big, mode="auto")
    assert r.status == "digest" and r.digested == ["Big"]
    md = r.markdown
    assert f"{N} rows" in md
    assert "min 2.5" in md and f"max {N * 2.5:g}" in md
    assert "sum 31256250" in md
    assert "mean 6251.25" in md
    assert "Digest: 20 of 5000 rows shown. Full data: big.xlsx#Big" in md
    assert "empty [" not in md  # all-empty column dropped
    # small sheet stays full
    assert "key9" in md and "Digest:" in md and md.count("Digest:") == 1
    assert "key9" in slim(md)


def test_modes(big):
    assert convert(big, mode="full").digested == []
    assert convert(big, mode="full").markdown.count("Digest:") == 0
    r = convert(big, mode="digest")
    assert set(r.digested) == {"Big", "Small"}
    r2 = convert(big, mode="auto", digest_rows=10_000)  # nothing big -> normal full conversion
    assert r2.digested == [] and r2.status == "ok"


def test_small_sheet_full(tmp_path):
    import fixtures as fx

    r = convert(fx.make_xlsx(tmp_path / "a.xlsx"), mode="auto")
    assert r.status == "ok" and r.digested == []
    assert "Widget 20" in r.markdown


def test_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("a,b\n" + "\n".join(f"{i},x{i % 4}" for i in range(300)), encoding="utf-8")
    r = convert(p, mode="auto")
    assert r.status == "digest" and "sum 44850" in r.markdown and "4 distinct" in r.markdown


def test_upload_estimate(tmp_path):
    import fixtures as fx
    from docmap.tokens import image_tokens, upload_estimate

    assert image_tokens(1275, 1650) <= 1568
    assert image_tokens(100, 100) == 4 * 4
    p = fx.make_pdf(tmp_path / "a.pdf")
    t, basis = upload_estimate(p, 100)
    assert t > 100 and "page images" in basis
    x = fx.make_xlsx(tmp_path / "a.xlsx")
    assert upload_estimate(x, 100) == (100, "= naive (text extraction assumed)")
