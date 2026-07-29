from backend.runtime.security.command_sandbox import CommandSandbox


def test_pwd_is_cross_platform_and_successful():
    result = CommandSandbox().execute("pwd")
    assert result["success"] is True
    assert result["stdout"].strip()


def test_echo_never_invokes_a_shell():
    result = CommandSandbox().execute("echo hello world")
    assert result["success"] is True
    assert result["stdout"] == "hello world\n"


def test_ls_cannot_escape_current_workspace():
    result = CommandSandbox().execute("ls ..")
    assert result["success"] is False
    assert result["error"] == "path outside workspace blocked"
