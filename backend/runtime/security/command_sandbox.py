import subprocess


class CommandSandbox:
    SAFE_COMMANDS = [
        "echo",
        "ls",
        "pwd",
    ]

    def execute(self, command: str):
        parts = command.split()
        if not parts:
            return {
                "success": False,
                "error": "empty command",
            }

        if parts[0] not in self.SAFE_COMMANDS:
            return {
                "success": False,
                "error": "command blocked",
            }

        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
