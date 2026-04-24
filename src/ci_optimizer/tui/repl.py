"""prompt_toolkit REPL session with history and key bindings."""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from ci_optimizer.config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "history"

SLASH_COMMANDS = ["/help", "/repo", "/skills", "/clear", "/cost", "/compact", "/model", "/quit"]


def build_session() -> PromptSession:
    """Create a configured PromptSession with history, completion, and key bindings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(SLASH_COMMANDS, sentence=True)
    history = FileHistory(str(HISTORY_FILE))

    kb = KeyBindings()

    @kb.add("c-c")
    def _cancel(event):
        """Ctrl+C: clear current input buffer."""
        event.current_buffer.reset()

    @kb.add("c-d")
    def _exit(event):
        """Ctrl+D: raise EOFError to exit the REPL."""
        event.app.exit(exception=EOFError)

    @kb.add("escape", "enter")
    def _newline(event):
        """Meta+Enter (Alt+Enter): insert a newline for multi-line input."""
        event.current_buffer.insert_text("\n")

    session: PromptSession = PromptSession(
        message="› ",
        history=history,
        completer=completer,
        key_bindings=kb,
        multiline=False,   # Enter submits; use Alt+Enter to insert newline
        enable_history_search=True,
    )

    return session
