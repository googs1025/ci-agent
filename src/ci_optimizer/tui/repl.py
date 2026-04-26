"""prompt_toolkit REPL session with history and key bindings."""
# 架构角色：输入层配置模块，封装 prompt_toolkit 的 PromptSession 构建细节。
# 核心职责：
#   1. 配置持久化历史文件（~/.ci-agent/history），让用户可用上下箭头翻历史
#   2. 注册斜杠命令的自动补全（WordCompleter）
#   3. 绑定 Ctrl+C（清空输入）、Ctrl+D（退出）、Alt+Enter（多行换行）
# 与其他模块的关系：
#   - app.py 调用 build_session() 获取 PromptSession，在 REPL 循环中通过 prompt_async() 读取用户输入

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from ci_optimizer.config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "history"

SLASH_COMMANDS = ["/help", "/repo", "/skills", "/clear", "/cost", "/compact", "/model", "/quit"]


def build_session() -> PromptSession:
    """构建并返回配置好的 PromptSession。
    CONFIG_DIR 在此处按需创建（parents=True），保证历史文件路径有效。
    multiline=False 保持单行提交语义；多行输入通过 Alt+Enter 注入换行符实现。
    """
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
        multiline=False,  # Enter submits; use Alt+Enter to insert newline
        enable_history_search=True,
    )

    return session
