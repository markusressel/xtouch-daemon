"""
What the status line of the footer says, the texts of the widgets. The pages say the ones about their lists with
`Shell.tell()` after they copied, cut, pasted or removed an entry.
"""

ENTRY_COPIED = "Copied, as in the file: Ctrl+V pastes it after the one picked, or into a text editor."
ENTRY_CUT = "Cut: Ctrl+V pastes it after the one picked, Ctrl+Z brings it back."
ENTRY_REMOVED = "Removed. Ctrl+Z brings it back."
UNDONE = "Undone."
REDONE = "Redone."
REVERTED = "Reverted to the file. Ctrl+Z brings the changes back."
RELOADED = "The file changed on disk: read it again. Ctrl+Z goes back to the version before."
RESTARTING = "Restarting the service…"
TRIAL_STARTING = "Starting a daemon with the virtual device…"
TRIAL_STOPPING = "Stopping the daemon for trying without a device, to start it again…"
TRIAL_AGAIN = "Starting the daemon for trying without a device again…"
TRIAL_ENDING = "Ending the trial: start the service to use the device."
DISK_CHANGED = (
    "The file changed on disk. Reload reads it again and drops the changes here (Ctrl+Z brings them back); "
    "Keep mine goes on with them, and saving overwrites the file."
)


def entry_pasted(count: int) -> str:
    return f"Pasted {count}. Ctrl+Z takes {'them' if count > 1 else 'it'} out again."


def clipboard_empty(entries: str) -> str:
    return f"The clipboard has no {entries}: copy them here, or from the file."


def slot_moved(source: int, target: int) -> str:
    return f"Moved slot {source} to {target}. Ctrl+Z moves it back."


def trial_ended(code: int) -> str:
    return f"The daemon for trying without a device ended (exit code {code})."


def error_raised(text: str) -> str:
    return f"Something went wrong: {text}. The window goes on; the terminal has the details."


def disk_unreadable(error: object) -> str:
    return f"The file on disk can't be read: {error}. The changes here stay; saving overwrites it."
