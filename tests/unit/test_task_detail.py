"""Detail /task: judul + anak + kutipan riset (offline, murni)."""

from types import SimpleNamespace

from jarvis.interfaces.telegram.task_commands import format_task_detail


def task(id="12345678-1234-1234-1234-1234567890ab", title="Riset kopi", status="succeeded"):
    return SimpleNamespace(id=id, title=title, status=status)


def test_detail_minimal_tanpa_anak_tanpa_kutipan():
    assert format_task_detail(task()) == "Riset kopi [succeeded] — 12345678"


def test_detail_tampilkan_anak_maksimal_lima():
    kids = [
        task(id=f"{i:08}-1234-1234-1234-1234567890ab", title=f"A{i}", status="queued")
        for i in range(7)
    ]
    text = format_task_detail(task(), children=kids)
    assert text.count("Anak:") == 1
    assert "- A0 [queued]" in text and "- A4 [queued]" in text
    assert "A5" not in text and "A6" not in text


def test_detail_tampilkan_kutipan_riset_terbatas():
    text = format_task_detail(task(), excerpt="[S1] kopi tubruk", sources=2)
    assert "Hasil riset (2 sumber):\n[S1] kopi tubruk" in text
    long = format_task_detail(task(), excerpt="x" * 2000)
    assert len(long.split("Hasil riset:\n", 1)[1]) == 800


def test_detail_tampilkan_versi_dokumen():
    text = format_task_detail(
        task(), document={"path": "catatan.md", "version": 2, "sha256": "ab" * 32}
    )
    assert "Dokumen: catatan.md (versi 2, sha abababab)" in text
    assert "Hasil riset" not in format_task_detail(task(), document=None)
