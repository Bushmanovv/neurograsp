"""Virtual EEG headset on an ESP32: replay recorded artifacts to the classifier.

Submodules are deliberately *not* imported here. Eagerly importing ``receiver``
would put it in ``sys.modules`` before ``python -m esp_headset.receiver`` runs it,
which trips a RuntimeWarning -- and would drag numpy into the import of a module
that only wants ``protocol``.
"""

__all__ = ["protocol", "receiver", "sender", "transport"]
