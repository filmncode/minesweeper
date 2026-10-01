class Mines < Formula
  include Language::Python::Shebang

  desc "Minesweeper in the terminal"
  homepage "https://github.com/filmncode/minesweeper"
  url "git@github.com:filmncode/minesweeper.git",
      using:    :git,
      revision: "a35eb2abf98af7eb5a4e792644dc7a4665ba30a1"
  version "0.1.0"
  head "git@github.com:filmncode/minesweeper.git", branch: "main"

  depends_on "python@3.13"

  def install
    # Checkouts keep the name minesweeper.py. The installed command is `mines`.
    inreplace "minesweeper.py", 'prog="minesweeper"', 'prog="mines"'

    libexec.install "game.py", "minesweeper.py"
    rewrite_shebang detected_python_shebang, libexec/"minesweeper.py"
    chmod 0755, libexec/"minesweeper.py"
    (bin/"mines").write_env_script libexec/"minesweeper.py", PYTHONPATH: libexec
  end

  test do
    assert_match "Play Minesweeper in the terminal.", shell_output("#{bin}/mines --help")
  end
end
