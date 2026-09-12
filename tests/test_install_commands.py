"""Unit tests for the one-paste install block assembler.

The block must be paste-safe: every non-comment line that survives into the
combined text is a real command, and prose or backticks can never turn into
an executable shell line.
"""
import unittest

from backend.install_commands import _paste_safe_line, assemble, render_combined


class PasteSafeLineTests(unittest.TestCase):
    def test_real_commands_survive_verbatim(self):
        for line in [
            "curl -fsSL https://ollama.com/install.sh | sh",
            "pipx install git+https://github.com/aliasrobotics/cai.git",
            "go install github.com/usestrix/strix@latest",
            "cd X && python3 -m venv .venv && . .venv/bin/activate",
            "python3 -m pip install --user llama-cpp-python",
            "mkdir -p ~/linux-vortex-terminal/models",
        ]:
            self.assertEqual(_paste_safe_line(line), line, line)

    def test_prose_becomes_comment(self):
        self.assertTrue(_paste_safe_line("Review https://github.com/x and its MIT license.").startswith("# "))
        self.assertTrue(_paste_safe_line("No public local CLI was verified.").startswith("# "))

    def test_backticks_and_substitutions_never_execute(self):
        out = _paste_safe_line("then click REFRESH in the Agents view (or run `vortex agents`)")
        self.assertTrue(out.startswith("# "), out)
        out2 = _paste_safe_line("curl x.sh | sh `whoami`")
        self.assertTrue(out2.startswith("# "), out2)
        out3 = _paste_safe_line("echo $(rm -rf ~)")
        self.assertTrue(out3.startswith("# "), out3)

    def test_existing_comments_and_blanks(self):
        self.assertEqual(_paste_safe_line("# keep"), "# keep")
        self.assertEqual(_paste_safe_line("   "), "")


class AssembleTests(unittest.TestCase):
    def test_assemble_shape_and_honesty(self):
        payload = assemble({})
        block = payload["install_commands"]
        self.assertIsInstance(block["sections"], list)
        self.assertIsInstance(block["combined"], str)
        self.assertIsInstance(block["nothing_missing"], bool)
        for section in block["sections"]:
            self.assertTrue(section["id"], "every section has an id")
            self.assertTrue(section["title"], "every section has a title")
        if block["nothing_missing"]:
            self.assertIn("nothing is missing", block["combined"])
        else:
            self.assertIn("VORTEX AI stack", block["combined"])
            # No non-comment line may carry shell metacharacters.
            for line in block["combined"].splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                self.assertNotIn("`", stripped, stripped)
                self.assertNotIn("$(", stripped, stripped)
                self.assertNotIn(";", stripped, stripped)

    def test_render_combined_empty(self):
        self.assertIn("nothing is missing", render_combined([]))


if __name__ == "__main__":
    unittest.main()
