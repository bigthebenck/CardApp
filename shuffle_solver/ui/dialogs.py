"""Message boxes, prompts and file pickers, in one place so tests can answer them."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox


def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def error(parent, title, text):
    QMessageBox.critical(parent, title, text)


def ask_yes_no(parent, title, text):
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


def ask_string(parent, title, prompt, initial=""):
    """The text typed, or None if the user cancels."""
    text, ok = QInputDialog.getText(parent, title, prompt, QLineEdit.Normal, initial)
    return text if ok else None


def save_path(parent, title, filters, suffix):
    """A path to save to (``suffix`` added if it has none), or None.

    ``filters``: e.g. ``"Shuffle setup (*.json)"``.
    """
    path, _ = QFileDialog.getSaveFileName(parent, title, "", filters)
    if not path:
        return None
    return path if Path(path).suffix else path + suffix


def open_path(parent, title, filters):
    path, _ = QFileDialog.getOpenFileName(parent, title, "", filters)
    return path or None
