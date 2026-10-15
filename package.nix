{
  lib,
  stdenvNoCC,
  makeWrapper,
  bash,
  tmux,
  jq,
  coreutils,
}:
stdenvNoCC.mkDerivation {
  pname = "claude-tmux-resurrect";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./Makefile
      ./bin
      ./share/claude-tmux-resurrect/lib.sh
      ./examples
      ./LICENSE.md
    ];
  };
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    make install PREFIX="$out"
    for script in "$out"/bin/*; do
      wrapProgram "$script" --prefix PATH : ${
        lib.makeBinPath [
          bash
          tmux
          jq
          coreutils
        ]
      }
    done
    runHook postInstall
  '';
  meta = {
    description = "Resume exact Claude Code sessions when restored tmux sessions are attached";
    license = lib.licenses.bsd3;
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
}
