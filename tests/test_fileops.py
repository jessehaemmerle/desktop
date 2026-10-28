import os

import pytest
from gi.repository import Gio

from tenwin import fileops


def test_unique_name(tmp_path):
    assert fileops.unique_name(str(tmp_path), "Neuer Ordner") == "Neuer Ordner"
    (tmp_path / "Neuer Ordner").mkdir()
    assert fileops.unique_name(str(tmp_path), "Neuer Ordner") == "Neuer Ordner (2)"
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "a (2).txt").write_text("x")
    assert fileops.unique_name(str(tmp_path), "a.txt") == "a (3).txt"


def test_new_folder_and_text_file(tmp_path):
    first = fileops.new_folder(str(tmp_path))
    second = fileops.new_folder(str(tmp_path))
    assert os.path.isdir(first) and os.path.isdir(second) and first != second
    path = fileops.new_text_file(str(tmp_path))
    assert path.endswith(".txt") and os.path.isfile(path)


def test_rename_validation(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    (tmp_path / "b.txt").write_text("y")
    with pytest.raises(ValueError):
        fileops.rename(str(src), "x/y")
    with pytest.raises(ValueError):
        fileops.rename(str(src), "..")
    with pytest.raises(ValueError):
        fileops.rename(str(src), "b.txt")
    assert fileops.rename(str(src), "c.txt") == str(tmp_path / "c.txt")


def _op(sources, destination, move, policy):
    op = fileops.FileOperation([Gio.File.new_for_path(str(s)) for s in sources], str(destination), move=move)
    op.policy = policy  # no dialogs in tests
    return op


def test_copy_tree(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "f.txt").write_text("hello")
    dest = tmp_path / "dest"
    dest.mkdir()
    op = _op([src], dest, move=False, policy="skip")
    for s in op.sources:
        op._transfer(s, Gio.File.new_for_path(str(dest / s.get_basename())))
    assert (dest / "src" / "sub" / "f.txt").read_text() == "hello"
    assert (src / "sub" / "f.txt").exists()


def test_move_merge_keeps_skipped_files(tmp_path):
    """Moving a folder onto an existing one must not delete skipped files."""
    src = tmp_path / "src" / "data"
    src.mkdir(parents=True)
    (src / "same.txt").write_text("new")
    (src / "only-new.txt").write_text("fresh")
    dest_parent = tmp_path / "dest"
    (dest_parent / "data").mkdir(parents=True)
    (dest_parent / "data" / "same.txt").write_text("old")
    op = _op([src], dest_parent, move=True, policy="skip")
    op._transfer(op.sources[0], Gio.File.new_for_path(str(dest_parent / "data")))
    assert (dest_parent / "data" / "same.txt").read_text() == "old"
    assert (dest_parent / "data" / "only-new.txt").read_text() == "fresh"
    # The skipped file is still at the source, the moved one is gone.
    assert (src / "same.txt").read_text() == "new"
    assert not (src / "only-new.txt").exists()


def test_move_merge_replace(tmp_path):
    src = tmp_path / "src" / "data"
    src.mkdir(parents=True)
    (src / "same.txt").write_text("new")
    dest = tmp_path / "dest" / "data"
    dest.mkdir(parents=True)
    (dest / "same.txt").write_text("old")
    op = _op([src], tmp_path / "dest", move=True, policy="replace")
    op._transfer(op.sources[0], Gio.File.new_for_path(str(dest)))
    assert (dest / "same.txt").read_text() == "new"
    assert not src.exists()


def test_delete_permanently(tmp_path):
    tree = tmp_path / "tree"
    (tree / "a" / "b").mkdir(parents=True)
    (tree / "a" / "b" / "c.txt").write_text("x")
    fileops.delete_permanently([str(tree)])
    assert not tree.exists()


def test_copy_continues_after_a_failing_item(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("ok")
    missing = tmp_path / "missing.txt"  # does not exist -> GLib.Error
    dest = tmp_path / "dest"
    dest.mkdir()
    op = _op([missing, good], dest, move=False, policy="skip")
    import tenwin.fileops as fo
    finished = []
    original = fo.GLib.idle_add
    fo.GLib.idle_add = lambda func, *a: finished.append(func)
    try:
        op._run()
    finally:
        fo.GLib.idle_add = original
    assert (dest / "good.txt").read_text() == "ok"
    assert len(op.errors) == 1 and "missing.txt" in op.errors[0]
    assert not op.succeeded


def test_delete_permanently_reports_errors(tmp_path):
    errors = fileops.delete_permanently([str(tmp_path / "does-not-exist")])
    assert errors and "does-not-exist" in errors[0]


def test_untrusted_launchers_are_not_trusted(tmp_path):
    launcher = tmp_path / "Invoice.pdf.desktop"
    launcher.write_text("[Desktop Entry]\nType=Application\nName=Invoice.pdf\nExec=true\n")
    assert not fileops.launcher_trusted(str(launcher))       # not executable, not trusted
    launcher.chmod(0o755)
    assert not fileops.launcher_trusted(str(launcher))       # executable but not marked trusted
    link = tmp_path / "link.desktop"
    link.symlink_to(launcher)
    assert not fileops.launcher_trusted(str(link))
