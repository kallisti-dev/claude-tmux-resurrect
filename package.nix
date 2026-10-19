{
  lib,
  tmuxPlugins,
  makeWrapper,
  bash,
  tmux,
  jq,
  coreutils,
}:
tmuxPlugins.mkTmuxPlugin {
  pluginName = "claude-tmux-resurrect";
  # The default file name replaces hyphens with underscores.
  rtpFilePath = "claude-tmux-resurrect.tmux";
  inherit (lib.importJSON ./.claude-plugin/plugin.json) version;
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./.claude-plugin/plugin.json
      ./claude-tmux-resurrect.tmux
      ./bin
      ./hooks
      ./lib
      ./LICENSE.md
    ];
  };
  nativeBuildInputs = [ makeWrapper ];
  # mkTmuxPlugin sets strictDeps, so patchShebangs finds bash only here.
  buildInputs = [ bash ];
  # tmux and Claude run these scripts by path with their own PATH.
  postInstall = ''
    plugin=$out/share/tmux-plugins/claude-tmux-resurrect
    for script in "$plugin"/claude-tmux-resurrect.tmux "$plugin"/bin/*; do
      wrapProgram "$script" --prefix PATH : ${
        lib.makeBinPath [
          bash
          tmux
          jq
          coreutils
        ]
      }
    done
  '';
  meta = {
    description = "tmux plugin that restores Claude Code conversations with tmux-resurrect";
    homepage = "https://github.com/kallisti-dev/claude-tmux-resurrect";
    license = lib.licenses.bsd3;
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
}
