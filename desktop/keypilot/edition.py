"""Separate window and kernel object names for the reproducible edition."""
WINDOW_TITLE = "KeyPilot 研究复现版"
INSTANCE_NAME = r"Local\KeyPilot.Repro.LocalAssistant"
DICTATION_NAME = r"Local\KeyPilot.Repro.ToggleDictation"


def identify_taskbar() -> None:
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KeyPilot.Repro")
    except (AttributeError, OSError):
        pass
